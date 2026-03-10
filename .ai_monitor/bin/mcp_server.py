# -*- coding: utf-8 -*-
"""
Minimal MCP stdio server for the local vibe-coding workspace.

This server exposes a few local helper tools to MCP-capable clients such as
Codex CLI. Different MCP clients on Windows do not always agree on stdio
framing, so this server mirrors the transport style used by the client:
Content-Length framing or line-delimited JSON.
"""

import json
import subprocess
import sys
from pathlib import Path


BIN_DIR = Path(__file__).resolve().parent
AI_MONITOR_DIR = BIN_DIR.parent
PROJECT_ROOT = AI_MONITOR_DIR.parent
SCRIPTS_DIR = PROJECT_ROOT / "scripts"
PYTHON_BIN = AI_MONITOR_DIR / "venv" / "Scripts" / "python.exe"


TOOLS = [
    {
        "name": "vibe_run_agent",
        "description": "Run a local Vibe Coding CLI agent task.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "task": {
                    "type": "string",
                    "description": "Instruction to pass to the agent",
                },
                "yolo": {
                    "type": "boolean",
                    "description": "Use the more autonomous CLI entrypoint",
                    "default": False,
                },
            },
            "required": ["task"],
        },
    },
    {
        "name": "vibe_hive_status",
        "description": "Return recent hive status log lines.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "lines": {
                    "type": "integer",
                    "description": "How many recent log lines to return",
                    "default": 20,
                }
            },
        },
    },
    {
        "name": "vibe_memory_list",
        "description": "List shared hive memory items from PostgreSQL hive_memory table.",
        "inputSchema": {"type": "object", "properties": {}},
    },
    # ── ITCP: Inter-Terminal Communication Protocol 도구 ─────────────────────
    # Codex가 Claude/Gemini와 PostgreSQL을 통해 메시지를 주고받을 수 있습니다.
    {
        "name": "itcp_send",
        "description": (
            "Send a message to another terminal agent via the Hive ITCP protocol (PostgreSQL pg_messages). "
            "Use this to communicate with Claude or Gemini terminals. "
            "to_terminal: 'claude', 'gemini', 'all' (broadcast). "
            "channel: 'general', 'task', 'debug', 'review', 'broadcast', 'hive'."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "to_terminal": {
                    "type": "string",
                    "description": "Recipient: 'claude', 'gemini', or 'all'",
                },
                "content": {
                    "type": "string",
                    "description": "Message content",
                },
                "channel": {
                    "type": "string",
                    "description": "Channel: general/task/debug/review/broadcast/hive",
                    "default": "general",
                },
                "msg_type": {
                    "type": "string",
                    "description": "Type: info/request/response/alert/summary",
                    "default": "info",
                },
            },
            "required": ["to_terminal", "content"],
        },
    },
    {
        "name": "itcp_receive",
        "description": (
            "Check and retrieve unread messages sent to this Codex terminal from other agents "
            "(Claude, Gemini) via PostgreSQL pg_messages. Call this at session start to catch up."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "terminal": {
                    "type": "string",
                    "description": "This terminal's name (default: 'codex')",
                    "default": "codex",
                }
            },
        },
    },
    {
        "name": "itcp_history",
        "description": "View recent inter-terminal message history from pg_messages.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "limit": {
                    "type": "integer",
                    "description": "Number of recent messages to show",
                    "default": 10,
                },
                "channel": {
                    "type": "string",
                    "description": "Filter by channel (optional)",
                    "default": "",
                },
            },
        },
    },
    {
        "name": "hive_memory_get",
        "description": (
            "Read a specific key from the Hive shared memory (PostgreSQL hive_memory table). "
            "Use this to access knowledge shared by Claude or Gemini."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "key": {
                    "type": "string",
                    "description": "Memory key to retrieve",
                },
            },
            "required": ["key"],
        },
    },
    {
        "name": "log_thought",
        "description": (
            "Record a thought/decision/action to the Hive knowledge graph (pg_thoughts table). "
            "This is how Codex appears as nodes in the Knowledge Graph visualization. "
            "Call this after completing significant actions: file edits, decisions, git commits, "
            "bug fixes, etc. Use type='decision' for architectural choices, 'action' for file "
            "changes, 'log' for general notes."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "title": {
                    "type": "string",
                    "description": "Short title for the thought (e.g. '파일 수정: App.tsx', 'Git 커밋')",
                },
                "content": {
                    "type": "string",
                    "description": "Detail of what was done or decided",
                },
                "skill": {
                    "type": "string",
                    "description": "Skill/category (e.g. 'file-edit', 'git', 'debug', 'build', 'session')",
                    "default": "general",
                },
                "type": {
                    "type": "string",
                    "description": "Node type: 'decision', 'action', or 'log'",
                    "default": "action",
                },
            },
            "required": ["title", "content"],
        },
    },
    {
        "name": "hive_memory_set",
        "description": (
            "Write a key-value entry to the Hive shared memory (PostgreSQL hive_memory table). "
            "Other agents (Claude, Gemini) will be able to read this knowledge."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "key": {
                    "type": "string",
                    "description": "Memory key",
                },
                "content": {
                    "type": "string",
                    "description": "Value / content to store",
                },
                "tags": {
                    "type": "string",
                    "description": "Comma-separated tags (e.g. 'bug,server,memory')",
                    "default": "",
                },
            },
            "required": ["key", "content"],
        },
    },
]


