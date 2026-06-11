# -*- coding: utf-8 -*-
"""
FILE: scripts/antigravity_hook.py
DESCRIPTION: Antigravity CLI hook integration.
             대시보드 유지, 하이브 로그 기록, HIVEMIND.md 갱신, JSON 훅 응답 반환.

REVISION HISTORY:
- 2026-03-17 Claude: BeforeAgent에서 작업 시작 시 pg_logs + pg_thoughts 자동 기록 추가
  - 다른 에이전트가 Antigravity가 뭘 하는지 하이브에서 볼 수 있도록 강제
  - 하이브 마인드 핵심 원칙: 모든 에이전트 활동은 공유되어야 함
"""

from __future__ import annotations

import io
import json
import os
import subprocess
import sys
import time
import urllib.request
from datetime import datetime
from pathlib import Path


ROOT_DIR = Path(__file__).resolve().parent.parent
MONITOR_DIR = ROOT_DIR / ".ai_monitor"
DATA_DIR = MONITOR_DIR / "data"
STAMP_DIR = DATA_DIR / "hook_stamps"
SCRIPT_DIR = Path(__file__).resolve().parent

for path in (MONITOR_DIR, SCRIPT_DIR):
    if str(path) not in sys.path:
        sys.path.insert(0, str(path))


# [2026-03-18 Claude] stdout/stderr 분리 순서 수정
# Antigravity CLI 훅 프로토콜: stdout에 JSON 응답만 출력해야 함
# 기존 문제: sys.stdout = sys.stderr 후 stderr를 교체하면 stdout이 stale 참조를 가리킴
# 수정: stderr를 먼저 래핑한 뒤 stdout을 리다이렉트

# 1) stderr UTF-8 래핑 (먼저!)
if sys.stderr.encoding and sys.stderr.encoding.lower() not in ("utf-8", "utf8"):
    try:
        sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding="utf-8", errors="replace")
    except Exception:
        pass

# 2) 원본 stdout 보존 (JSON 응답용) → 이후 print()는 stderr로 감
_real_stdout = sys.stdout
sys.stdout = sys.stderr


SKIP_SHELL_PREFIXES = (
    "ls ",
    "ls\n",
    "cat ",
    "head ",
    "tail ",
    "echo ",
    "pwd",
    "git status",
    "git log",
    "git diff",
    "python scripts/memory.py",
)

INTENT_RULES = [
    {
        "name": "bug_fix",
        "keywords": ["bug", "error", "fix", "debug", "문제", "버그", "에러", "고쳐"],
        "context": (
            "[Auto context: debugging]\n"
            "Work this as a reproducible bug fix. Verify the failure mode first, "
            "make the smallest correct change, and run a direct validation step before reporting back."
        ),
    },
    {
        "name": "new_feature",
        "keywords": ["feature", "create", "implement", "추가", "구현", "만들어"],
        "context": (
            "[Auto context: feature work]\n"
            "Start from a concrete plan, keep the scope explicit, and validate the finished flow "
            "before closing the task."
        ),
    },
]


SESSION_MODIFIED_FILES: list[str] = []
SESSION_LAST_TASK: str = ""
SESSION_HAD_ERROR: bool = False


def _stamp_path(name: str) -> Path:
    STAMP_DIR.mkdir(parents=True, exist_ok=True)
    return STAMP_DIR / f"{name}.stamp"


def _touch_stamp(name: str) -> None:
    path = _stamp_path(name)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(str(time.time()), encoding="utf-8")


def _should_attempt(name: str, interval_seconds: int) -> bool:
    path = _stamp_path(name)
    if path.exists():
        age = time.time() - path.stat().st_mtime
        if age < interval_seconds:
            return False
    _touch_stamp(name)
    return True


def _success_response() -> None:
    _real_stdout.write("{}\n")
    _real_stdout.flush()


