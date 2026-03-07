# -*- coding: utf-8 -*-
"""
FILE: scripts/skill_orchestrator.py
DESCRIPTION: AI 오케스트레이터 스킬 체인 실행 상태 추적기.
             vibe-orchestrate.md 스킬이 실행 중인 스킬 체인의 상태를
             skill_chain.db(SQLite)에 영속화하여 대시보드에 실시간 표시합니다.

             [CLI 사용법]
             python skill_orchestrator.py plan [--terminal N] "요청내용" skill1 skill2 ...
               → 새 체인 계획 생성 (해당 터미널의 기존 계획 덮어쓰기)
               → --terminal 미지정 시 terminal_id=0 (unknown)

             python skill_orchestrator.py update <step번호> <status> [summary]
               → 특정 단계 상태 갱신 (TERMINAL_ID 환경변수 참조)
               status: running | done | failed | skipped

             python skill_orchestrator.py status
               → 현재 실행 상태 JSON 출력

             python skill_orchestrator.py done
               → 전체 체인 완료 처리

             python skill_orchestrator.py reset [--terminal N]
               → 해당 터미널 상태 초기화

REVISION HISTORY:
- 2026-03-01 Claude: [리팩터링] JSON → SQLite(skill_chain.db) 전환
  - skill_chain.db 전용 DB 생성 (오케스트레이터 독립 관리)
  - --terminal N 플래그로 터미널별 독립 체인 추적
  - SKILL_REGISTRY 상수로 스킬 번호 전역 관리 (1=debug ~ 7=release)
  - 터미널별 최신 세션만 활성 상태로 노출 (API 응답에 terminals 맵 반환)
- 2026-03-07 Claude: [버그수정] Ghost 세션 표시 문제 — 3가지 수정:
  1) cmd_plan()/cmd_reset(): 이전 pending 레코드 skip 시 updated_at 갱신 제거.
     기존에는 updated_at을 현재 시각으로 갱신하여 오래된 ghost 세션이 "최근 8시간"
     fallback 쿼리에 계속 노출되는 문제가 있었음.
  2) _build_response() fallback: HAVING 절 추가 — 모든 step이 skipped인 세션 제외.
     (이미 updated_at이 갱신된 기존 ghost 레코드에 대한 안전망)
  3) 의미 있는 세션(done/running/failed step 1개 이상)만 대시보드에 표시.
- 2026-03-06 Claude: [버그수정] 스테일 체인 표시 문제 — _build_response() 활성 세션 쿼리에
  15분 시간 제한 추가. 프로세스 비정상 종료로 상태 미갱신된 running/pending 레코드가
  대시보드에 영원히 남는 레거시 데이터 오염 현상 수정.
- 2026-03-01 Claude: 최초 구현 — AI 오케스트레이터 B안 상태 추적기
  - skill_chain.json 읽기/쓰기로 실행 상태 영속화
"""

import sys
import os
import json
import sqlite3
from datetime import datetime
from pathlib import Path


# ── 스킬 레지스트리 — 전역 고정 번호 (UI에서 N-M 표기에 사용) ────────────────
# N-M 표기: N=터미널 번호, M=이 배열의 num 값
SKILL_REGISTRY = [
    {"num": 1, "name": "vibe-debug",        "short": "debug"},
    {"num": 2, "name": "vibe-tdd",          "short": "tdd"},
    {"num": 3, "name": "vibe-brainstorm",   "short": "brainstorm"},
    {"num": 4, "name": "vibe-write-plan",   "short": "write-plan"},
    {"num": 5, "name": "vibe-execute-plan", "short": "execute"},
    {"num": 6, "name": "vibe-code-review",  "short": "review"},
    {"num": 7, "name": "vibe-release",      "short": "release"},
    {"num": 8, "name": "vibe-heal",         "short": "heal"},    # 자기치유 스킬
]

# 스킬 이름 → 번호 조회용 딕셔너리 (plan 시 스킬 이름을 번호로 변환)
_SKILL_NAME_TO_NUM: dict = {s["name"]: s["num"] for s in SKILL_REGISTRY}


def _skill_num(name: str) -> int:
    """스킬 이름으로 전역 번호를 반환. 미등록 스킬은 0으로 처리."""
    return _SKILL_NAME_TO_NUM.get(name, 0)


