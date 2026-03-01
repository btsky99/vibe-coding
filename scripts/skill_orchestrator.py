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
    """환경변수 TERMINAL_ID 또는 0(unknown) 반환."""
    try:
        return int(os.getenv('TERMINAL_ID', '0'))
    except (ValueError, TypeError):
        return 0


def _active_session(conn: sqlite3.Connection, terminal_id: int) -> str | None:
    """해당 터미널의 가장 최근 running/pending 세션 ID 반환."""
    row = conn.execute(
        "SELECT session_id FROM skill_chains "
        "WHERE terminal_id = ? AND status IN ('running', 'pending') "
        "ORDER BY started_at DESC LIMIT 1",
        (terminal_id,)
    ).fetchone()
    return row['session_id'] if row else None


def _save_result_history(terminal_id: int, session_id: str, request: str,
                          results: list, completed_at: str) -> None:
    """완료된 스킬 체인 결과를 skill_results.jsonl에 영구 누적 저장합니다."""
    record = {
        "session_id": session_id,
        "terminal_id": terminal_id,
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
        conn.execute(
            "UPDATE skill_chains SET status='skipped', updated_at=? "
            "WHERE terminal_id=? AND status IN ('running','pending')",
            (now, terminal_id)
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
    """해당 터미널의 스킬 체인 상태를 초기화합니다 (running/pending → skipped)."""
    conn = _connect()
    try:
        conn.execute(
            "UPDATE skill_chains SET status='skipped', updated_at=? "
            "WHERE terminal_id=? AND status IN ('running','pending')",
            (_now(), terminal_id)
        )
        conn.commit()
    finally:
        conn.close()
    print(f"[OK] T{terminal_id or '?'} 스킬 체인 초기화 완료")


def _build_response() -> dict:
    """API 응답용: 스킬 레지스트리 + 터미널별 최신 세션 반환."""
    conn = _connect()
    try:
        # 터미널별 최신 활성(running/pending) 세션 ID 조회
        # 없으면 가장 최근 완료 세션으로 fallback (최근 1시간 이내)
        active_sessions: dict[int, str] = {}
        rows = conn.execute(
            "SELECT terminal_id, session_id FROM skill_chains "
            "WHERE status IN ('running', 'pending') "
            "GROUP BY terminal_id "
            "ORDER BY updated_at DESC"
        ).fetchall()
        for row in rows:
            tid = row['terminal_id']
            if tid not in active_sessions:
                active_sessions[tid] = row['session_id']

        # 활성 세션 없는 터미널에 대해 최근 완료 세션 fallback (최근 30분)
        cutoff = datetime.now().strftime("%Y-%m-%dT%H:%M:%S")
        fallback_rows = conn.execute(
            "SELECT terminal_id, session_id, MAX(updated_at) as last_update "
            "FROM skill_chains "
            "WHERE terminal_id NOT IN ({}) "
            "AND updated_at >= datetime(?, '-30 minutes') "
            "GROUP BY terminal_id, session_id "
            "ORDER BY last_update DESC".format(
                ','.join(['?'] * len(active_sessions)) if active_sessions else '?'
            ),
            list(active_sessions.keys()) + [cutoff] if active_sessions else [cutoff]
        ).fetchall()
        for row in fallback_rows:
            tid = row['terminal_id']
            if tid not in active_sessions:
                active_sessions[tid] = row['session_id']

        # 각 세션의 스킬 목록 조회 → terminals 맵 구성
        terminals: dict[str, dict] = {}
        for tid, session_id in active_sessions.items():
            if tid == 0:
                continue  # unknown 터미널은 제외
            steps_rows = conn.execute(
                "SELECT skill_num, skill_name, step_order, status, summary, request, updated_at, agent "
                "FROM skill_chains WHERE session_id=? AND terminal_id=? ORDER BY step_order",
                (session_id, tid)
            ).fetchall()
            if not steps_rows:
                continue

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
