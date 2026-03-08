# -*- coding: utf-8 -*-
"""
FILE: scripts/itcp.py
DESCRIPTION: Inter-Terminal Communication Protocol (ITCP) — PostgreSQL 기반 터미널 간 통신 코어.
             Claude, Gemini 등 서로 다른 터미널의 LLM이 pg_messages 테이블을 공유 메시지 버스로
             사용하여 비동기 양방향 통신을 실현합니다.

             [핵심 설계 원칙]
             - PostgreSQL FIRST: pg_messages 테이블이 단일 진실 소스 (Single Source of Truth)
             - 파일 기반 JSONL/SQLite는 모두 이 모듈로 대체됩니다
             - PostgreSQL이 미실행 중이면 자동으로 pg_manager.start()를 호출해 기동합니다
             - LISTEN/NOTIFY 지원: 실시간 알림 채널 구독 가능

             [통신 모델]
             터미널 A (Claude) ──[send]──▶ pg_messages ──[receive]──▶ 터미널 B (Gemini)
             터미널 B (Gemini) ──[send]──▶ pg_messages ──[receive]──▶ 터미널 A (Claude)

             각 LLM 호출 시 UserPromptSubmit 훅이 receive()를 호출하여
             상대방이 남긴 메시지를 자동으로 컨텍스트에 주입합니다.
             이로써 "다음 LLM 호출 시 메시지 전달"이라는 비동기 통신이 구현됩니다.

             [채널 목록]
             - general   : 일반 정보 공유
             - task      : 작업 요청/위임
             - debug     : 디버그 협업 (A가 발견한 버그를 B에게 알림)
             - review    : 코드 리뷰 요청
             - broadcast : 모든 터미널에 전달 (to_agent='all')
             - hive      : 하이브 마인드 시스템 내부 메시지

REVISION HISTORY:
- 2026-03-08 Claude: 최초 구현 — PostgreSQL 기반 ITCP 통신 코어
  - send(), receive(), broadcast() 핵심 API 구현
  - PostgreSQL 자동 시작 로직 포함 (pg_manager 연동)
  - psycopg2 없이 psql.exe 직접 호출 방식으로 외부 의존성 제거
  - history(), clear_old() 유틸리티 추가
"""

import os
import sys
import json
import subprocess
import time
from datetime import datetime
from pathlib import Path
from typing import Optional

# 경로 설정
_SCRIPT_DIR = Path(__file__).parent
_PROJECT_ROOT = _SCRIPT_DIR.parent
_PG_BIN = _PROJECT_ROOT / ".ai_monitor" / "bin" / "pgsql" / "bin" / "psql.exe"
_PG_CTL = _PROJECT_ROOT / ".ai_monitor" / "bin" / "pgsql" / "bin" / "pg_ctl.exe"
_PG_DATA = _PROJECT_ROOT / ".ai_monitor" / "bin" / "pgsql" / "data"
_PG_LOG = _PROJECT_ROOT / ".ai_monitor" / "data" / "pgsql.log"

PG_PORT = "5433"
PG_USER = "postgres"
PG_DB = "postgres"

# Windows 환경 UTF-8 강제
if hasattr(sys.stdout, "reconfigure"):
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass


def _run_psql(sql: str, timeout: int = 5) -> tuple[bool, str]:
    """psql.exe를 통해 SQL을 실행하고 결과를 CSV로 반환합니다.

    [설계 의도]
    psycopg2 같은 외부 패키지 없이 번들된 psql.exe를 직접 호출합니다.
    이로써 Python 환경 의존성 없이 PostgreSQL과 통신 가능합니다.

    [인코딩 처리 — 중요]
    Windows 환경에서 커맨드라인 인자(-c SQL)로 한글을 전달하면 CP949 인코딩 충돌 발생.
    해결: SQL을 stdin으로 전달하여 UTF-8 인코딩을 명시적으로 보장합니다.
    또한 PGCLIENTENCODING=UTF8 환경변수로 PostgreSQL 클라이언트 인코딩을 강제합니다.

    반환: (성공여부, 출력텍스트)
    """
    if not _PG_BIN.exists():
        return False, "psql.exe not found"

    no_window = getattr(subprocess, "CREATE_NO_WINDOW", 0x08000000)
    env = {**os.environ, "PGCLIENTENCODING": "UTF8"}  # 클라이언트 인코딩 UTF-8 강제

    try:
        result = subprocess.run(
            [str(_PG_BIN), "-p", PG_PORT, "-U", PG_USER, "-d", PG_DB,
             "--csv", "--tuples-only"],
            input=sql,              # stdin으로 SQL 전달 → CP949/UTF-8 충돌 방지
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=timeout,
            creationflags=no_window,
            env=env,
        )
        return result.returncode == 0, result.stdout.strip()
    except subprocess.TimeoutExpired:
        return False, "timeout"
    except Exception as e:
        return False, str(e)


