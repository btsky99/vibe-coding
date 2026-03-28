"""그룹챗 브릿지 — 하이브 마인드 NOTIFY → WebSocket (대시보드 UI 실시간 연동).

hive_memory에 채팅 메시지 INSERT → NOTIFY(hive_realtime)
→ 이 브릿지가 감지 → WebSocket 서버에 전달 → 대시보드 UI에 표시.

동시에 대시보드에서 WebSocket으로 보낸 메시지 → hive_memory에 저장 → NOTIFY.
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


def _make_ws_msg(sender: str, content: str) -> str:
    return json.dumps({
        "type": "message", "sender": sender, "content": content,
        "room": "default",
        "timestamp": time.strftime("%Y-%m-%dT%H:%M:%S+00:00"),
    }, ensure_ascii=False)


def _on_hive_notify(msg: dict):
    """hive_realtime NOTIFY 콜백 — 채팅 메시지를 WebSocket으로 전달."""
    if not _bridge_connected or not _bridge_ws or not _bridge_loop:
        return

    sender = msg.get("author", "")
    content = msg.get("content", "")
    if not content or sender == "dashboard":
        return

    try:
        ws_msg = _make_ws_msg(sender, content)
        asyncio.run_coroutine_threadsafe(_bridge_ws.send(ws_msg), _bridge_loop)
    except Exception:
        pass


async def _bridge_loop_async():
    """WebSocket 연결 + 대시보드 메시지 수신 → hive_memory INSERT."""
    global _bridge_ws, _bridge_connected
    import websockets

    while True:
        try:
            async with websockets.connect(f"ws://{WS_HOST}:{WS_PORT}") as ws:
                _bridge_ws = ws
                _bridge_connected = True
                print("[브릿지] WS + 하이브 LISTEN 연결됨")

                join_msg = json.dumps({
                    "type": "join", "sender": "bridge", "content": "",
                    "room": "default", "timestamp": time.strftime("%Y-%m-%dT%H:%M:%S+00:00"),
                }, ensure_ascii=False)
                await ws.send(join_msg)

                async for raw in ws:
                    try:
                        msg = json.loads(raw)
                        sender = msg.get("sender", "")

                        # bridge/에이전트 자신 무시
                        if sender in ("bridge", "") or sender.startswith("T"):
                            continue

                        # 대시보드 메시지 → hive_memory INSERT (→ NOTIFY → 에이전트 감지)
                        if msg.get("type") == "message":
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
    """브릿지 초기화 — WS 연결 + 하이브 LISTEN."""
    threading.Thread(target=_run_bridge_thread, daemon=True, name="GroupChatBridge").start()

    try:
        from llm_group_chat.shared_history import add_listener
        add_listener(_on_hive_notify)
        print("[브릿지] 하이브 LISTEN 등록됨 — 실시간 채팅 활성화")
    except Exception as e:
        print(f"[브릿지] LISTEN 등록 실패: {e}")


def set_pty_url(url: str):
    pass


def get_status() -> dict:
    return {"connected": _bridge_connected}