def _hook_response(decision: str = "allow", context: str | None = None) -> None:
    payload = {"decision": decision}
    if context:
        payload["hookSpecificOutput"] = {"additionalContext": context}
    _real_stdout.write(json.dumps(payload, ensure_ascii=False) + "\n")
    _real_stdout.flush()


def _send_heartbeat(status: str = "active", task: str = "Thinking...") -> None:
    try:
        data = json.dumps({"agent": "Antigravity", "status": status, "task": task}).encode("utf-8")
        request = urllib.request.Request(
            "http://localhost:9000/api/agents/heartbeat",
            data=data,
            headers={"Content-Type": "application/json"},
        )
        urllib.request.urlopen(request, timeout=0.5)
    except Exception:
        pass


def _server_alive() -> bool:
    try:
        with urllib.request.urlopen("http://localhost:9000/api/agents/heartbeat", timeout=0.3) as response:
            return response.status == 200
    except Exception:
        return False


def _spawn_background(args: list[str]) -> None:
    creationflags = getattr(subprocess, "CREATE_NO_WINDOW", 0x08000000) if sys.platform == "win32" else 0
    subprocess.Popen(
        args,
        cwd=str(ROOT_DIR),
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        creationflags=creationflags,
    )


def _ensure_dashboard_running() -> None:
    if not _server_alive() and _should_attempt("dashboard_server", 30):
        server_script = MONITOR_DIR / "server.py"
        if server_script.exists():
            try:
                _spawn_background([sys.executable, "-X", "utf8", str(server_script)])
            except Exception:
                pass

    if _should_attempt("dashboard_ui", 45):
        ui_script = MONITOR_DIR / "mission_control_ui.py"
        if ui_script.exists():
            try:
                _spawn_background([sys.executable, "-X", "utf8", str(ui_script)])
            except Exception:
                pass


def _refresh_hivemind_doc(force: bool = False) -> None:
    if not force and not _should_attempt("hivemind_refresh", 5):
        return
    script_path = SCRIPT_DIR / "generate_hivemind_doc.py"
    if not script_path.exists():
        return
    try:
        _spawn_background([sys.executable, str(script_path)])
    except Exception:
        pass


def _read_antigravity_messages(agent_name: str) -> list[dict]:
    try:
        from itcp import receive as itcp_receive
        # [2026-03-18 Claude] 터미널 ID 전달 — 같은 에이전트 간 자기 메시지 제외
        _tid = os.environ.get('TERMINAL_ID', 'T2')
        return itcp_receive(agent_name, mark_read=True, my_terminal_id=_tid)
    except Exception:
        return []


def _send_session_summary() -> None:
    logs_file = DATA_DIR / "task_logs.jsonl"
    if not logs_file.exists():
        return

    today = datetime.now().strftime("%Y-%m-%d")
    actions: list[str] = []

    try:
        with logs_file.open("r", encoding="utf-8", errors="replace") as handle:
            for raw_line in handle:
                raw_line = raw_line.strip()
                if not raw_line:
                    continue
                try:
                    entry = json.loads(raw_line)
                except Exception:
                    continue
                if not str(entry.get("timestamp", "")).startswith(today):
                    continue
                if entry.get("agent") != "Antigravity":
                    continue
                task = str(entry.get("task", ""))
                if any(marker in task for marker in ("[edit done]", "[create done]", "[run done]", "[commit]")):
                    actions.append(task)
    except Exception:
        return

    if not actions:
        return

    summary = "\n".join(actions[-10:])
    try:
        from itcp import send as itcp_send

        itcp_send(
            from_terminal="antigravity",
            to_terminal="claude",
            content=f"[Antigravity session summary {today}]\n{summary}",
            channel="hive",
            msg_type="session_summary",
        )
    except Exception:
        pass


def _snippet(text: str, max_len: int = 80) -> str:
    if not text:
        return ""
    compact = " ".join(str(text).split())
    if len(compact) <= max_len:
        return compact
    return compact[: max_len - 3] + "..."