# ── 데이터 디렉토리 경로 결정 (frozen/개발 모드 자동 구분) ────────────────────
def _get_data_dir() -> Path:
    """frozen(배포) 모드와 개발 모드를 자동 구분하여 데이터 디렉토리 반환."""
    if getattr(sys, 'frozen', False):
        appdata = os.getenv('APPDATA', '')
        _appdata_dir = Path(appdata) / "VibeCoding"
        if _appdata_dir.exists():
            return _appdata_dir
        return Path(sys.executable).parent / "data"
    else:
        return Path(__file__).parent.parent / ".ai_monitor" / "data"


DATA_DIR = _get_data_dir()
DB_FILE = DATA_DIR / "skill_chain.db"

# 하위 호환: skill_results.jsonl은 기존 위치 유지
RESULTS_FILE = DATA_DIR / "skill_results.jsonl"


def _now() -> str:
    """현재 시각을 ISO 8601 형식 문자열로 반환."""
    return datetime.now().isoformat(timespec='seconds')


def _connect() -> sqlite3.Connection:
    """skill_chain.db 연결 및 테이블 자동 생성."""
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(DB_FILE), timeout=10, check_same_thread=False)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")  # 동시 읽기/쓰기 성능 향상
    # ── skill_chains 테이블 생성 (없을 때만) ──────────────────────────────
    # 한 세션의 스킬 하나 = 한 레코드.
    # 같은 session_id + step_order 조합이 한 스킬의 실행 상태를 나타냄.
    conn.execute("""
        CREATE TABLE IF NOT EXISTS skill_chains (
            id          INTEGER PRIMARY KEY AUTOINCREMENT,
            session_id  TEXT NOT NULL,
            terminal_id INTEGER NOT NULL DEFAULT 0,
            agent       TEXT DEFAULT '',
            request     TEXT,
            skill_num   INTEGER DEFAULT 0,
            skill_name  TEXT,
            step_order  INTEGER,
            status      TEXT DEFAULT 'pending',
            summary     TEXT DEFAULT '',
            started_at  TEXT,
            updated_at  TEXT
        )
    """)
    # agent 컬럼 마이그레이션 — 기존 DB에 없는 경우 추가 (하위 호환)
    try:
        conn.execute("ALTER TABLE skill_chains ADD COLUMN agent TEXT DEFAULT ''")
        conn.commit()
    except Exception:
        pass  # 이미 존재하면 무시
    conn.execute("""
        CREATE INDEX IF NOT EXISTS idx_sc_terminal_session
        ON skill_chains (terminal_id, session_id)
    """)
    conn.commit()
    return conn


def _get_agent() -> str:
    """환경변수 HIVE_AGENT 또는 빈 문자열 반환. server.py가 PTY 실행 시 자동 주입."""
    return os.getenv('HIVE_AGENT', '')


def _get_terminal_id() -> int:
    """환경변수 TERMINAL_ID 또는 0(unknown) 반환.

    'T3', 'T1' 형식(hook_bridge.py 방식)과 순수 숫자 '3' 형식 모두 지원.
    예: 'T3' → 3, '3' → 3, '' → 0
    """
    raw = os.getenv('TERMINAL_ID', '').strip()
    if not raw:
        return 0
    try:
        # 'T3' → '3' → 3
        return int(raw.lstrip('Tt'))
    except (ValueError, TypeError):
        return 0


def _active_session(conn: sqlite3.Connection, terminal_id: int) -> str | None:
    """해당 터미널의 가장 최근 활성 세션 ID 반환.

    우선순위:
    1) running/pending 상태가 있는 세션 (진행 중)
    2) 없으면 최근 5분 이내 가장 최근 세션 (모든 step이 done/skipped인 경우 — done 명령 직후)
    """
    # 1순위: running 또는 pending 상태 세션
    row = conn.execute(
        "SELECT session_id FROM skill_chains "
        "WHERE terminal_id = ? AND status IN ('running', 'pending') "
        "ORDER BY started_at DESC LIMIT 1",
        (terminal_id,)
    ).fetchone()
    if row:
        return row['session_id']
    # 2순위: 최근 5분 내 가장 최근 세션 (update가 모두 완료된 직후 done 호출 대응)
    row = conn.execute(
        "SELECT session_id FROM skill_chains "
        "WHERE terminal_id = ? "
        "AND updated_at >= datetime('now', '-5 minutes', 'localtime') "
        "ORDER BY updated_at DESC LIMIT 1",
        (terminal_id,)
    ).fetchone()
    return row['session_id'] if row else None


