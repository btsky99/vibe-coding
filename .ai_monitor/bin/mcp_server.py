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
        "description": "List shared hive memory items.",
        "inputSchema": {"type": "object", "properties": {}},
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