def _short_cmd(command: str, max_len: int = 100) -> str:
    return _snippet(command.replace("\n", " "), max_len=max_len)


def _short_path(file_path: str, depth: int = 3) -> str:
    parts = str(file_path).replace("\\", "/").split("/")
    return "/".join(parts[-depth:]) if len(parts) >= depth else str(file_path)


def _get_tool_name(payload: dict) -> str:
    return str(payload.get("tool_name") or payload.get("tool") or payload.get("name") or "")


def _get_tool_input(payload: dict):
    return payload.get("tool_input") or payload.get("input") or payload.get("args") or {}


def _tool_path(tool_input) -> str:
    if isinstance(tool_input, dict):
        return str(
            tool_input.get("path")
            or tool_input.get("file_path")
            or tool_input.get("filename")
            or tool_input.get("target_file")
            or "?"
        )
    return "?"


def _tool_command(tool_input) -> str:
    if not isinstance(tool_input, dict):
        return ""
    return str(tool_input.get("command") or tool_input.get("cmd") or tool_input.get("code") or "")


def _tool_content(tool_input) -> str:
    if not isinstance(tool_input, dict):
        return ""
    return str(tool_input.get("content") or tool_input.get("text") or tool_input.get("new") or "")


def _extract_result_text(tool_result) -> str:
    if isinstance(tool_result, str):
        return _snippet(tool_result)
    if isinstance(tool_result, dict):
        # Antigravity CLI의 run_shell_command 결과는 stdout, stderr, output 등을 포함할 수 있음
        for key in ("stdout", "output", "content", "message", "result", "stderr"):
            value = tool_result.get(key)
            if value:
                return _snippet(str(value))
        return _snippet(json.dumps(tool_result, ensure_ascii=False))
    return _snippet(str(tool_result))


def _register_prompt_task(prompt: str) -> None:
    if not prompt.strip():
        return
    try:
        from src.pg_store import save_task

        payload = {
            "id": datetime.now().strftime("%Y%m%d%H%M%S%f"),
            "title": _snippet(prompt, 80),
            "description": prompt[:500],
            "status": "in_progress",
            "assigned_to": "antigravity",
            "priority": "medium",
            "created_by": "user",
            "created_at": datetime.now().isoformat(),
        }
        save_task(payload)
    except Exception:
        pass


def _build_additional_context(prompt: str) -> str:
    sections: list[str] = []

    unread = _read_antigravity_messages("antigravity")
    if unread:
        # [2026-03-27 Claude] 무한루프 방지: 자기참조/중복 메시지 필터링
        # 1) Antigravity 자신이 보낸 메시지 (session_summary, task_result 등) 제외
        # 2) dispatcher broadcast 중 Antigravity에게 이미 직접 전달된 태스크 중복 제외
        # 3) 검증 결과(verify_result)로 인한 재진입 방지
        _SELF_MSG_TYPES = {"session_summary", "response"}
        _SELF_CONTENT_MARKERS = {"[TASK-RESULT]", "[VERIFY-RESULT]", "[Antigravity session summary"}
        filtered = []
        for message in unread:
            sender = message.get("from_agent") or message.get("from") or "?"
            msg_type = message.get("msg_type") or message.get("type") or ""
            content = message.get("content", "")

            # 자기가 보낸 메시지 무시
            if sender.lower() == "antigravity":
                continue

            # 결과/응답 메시지 무시 (재진입 루프 방지)
            if msg_type in _SELF_MSG_TYPES:
                continue

            # 태스크 결과/검증 결과 메시지 무시
            if any(marker in content for marker in _SELF_CONTENT_MARKERS):
                continue

            # dispatcher broadcast 중 이미 직접 수신된 태스크 중복 제거
            # (broadcast to_agent='all' + 직접 send to_agent='antigravity' 이중 수신 방지)
            to_agent = message.get("to_agent", "")
            if sender == "dispatcher" and to_agent == "all" and "[DISPATCH]" in content:
                continue

            filtered.append(message)

        lines = []
        for message in filtered:
            sender = message.get("from_agent") or message.get("from") or "?"
            msg_type = message.get("channel") or message.get("msg_type") or message.get("type") or "info"
            content = message.get("content", "")
            lines.append(f"- [{sender} -> antigravity] ({msg_type}) {content}")
        if lines:
            sections.append("[Claude messages]\n" + "\n".join(lines))

    lowered_prompt = prompt.lower()
    for rule in INTENT_RULES:
        if any(keyword.lower() in lowered_prompt for keyword in rule["keywords"]):
            sections.append(rule["context"])
            break

    return "\n\n".join(section for section in sections if section)