def _ensure_pg_running() -> bool:
    """PostgreSQL이 실행 중인지 확인하고, 꺼져 있으면 자동으로 시작합니다.

    [동작 순서]
    1. psql.exe로 간단한 쿼리 실행 → 응답하면 True 반환
    2. 실패 시 pg_manager.py start 호출
    3. 3초 대기 후 재시도
    4. 최종 실패 시 False 반환

    [왜 필요한가]
    Windows 재시작 후 PostgreSQL이 꺼진 상태에서 훅이 실행될 수 있음.
    사용자가 수동으로 DB를 켤 필요 없이 자동으로 기동하여 통신 재개.
    """
    # 1단계: 이미 실행 중인지 확인
    ok, _ = _run_psql("SELECT 1;", timeout=2)
    if ok:
        return True

    # 2단계: pg_manager.py로 자동 시작
    pg_manager = _SCRIPT_DIR / "pg_manager.py"
    if not pg_manager.exists():
        return False

    no_window = getattr(subprocess, "CREATE_NO_WINDOW", 0x08000000)
    try:
        subprocess.Popen(
            [sys.executable, str(pg_manager), "start"],
            cwd=str(_PROJECT_ROOT),
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            creationflags=no_window,
        )
    except Exception:
        return False

    # 3단계: 최대 5초 대기
    for _ in range(10):
        time.sleep(0.5)
        ok, _ = _run_psql("SELECT 1;", timeout=2)
        if ok:
            return True

    return False


def send(
    from_terminal: str,
    to_terminal: str,
    content: str,
    channel: str = "general",
    msg_type: str = "info",
    terminal_id: str = "",
    metadata: Optional[dict] = None,
) -> bool:
    """터미널 간 메시지를 pg_messages에 저장합니다.

    [사용 예]
    itcp.send("claude", "gemini", "서버 버그 발견: server.py:145", channel="debug")
    itcp.send("gemini", "all", "배포 완료 v3.7.5", channel="broadcast")

    [인자]
    - from_terminal: 발신자 (예: "claude", "gemini")
    - to_terminal  : 수신자 (예: "claude", "gemini", "all" = 전체 브로드캐스트)
    - content      : 메시지 내용
    - channel      : 채널 분류 (general/task/debug/review/broadcast/hive)
    - msg_type     : 메시지 유형 (info/request/response/alert/summary)
    - terminal_id  : 터미널 ID (예: "T1", "T2") — 멀티터미널 구분용
    - metadata     : 추가 JSONB 데이터 (선택)
    """
    if not _ensure_pg_running():
        # PostgreSQL 불가 시 파일 fallback
        return _fallback_file_send(from_terminal, to_terminal, content, channel, msg_type)

    meta_json = json.dumps(metadata or {}, ensure_ascii=False).replace("'", "''")
    content_safe = content.replace("'", "''")
    tid = terminal_id.replace("'", "''")

    sql = (
        f"INSERT INTO pg_messages "
        f"(from_agent, to_agent, msg_type, content, channel, terminal_id, metadata, is_read) "
        f"VALUES "
        f"('{from_terminal}', '{to_terminal}', '{msg_type}', '{content_safe}', "
        f"'{channel}', '{tid}', '{meta_json}'::jsonb, false) "
        f"RETURNING id;"
    )
    ok, result = _run_psql(sql)
    if ok and result:
        # NOTIFY로 수신 측에 즉시 알림 전송 (LISTEN 중인 프로세스가 있으면 즉시 수신)
        _run_psql(f"NOTIFY hive_messages, '{to_terminal}';")
        return True
    return False


