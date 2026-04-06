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
import re
import subprocess
import time
from datetime import datetime
from pathlib import Path
from typing import Optional

try:
    from pg_project import resolve_project_db
except ImportError:
    from scripts.pg_project import resolve_project_db

# 경로 설정
_SCRIPT_DIR = Path(__file__).parent
_PROJECT_ROOT = _SCRIPT_DIR.parent
_PG_BIN = _PROJECT_ROOT / ".ai_monitor" / "bin" / "pgsql" / "bin" / "psql.exe"
_PG_CTL = _PROJECT_ROOT / ".ai_monitor" / "bin" / "pgsql" / "bin" / "pg_ctl.exe"
_PG_DATA = _PROJECT_ROOT / ".ai_monitor" / "bin" / "pgsql" / "data"
_PG_LOG = _PROJECT_ROOT / ".ai_monitor" / "data" / "pgsql.log"
if getattr(sys, 'frozen', False):
    _DATA_DIR = Path(os.environ.get('APPDATA', Path.home())) / "VibeCoding"
else:
    _DATA_DIR = _PROJECT_ROOT / ".ai_monitor" / "data"
_CONFIG_FILE = _DATA_DIR / "config.json"
_LEGACY_CONFIG_FILE = _PROJECT_ROOT / ".ai_monitor" / "config.json"

PG_PORT = os.environ.get('VIBE_PG_PORT', '5433')
PG_USER = "postgres"
PG_DB = resolve_project_db(_PROJECT_ROOT)

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
        stdout = result.stdout if result.stdout is not None else ""
        return result.returncode == 0, stdout.strip()
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

    # [2026-03-30 Claude] SQL 인젝션 방지 — 모든 파라미터에 싱글쿼트 이스케이프 적용
    # psql subprocess 방식에서는 parameterized query를 사용할 수 없으므로
    # 모든 문자열 값을 _sql_escape()로 처리하여 SQL 인젝션을 방지한다.
    def _sql_escape(val: str) -> str:
        """싱글쿼트를 이스케이프하고, 허용되지 않는 제어문자를 제거한다."""
        return str(val).replace("'", "''").replace("\x00", "")

    from_safe = _sql_escape(from_terminal)
    to_safe = _sql_escape(to_terminal)
    type_safe = _sql_escape(msg_type)
    channel_safe = _sql_escape(channel)
    content_safe = _sql_escape(content)
    tid_safe = _sql_escape(terminal_id)
    meta_json = json.dumps(metadata or {}, ensure_ascii=False).replace("'", "''").replace("\x00", "")

    sql = (
        f"INSERT INTO pg_messages "
        f"(from_agent, to_agent, msg_type, content, channel, terminal_id, metadata, is_read) "
        f"VALUES "
        f"('{from_safe}', '{to_safe}', '{type_safe}', '{content_safe}', "
        f"'{channel_safe}', '{tid_safe}', '{meta_json}'::jsonb, false) "
        f"RETURNING id;"
    )
    ok, result = _run_psql(sql)
    if ok and result:
        # NOTIFY로 수신 측에 즉시 알림 전송 (LISTEN 중인 프로세스가 있으면 즉시 수신)
        # NOTIFY payload도 이스케이프 적용
        _run_psql(f"NOTIFY hive_messages, '{to_safe}';")
        return True
    return False


