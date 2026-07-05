"""
FILE: api/logs_api.py
DESCRIPTION: 로그/메시지/실시간 로그 스트림 라우트 4종 — GET /stream(SSE), GET /api/server-logs,
             GET /api/messages, POST /api/messages/clear. server.py do_GET/do_POST 인라인 블록을
             verbatim 이전(Phase 2 R3). 동작 완전 불변.

  [불변식/핵심 함정] stream()의 psycopg2 직접연결은 풀을 거치지 않는다. server.py의
    살아있는 전역 PG_PORT / PG_PROJECT_DB(동적 포트 폴백 시 global로 갱신됨)와
    run_pg_sql_csv를 인자로 주입받아야 한다 — server.py wrapper는 함수 바디 안에서
    전역 이름을 참조해 매 호출 시 최신값을 재조회한다(디폴트 인자 late-binding 금지).
  [구조 유지] psycopg2 직접연결→풀 전환은 별도 작업. 여기서는 원본 그대로 옮기기만 한다.

REVISION HISTORY:
- 2026-07-06 Claude: server.py do_GET/do_POST 로그·스트림 4블록 분리(Phase 2 R3).
  전역(PG_PORT/PG_PROJECT_DB/DATA_DIR/run_pg_sql_csv/get_messages/clear_messages)은 참조 주입.
"""
from __future__ import annotations

import json
import socket
from urllib.parse import parse_qs


def stream(h, pg_port, pg_project_db, run_pg_sql_csv) -> None:
    """GET /stream — pg_logs 실시간 SSE(psycopg2 LISTEN/NOTIFY 무한루프).
    [불변식] pg_port/pg_project_db는 server.py 전역의 최신값이어야 함(동적 포트 폴백 대응).
      풀 미경유 직접연결 — 클라이언트별 전용 커넥션에서 LISTEN 도는 구조라 그대로 유지.
    """
    h.send_response(200)
    h.send_header('Content-Type', 'text/event-stream')
    h.send_header('Access-Control-Allow-Origin', h._cors_origin())
    h.send_header('Cache-Control', 'no-cache')
    h.send_header('Connection', 'keep-alive')
    h.end_headers()

    import psycopg2
    import select

    # 1. 초기 데이터 전송 (최근 50개 - PostgreSQL pg_logs 테이블에서 조회)
    try:
        rows = run_pg_sql_csv(
            "SELECT agent, metadata->>'level' as level, task as trigger, metadata->>'session_id' as session_id, "
            "terminal_id as terminal_id, project_id as project, "
            "status as status, to_char(ts, 'YYYY-MM-DD HH24:MI:SS') as timestamp "
            "FROM pg_logs ORDER BY id DESC LIMIT 50"
        )
        if rows:
            for row in reversed(rows):
                if not row.get('level'):
                    row['level'] = 'info'
                h.wfile.write(f"data: {json.dumps(row, ensure_ascii=False)}\n\n".encode('utf-8'))
                h.wfile.flush()
    except Exception as e:
        print(f"[SSE-PG] Initial Read Error: {e}")

    # 2. 실시간 LISTEN 루프
    try:
        pg_conn = psycopg2.connect(host="localhost", port=pg_port, user="postgres", database=pg_project_db)
        pg_conn.set_isolation_level(psycopg2.extensions.ISOLATION_LEVEL_AUTOCOMMIT)
        cursor = pg_conn.cursor()
        cursor.execute("LISTEN hive_log_channel;")

        h.connection.settimeout(60.0)  # SSE 연결 타임아웃

        while True:
            if select.select([pg_conn], [], [], 5) == ([], [], []):
                # 하트비트 전송
                h.wfile.write(b": heartbeat\n\n")
                h.wfile.flush()
                continue

            pg_conn.poll()
            while pg_conn.notifies:
                notify = pg_conn.notifies.pop(0)
                payload = json.loads(notify.payload)

                table_name = payload.get('table')
                if table_name in ('hive_logs', 'pg_logs'):
                    data = payload.get('data', {})
                    meta = data.get('metadata', {})
                    if isinstance(meta, str):
                        try: meta = json.loads(meta)
                        except: meta = {}

                    agent = data.get('agent')
                    level = meta.get('level', 'info') if meta else 'info'
                    trigger = data.get('task') if table_name == 'pg_logs' else data.get('message')
                    session_id = meta.get('session_id') or meta.get('task_id') if meta else None
                    terminal_id = data.get('terminal_id') if table_name == 'pg_logs' else (meta.get('terminal_id') if meta else '')
                    project = data.get('project_id') if table_name == 'pg_logs' else (meta.get('project') if meta else '')
                    status = data.get('status') if table_name == 'pg_logs' else (meta.get('raw_status') if meta else '')
                    timestamp = data.get('ts') or data.get('created_at') if table_name == 'pg_logs' else data.get('timestamp')

                    out_row = {
                        "agent": agent,
                        "level": level,
                        "trigger": trigger,
                        "session_id": session_id,
                        "terminal_id": terminal_id,
                        "project": project,
                        "status": status,
                        "timestamp": timestamp
                    }

                    h.wfile.write(f"data: {json.dumps(out_row, ensure_ascii=False)}\n\n".encode('utf-8'))
                    h.wfile.flush()
    except (BrokenPipeError, ConnectionResetError, socket.timeout):
        pass
    except Exception as e:
        print(f"[SSE-PG] Stream Error: {e}")
    finally:
        try: pg_conn.close()
        except: pass