def receive(terminal_name: str, mark_read: bool = True) -> list[dict]:
    """나(terminal_name)에게 온 미읽음 메시지를 가져옵니다.

    [동작]
    1. pg_messages에서 to_agent = terminal_name OR 'all' AND is_read = false 조회
    2. mark_read=True면 조회한 메시지를 is_read=true로 업데이트
    3. 메시지 목록 반환

    [훅에서의 활용]
    hive_hook.py의 UserPromptSubmit 이벤트에서 호출되어
    상대 에이전트가 보낸 메시지를 Claude 컨텍스트에 자동 주입합니다.

    반환: [{"id": 1, "from_agent": "gemini", "channel": "debug", "content": "...", "ts": "..."}, ...]
    """
    if not _ensure_pg_running():
        return _fallback_file_receive(terminal_name, mark_read)

    # 미읽음 메시지 조회 (내게 온 것 + 전체 브로드캐스트)
    sql = (
        f"SELECT id, from_agent, to_agent, channel, msg_type, content, ts::text "
        f"FROM pg_messages "
        f"WHERE (to_agent = '{terminal_name}' OR to_agent = 'all') "
        f"AND is_read = false "
        f"ORDER BY ts ASC "
        f"LIMIT 20;"
    )
    ok, result = _run_psql(sql)
    if not ok or not result:
        return []

    messages = []
    import csv, io
    reader = csv.DictReader(
        io.StringIO(result),
        fieldnames=["id", "from_agent", "to_agent", "channel", "msg_type", "content", "ts"]
    )
    for row in reader:
        messages.append(dict(row))

    if not messages:
        return []

    # 읽음 처리
    if mark_read:
        ids = ",".join(m["id"] for m in messages)
        _run_psql(f"UPDATE pg_messages SET is_read = true WHERE id IN ({ids});")

    return messages


def broadcast(from_terminal: str, content: str, channel: str = "broadcast") -> bool:
    """모든 터미널에 브로드캐스트 메시지를 전송합니다.

    [사용 예]
    itcp.broadcast("claude", "빌드 완료 v3.7.5 — 전체 확인 요청")
    """
    return send(from_terminal, "all", content, channel=channel, msg_type="broadcast")


def history(limit: int = 20, channel: Optional[str] = None) -> list[dict]:
    """최근 메시지 이력을 조회합니다 (읽음/미읽음 모두 포함).

    [활용]
    대시보드 메시지 패널, 에이전트 컨텍스트 초기 로드 시 최근 대화 파악용
    """
    if not _ensure_pg_running():
        return []

    channel_filter = f"AND channel = '{channel}'" if channel else ""
    sql = (
        f"SELECT id, from_agent, to_agent, channel, msg_type, content, is_read, ts::text "
        f"FROM pg_messages "
        f"WHERE 1=1 {channel_filter} "
        f"ORDER BY ts DESC LIMIT {limit};"
    )
    ok, result = _run_psql(sql)
    if not ok or not result:
        return []

    messages = []
    import csv, io
    reader = csv.DictReader(
        io.StringIO(result),
        fieldnames=["id", "from_agent", "to_agent", "channel", "msg_type", "content", "is_read", "ts"]
    )
    for row in reader:
        messages.append(dict(row))
    return messages


def clear_old(days: int = 7) -> int:
    """오래된 메시지를 정리합니다 (기본 7일 이상 읽음 메시지 삭제).

    [목적] pg_messages 테이블이 무한정 커지는 것을 방지합니다.
    """
    if not _ensure_pg_running():
        return 0
    sql = (
        f"DELETE FROM pg_messages "
        f"WHERE is_read = true "
        f"AND ts < NOW() - INTERVAL '{days} days' "
        f"RETURNING id;"
    )
    ok, result = _run_psql(sql)
    if ok and result:
        return len(result.strip().splitlines())
    return 0


# ── 파일 기반 폴백 (PostgreSQL 완전 불가 시 최후 수단) ──────────────────────────
_FALLBACK_FILE = _PROJECT_ROOT / ".ai_monitor" / "data" / "messages.jsonl"