def send(obj: dict, transport: str = "content-length") -> None:
    body = json.dumps(obj, ensure_ascii=False).encode("utf-8")
    if transport == "jsonl":
        sys.stdout.buffer.write(body + b"\n")
    else:
        header = f"Content-Length: {len(body)}\r\n\r\n".encode("ascii")
        sys.stdout.buffer.write(header)
        sys.stdout.buffer.write(body)
    sys.stdout.buffer.flush()


def read_message():
    stdin = sys.stdin.buffer
    first_line = stdin.readline()
    if not first_line:
        return None, None

    stripped = first_line.strip()
    if stripped.startswith(b"{"):
        try:
            return json.loads(stripped.decode("utf-8")), "jsonl"
        except json.JSONDecodeError:
            return None, "jsonl"

    headers = {}
    line = first_line
    while line:
        decoded = line.decode("ascii", errors="ignore").strip()
        if not decoded:
            break
        if ":" in decoded:
            key, value = decoded.split(":", 1)
            headers[key.strip().lower()] = value.strip()
        line = stdin.readline()

    content_length = headers.get("content-length")
    if not content_length:
        return None, "content-length"

    try:
        length = int(content_length)
    except ValueError:
        return None, "content-length"

    body = stdin.read(length)
    if not body:
        return None, "content-length"

    try:
        return json.loads(body.decode("utf-8")), "content-length"
    except json.JSONDecodeError:
        return None, "content-length"