def _save_result_history(terminal_id: int, session_id: str, request: str,
                          results: list, completed_at: str) -> None:
    """완료된 스킬 체인 결과를 skill_results.jsonl에 영구 누적 저장합니다."""
    record = {
        "session_id": session_id,
        "terminal_id": terminal_id,
        "agent": _get_agent(),  # HIVE_AGENT 환경변수 — 프론트엔드 에이전트별 필터링용
        "request": request,
        "results": results,
        "completed_at": completed_at,
    }
    try:
        DATA_DIR.mkdir(parents=True, exist_ok=True)
        with open(RESULTS_FILE, 'a', encoding='utf-8') as f:
            f.write(json.dumps(record, ensure_ascii=False) + "\n")
    except Exception as e:
        print(f"[WARN] 결과 저장 실패: {e}")


def _broadcast_status(agent: str, content: str) -> None:
    """messages.jsonl에 스킬 실행 상태를 브로드캐스트합니다 (Phase 3).

    대시보드 메시지 탭에 "XX 에이전트가 현재 XX 작업 중" 메시지를 자동 게시합니다.
    서버 HTTP 의존 없이 직접 파일 기록 방식을 사용합니다.
    """
    import time as _time
    from datetime import datetime as _dt
    messages_file = DATA_DIR / "messages.jsonl"
    msg = {
        "id": str(int(_time.time() * 1000)),
        "timestamp": _dt.now().strftime("%Y-%m-%dT%H:%M:%S"),
        "from": agent or "agent",
        "to": "all",
        "type": "status",
        "content": content,
        "read": False,
    }
    try:
        DATA_DIR.mkdir(parents=True, exist_ok=True)
        with open(messages_file, "a", encoding="utf-8") as f:
            f.write(json.dumps(msg, ensure_ascii=False) + "\n")
    except Exception as e:
        print(f"[WARN] 메시지 브로드캐스트 실패: {e}")


def cmd_plan(terminal_id: int, request: str, skills: list[str]) -> None:
    """새 스킬 체인 계획을 생성하고 DB에 저장합니다.

    [동작]
    - 해당 터미널의 기존 running/pending 레코드를 모두 skipped로 처리
    - 각 스킬을 pending 상태로 INSERT
    - HIVE_AGENT 환경변수에서 에이전트 이름(claude/gemini) 자동 읽기

    Args:
        terminal_id: 터미널 번호 (0=unknown, 1~8)
        request:     사용자 원본 요청 문자열
        skills:      실행할 스킬 이름 목록
    """
    session_id = datetime.now().strftime("%Y%m%d_%H%M%S")
    agent = _get_agent()  # server.py가 PTY 시작 시 자동 주입한 HIVE_AGENT 읽기
    now = _now()

    conn = _connect()
    try:
        # 해당 터미널의 기존 활성 세션 종료 처리 (덮어쓰기 방지)
        # [버그수정] updated_at을 현재 시각으로 갱신하지 않음 — 이전 레코드의 타임스탬프를
        #   갱신하면 오래된 ghost 세션이 "최근" 세션으로 오인되어 대시보드에 계속 노출됩니다.
        conn.execute(
            "UPDATE skill_chains SET status='skipped' "
            "WHERE terminal_id=? AND status IN ('running','pending')",
            (terminal_id,)
        )
        # 각 스킬을 개별 레코드로 INSERT (agent 컬럼 포함)
        for order, skill_name in enumerate(skills):
            num = _skill_num(skill_name)
            conn.execute(
                "INSERT INTO skill_chains "
                "(session_id, terminal_id, agent, request, skill_num, skill_name, step_order, status, summary, started_at, updated_at) "
                "VALUES (?, ?, ?, ?, ?, ?, ?, 'pending', '', ?, ?)",
                (session_id, terminal_id, agent, request, num, skill_name, order, now, now)
            )
        conn.commit()
    finally:
        conn.close()

    print(f"[OK] 스킬 체인 계획 저장: {' → '.join(skills)}")
    print(f"     세션 ID: {session_id}  터미널: T{terminal_id or '?'}  에이전트: {agent or '(미지정)'}")

    # Phase 3: 체인 계획을 메시지 채널에 브로드캐스트 (상대 에이전트에게 브리핑)
    chain_str = " → ".join(skills)
    _broadcast_status(
        agent=agent or "agent",
        content=f"[스킬 체인 시작] T{terminal_id or '?'}: {request[:60]} | 체인: {chain_str}",
    )