def _fallback_file_send(
    from_terminal: str, to_terminal: str, content: str,
    channel: str, msg_type: str
) -> bool:
    """PostgreSQL 불가 시 messages.jsonl 파일로 폴백 저장합니다."""
    try:
        msg = {
            "id": str(int(time.time() * 1000)),
            "ts": datetime.now().isoformat(),
            "from_agent": from_terminal,
            "to_agent": to_terminal,
            "channel": channel,
            "msg_type": msg_type,
            "content": content,
            "is_read": False,
        }
        with open(_FALLBACK_FILE, "a", encoding="utf-8") as f:
            f.write(json.dumps(msg, ensure_ascii=False) + "\n")
        return True
    except Exception:
        return False


def _fallback_file_receive(terminal_name: str, mark_read: bool) -> list[dict]:
    """PostgreSQL 불가 시 messages.jsonl 파일에서 폴백 읽기합니다."""
    if not _FALLBACK_FILE.exists():
        return []
    try:
        messages = []
        with open(_FALLBACK_FILE, encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    m = json.loads(line)
                    messages.append(m)
                except Exception:
                    pass

        unread = [
            m for m in messages
            if m.get("to_agent") in (terminal_name, "all") and not m.get("is_read")
        ]

        if unread and mark_read:
            now = datetime.now().isoformat()
            for m in messages:
                if m in unread:
                    m["is_read"] = True
                    m["read_at"] = now
            with open(_FALLBACK_FILE, "w", encoding="utf-8") as f:
                for m in messages:
                    f.write(json.dumps(m, ensure_ascii=False) + "\n")

        return unread
    except Exception:
        return []


# ── CLI 인터페이스 ────────────────────────────────────────────────────────────
if __name__ == "__main__":
    """
    CLI 사용법:
      python scripts/itcp.py send claude gemini "서버 버그 발견" debug
      python scripts/itcp.py receive claude
      python scripts/itcp.py broadcast gemini "빌드 완료"
      python scripts/itcp.py history 10
      python scripts/itcp.py status
    """
    args = sys.argv[1:]
    if not args:
        print("사용법: itcp.py [send|receive|broadcast|history|status] ...")
        sys.exit(1)

    cmd = args[0]

    if cmd == "send" and len(args) >= 4:
        from_t, to_t, content = args[1], args[2], args[3]
        channel = args[4] if len(args) > 4 else "general"
        ok = send(from_t, to_t, content, channel=channel)
        print(f"{'✅ 전송 성공' if ok else '❌ 전송 실패'}: [{from_t} → {to_t}] {content[:50]}")

    elif cmd == "receive" and len(args) >= 2:
        terminal = args[1]
        msgs = receive(terminal)
        if msgs:
            print(f"📨 {terminal}의 미읽음 메시지 {len(msgs)}개:")
            for m in msgs:
                print(f"  [{m['from_agent']} → {m['to_agent']}] ({m['channel']}) {m['content'][:80]}")
        else:
            print(f"📭 {terminal}의 미읽음 메시지 없음")

    elif cmd == "broadcast" and len(args) >= 3:
        from_t, content = args[1], args[2]
        channel = args[3] if len(args) > 3 else "broadcast"
        ok = broadcast(from_t, content, channel)
        print(f"{'✅ 브로드캐스트 성공' if ok else '❌ 실패'}: {content[:50]}")

    elif cmd == "history":
        limit = int(args[1]) if len(args) > 1 else 10
        msgs = history(limit)
        print(f"📜 최근 메시지 {len(msgs)}개:")
        for m in reversed(msgs):
            read_mark = "✓" if m.get("is_read") == "t" else "●"
            print(f"  {read_mark} [{m['from_agent']} → {m['to_agent']}] ({m['channel']}) {m['content'][:60]}")

    elif cmd == "status":
        ok, result = _run_psql("SELECT COUNT(*) FROM pg_messages WHERE is_read = false;")
        if ok:
            print(f"✅ PostgreSQL 연결 OK | 미읽음 메시지: {result.strip()}개")
        else:
            print(f"❌ PostgreSQL 연결 실패")

    else:
        print(f"알 수 없는 명령: {cmd}")
        sys.exit(1)
