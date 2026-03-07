# -*- coding: utf-8 -*-
"""
FILE: .ai_monitor/bin/mcp_server.py
DESCRIPTION: Vibe Coding MCP stdio 서버.
             Gemini CLI / Claude Desktop에서 호출하는 MCP 도구 서버입니다.
             JSON-RPC 2.0 (stdio transport)으로 vibe-coding 툴셋을 노출합니다.

REVISION HISTORY:
- 2026-03-08 Claude-1: 최초 구현 (MCP stdio 서버, 기본 도구 3종 탑재)
"""

import sys
import json
import subprocess
from pathlib import Path

# ── 경로 설정 ──────────────────────────────────────────────────────────────────
BIN_DIR       = Path(__file__).resolve().parent
AI_MONITOR_DIR = BIN_DIR.parent
PROJECT_ROOT  = AI_MONITOR_DIR.parent
SCRIPTS_DIR   = PROJECT_ROOT / "scripts"
PYTHON_BIN    = AI_MONITOR_DIR / "venv" / "Scripts" / "python.exe"

# ── MCP 도구 정의 ──────────────────────────────────────────────────────────────
# MCP 프로토콜 tools/list에 응답할 도구 목록입니다.
TOOLS = [
    {
        "name": "vibe_run_agent",
        "description": "Vibe Coding 에이전트(CLI Agent)에게 작업을 지시합니다.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "task": {"type": "string", "description": "에이전트에게 내릴 지시 내용"},
                "yolo": {"type": "boolean", "description": "자율 모드(YOLO) 여부", "default": False}
            },
            "required": ["task"]
        }
    },
    {
        "name": "vibe_hive_status",
        "description": "Vibe Coding 하이브 마인드의 현재 상태와 최근 작업 로그를 반환합니다.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "lines": {"type": "integer", "description": "반환할 최근 로그 줄 수", "default": 20}
            }
        }
    },
    {
        "name": "vibe_memory_list",
        "description": "하이브 마인드 공유 메모리 항목 목록을 반환합니다.",
        "inputSchema": {"type": "object", "properties": {}}
    }
]


# ── 도구 실행 핸들러 ────────────────────────────────────────────────────────────
def handle_tool_call(name: str, args: dict) -> str:
    """도구 이름과 인자를 받아 결과 문자열을 반환합니다."""

    if name == "vibe_run_agent":
        task = args.get("task", "")
        yolo = args.get("yolo", False)
        cli_script = SCRIPTS_DIR / ("cli_agent.py" if yolo else "terminal_agent.py")
        cmd = [str(PYTHON_BIN), str(cli_script), task]
        try:
            result = subprocess.run(cmd, capture_output=True, text=True, timeout=120,
                                    cwd=str(PROJECT_ROOT))
            return result.stdout or result.stderr or "(출력 없음)"
        except subprocess.TimeoutExpired:
            return "[오류] 에이전트 실행 시간 초과 (120초)"
        except Exception as e:
            return f"[오류] {e}"

    elif name == "vibe_hive_status":
        lines = args.get("lines", 20)
        log_file = AI_MONITOR_DIR / "data" / "task_logs.jsonl"
        if not log_file.exists():
            return "(task_logs.jsonl 없음)"
        try:
            all_lines = log_file.read_text(encoding="utf-8").splitlines()
            return "\n".join(all_lines[-lines:])
        except Exception as e:
            return f"[오류] {e}"

    elif name == "vibe_memory_list":
        memory_script = SCRIPTS_DIR / "memory.py"
        try:
            result = subprocess.run([str(PYTHON_BIN), str(memory_script), "list"],
                                    capture_output=True, text=True, timeout=30,
                                    cwd=str(PROJECT_ROOT))
            return result.stdout or result.stderr or "(메모리 없음)"
        except Exception as e:
            return f"[오류] {e}"

    return f"[오류] 알 수 없는 도구: {name}"


# ── MCP JSON-RPC stdio 루프 ────────────────────────────────────────────────────
def send(obj: dict):
    """JSON-RPC 메시지를 stdout으로 출력합니다."""
    print(json.dumps(obj, ensure_ascii=False), flush=True)


def main():
    # stdin을 한 줄씩 읽으며 MCP 요청을 처리합니다.
    for line in sys.stdin:
        line = line.strip()
        if not line:
            continue
        try:
            req = json.loads(line)
        except json.JSONDecodeError:
            continue

        req_id  = req.get("id")
        method  = req.get("method", "")
        params  = req.get("params", {})

        # MCP 초기화 핸드셰이크
        if method == "initialize":
            send({
                "jsonrpc": "2.0", "id": req_id,
                "result": {
                    "protocolVersion": "2024-11-05",
                    "capabilities": {"tools": {}},
                    "serverInfo": {"name": "vibe-coding", "version": "1.0.0"}
                }
            })

        # 도구 목록 반환
        elif method == "tools/list":
            send({"jsonrpc": "2.0", "id": req_id, "result": {"tools": TOOLS}})

        # 도구 실행
        elif method == "tools/call":
            tool_name = params.get("name", "")
            tool_args = params.get("arguments", {})
            output = handle_tool_call(tool_name, tool_args)
            send({
                "jsonrpc": "2.0", "id": req_id,
                "result": {
                    "content": [{"type": "text", "text": output}],
                    "isError": False
                }
            })

        # notifications/initialized — 응답 불필요 (notification)
        elif method == "notifications/initialized":
            pass

        else:
            send({
                "jsonrpc": "2.0", "id": req_id,
                "error": {"code": -32601, "message": f"지원하지 않는 메서드: {method}"}
            })


if __name__ == "__main__":
    main()