def receive(terminal_name: str, mark_read: bool = True, my_terminal_id: str = "") -> list[dict]:
    """나(terminal_name)에게 온 미읽음 메시지를 가져옵니다.

    [동작]
    1. pg_messages에서 to_agent = terminal_name OR 'all' AND is_read = false 조회
    2. mark_read=True면 조회한 메시지를 is_read=true로 업데이트
    3. 메시지 목록 반환

    [터미널 ID 기반 필터링 — 2026-03-18 추가]
    같은 에이전트(예: Claude)가 여러 터미널에서 실행될 때 구분하기 위해
    my_terminal_id를 지정하면 자기 자신이 보낸 메시지를 제외합니다.
    예: T1에서 receive("claude", my_terminal_id="T1") → T1이 보낸 메시지 제외

    [훅에서의 활용]
    hive_hook.py의 UserPromptSubmit 이벤트에서 호출되어
    상대 에이전트가 보낸 메시지를 Claude 컨텍스트에 자동 주입합니다.

    반환: [{"id": 1, "from_agent": "gemini", "channel": "debug", "content": "...", "ts": "..."}, ...]
    """
    if not _ensure_pg_running():
        return _fallback_file_receive(terminal_name, mark_read)

    # [2026-03-18 Claude] 터미널 ID 기반 자기 메시지 제외 필터
    # 같은 에이전트(claude↔claude)가 여러 터미널에서 실행될 때
    # 자기가 보낸 메시지를 자기가 읽는 문제 방지
    # [2026-03-30 Claude] SQL 인젝션 방지 — 모든 파라미터 이스케이프 적용
    def _esc(val: str) -> str:
        return str(val).replace("'", "''").replace("\x00", "")

    safe_name = _esc(terminal_name)
    self_filter = ""
    if my_terminal_id:
        safe_tid = _esc(my_terminal_id)
        # 내 터미널 ID로 보낸 메시지는 제외 (from_agent가 나이고 terminal_id가 내 터미널)
        self_filter = f"AND NOT (from_agent = '{safe_name}' AND terminal_id = '{safe_tid}') "

    # 미읽음 메시지 조회 (내게 온 것 + 전체 브로드캐스트)
    sql = (
        f"SELECT id, from_agent, to_agent, channel, msg_type, content, "
        f"COALESCE(metadata::text, '{{}}') AS metadata, "
        f"COALESCE(terminal_id, '') AS terminal_id, ts::text "
        f"FROM pg_messages "
        f"WHERE (to_agent = '{safe_name}' OR to_agent = 'all') "
        f"AND is_read = false "
        f"{self_filter}"
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
        fieldnames=["id", "from_agent", "to_agent", "channel", "msg_type", "content", "metadata", "terminal_id", "ts"]
    )
    for row in reader:
        meta_raw = row.get("metadata", "") or "{}"
        try:
            row["metadata"] = json.loads(meta_raw)
        except Exception:
            row["metadata"] = {}
        messages.append(dict(row))

    if not messages:
        return []

    # 읽음 처리
    if mark_read:
        ids = ",".join(m["id"] for m in messages)
        _run_psql(f"UPDATE pg_messages SET is_read = true WHERE id IN ({ids});")

    return messages


def broadcast(
    from_terminal: str,
    content: str,
    channel: str = "broadcast",
    terminal_id: str = "",
    metadata: Optional[dict] = None,
) -> bool:
    """모든 터미널에 브로드캐스트 메시지를 전송합니다.

    [사용 예]
    itcp.broadcast("claude", "빌드 완료 v3.7.5 — 전체 확인 요청")
    """
    return send(
        from_terminal,
        "all",
        content,
        channel=channel,
        msg_type="broadcast",
        terminal_id=terminal_id,
        metadata=metadata,
    )


def history(limit: int = 20, channel: Optional[str] = None) -> list[dict]:
    """최근 메시지 이력을 조회합니다 (읽음/미읽음 모두 포함).

    [활용]
    대시보드 메시지 패널, 에이전트 컨텍스트 초기 로드 시 최근 대화 파악용
    """
    if not _ensure_pg_running():
        return []

    # [2026-03-30 Claude] SQL 인젝션 방지 — channel 파라미터 이스케이프
    channel_filter = f"AND channel = '{str(channel).replace(chr(39), chr(39)*2)}'" if channel else ""
    sql = (
        f"SELECT id, from_agent, to_agent, channel, msg_type, content, is_read, "
        f"COALESCE(metadata::text, '{{}}') AS metadata, "
        f"COALESCE(terminal_id, '') AS terminal_id, ts::text "
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
        fieldnames=["id", "from_agent", "to_agent", "channel", "msg_type", "content", "is_read", "metadata", "terminal_id", "ts"]
    )
    for row in reader:
        meta_raw = row.get("metadata", "") or "{}"
        try:
            row["metadata"] = json.loads(meta_raw)
        except Exception:
            row["metadata"] = {}
        messages.append(dict(row))
    return messages


def _read_context_file(path: Path, max_chars: int = 1200) -> str:
    """Read a UTF-8 text file and clip it for prompt-safe bootstrap context."""
    try:
        text = path.read_text(encoding="utf-8", errors="replace").strip()
    except Exception:
        return ""
    if not text:
        return ""
    if len(text) > max_chars:
        text = text[: max_chars - 3].rstrip() + "..."
    return text


def _run_context_command(args: list[str], timeout: int = 5, max_chars: int = 1200) -> str:
    """Run a short local helper command and clip stdout for prompt bootstrap."""
    try:
        no_window = getattr(subprocess, "CREATE_NO_WINDOW", 0x08000000)
        result = subprocess.run(
            args,
            cwd=str(_PROJECT_ROOT),
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=timeout,
            creationflags=no_window,
        )
    except Exception:
        return ""

    output = (result.stdout or "").strip()
    if not output:
        return ""
    if len(output) > max_chars:
        output = output[: max_chars - 3].rstrip() + "..."
    return output


