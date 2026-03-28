"""WebSocket 채팅 서버 - 메시지 브로커 역할"""
import asyncio
import json
from pathlib import Path
from llm_group_chat.protocol import ChatMessage

# 연결된 클라이언트 관리: {websocket: name}
connected_clients: dict = {}

# 채팅 로그 파일
LOG_FILE = Path("chat.jsonl")


async def broadcast(message: ChatMessage, exclude=None):
    """모든 클라이언트에게 메시지 브로드캐스트"""
    data = message.to_json()

    # 로그 파일에 저장
    with open(LOG_FILE, "a", encoding="utf-8") as f:
        f.write(data + "\n")

    # 모든 연결된 클라이언트에게 전송
    for ws, name in list(connected_clients.items()):
        if ws != exclude:
            try:
                await ws.send(data)
            except Exception:
                pass


async def handle_client(websocket):
    """개별 클라이언트 연결 처리"""
    client_name = "unknown"

    try:
        async for raw in websocket:
            msg = ChatMessage.from_json(raw)

            if msg.type == "join":
                # 새 클라이언트 등록
                client_name = msg.sender
                connected_clients[websocket] = client_name
                # 입장 알림 브로드캐스트
                join_msg = ChatMessage(
                    type="system",
                    sender="server",
                    content=f"{client_name} 님이 입장했습니다. (현재 {len(connected_clients)}명)"
                )
                await broadcast(join_msg)
                print(f"[서버] {client_name} 연결됨 (총 {len(connected_clients)}명)")

            elif msg.type == "message":
                # 일반 메시지 브로드캐스트
                await broadcast(msg, exclude=websocket)

    except Exception as e:
        print(f"[서버] {client_name} 연결 오류: {e}")

    finally:
        # 클라이언트 연결 해제
        if websocket in connected_clients:
            del connected_clients[websocket]
            leave_msg = ChatMessage(
                type="system",
                sender="server",
                content=f"{client_name} 님이 퇴장했습니다. (현재 {len(connected_clients)}명)"
            )
            await broadcast(leave_msg)
            print(f"[서버] {client_name} 연결 해제 (총 {len(connected_clients)}명)")


async def _serve(host: str, port: int):
    """비동기 서버 시작"""
    import websockets
    async with websockets.serve(handle_client, host, port):
        print(f"[서버] ws://{host}:{port} 에서 대기 중...")
        await asyncio.Future()  # 무한 대기


def run_server(host: str = "localhost", port: int = 8765):
    """서버 실행 (동기 래퍼)"""
    asyncio.run(_serve(host, port))