def cmd_update(terminal_id: int, step: int, status: str, summary: str = "") -> None:
    """특정 단계의 실행 상태를 DB에서 갱신합니다.

    Args:
        terminal_id: 터미널 번호 (TERMINAL_ID 환경변수 또는 --terminal 플래그)
        step:        0-based 단계 인덱스
        status:      "running" | "done" | "failed" | "skipped"
        summary:     완료 결과 한 줄 요약 (선택)
    """
    conn = _connect()
    try:
        session_id = _active_session(conn, terminal_id)
        if not session_id:
            # terminal_id=0으로 재시도 (--terminal 미지정 세션 대응)
            session_id = _active_session(conn, 0)
        if not session_id:
            print("[WARN] 활성 체인 없음 — plan 먼저 실행하세요")
            sys.exit(1)

        # 해당 step의 레코드 조회
        row = conn.execute(
            "SELECT id, skill_name FROM skill_chains "
            "WHERE session_id=? AND step_order=? AND terminal_id=?",
            (session_id, step, terminal_id if terminal_id else 0)
        ).fetchone()
        if not row:
            print(f"[ERROR] 유효하지 않은 step: {step}")
            sys.exit(1)

        conn.execute(
            "UPDATE skill_chains SET status=?, summary=?, updated_at=? WHERE id=?",
            (status, summary, _now(), row['id'])
        )
        conn.commit()

        skill_name = row['skill_name']
        icon = {"running": "🔄", "done": "✅", "failed": "❌", "skipped": "⏭️"}.get(status, "❓")
        print(f"[OK] {icon} {skill_name}: {status}" + (f" — {summary}" if summary else ""))

        # Phase 3: 스킬 상태 변경을 메시지 채널에 자동 게시
        # "XX 에이전트가 현재 XX 작업 중입니다" 형식으로 대시보드 메시지 탭에 표시
        agent = _get_agent()
        agent_label = agent or "에이전트"
        if status == "running":
            status_msg = f"{icon} {agent_label}가 현재 [{skill_name}] 작업 중입니다"
        elif status == "done":
            status_msg = f"{icon} {agent_label}: [{skill_name}] 완료" + (f" — {summary}" if summary else "")
        elif status == "failed":
            status_msg = f"{icon} {agent_label}: [{skill_name}] 실패" + (f" — {summary}" if summary else "")
        else:
            status_msg = f"{icon} {agent_label}: [{skill_name}] {status}"
        _broadcast_status(agent=agent_label, content=status_msg)
    finally:
        conn.close()


def cmd_status() -> None:
    """현재 스킬 체인 실행 상태를 터미널별로 JSON 출력합니다."""
    data = _build_response()
    print(json.dumps(data, ensure_ascii=False, indent=2))


def cmd_done(terminal_id: int) -> None:
    """해당 터미널의 스킬 체인을 완료 처리합니다."""
    conn = _connect()
    try:
        session_id = _active_session(conn, terminal_id)
        if not session_id:
            session_id = _active_session(conn, 0)
        if not session_id:
            print("[WARN] 활성 체인 없음")
            return

        now = _now()
        # pending 상태 항목을 skipped로 처리
        conn.execute(
            "UPDATE skill_chains SET status='skipped', updated_at=? "
            "WHERE session_id=? AND status='pending'",
            (now, session_id)
        )
        # running 상태 항목을 done으로 처리
        conn.execute(
            "UPDATE skill_chains SET status='done', updated_at=? "
            "WHERE session_id=? AND status='running'",
            (now, session_id)
        )
        conn.commit()

        # 결과 조회 후 jsonl에 저장
        rows = conn.execute(
            "SELECT skill_name, status, summary, request FROM skill_chains "
            "WHERE session_id=? ORDER BY step_order",
            (session_id,)
        ).fetchall()
        request = rows[0]['request'] if rows else ""
        results = [{"skill": r['skill_name'], "status": r['status'], "summary": r['summary']} for r in rows]
        _save_result_history(terminal_id, session_id, request, results, now)

        print("[OK] ✅ 오케스트레이터 체인 완료")
        for r in results:
            icon = {"done": "✅", "failed": "❌", "skipped": "⏭️", "running": "🔄"}.get(r["status"], "❓")
            summary = f" — {r['summary']}" if r.get("summary") else ""
            print(f"     {icon} {r['skill']}{summary}")
    finally:
        conn.close()