def handle_tool_call(name: str, args: dict) -> str:
    if name == "vibe_run_agent":
        task = args.get("task", "")
        yolo = args.get("yolo", False)
        cli_script = SCRIPTS_DIR / ("cli_agent.py" if yolo else "terminal_agent.py")
        cmd = [str(PYTHON_BIN), str(cli_script), task]
        try:
            result = subprocess.run(
                cmd,
                capture_output=True,
                text=True,
                timeout=120,
                cwd=str(PROJECT_ROOT),
            )
            return result.stdout or result.stderr or "(no output)"
        except subprocess.TimeoutExpired:
            return "[error] agent execution timed out after 120 seconds"
        except Exception as exc:
            return f"[error] {exc}"

    if name == "vibe_hive_status":
        lines = args.get("lines", 20)
        log_file = AI_MONITOR_DIR / "data" / "task_logs.jsonl"
        if not log_file.exists():
            return "(task_logs.jsonl missing)"
        try:
            all_lines = log_file.read_text(encoding="utf-8").splitlines()
            return "\n".join(all_lines[-lines:])
        except Exception as exc:
            return f"[error] {exc}"

    if name == "vibe_memory_list":
        memory_script = SCRIPTS_DIR / "memory.py"
        try:
            result = subprocess.run(
                [str(PYTHON_BIN), str(memory_script), "list"],
                capture_output=True,
                text=True,
                timeout=30,
                cwd=str(PROJECT_ROOT),
            )
            return result.stdout or result.stderr or "(no memory items)"
        except Exception as exc:
            return f"[error] {exc}"

    # ── ITCP 도구 핸들러 ────────────────────────────────────────────────────
    # Codex가 Claude/Gemini와 PostgreSQL pg_messages를 통해 통신할 수 있도록 합니다.
    if name == "itcp_send":
        to_terminal = args.get("to_terminal", "all")
        content = args.get("content", "")
        channel = args.get("channel", "general")
        msg_type = args.get("msg_type", "info")
        itcp_script = SCRIPTS_DIR / "itcp.py"
        try:
            result = subprocess.run(
                [str(PYTHON_BIN), str(itcp_script), "send",
                 "codex", to_terminal, content, channel],
                capture_output=True, text=True, timeout=10,
                cwd=str(PROJECT_ROOT),
                env={**__import__("os").environ, "PGCLIENTENCODING": "UTF8"},
            )
            return result.stdout.strip() or result.stderr.strip() or "전송 완료"
        except Exception as exc:
            return f"[error] {exc}"

    if name == "itcp_receive":
        terminal = args.get("terminal", "codex")
        itcp_script = SCRIPTS_DIR / "itcp.py"
        try:
            result = subprocess.run(
                [str(PYTHON_BIN), str(itcp_script), "receive", terminal],
                capture_output=True, text=True, timeout=10,
                cwd=str(PROJECT_ROOT),
                env={**__import__("os").environ, "PGCLIENTENCODING": "UTF8"},
            )
            return result.stdout.strip() or "(미읽음 메시지 없음)"
        except Exception as exc:
            return f"[error] {exc}"

    if name == "itcp_history":
        limit = args.get("limit", 10)
        channel_filter = args.get("channel", "")
        itcp_script = SCRIPTS_DIR / "itcp.py"
        try:
            result = subprocess.run(
                [str(PYTHON_BIN), str(itcp_script), "history", str(limit)],
                capture_output=True, text=True, timeout=10,
                cwd=str(PROJECT_ROOT),
                env={**__import__("os").environ, "PGCLIENTENCODING": "UTF8"},
            )
            output = result.stdout.strip()
            if channel_filter:
                lines = [l for l in output.splitlines() if channel_filter in l or l.startswith("📜")]
                return "\n".join(lines) or f"({channel_filter} 채널 메시지 없음)"
            return output or "(메시지 없음)"
        except Exception as exc:
            return f"[error] {exc}"

    if name == "log_thought":
        # pg_thoughts에 Codex 노드 기록 — 지식 그래프에 표시됨
        title   = args.get("title", "")
        content = args.get("content", "")
        skill   = args.get("skill", "general")
        t_type  = args.get("type", "action")
        thought = {"type": t_type, "title": title, "content": content}
        # ensure_ascii=True: 한글 → \\uXXXX 이스케이프 (psql -c 인코딩 오류 방지)
        safe_thought = json.dumps(thought, ensure_ascii=True).replace("'", "''")
        sql = (f"INSERT INTO pg_thoughts (agent, skill, thought) "
               f"VALUES ('codex', '{skill}', '{safe_thought}'::jsonb);")
        try:
            pg_bin = AI_MONITOR_DIR / "bin" / "pgsql" / "bin" / "psql.exe"
            if not pg_bin.exists():
                pg_bin = Path("psql")
            result = subprocess.run(
                [str(pg_bin), "-p", "5433", "-U", "postgres", "-d", "postgres", "-c", sql],
                capture_output=True, text=True, timeout=10,
                creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
            )
            if "INSERT" in result.stdout:
                return f"[지식 그래프] Codex 노드 기록 완료: {title}"
            return f"[지식 그래프] 기록 실패: {result.stderr.strip()[:100]}"
        except Exception as exc:
            return f"[error] {exc}"

    if name == "hive_memory_get":
        key = args.get("key", "")
        memory_script = SCRIPTS_DIR / "memory.py"
        try:
            result = subprocess.run(
                [str(PYTHON_BIN), str(memory_script), "get", key],
                capture_output=True, text=True, timeout=15,
                cwd=str(PROJECT_ROOT),
            )
            return result.stdout.strip() or f"(키 '{key}' 없음)"
        except Exception as exc:
            return f"[error] {exc}"

    if name == "hive_memory_set":
        key = args.get("key", "")
        content = args.get("content", "")
        tags = args.get("tags", "")
        memory_script = SCRIPTS_DIR / "memory.py"
        try:
            cmd = [str(PYTHON_BIN), str(memory_script), "set", key, content]
            if tags:
                cmd.extend(["--tags", tags])
            result = subprocess.run(
                cmd, capture_output=True, text=True, timeout=15,
                cwd=str(PROJECT_ROOT),
            )
            return result.stdout.strip() or "저장 완료"
        except Exception as exc:
            return f"[error] {exc}"

    return f"[error] unknown tool: {name}"


def main() -> None:
    transport = "content-length"
    while True:
        req, detected_transport = read_message()
        if req is None:
            break
        if detected_transport:
            transport = detected_transport

        req_id = req.get("id")
        method = req.get("method", "")
        params = req.get("params", {})

        if method == "initialize":
            send(
                {
                    "jsonrpc": "2.0",
                    "id": req_id,
                    "result": {
                        "protocolVersion": "2024-11-05",
                        "capabilities": {"tools": {}},
                        "serverInfo": {"name": "vibe-coding", "version": "1.0.1"},
                    },
                },
                transport=transport,
            )
            continue

        if method == "notifications/initialized":
            continue

        if method == "tools/list":
            send({"jsonrpc": "2.0", "id": req_id, "result": {"tools": TOOLS}}, transport=transport)
            continue

        if method == "tools/call":
            tool_name = params.get("name", "")
            tool_args = params.get("arguments", {})
            output = handle_tool_call(tool_name, tool_args)
            send(
                {
                    "jsonrpc": "2.0",
                    "id": req_id,
                    "result": {
                        "content": [{"type": "text", "text": output}],
                        "isError": False,
                    },
                },
                transport=transport,
            )
            continue

        # Some clients probe with pings during startup.
        if method == "ping":
            send({"jsonrpc": "2.0", "id": req_id, "result": {}}, transport=transport)
            continue

        if req_id is not None:
            send(
                {
                    "jsonrpc": "2.0",
                    "id": req_id,
                    "error": {
                        "code": -32601,
                        "message": f"Unsupported method: {method}",
                    },
                },
                transport=transport,
            )


if __name__ == "__main__":
    main()
