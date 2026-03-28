"""그룹챗 브릿지 — 대시보드 라이브 채팅 ↔ WebSocket 서버 연결만 담당.

에이전트 응답은 agents.py의 squad가 별도 프로세스로 처리합니다.
이 브릿지는 오직 대시보드 UI ↔ WS 서버 연결만 합니다.
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


async def _bridge_loop_async():
    global _bridge_ws, _bridge_connected
    import websockets

    while True:
        try:
            async with websockets.connect(f"ws://{WS_HOST}:{WS_PORT}") as ws:
                _bridge_ws = ws
                _bridge_connected = True
                print("[브릿지] 그룹챗 서버 연결됨")
                await ws.send(_make_msg("join", "bridge"))

                async for raw in ws:
                    pass  # 수신만 유지 (연결 keep-alive)

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
    """브릿지 초기화 — WS 연결만."""
    threading.Thread(target=_run_bridge_thread, daemon=True, name="GroupChatBridge").start()
    print("[브릿지] 그룹챗 브릿지 시작됨")


def set_pty_url(url: str):
    """하위 호환용 — 더 이상 사용하지 않음."""
    pass


def get_status() -> dict:
    return {"connected": _bridge_connected, "ws_url": f"ws://{WS_HOST}:{WS_PORT}"}
