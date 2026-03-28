"""그룹챗 MCP 서버 — PostgreSQL LISTEN/NOTIFY 기반 실시간 통신.

Claude Code / Gemini CLI 터미널에서 직접 그룹 채팅 참여.
새 메시지가 DB에 INSERT되면 NOTIFY → 이 서버가 감지 → 에이전트에 알림.

MCP 도구:
  - send_group_message: 그룹챗에 메시지 전송
  - read_group_messages: 최근 메시지 조회
  - check_new_messages: 마지막 확인 이후 새 메시지 조회
  - group_chat_status: 연결 상태 확인

MCP 리소스:
  - groupchat://inbox: 읽지 않은 새 메시지 (자동 업데이트)

설정 (claude config.json):
{
  "mcpServers": {
    "groupchat": {
      "command": "python",
      "args": ["-m", "llm_group_chat.mcp_server"],
      "cwd": "D:/vibe-coding",
      "env": { "MCP_AGENT_NAME": "T1-claude" }
    }
  }
}
"""
import json
import sys
import os
import threading
import time

_AGENT_NAME = os.environ.get("MCP_AGENT_NAME", f"mcp-{os.getpid()}")

# 새 메시지 큐 (LISTEN으로 수신된 메시지)
_inbox: list[dict] = []
_inbox_lock = threading.Lock()
_MAX_INBOX = 50

# 마지막으로 읽은 메시지 ID
_last_read_id = 0


def _setup_listener():
    """PostgreSQL LISTEN 시작 — 새 메시지 자동 감지."""
    try:
        from llm_group_chat.shared_history import add_listener, _ensure_table
        _ensure_table()

        def on_new_message(msg: dict):
            """새 메시지 도착 콜백."""
            sender = msg.get("sender", "")
            # 자기 메시지는 무시
            if sender == _AGENT_NAME:
                return

            with _inbox_lock:
                _inbox.append(msg)
                if len(_inbox) > _MAX_INBOX:
                    del _inbox[:len(_inbox) - _MAX_INBOX]

            # stderr로 알림 (에이전트가 볼 수 있음)
            content = msg.get("content", "")[:100]
            sys.stderr.write(f"\n[그룹챗] {sender}: {content}\n")
            sys.stderr.flush()

        add_listener(on_new_message)
        sys.stderr.write(f"[그룹챗 MCP] LISTEN 시작됨 — {_AGENT_NAME}\n")
        sys.stderr.flush()
    except Exception as e:
        sys.stderr.write(f"[그룹챗 MCP] LISTEN 실패: {e}\n")
        sys.stderr.flush()


def _send_message(content: str) -> dict:
    """그룹챗에 메시지 전송 (PostgreSQL INSERT → NOTIFY)."""
    try:
        from llm_group_chat.shared_history import save_message
        msg_id = save_message(_AGENT_NAME, content)

        # WebSocket 서버에도 전달 (대시보드 UI 연동)
        _relay_to_ws(content)

        return {"status": "sent", "id": msg_id, "sender": _AGENT_NAME}
    except Exception as e:
        return {"error": str(e)}


def _relay_to_ws(content: str):
    """WebSocket 그룹챗 서버에 메시지 전달 (대시보드 UI 표시용)."""
    try:
        import asyncio
        import websockets

        msg = json.dumps({
            "type": "message", "sender": _AGENT_NAME, "content": content,
            "room": "default",
            "timestamp": time.strftime("%Y-%m-%dT%H:%M:%S+00:00"),
        }, ensure_ascii=False)

        async def _send():
            try:
                async with websockets.connect("ws://127.0.0.1:8765") as ws:
                    await ws.send(msg)
            except Exception:
                pass

        # 새 이벤트 루프에서 실행
        loop = asyncio.new_event_loop()
        loop.run_until_complete(_send())
        loop.close()
    except Exception:
        pass


def _read_messages(count: int = 10) -> list[dict]:
    """최근 메시지 조회."""
    try:
        from llm_group_chat.shared_history import get_recent
        return get_recent(count)
    except Exception as e:
        return [{"error": str(e)}]


def _check_new() -> list[dict]:
    """읽지 않은 새 메시지 가져오기 + 인박스 비우기."""
    global _last_read_id
    with _inbox_lock:
        new_msgs = list(_inbox)
        _inbox.clear()

    # DB에서도 확인 (LISTEN 놓친 메시지 보완)
    try:
        from llm_group_chat.shared_history import get_new_since
        db_msgs, new_id = get_new_since(_last_read_id, exclude_sender=_AGENT_NAME, limit=20)
        if new_id > _last_read_id:
            _last_read_id = new_id

        # inbox + DB 메시지 병합 (중복 제거)
        seen_ids = {m.get("id") for m in new_msgs if m.get("id")}
        for m in db_msgs:
            if m.get("id") not in seen_ids:
                new_msgs.append(m)

    except Exception:
        pass

    return new_msgs


# ── MCP JSON-RPC 핸들러 ──

def _handle_initialize(params: dict) -> dict:
    return {
        "protocolVersion": "2024-11-05",
        "capabilities": {
            "tools": {},
            "resources": {"subscribe": True},
        },
        "serverInfo": {"name": "groupchat", "version": "2.0.0"},
    }