def cmd_reset(terminal_id: int) -> None:
    """해당 터미널의 스킬 체인 상태를 초기화합니다 (running/pending → skipped).

    [버그수정] updated_at을 갱신하지 않음 — 타임스탬프 갱신 시 오래된 ghost 세션이
    "최근 활동" 세션으로 오인되어 대시보드 fallback 쿼리에 계속 노출됩니다.
    """
    conn = _connect()
    try:
        conn.execute(
            "UPDATE skill_chains SET status='skipped' "
            "WHERE terminal_id=? AND status IN ('running','pending')",
            (terminal_id,)
        )
        conn.commit()
    finally:
        conn.close()
    print(f"[OK] T{terminal_id or '?'} 스킬 체인 초기화 완료")


def _build_response() -> dict:
    """API 응답용: 스킬 레지스트리 + 터미널별 최신 세션 반환."""
    conn = _connect()
    try:
        # ── 스테일 pending 세션 자동 정리 ─────────────────────────────────────
        # 1시간 이상 업데이트 없는 pending/running 세션 → skipped 처리
        # (프로세스 비정상 종료로 상태가 갱신되지 않은 좀비 세션 제거)
        # [중요] updated_at을 변경하지 않음 — 타임스탬프 변경 시 8시간 fallback이
        #   오래된 스테일 세션을 "최근 데이터"로 오인하여 패널에 표시하는 부작용 방지
        conn.execute(
            "UPDATE skill_chains SET status='skipped' "
            "WHERE status IN ('running', 'pending') "
            "AND updated_at < datetime('now', '-1 hours', 'localtime')"
        )
        conn.commit()

        # 터미널별 최신 활성(running/pending) 세션 ID 조회
        # 1시간 이내 업데이트된 세션만 활성으로 간주 — 위에서 이미 정리했으나 경계 케이스 방어용
        active_sessions: dict[int, str] = {}
        rows = conn.execute(
            "SELECT terminal_id, session_id FROM skill_chains "
            "WHERE status IN ('running', 'pending') "
            "AND updated_at >= datetime('now', '-1 hours', 'localtime') "
            "GROUP BY terminal_id "
            "ORDER BY updated_at DESC"
        ).fetchall()
        for row in rows:
            tid = row['terminal_id']
            if tid not in active_sessions:
                active_sessions[tid] = row['session_id']

        # 활성 세션 없는 터미널에 대해 최근 완료 세션 fallback (최근 8시간)
        # [기존 30분 → 8시간] 오늘 작업한 내역이 패널에서 사라지지 않도록 연장
        # [버그수정] active_sessions 빈 경우 NOT IN () 바인딩 오류 방지:
        #   빈 경우 NOT IN 조건 자체를 제거하여 전체 터미널 대상으로 조회
        cutoff = datetime.now().strftime("%Y-%m-%dT%H:%M:%S")
        if active_sessions:
            where_clause = "WHERE terminal_id NOT IN ({}) AND ".format(
                ','.join(['?'] * len(active_sessions))
            )
            params: list = list(active_sessions.keys()) + [cutoff]
        else:
            where_clause = "WHERE "
            params = [cutoff]
        # [버그수정] all-skipped 세션(ghost session) 제외 — HAVING 절 추가:
        #   cmd_plan()/cmd_reset()에서 이미 updated_at을 갱신하지 않도록 수정했으나,
        #   이전 버전의 잔존 ghost 레코드(updated_at이 이미 갱신된 것)에 대한 안전망.
        #   하나라도 'done'/'running'/'failed' 단계가 있는 세션만 표시 (의미 있는 세션).
        fallback_rows = conn.execute(
            "SELECT terminal_id, session_id, MAX(updated_at) as last_update "
            "FROM skill_chains "
            "{}"
            "updated_at >= datetime(?, '-8 hours') "
            "GROUP BY terminal_id, session_id "
            "HAVING COUNT(CASE WHEN status IN ('done','running','failed') THEN 1 END) > 0 "
            "ORDER BY last_update DESC".format(where_clause),
            params
        ).fetchall()
        for row in fallback_rows:
            tid = row['terminal_id']
            if tid not in active_sessions:
                active_sessions[tid] = row['session_id']

        # 각 세션의 스킬 목록 조회 → terminals 맵 구성
        terminals: dict[str, dict] = {}
        for tid, session_id in active_sessions.items():
            steps_rows = conn.execute(
                "SELECT skill_num, skill_name, step_order, status, summary, request, updated_at, agent "
                "FROM skill_chains WHERE session_id=? AND terminal_id=? ORDER BY step_order",
                (session_id, tid)
            ).fetchall()
            if not steps_rows:
                continue
            # terminal_id=0(TERMINAL_ID 미설정 — Claude Code 직접 실행)도 표시 허용
            # → 기존 "unknown 터미널 제외" 로직 제거

            request = steps_rows[0]['request'] or ''
            updated_at = max(r['updated_at'] for r in steps_rows if r['updated_at'])
            # agent: 세션 레코드에 저장된 값 사용 (HIVE_AGENT 환경변수가 주입된 경우에만 존재)
            agent_in_db = steps_rows[0]['agent'] or ''

            # 세션 전체 상태 결정: 하나라도 running이면 running, 전부 done/skipped면 done
            statuses = [r['status'] for r in steps_rows]
            if 'running' in statuses:
                chain_status = 'running'
            elif all(s in ('done', 'skipped', 'failed') for s in statuses):
                chain_status = 'done'
            else:
                chain_status = 'running'

            steps = [
                {
                    "label": f"{tid}-{r['skill_num']}",   # 예: "1-3"
                    "skill_num": r['skill_num'],
                    "skill_name": r['skill_name'],
                    "step_order": r['step_order'],
                    "status": r['status'],
                    "summary": r['summary'] or '',
                }
                for r in steps_rows
            ]
            terminals[str(tid)] = {
                "session_id": session_id,
                "request": request,
                "status": chain_status,
                "updated_at": updated_at,
                "agent": agent_in_db,   # PTY 세션 종료 후에도 에이전트 정보 유지
                "steps": steps,
            }

        return {
            "skill_registry": SKILL_REGISTRY,
            "terminals": terminals,
        }
    finally:
        conn.close()


