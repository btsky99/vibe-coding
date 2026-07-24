"""
FILE: api/hive_ingest_api.py
DESCRIPTION: 하이브 수집(ingest) POST 핸들러 3종 — pg_logs 기록 / thought PG 기록 /
             사고과정 추가(SSE 브로드캐스트 + 벡터DB 영구 저장). server.py do_POST에서 분리.

             [불변식 — 절대 준수] thoughts_add는 사고 SSE 팬아웃의 writer 측이다.
             THOUGHT_LOGS / THOUGHT_CLIENTS / _SSE_LOCK 3개는 반드시 server.py 전역과
             '동일 객체 identity'를 참조 주입받아야 한다. events_api.stream_thoughts(broadcaster)가
             똑같은 3개 전역을 구독자 등록에 쓰기 때문 — 새로 만들거나 사본을 넘기면 구독자는
             붙어있는데 새 thought가 절대 도달하지 않는다(에러도 안 남, 런타임에만 드러나는 치명 버그).
             그래서 이 함수들은 상태를 모듈 내부에 두지 않고 전부 파라미터로 주입받는다.

REVISION HISTORY:
- 2026-07-06 Claude: server.py do_POST 하이브 수집 3라우트 분리(Phase 2 R7).
  로직 원본 verbatim 이전. 공유 전역(집합/락/로그리스트)·PG 헬퍼·벡터DB 헬퍼는 참조 주입.
"""
from __future__ import annotations

import json
import time
from datetime import datetime


def hive_log_pg(h, log_to_pg) -> None:
    """POST /api/hive/log/pg — pg_logs 테이블 기록.
    log_to_pg는 server.py 모듈 함수를 참조 주입(PROJECT_ID/pgmq 상태를 server.py 쪽에서 관리)."""
    h.send_response(200)
    h.send_header('Content-Type', 'application/json;charset=utf-8')
    h.send_header('Access-Control-Allow-Origin', h._cors_origin())
    h.end_headers()
    try:
        content_length = int(h.headers['Content-Length'])
        data = json.loads(h.rfile.read(content_length).decode('utf-8'))
        log_to_pg(
            agent=data.get('agent', 'unknown'),
            terminal_id=data.get('terminal_id', 'T0'),
            task=data.get('task', ''),
            status=data.get('status', 'success'),
            # [크로스 프로젝트 경계] 호출 세션이 보낸 project_id를 존중 — 없으면 log_to_pg가
            # 서버 자기 PROJECT_ID로 폴백. 외부 프로젝트 로그가 이 서버 프로젝트로 오태깅되는 것 차단.
            project_id=data.get('project_id')
        )
        h.wfile.write(json.dumps({"status": "success"}).encode('utf-8'))
    except Exception as e:
        h.wfile.write(json.dumps({"status": "error", "message": str(e)}).encode('utf-8'))


def hive_thought_pg(h, thought_to_pg) -> None:
    """POST /api/hive/thought/pg — thought PG 기록. parent_id 수신 + 응답에 id 포함.
    thought_to_pg는 server.py 모듈 함수를 참조 주입."""
    h.send_response(200)
    h.send_header('Content-Type', 'application/json;charset=utf-8')
    h.send_header('Access-Control-Allow-Origin', h._cors_origin())
    h.end_headers()
    try:
        content_length = int(h.headers['Content-Length'])
        data = json.loads(h.rfile.read(content_length).decode('utf-8'))
        # parent_id를 받아 지식 그래프 연결선 생성 지원
        new_id = thought_to_pg(
            agent=data.get('agent', 'unknown'),
            skill=data.get('skill', 'general'),
            thought=data.get('thought', {}),
            parent_id=data.get('parent_id')
        )
        h.wfile.write(json.dumps({"status": "success", "id": new_id}).encode('utf-8'))
    except Exception as e:
        h.wfile.write(json.dumps({"status": "error", "message": str(e)}).encode('utf-8'))


def thoughts_add(h, thought_logs, thought_clients, sse_lock, set_memory, project_id) -> None:
    """POST /api/thoughts/add — 사고과정 추가 + 실시간 SSE 브로드캐스트 + 벡터DB 영구 저장.

    [불변식] thought_logs/thought_clients/sse_lock은 server.py 전역과 동일 객체여야 함
      (events_api.stream_thoughts가 등록한 구독자 집합과 같아야 팬아웃이 닿음).
    set_memory/project_id도 참조 주입(server.py의 pg_store.set_memory / 전역 PROJECT_ID)."""
    h.send_response(200)
    h.send_header('Content-Type', 'application/json;charset=utf-8')
    h.send_header('Access-Control-Allow-Origin', h._cors_origin())
    h.end_headers()
    try:
        content_length = int(h.headers['Content-Length'])
        data = json.loads(h.rfile.read(content_length).decode('utf-8'))

        # 데이터 유효성 검사 및 타임스탬프 추가
        data['timestamp'] = datetime.now().isoformat()
        thought_logs.append(data)
        if len(thought_logs) > 100:
            thought_logs.pop(0)

        # ── 실시간 SSE 브로드캐스트 ──────────────────────────────
        msg = f"data: {json.dumps(data, ensure_ascii=False)}\n\n"
        disconnected = []
        with sse_lock:
            clients_snapshot = list(thought_clients)
        for client in clients_snapshot:
            try:
                client.wfile.write(msg.encode('utf-8'))
                client.wfile.flush()
            except Exception:
                disconnected.append(client)
        if disconnected:
            with sse_lock:
                for client in disconnected:
                    thought_clients.discard(client)

        # ── 벡터 DB에 영구 저장 ──────────────────────────────────
        try:
            agent   = data.get('agent', 'unknown')
            thought = data.get('thought', '')
            level   = data.get('level', 'info')
            tool    = data.get('tool', '')
            step    = data.get('step', '')
            ts_ms   = str(int(time.time() * 1000))

            key     = f"thought:{agent}:{ts_ms}"
            title   = f"[{level}] {thought[:80]}"
            content = thought
            if tool:  content += f"\n🔧 tool: {tool}"
            if step:  content += f"\n📍 step: {step}"

            tags = ['thought', level, agent]
            set_memory(
                key=key,
                title=title,
                content=content,
                tags=tags,
                author=agent,
                project_id=project_id,
                created_at=data['timestamp'],
                updated_at=data['timestamp'],
            )

            print(f"🧠 [Thought→DB] {key}")
        except Exception as db_err:
            print(f"[Thought→DB] 저장 실패 (무시): {db_err}")
        # ─────────────────────────────────────────────────────────

        print(f"🧠 [Thought Trace] New thought captured: {data.get('thought', '')[:50]}...")
        h.wfile.write(json.dumps({"status": "success"}).encode('utf-8'))
    except Exception as e:
        print(f"[Error] /api/thoughts/add failed: {e}")
        h.wfile.write(json.dumps({"status": "error", "message": str(e)}).encode('utf-8'))