def _load_runtime_config() -> dict:
    """Load per-PC runtime configuration with legacy fallback."""
    for candidate in (_CONFIG_FILE, _LEGACY_CONFIG_FILE):
        try:
            if candidate.exists():
                return json.loads(candidate.read_text(encoding="utf-8"))
        except Exception:
            continue
    return {}


def _summarize_feature_list(max_items: int = 4) -> str:
    """Summarize current feature pass/fail state for Codex bootstrap."""
    feature_path = _PROJECT_ROOT / "feature_list.json"
    try:
        payload = json.loads(feature_path.read_text(encoding="utf-8"))
    except Exception:
        return ""

    features = payload.get("features")
    if not isinstance(features, list) or not features:
        return ""

    pending: list[str] = []
    completed = 0
    for feature in features:
        if not isinstance(feature, dict):
            continue
        fid = str(feature.get("id") or "?")
        description = str(feature.get("description") or "").strip()
        if feature.get("passes") is True:
            completed += 1
            continue
        label = f"{fid} {description}".strip()
        pending.append(label)

    lines = [f"- completed: {completed}/{len(features)}"]
    if pending:
        lines.append("- pending:")
        for item in pending[:max_items]:
            lines.append(f"  - {item}")
    else:
        lines.append("- pending: none")
    return "\n".join(lines)


def _summarize_progress(max_items: int = 3) -> str:
    """Summarize the most recent progress.md state for Codex bootstrap."""
    progress_path = _PROJECT_ROOT / "progress.md"
    try:
        text = progress_path.read_text(encoding="utf-8", errors="replace")
    except Exception:
        return ""

    lines = [line.rstrip() for line in text.splitlines()]
    updated_line = next((line.strip() for line in lines if line.startswith("## ")), "")

    active_items: list[str] = []
    in_progress = False
    section_index = 0
    for raw in lines:
        stripped = raw.strip()
        if stripped.startswith("### "):
            section_index += 1
            in_progress = section_index == 2
            continue
        if in_progress and stripped.startswith("- "):
            active_items.append(stripped)
            if len(active_items) >= max_items:
                break

    if not updated_line and not active_items:
        return ""

    result: list[str] = []
    if updated_line:
        result.append(updated_line)
    if active_items:
        result.append("In progress:")
        result.extend(active_items)
    return "\n".join(result)


def _summarize_harness_status() -> str:
    """Run harness_verify and return a compact status summary."""
    harness_script = _SCRIPT_DIR / "harness_verify.py"
    if not harness_script.exists():
        return ""

    raw = _run_context_command(
        [sys.executable, str(harness_script), "--json"],
        timeout=8,
        max_chars=4000,
    )
    if not raw:
        return ""

    try:
        payload = json.loads(raw)
    except Exception:
        return raw

    summary = payload.get("summary") or {}
    warnings = payload.get("details", {}).get("warnings") or []
    lines = [
        f"- status: {payload.get('status', 'unknown')}",
        f"- passes: {summary.get('passes', 0)}",
        f"- warnings: {summary.get('warnings', 0)}",
        f"- errors: {summary.get('errors', 0)}",
    ]
    if warnings:
        lines.append(f"- first warning: {warnings[0]}")
    return "\n".join(lines)


def _build_project_bootstrap(agent_name: str) -> str:
    """Build a compact project bootstrap block for agents without repo hooks."""
    if agent_name != "codex":
        return ""

    sections: list[str] = [
        "[Session init]\n"
        f"- cwd: {_PROJECT_ROOT}\n"
        "- protocol: pwd -> memory.py list -> analyze_hive.py -> feature_list.json -> git log -> harness_verify.py"
    ]

    feature_summary = _summarize_feature_list()
    if feature_summary:
        sections.append(f"[Feature status]\n{feature_summary}")

    progress_summary = _summarize_progress()
    if progress_summary:
        sections.append(f"[Progress snapshot]\n{progress_summary}")

    harness_summary = _summarize_harness_status()
    if harness_summary:
        sections.append(f"[Harness status]\n{harness_summary}")

    sections.append(
        "[Execution guardrails]\n"
        "- Follow RULES.md before making changes.\n"
        "- Use PROJECT_MAP.md and memory.md to stay aligned with repo direction.\n"
        "- Keep scope narrow to the assigned task and referenced files.\n"
        "- Prefer targeted edits plus validation over broad refactors."
    )

    docs = [
        ("Core rules", _PROJECT_ROOT / "RULES.md", 1000),
        ("Project map", _PROJECT_ROOT / "PROJECT_MAP.md", 1200),
        ("Long-term memory", _PROJECT_ROOT / "memory.md", 900),
    ]
    for label, path, limit in docs:
        excerpt = _read_context_file(path, max_chars=limit)
        if excerpt:
            sections.append(f"[{label}: {path.name}]\n{excerpt}")

    py = sys.executable
    runtime_commands = [
        ("Hive memory", [py, str(_SCRIPT_DIR / "memory.py"), "list"], 6, 1000),
        ("Hive summary", [py, str(_SCRIPT_DIR / "orchestrator.py"), "--summary"], 6, 1000),
        ("Hive analysis", [py, str(_SCRIPT_DIR / "analyze_hive.py")], 6, 1000),
        ("Recent commits", ["git", "log", "--oneline", "-5"], 6, 800),
    ]
    for label, args, timeout, limit in runtime_commands:
        output = _run_context_command(args, timeout=timeout, max_chars=limit)
        if output:
            sections.append(f"[{label}]\n{output}")

    runtime_config = _load_runtime_config()
    local_prompt = str(runtime_config.get("codex_boot_prompt") or "").strip()
    if local_prompt:
        sections.append(f"[Local codex operator prompt]\n{local_prompt}")

    return "\n\n".join(section for section in sections if section)


