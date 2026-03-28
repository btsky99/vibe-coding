"""그룹챗 MCP 서버 — Claude Code/Gemini CLI가 터미널에서 직접 그룹 채팅 참여.

이 MCP 서버를 Claude Code에 등록하면:
- claude 터미널에서 send_group_message("안녕") → 그룹챗에 전송
- read_group_messages() → 최근 그룹챗 메시지 조회
- 다른 에이전트의 메시지를 실시간으로 확인 가능

설정 (claude config에 추가):
{
  "mcpServers": {
    "groupchat": {
      "command": "python",
      "args": ["-m", "llm_group_chat.mcp_server"],
      "cwd": "D:/vibe-coding"
    }
  }
}

이러면 진짜 터미널에서:
- 파일 편집하면서 동시에 그룹챗 메시지를 보내고 받을 수 있음
- PTY 해킹 없이, MCP 프로토콜로 깔끔하게 통신
"""
import asyncio
import json
import sys
import threading
import time
import os

# MCP 프로토콜 — JSON-RPC over stdin/stdout
# https://modelcontextprotocol.io/specification

# 그룹챗 WebSocket 연결 (백그라운드)
_ws_connection = None
_ws_connected = False
_ws_loop = None
_received_messages: list[dict] = []
_MAX_MESSAGES = 100
_AGENT_NAME = os.environ.get("MCP_AGENT_NAME", "mcp-agent")

WS_HOST = "127.0.0.1"
WS_PORT = 8765


def _make_chat_msg(sender: str, content: str, msg_type: str = "message") -> str:
    return json.dumps({
        "type": msg_type, "sender": sender, "content": content,
        "room": "default",
        "timestamp": time.strftime("%Y-%m-%dT%H:%M:%S+00:00"),
    }, ensure_ascii=False)


async def _ws_receiver():
    """WebSocket 수신 루프 — 백그라운드에서 그룹챗 메시지 수집."""
    global _ws_connection, _ws_connected
    import websockets

    while True:
        try:
            async with websockets.connect(f"ws://{WS_HOST}:{WS_PORT}") as ws:
                _ws_connection = ws
                _ws_connected = True

                # 입장
                await ws.send(_make_chat_msg(_AGENT_NAME, "", "join"))

                async for raw in ws:
                    try:
                        msg = json.loads(raw)
                        if msg.get("sender") != _AGENT_NAME:
                            _received_messages.append({
                                "sender": msg.get("sender", ""),
                                "content": msg.get("content", ""),
                                "type": msg.get("type", "message"),
                                "timestamp": msg.get("timestamp", ""),
                            })
                            # 오래된 메시지 정리
                            if len(_received_messages) > _MAX_MESSAGES:
                                del _received_messages[:len(_received_messages) - _MAX_MESSAGES]
                    except Exception:
                        pass

        except Exception:
            _ws_connected = False
            _ws_connection = None
            await asyncio.sleep(3)


def _start_ws_thread():
    """WebSocket 수신을 별도 스레드에서 실행."""
    global _ws_loop
    _ws_loop = asyncio.new_event_loop()
    asyncio.set_event_loop(_ws_loop)
    _ws_loop.run_until_complete(_ws_receiver())


def _send_message(content: str) -> bool:
    """그룹챗에 메시지 전송."""
    if not _ws_connected or not _ws_connection or not _ws_loop:
        return False
    try:
        msg = _make_chat_msg(_AGENT_NAME, content)
        asyncio.run_coroutine_threadsafe(
            _ws_connection.send(msg), _ws_loop
        ).result(timeout=5)

        # DB에도 저장
        try:
            from llm_group_chat.shared_history import save_message
            save_message(_AGENT_NAME, content)
        except Exception:
            pass

        return True
    except Exception:
        return False


def _read_messages(count: int = 10) -> list[dict]:
    """최근 그룹챗 메시지 조회."""
    # DB에서도 읽기
    try:
        from llm_group_chat.shared_history import get_recent
        db_msgs = get_recent(count)
        if db_msgs:
            return db_msgs[-count:]
    except Exception:
        pass

    return _received_messages[-count:]


# ── MCP JSON-RPC 핸들러 ──

def _handle_initialize(params: dict) -> dict:
    return {
        "protocolVersion": "2024-11-05",
        "capabilities": {"tools": {}},
        "serverInfo": {
            "name": "groupchat",
            "version": "1.0.0",
        },
    }