def main():
    """CLI 진입점 — 서브커맨드를 파싱하여 해당 함수 호출."""
    # Windows cp949 환경에서 emoji/유니코드 출력 시 UnicodeEncodeError 방지
    # (Python 3.7+ 지원, reconfigure 없는 경우 errors='replace' fallback)
    if sys.platform == 'win32':
        try:
            sys.stdout.reconfigure(encoding='utf-8', errors='replace')
            sys.stderr.reconfigure(encoding='utf-8', errors='replace')
        except AttributeError:
            pass  # Python 3.6 이하 호환

    args = sys.argv[1:]
    if not args:
        print("사용법:")
        print("  python skill_orchestrator.py plan [--terminal N] <요청> <skill1> [skill2 ...]")
        print("  python skill_orchestrator.py update <step> <status> [summary]")
        print("  python skill_orchestrator.py status")
        print("  python skill_orchestrator.py done [--terminal N]")
        print("  python skill_orchestrator.py reset [--terminal N]")
        sys.exit(0)

    cmd = args[0].lower()
    rest = args[1:]

    # ── --terminal N 플래그 파싱 (공통) ──────────────────────────────────────
    terminal_id = _get_terminal_id()
    filtered = []
    i = 0
    while i < len(rest):
        if rest[i] == '--terminal' and i + 1 < len(rest):
            try:
                terminal_id = int(rest[i + 1])
            except ValueError:
                print(f"[ERROR] --terminal 값이 숫자가 아님: {rest[i+1]}")
                sys.exit(1)
            i += 2
        else:
            filtered.append(rest[i])
            i += 1
    rest = filtered

    if cmd == "plan":
        if len(rest) < 2:
            print("[ERROR] 사용법: plan [--terminal N] <요청> <skill1> [skill2 ...]")
            sys.exit(1)
        request = rest[0]
        skills = rest[1:]
        cmd_plan(terminal_id, request, skills)

    elif cmd == "update":
        if len(rest) < 2:
            print("[ERROR] 사용법: update <step번호> <status> [summary]")
            sys.exit(1)
        step = int(rest[0])
        status = rest[1]
        summary = rest[2] if len(rest) > 2 else ""
        cmd_update(terminal_id, step, status, summary)

    elif cmd == "status":
        cmd_status()

    elif cmd == "done":
        cmd_done(terminal_id)

    elif cmd == "reset":
        cmd_reset(terminal_id)

    else:
        print(f"[ERROR] 알 수 없는 커맨드: {cmd}")
        sys.exit(1)


if __name__ == "__main__":
    main()