def build_agent_context(
    agent_name: str,
    *,
    include_unread: bool = True,
    include_debate: bool = True,
    include_project_bootstrap: bool = False,
    mark_read: bool = True,
    max_messages: int = 5,
    unread_messages: Optional[list[dict]] = None,
) -> str:
    """Build extra prompt context for agents without native inbox hooks.

    This is primarily used by Codex launches, because Claude/Gemini already
    inject ITCP inbox state through their own hook systems.
    """
    sections: list[str] = []

    if include_unread:
        unread = unread_messages if unread_messages is not None else receive(agent_name, mark_read=mark_read)
        if unread:
            lines = []
            for message in unread[:max_messages]:
                sender = message.get("from_agent") or message.get("from") or "?"
                channel_name = message.get("channel") or "general"
                content = str(message.get("content") or "").strip()
                lines.append(f"- [{sender} -> {agent_name}] ({channel_name}) {content}")
            sections.append("[ITCP inbox]\n" + "\n".join(lines))

    if include_debate:
        debate_json = os.environ.get("HIVE_DEBATE_CONTEXT", "").strip()
        if debate_json:
            sections.append("[Hive debate context]\n" + debate_json)

    if include_project_bootstrap:
        bootstrap = _build_project_bootstrap(agent_name)
        if bootstrap:
            sections.append("[Project bootstrap]\n" + bootstrap)

    return "\n\n".join(section for section in sections if section)


def inject_agent_context(
    task: str,
    agent_name: str,
    *,
    include_unread: bool = True,
    include_debate: bool = True,
    include_project_bootstrap: bool = False,
    mark_read: bool = True,
    max_messages: int = 5,
    unread_messages: Optional[list[dict]] = None,
) -> str:
    """Prepend agent inbox/debate context to a task prompt when available."""
    extra = build_agent_context(
        agent_name,
        include_unread=include_unread,
        include_debate=include_debate,
        include_project_bootstrap=include_project_bootstrap,
        mark_read=mark_read,
        max_messages=max_messages,
        unread_messages=unread_messages,
    )
    if not extra:
        return task
    return f"{extra}\n\n[Assigned task]\n{task}"


_TASK_ID_RE = re.compile(r"TASK-\d{8,14}-[A-Za-z0-9]+")
_AUTHOR_RE = re.compile(r"작성자:\s*([A-Za-z0-9_-]+)")


def parse_task_reference(message: dict) -> dict:
    """Extract dispatch/review identifiers from an ITCP message."""
    metadata = message.get("metadata")
    if not isinstance(metadata, dict):
        metadata = {}
    content = str(message.get("content") or "")
    channel = str(message.get("channel") or "")

    task_id = str(metadata.get("task_id") or "")
    if not task_id:
        match = _TASK_ID_RE.search(content)
        if match:
            task_id = match.group(0)

    author = str(metadata.get("author") or "")
    if not author:
        match = _AUTHOR_RE.search(content)
        if match:
            author = match.group(1)

    verifier = str(metadata.get("verifier") or "")
    assigned_to = str(metadata.get("assigned_to") or "")
    parent_task_id = str(metadata.get("parent_task_id") or "")

    kind = ""
    if "[CROSS-VERIFY]" in content or channel == "review":
        kind = "review"
    elif "[AUTO-DISPATCH]" in content or channel == "task":
        kind = "task"

    return {
        "kind": kind,
        "task_id": task_id,
        "author": author,
        "verifier": verifier,
        "assigned_to": assigned_to,
        "parent_task_id": parent_task_id,
        "content": content,
        "channel": channel,
        "from_agent": str(message.get("from_agent") or message.get("from") or ""),
        "to_agent": str(message.get("to_agent") or ""),
        "terminal_id": str(message.get("terminal_id") or ""),
        "metadata": metadata,
    }


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