def _log_tool_start(log_task, tool_name: str, tool_input) -> None:
    if tool_name in ("write_file", "create_file", "overwrite_file"):
        file_path = _tool_path(tool_input)
        preview = _snippet(_tool_content(tool_input), 60)
        log_task("Antigravity", f"[create start] {_short_path(file_path)} :: {preview or '(empty)'}")
        return

    if tool_name in ("replace", "edit_file", "str_replace"):
        file_path = _tool_path(tool_input)
        old_text = _snippet(str(tool_input.get("old_str") or tool_input.get("old_string") or tool_input.get("old") or ""), 40)
        new_text = _snippet(str(tool_input.get("new_str") or tool_input.get("new_string") or tool_input.get("new") or tool_input.get("content") or ""), 40)
        parts = [f"[edit start] {_short_path(file_path)}"]
        if old_text:
            parts.append(f"from={old_text}")
        if new_text:
            parts.append(f"to={new_text}")
        log_task("Antigravity", " | ".join(parts))
        return

    if tool_name in ("run_shell_command", "shell", "bash", "execute_command"):
        command = _tool_command(tool_input).strip()
        if command and not any(command.startswith(prefix) for prefix in SKIP_SHELL_PREFIXES):
            log_task("Antigravity", f"[run start] {_short_cmd(command)}")


def _log_tool_finish(log_task, log_thought, tool_name: str, tool_input, tool_result) -> None:
    global SESSION_MODIFIED_FILES
    result_text = _extract_result_text(tool_result)

    if tool_name in ("write_file", "create_file", "overwrite_file"):
        file_path = _tool_path(tool_input)
        content = _tool_content(tool_input)
        line_count = len(content.splitlines()) if content else 0
        log_task("Antigravity", f"[create done] {_short_path(file_path)} lines={line_count}")
        log_thought(
            "antigravity",
            "file-write",
            {
                "type": "action",
                "title": f"File created: {_short_path(file_path)}",
                "content": f"lines={line_count} preview={_snippet(content, 80)}",
            },
        )
        short_path = _short_path(file_path)
        if short_path not in SESSION_MODIFIED_FILES:
            SESSION_MODIFIED_FILES.append(short_path)
        return

    if tool_name in ("replace", "edit_file", "str_replace"):
        file_path = _tool_path(tool_input)
        suffix = f" -> {result_text}" if result_text else ""
        log_task("Antigravity", f"[edit done] {_short_path(file_path)}{suffix}")
        log_thought(
            "antigravity",
            "file-edit",
            {
                "type": "action",
                "title": f"File edited: {_short_path(file_path)}",
                "content": result_text or "success",
            },
        )
        short_path = _short_path(file_path)
        if short_path not in SESSION_MODIFIED_FILES:
            SESSION_MODIFIED_FILES.append(short_path)
        return

    if tool_name in ("run_shell_command", "shell", "bash", "execute_command"):
        command = _tool_command(tool_input).strip()
        if not command or any(command.startswith(prefix) for prefix in SKIP_SHELL_PREFIXES):
            return
        if "git commit" in command:
            log_task("Antigravity", f"[commit] {_short_cmd(command)}")
            log_thought(
                "antigravity",
                "git",
                {
                    "type": "decision",
                    "title": "Git commit",
                    "content": _short_cmd(command),
                },
            )
            return
        suffix = f" -> {result_text}" if result_text else ""
        log_task("Antigravity", f"[run done] {_short_cmd(command, 60)}{suffix}")