def _handle_tools_list(params: dict) -> dict:
    return {
        "tools": [
            {
                "name": "send_group_message",
                "description": "그룹 채팅에 메시지를 전송합니다. 다른 터미널의 에이전트들이 볼 수 있습니다.",
                "inputSchema": {
                    "type": "object",
                    "properties": {
                        "message": {
                            "type": "string",
                            "description": "보낼 메시지 내용",
                        },
                    },
                    "required": ["message"],
                },
            },
            {
                "name": "read_group_messages",
                "description": "그룹 채팅의 최근 메시지를 읽습니다. 다른 에이전트들이 뭘 말했는지 확인할 수 있습니다.",
                "inputSchema": {
                    "type": "object",
                    "properties": {
                        "count": {
                            "type": "integer",
                            "description": "읽을 메시지 수 (기본: 10)",
                            "default": 10,
                        },
                    },
                },
            },
            {
                "name": "group_chat_status",
                "description": "그룹 채팅 연결 상태를 확인합니다.",
                "inputSchema": {
                    "type": "object",
                    "properties": {},
                },
            },
        ],
    }


def _handle_tools_call(params: dict) -> dict:
    tool_name = params.get("name", "")
    args = params.get("arguments", {})

    if tool_name == "send_group_message":
        message = args.get("message", "")
        if not message:
            return {"content": [{"type": "text", "text": "메시지가 비어있습니다."}]}

        ok = _send_message(message)
        if ok:
            return {"content": [{"type": "text", "text": f"그룹챗에 전송 완료: {message}"}]}
        else:
            return {"content": [{"type": "text", "text": "전송 실패 — 그룹챗 서버에 연결되지 않았습니다."}], "isError": True}

    elif tool_name == "read_group_messages":
        count = args.get("count", 10)
        messages = _read_messages(count)

        if not messages:
            return {"content": [{"type": "text", "text": "(그룹챗 메시지 없음)"}]}

        lines = []
        for m in messages:
            sender = m.get("sender", "?")
            content = m.get("content", "")
            ts = m.get("ts", m.get("timestamp", ""))
            lines.append(f"[{ts}] {sender}: {content}")

        return {"content": [{"type": "text", "text": "\n".join(lines)}]}

    elif tool_name == "group_chat_status":
        return {"content": [{"type": "text", "text": json.dumps({
            "connected": _ws_connected,
            "agent_name": _AGENT_NAME,
            "buffered_messages": len(_received_messages),
            "ws_url": f"ws://{WS_HOST}:{WS_PORT}",
        }, indent=2, ensure_ascii=False)}]}

    else:
        return {"content": [{"type": "text", "text": f"알 수 없는 도구: {tool_name}"}], "isError": True}


def _handle_request(method: str, params: dict) -> dict:
    """JSON-RPC 요청 처리."""
    if method == "initialize":
        return _handle_initialize(params)
    elif method == "tools/list":
        return _handle_tools_list(params)
    elif method == "tools/call":
        return _handle_tools_call(params)
    elif method == "notifications/initialized":
        return None  # 알림은 응답 불필요
    elif method == "ping":
        return {}
    else:
        return None


def main():
    """MCP 서버 메인 루프 — stdin/stdout JSON-RPC."""
    global _AGENT_NAME

    # 에이전트 이름 설정 (환경 변수 또는 기본값)
    _AGENT_NAME = os.environ.get("MCP_AGENT_NAME", f"mcp-{os.getpid()}")

    # WebSocket 수신 스레드 시작
    ws_thread = threading.Thread(target=_start_ws_thread, daemon=True)
    ws_thread.start()

    # 서버 시작 로그 (stderr로 — stdout은 MCP 프로토콜 전용)
    sys.stderr.write(f"[그룹챗 MCP] 서버 시작됨 — {_AGENT_NAME}\n")
    sys.stderr.flush()

    # stdin/stdout JSON-RPC 루프
    for line in sys.stdin:
        line = line.strip()
        if not line:
            continue

        try:
            request = json.loads(line)
        except json.JSONDecodeError:
            continue

        method = request.get("method", "")
        params = request.get("params", {})
        req_id = request.get("id")

        result = _handle_request(method, params)

        # 알림(id 없음)이면 응답 안 함
        if req_id is None:
            continue

        if result is not None:
            response = {
                "jsonrpc": "2.0",
                "id": req_id,
                "result": result,
            }
        else:
            response = {
                "jsonrpc": "2.0",
                "id": req_id,
                "error": {"code": -32601, "message": f"Method not found: {method}"},
            }

        sys.stdout.write(json.dumps(response, ensure_ascii=False) + "\n")
        sys.stdout.flush()


if __name__ == "__main__":
    main()