def server_logs(h, data_dir) -> None:
    """GET /api/server-logs — server_error.log / pgsql.log / task_logs.jsonl tail 조회."""
    h.send_response(200)
    h.send_header('Content-Type', 'application/json;charset=utf-8')
    h.send_header('Access-Control-Allow-Origin', h._cors_origin())
    h.end_headers()
    query = parse_qs(h.path.split('?', 1)[1] if '?' in h.path else '')
    # tail 줄 수 (기본 200줄)
    tail_n = int(query.get('lines', ['200'])[0])
    log_type = query.get('type', ['server'])[0]  # server | pgsql | task
    logs_data: dict = {"type": log_type, "lines": [], "path": ""}
    try:
        if log_type == 'pgsql':
            log_path = data_dir.parent / "pgsql.log"
            if not log_path.exists():
                log_path = data_dir / "pgsql.log"
        elif log_type == 'task':
            log_path = data_dir / "task_logs.jsonl"
        else:
            log_path = data_dir / "server_error.log"
        logs_data["path"] = str(log_path)
        if log_path.exists():
            all_lines = log_path.read_text(encoding='utf-8', errors='replace').splitlines()
            logs_data["lines"] = all_lines[-tail_n:]
        else:
            logs_data["lines"] = [f"(로그 파일 없음: {log_path})"]
    except Exception as e:
        logs_data["lines"] = [f"(로그 읽기 오류: {e})"]
    body = json.dumps(logs_data, ensure_ascii=False).encode('utf-8')
    h.wfile.write(body)


def messages(h, get_messages) -> None:
    """GET /api/messages — 에이전트 간 메시지 채널 목록(최신 100개)."""
    h.send_response(200)
    h.send_header('Content-Type', 'application/json;charset=utf-8')
    h.send_header('Access-Control-Allow-Origin', h._cors_origin())
    h.end_headers()
    try:
        msgs = get_messages(100)
        h.wfile.write(json.dumps(msgs, ensure_ascii=False).encode('utf-8'))
    except Exception as e:
        h.wfile.write(json.dumps({'error': str(e)}).encode('utf-8'))


def clear(h, clear_messages) -> None:
    """POST /api/messages/clear — 메시지 채널 전체 삭제(대시보드 UI 초기화용)."""
    h.send_response(200)
    h.send_header('Content-Type', 'application/json;charset=utf-8')
    h.send_header('Access-Control-Allow-Origin', h._cors_origin())
    h.end_headers()
    ok = clear_messages()
    h.wfile.write(json.dumps({'status': 'ok' if ok else 'error'}).encode('utf-8'))
