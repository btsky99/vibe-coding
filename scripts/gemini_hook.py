# -*- coding: utf-8 -*-
"""
FILE: scripts/gemini_hook.py
DESCRIPTION: Gemini CLI hook integration.
             대시보드 유지, 하이브 로그 기록, HIVEMIND.md 갱신, JSON 훅 응답 반환.

REVISION HISTORY:
- 2026-03-17 Claude: BeforeAgent에서 작업 시작 시 pg_logs + pg_thoughts 자동 기록 추가
  - 다른 에이전트가 Gemini가 뭘 하는지 하이브에서 볼 수 있도록 강제
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


_real_stdout = sys.stdout
sys.stdout = sys.stderr

if sys.stderr.encoding and sys.stderr.encoding.lower() not in ("utf-8", "utf8"):
    try:
        sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding="utf-8", errors="replace")
    except Exception:
        pass


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
SESSION_ASSIGNED_TASKS: list[dict] = []
SESSION_REVIEW_REQUESTS: list[dict] = []


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
        data = json.dumps({"agent": "Gemini", "status": status, "task": task}).encode("utf-8")
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


def _read_gemini_messages(agent_name: str) -> list[dict]:
    try:
        from itcp import receive as itcp_receive

        return itcp_receive(agent_name, mark_read=True)
    except Exception:
        return []


def _remember_itcp_work_items(messages: list[dict]) -> None:
    global SESSION_ASSIGNED_TASKS, SESSION_REVIEW_REQUESTS
    try:
        from itcp import parse_task_reference
    except Exception:
        return

    for message in messages:
        ref = parse_task_reference(message)
        task_id = ref.get("task_id", "")
        if not task_id:
            continue
        if ref.get("kind") == "review":
            if not any(item.get("task_id") == task_id for item in SESSION_REVIEW_REQUESTS):
                SESSION_REVIEW_REQUESTS.append(ref)
        elif ref.get("kind") == "task":
            if not any(item.get("task_id") == task_id for item in SESSION_ASSIGNED_TASKS):
                SESSION_ASSIGNED_TASKS.append(ref)


def _report_completed_itcp_work(agent_name: str) -> None:
    global SESSION_ASSIGNED_TASKS, SESSION_REVIEW_REQUESTS
    if SESSION_HAD_ERROR:
        return

    summary_bits = []
    if SESSION_LAST_TASK:
        summary_bits.append(_snippet(SESSION_LAST_TASK, 120))
    if SESSION_MODIFIED_FILES:
        summary_bits.append("files=" + ", ".join(SESSION_MODIFIED_FILES[-5:]))
    summary = " | ".join(summary_bits) if summary_bits else "session completed"

    try:
        from auto_dispatcher import report_task_completion, report_verification_result
    except Exception:
        return

    while SESSION_ASSIGNED_TASKS:
        ref = SESSION_ASSIGNED_TASKS.pop(0)
        task_id = ref.get("task_id", "")
        if task_id:
            report_task_completion(task_id=task_id, author=agent_name, result_summary=summary)

    while SESSION_REVIEW_REQUESTS:
        ref = SESSION_REVIEW_REQUESTS.pop(0)
        task_id = ref.get("task_id", "")
        if task_id:
            report_verification_result(
                task_id=task_id,
                reviewer=agent_name,
                summary=summary,
                verdict="approved",
                author=ref.get("author", ""),
            )


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
                if entry.get("agent") != "Gemini":
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
            from_terminal="gemini",
            to_terminal="claude",
            content=f"[Gemini session summary {today}]\n{summary}",
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
        # Gemini CLI의 run_shell_command 결과는 stdout, stderr, output 등을 포함할 수 있음
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
            "assigned_to": "gemini",
            "priority": "medium",
            "created_by": "user",
            "created_at": datetime.now().isoformat(),
        }
        save_task(payload)
    except Exception:
        pass


def _build_additional_context(prompt: str) -> str:
    sections: list[str] = []

    unread = _read_gemini_messages("gemini")
    if unread:
        _remember_itcp_work_items(unread)
        lines = []
        for message in unread:
            sender = message.get("from_agent") or message.get("from") or "?"
            msg_type = message.get("channel") or message.get("msg_type") or message.get("type") or "info"
            content = message.get("content", "")
            lines.append(f"- [{sender} -> gemini] ({msg_type}) {content}")
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
        log_task("Gemini", f"[create start] {_short_path(file_path)} :: {preview or '(empty)'}")
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
        log_task("Gemini", " | ".join(parts))
        return

    if tool_name in ("run_shell_command", "shell", "bash", "execute_command"):
        command = _tool_command(tool_input).strip()
        if command and not any(command.startswith(prefix) for prefix in SKIP_SHELL_PREFIXES):
            log_task("Gemini", f"[run start] {_short_cmd(command)}")


def _log_tool_finish(log_task, log_thought, tool_name: str, tool_input, tool_result) -> None:
    global SESSION_MODIFIED_FILES
    result_text = _extract_result_text(tool_result)

    if tool_name in ("write_file", "create_file", "overwrite_file"):
        file_path = _tool_path(tool_input)
        content = _tool_content(tool_input)
        line_count = len(content.splitlines()) if content else 0
        log_task("Gemini", f"[create done] {_short_path(file_path)} lines={line_count}")
        log_thought(
            "gemini",
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
        log_task("Gemini", f"[edit done] {_short_path(file_path)}{suffix}")
        log_thought(
            "gemini",
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
            log_task("Gemini", f"[commit] {_short_cmd(command)}")
            log_thought(
                "gemini",
                "git",
                {
                    "type": "decision",
                    "title": "Git commit",
                    "content": _short_cmd(command),
                },
            )
            return
        suffix = f" -> {result_text}" if result_text else ""
        log_task("Gemini", f"[run done] {_short_cmd(command, 60)}{suffix}")


def main() -> None:
    # Windows 환경에서 PAGER=cat으로 인해 psql/git 등이 먹통되는 문제 방지
    if sys.platform == "win32":
        os.environ["PAGER"] = ""

    _ensure_dashboard_running()
    _send_heartbeat()

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
        global SESSION_LAST_TASK, SESSION_MODIFIED_FILES, SESSION_HAD_ERROR, SESSION_ASSIGNED_TASKS, SESSION_REVIEW_REQUESTS
        prompt = str(payload.get("prompt") or "")
        SESSION_LAST_TASK = prompt.strip()
        SESSION_MODIFIED_FILES = []
        SESSION_HAD_ERROR = False
        SESSION_ASSIGNED_TASKS = []
        SESSION_REVIEW_REQUESTS = []
        additional_context = _build_additional_context(prompt)
        _register_prompt_task(prompt)

        # ── 하이브 자동 기록: 작업 시작 시 pg_logs + pg_thoughts에 기록 ──
        # 핵심: 다른 에이전트가 "Gemini가 뭘 하고 있는지" 볼 수 있게 하는 것
        if prompt.strip():
            terminal_id = os.environ.get('TERMINAL_ID', 'T2')
            try:
                from hive_bridge import log_task as _lt, log_thought as _lth
                _lt(f'gemini:{terminal_id}', f'[작업 시작] {_snippet(prompt, 120)}')
                _lth('gemini', 'task-start', {
                    'type': 'intent',
                    'title': f'[{terminal_id}] 새 작업 수신',
                    'content': _snippet(prompt, 120),
                    'terminal': terminal_id
                })
            except Exception:
                pass

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
        log_task("Gemini", "Session end")
        try:
            from src.pg_store import bulk_update_tasks

            bulk_update_tasks("gemini", ["pending", "in_progress"], "done")
        except Exception:
            pass
        try:
            _report_completed_itcp_work("gemini")
        except Exception:
            pass
        _send_session_summary()
        _refresh_hivemind_doc(force=True)

    _success_response()


if __name__ == "__main__":
    main()
