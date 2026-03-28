"""그룹챗 브릿지 — PostgreSQL NOTIFY → WebSocket (대시보드 UI 실시간 연동).

PostgreSQL의 LISTEN으로 새 메시지를 감지하고,
WebSocket 서버에 전달하여 대시보드 실시간 채팅 UI에 표시합니다.

동시에 WebSocket에서 대시보드 UI 메시지를 수신하면
PostgreSQL에 INSERT (→ NOTIFY → 다른 에이전트 MCP 서버가 감지).
"""
import asyncio
import json
import threading
import time

WS_HOST = "127.0.0.1"
WS_PORT = 8765

_bridge_ws = None
_bridge_connected = False
_bridge_loop = None


def _make_msg(msg_type: str, sender: str, content: str = "") -> str:
    return json.dumps({
        "type": msg_type, "sender": sender, "content": content,
        "room": "default",
        "timestamp": time.strftime("%Y-%m-%dT%H:%M:%S+00:00"),
    }, ensure_ascii=False)


def _on_db_notify(msg: dict):
    """PostgreSQL NOTIFY 콜백 — 새 메시지를 WebSocket으로 전달."""
    if not _bridge_connected or not _bridge_ws or not _bridge_loop:
        return

    sender = msg.get("sender", "")
    content = msg.get("content", "")
    if not content or sender == "dashboard":
        return

    ws_msg = _make_msg("message", sender, content)
    try:
        asyncio.run_coroutine_threadsafe(
            _bridge_ws.send(ws_msg), _bridge_loop
        )
    except Exception:
        pass


async def _bridge_loop_async():
    """WebSocket 연결 + 대시보드 메시지 수신 → PostgreSQL INSERT."""
    global _bridge_ws, _bridge_connected
    import websockets

    while True:
        try:
            async with websockets.connect(f"ws://{WS_HOST}:{WS_PORT}") as ws:
                _bridge_ws = ws
                _bridge_connected = True
                print("[브릿지] WS + PG LISTEN 연결됨")

                await ws.send(_make_msg("join", "bridge"))

                async for raw in ws:
                    try:
                        msg = json.loads(raw)
                        sender = msg.get("sender", "")
                        msg_type = msg.get("type", "")

                        # bridge 자신이 보낸 건 무시
                        if sender == "bridge":
                            continue
                        # 에이전트(MCP)가 보낸 건 이미 DB에 있으므로 무시
                        if sender.startswith("T") or sender.startswith("mcp"):
                            continue

                        # 대시보드 사용자 메시지 → PostgreSQL INSERT (→ NOTIFY → 에이전트 MCP 감지)
                        if msg_type == "message":
                            content = msg.get("content", "").strip()
                            if content:
                                try:
                                    from llm_group_chat.shared_history import save_message
                                    save_message(sender, content)
                                except Exception:
                                    pass

                    except (json.JSONDecodeError, KeyError):
                        pass

        except Exception as e:
            _bridge_connected = False
            _bridge_ws = None
            print(f"[브릿지] 연결 끊김, 5초 후 재시도: {e}")
            await asyncio.sleep(5)


def _run_bridge_thread():
    global _bridge_loop
    _bridge_loop = asyncio.new_event_loop()
    asyncio.set_event_loop(_bridge_loop)
    _bridge_loop.run_until_complete(_bridge_loop_async())


def init_bridge():
    """브릿지 초기화 — WS 연결 + PostgreSQL LISTEN."""
    # WS 브릿지 스레드
    threading.Thread(target=_run_bridge_thread, daemon=True, name="GroupChatBridge-WS").start()

    # PostgreSQL LISTEN → WS 전달
    try:
        from llm_group_chat.shared_history import add_listener
        add_listener(_on_db_notify)
        print("[브릿지] PostgreSQL LISTEN 등록됨 — DB 메시지 → 대시보드 자동 전달")
    except Exception as e:
        print(f"[브릿지] LISTEN 등록 실패: {e}")

    print("[브릿지] 그룹챗 브릿지 시작됨")


def set_pty_url(url: str):
    """하위 호환용."""
    pass


def get_status() -> dict:
    return {"connected": _bridge_connected, "ws_url": f"ws://{WS_HOST}:{WS_PORT}"}