def main() -> None:
    # Windows 환경에서 PAGER=cat으로 인해 psql/git 등이 먹통되는 문제 방지
    if sys.platform == "win32":
        os.environ["PAGER"] = ""

    try:
        raw = sys.stdin.buffer.read().decode("utf-8", errors="replace")
        if not raw.strip():
            _success_response()
            return
        payload = json.loads(raw)
    except Exception:
        _success_response()
        return

    event = str(payload.get("hook_event_name") or "")

    if event == "BeforeAgent":
        # [2026-03-18 Claude] BeforeAgent는 최대한 빠르게 JSON만 반환해야 함
        # 무거운 작업(대시보드 체크, DB 기록, 하트비트)은 전부 제거 — 타임아웃 유발 원인
        # 이 작업들은 AfterTool/SessionEnd에서 수행
        global SESSION_LAST_TASK, SESSION_MODIFIED_FILES, SESSION_HAD_ERROR
        prompt = str(payload.get("prompt") or "")
        SESSION_LAST_TASK = prompt.strip()
        SESSION_MODIFIED_FILES = []
        SESSION_HAD_ERROR = False

        # [2026-03-27 Claude] 세션 히스토리 자동 수리 (백그라운드)
        # Antigravity CLI가 이미지 파일 read_file 시 result에 inlineData + functionResponse
        # 2개 파트를 넣어 API 400 에러 유발 → 세션 시작 시 자동 정리
        _repair_script = SCRIPT_DIR / "antigravity_session_repair.py"
        if _repair_script.exists():
            try:
                subprocess.Popen(
                    [sys.executable, str(_repair_script)],
                    stdout=subprocess.DEVNULL,
                    stderr=subprocess.DEVNULL,
                    creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
                )
            except Exception:
                pass

        # ITCP 수신 + 의도 감지만 수행 (가벼움)
        additional_context = _build_additional_context(prompt)

        if additional_context:
            _hook_response(decision="allow", context=additional_context)
        else:
            _hook_response(decision="allow")
        return

    try:
        from hive_bridge import log_task, log_thought
    except ImportError:
        _success_response()
        return

    tool_name = _get_tool_name(payload)
    tool_input = _get_tool_input(payload)

    if event == "BeforeTool":
        _log_tool_start(log_task, tool_name, tool_input)

    elif event == "AfterTool":
        tool_result = payload.get("tool_result") or payload.get("result") or payload.get("output") or payload.get("response") or {}
        _log_tool_finish(log_task, log_thought, tool_name, tool_input, tool_result)
        _refresh_hivemind_doc(force=False)

    elif event == "SessionEnd":
        log_task("Antigravity", "Session end")
        try:
            from src.pg_store import bulk_update_tasks

            bulk_update_tasks("antigravity", ["pending", "in_progress"], "done")
        except Exception:
            pass
        # [2026-06-11] _report_completed_itcp_work 제거 — auto_dispatcher 폐기로
        # import가 항상 실패하던 죽은 경로였음 (2차 정리 보류분)
        _send_session_summary()
        _refresh_hivemind_doc(force=True)

    _success_response()


if __name__ == "__main__":
    try:
        main()
    except Exception:
        # [2026-03-18 Claude] 어떤 예외든 훅이 유효한 JSON 응답을 반환해야 함
        # Gemini CLI는 훅이 비정상 종료하면 "hook failed" 경고를 표시함
        try:
            _real_stdout.write("{}\n")
            _real_stdout.flush()
        except Exception:
            pass