def _handle_tools_list(params: dict) -> dict:
    return {"tools": [
        {
            "name": "send_group_message",
            "description": "그룹 채팅에 메시지를 전송합니다. 다른 터미널의 에이전트(Claude/Gemini/Codex)가 실시간으로 수신합니다. PostgreSQL NOTIFY로 즉시 전달됩니다.",
            "inputSchema": {
                "type": "object",
                "properties": {
                    "message": {"type": "string", "description": "보낼 메시지"},
                },
                "required": ["message"],
            },
        },
        {
            "name": "read_group_messages",
            "description": "그룹 채팅의 최근 대화를 읽습니다. 모든 에이전트의 메시지가 포함됩니다.",
            "inputSchema": {
                "type": "object",
                "properties": {
                    "count": {"type": "integer", "description": "읽을 메시지 수 (기본: 10)", "default": 10},
                },
            },
        },
        {
            "name": "check_new_messages",
            "description": "마지막 확인 이후 새로 도착한 메시지를 확인합니다. 새 메시지가 있으면 반환하고, 없으면 빈 배열을 반환합니다. 주기적으로 호출하면 실시간 대화가 가능합니다.",
            "inputSchema": {
                "type": "object",
                "properties": {},
            },
        },
        {
            "name": "group_chat_status",
            "description": "그룹 채팅 연결 상태와 참여 정보를 확인합니다.",
            "inputSchema": {
                "type": "object",
                "properties": {},
            },
        },
    ]}


def _handle_resources_list(params: dict) -> dict:
    return {"resources": [
        {
            "uri": "groupchat://inbox",
            "name": "그룹챗 인박스",
            "description": "읽지 않은 새 그룹챗 메시지. 새 메시지가 도착하면 자동 업데이트됩니다.",
            "mimeType": "application/json",
        },
    ]}


def _handle_resources_read(params: dict) -> dict:
    uri = params.get("uri", "")
    if uri == "groupchat://inbox":
        new_msgs = _check_new()
        content = json.dumps(new_msgs, ensure_ascii=False, indent=2) if new_msgs else "새 메시지 없음"
        return {"contents": [{"uri": uri, "mimeType": "application/json", "text": content}]}
    return {"contents": []}


def _handle_tools_call(params: dict) -> dict:
    tool = params.get("name", "")
    args = params.get("arguments", {})

    if tool == "send_group_message":
        msg = args.get("message", "")
        if not msg:
            return {"content": [{"type": "text", "text": "메시지가 비어있습니다."}]}
        result = _send_message(msg)
        if "error" in result:
            return {"content": [{"type": "text", "text": f"전송 실패: {result['error']}"}], "isError": True}
        return {"content": [{"type": "text", "text": f"그룹챗 전송 완료: {msg}"}]}

    elif tool == "read_group_messages":
        count = args.get("count", 10)
        msgs = _read_messages(count)
        if not msgs:
            return {"content": [{"type": "text", "text": "(그룹챗 메시지 없음)"}]}
        lines = [f"[{m.get('ts','')}] {m['sender']}: {m['content']}" for m in msgs]
        return {"content": [{"type": "text", "text": "\n".join(lines)}]}

    elif tool == "check_new_messages":
        new_msgs = _check_new()
        if not new_msgs:
            return {"content": [{"type": "text", "text": "(새 메시지 없음)"}]}
        lines = [f"[{m.get('ts','')}] {m.get('sender','?')}: {m.get('content','')}" for m in new_msgs]
        return {"content": [{"type": "text", "text": f"새 메시지 {len(new_msgs)}개:\n" + "\n".join(lines)}]}

    elif tool == "group_chat_status":
        return {"content": [{"type": "text", "text": json.dumps({
            "agent_name": _AGENT_NAME,
            "inbox_count": len(_inbox),
            "last_read_id": _last_read_id,
            "listener_active": True,
        }, indent=2, ensure_ascii=False)}]}

    return {"content": [{"type": "text", "text": f"알 수 없는 도구: {tool}"}], "isError": True}


def _handle_request(method: str, params: dict) -> dict:
    handlers = {
        "initialize": _handle_initialize,
        "tools/list": _handle_tools_list,
        "tools/call": _handle_tools_call,
        "resources/list": _handle_resources_list,
        "resources/read": _handle_resources_read,
        "ping": lambda p: {},
    }
    handler = handlers.get(method)
    if handler:
        return handler(params)
    # 알림(notifications)은 None 반환
    if method.startswith("notifications/"):
        return None
    return None


def main():
    """MCP 서버 메인 — stdin/stdout JSON-RPC + PostgreSQL LISTEN."""
    global _AGENT_NAME, _last_read_id
    _AGENT_NAME = os.environ.get("MCP_AGENT_NAME", f"mcp-{os.getpid()}")

    # 마지막 메시지 ID 초기화 (이전 메시지는 무시)
    try:
        from llm_group_chat.shared_history import get_recent, _ensure_table
        _ensure_table()
        recent = get_recent(1)
        if recent:
            from llm_group_chat.shared_history import _get_conn
            conn = _get_conn()
            cur = conn.cursor()
            cur.execute("SELECT MAX(id) FROM groupchat_messages")
            row = cur.fetchone()
            if row and row[0]:
                _last_read_id = row[0]
            conn.close()
    except Exception:
        pass

    # LISTEN 시작 (백그라운드 스레드)
    threading.Thread(target=_setup_listener, daemon=True).start()

    sys.stderr.write(f"[그룹챗 MCP] 서버 시작 — {_AGENT_NAME} (LISTEN/NOTIFY 모드)\n")
    sys.stderr.flush()

    # stdin JSON-RPC 루프
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

        if req_id is None:
            continue

        if result is not None:
            response = {"jsonrpc": "2.0", "id": req_id, "result": result}
        else:
            response = {"jsonrpc": "2.0", "id": req_id,
                         "error": {"code": -32601, "message": f"Method not found: {method}"}}

        sys.stdout.write(json.dumps(response, ensure_ascii=False) + "\n")
        sys.stdout.flush()


if __name__ == "__main__":
    main()
