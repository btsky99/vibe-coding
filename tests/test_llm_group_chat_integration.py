"""통합 테스트 - 서버 + 2개 클라이언트 연결 + 메시지 교환"""
import asyncio
import pytest
import websockets
from llm_group_chat.protocol import ChatMessage
from llm_group_chat.server import handle_client, connected_clients

# 테스트용 서버 포트 (충돌 방지)
TEST_PORT = 18765
TEST_HOST = "localhost"


@pytest.fixture()
async def chat_server():
    """테스트용 WebSocket 서버 시작/종료"""
    connected_clients.clear()
    server = await websockets.serve(handle_client, TEST_HOST, TEST_PORT)
    yield server
    server.close()
    await server.wait_closed()
    connected_clients.clear()


@pytest.mark.asyncio
async def test_two_clients_message_exchange(chat_server):
    """2개 클라이언트가 연결하여 메시지를 주고받는 통합 테스트"""
    uri = f"ws://{TEST_HOST}:{TEST_PORT}"

    async with websockets.connect(uri) as ws_alice, \
               websockets.connect(uri) as ws_bob:

        # Alice 입장
        join_alice = ChatMessage(type="join", sender="alice", content="")
        await ws_alice.send(join_alice.to_json())
        # Alice 입장 시스템 메시지 수신 대기 (서버가 브로드캐스트)
        # Alice는 exclude되지 않으므로 시스템 메시지를 받음 (broadcast에 exclude=None)
        # 실제로 join 시 broadcast(join_msg)는 exclude=None이므로 모두에게 전송

        # Bob 입장
        join_bob = ChatMessage(type="join", sender="bob", content="")
        await ws_bob.send(join_bob.to_json())

        # 시스템 메시지들 소비 (입장 알림)
        # Alice: alice 입장 알림 + bob 입장 알림
        msg1 = await asyncio.wait_for(ws_alice.recv(), timeout=2)
        msg2 = await asyncio.wait_for(ws_alice.recv(), timeout=2)
        # Bob: bob 입장 알림 (alice 입장은 bob 연결 전이므로 못 받음)
        msg3 = await asyncio.wait_for(ws_bob.recv(), timeout=2)

        # Alice가 메시지 전송 → Bob이 수신
        chat_msg = ChatMessage(type="message", sender="alice", content="안녕 Bob!")
        await ws_alice.send(chat_msg.to_json())

        received_raw = await asyncio.wait_for(ws_bob.recv(), timeout=2)
        received = ChatMessage.from_json(received_raw)
        assert received.sender == "alice"
        assert received.content == "안녕 Bob!"

        # Bob이 메시지 전송 → Alice가 수신
        reply_msg = ChatMessage(type="message", sender="bob", content="반가워 Alice!")
        await ws_bob.send(reply_msg.to_json())

        received_raw2 = await asyncio.wait_for(ws_alice.recv(), timeout=2)
        received2 = ChatMessage.from_json(received_raw2)
        assert received2.sender == "bob"
        assert received2.content == "반가워 Alice!"


@pytest.mark.asyncio
async def test_broadcast_excludes_sender(chat_server):
    """메시지 보낸 사람에게는 다시 전송하지 않는지 확인"""
    uri = f"ws://{TEST_HOST}:{TEST_PORT}"

    async with websockets.connect(uri) as ws_alice, \
               websockets.connect(uri) as ws_bob:

        # 둘 다 입장
        await ws_alice.send(ChatMessage(type="join", sender="alice", content="").to_json())
        await ws_bob.send(ChatMessage(type="join", sender="bob", content="").to_json())

        # 시스템 메시지 모두 소비
        await asyncio.wait_for(ws_alice.recv(), timeout=2)  # alice 입장
        await asyncio.wait_for(ws_alice.recv(), timeout=2)  # bob 입장
        await asyncio.wait_for(ws_bob.recv(), timeout=2)    # bob 입장

        # Alice가 메시지 전송
        await ws_alice.send(ChatMessage(type="message", sender="alice", content="test").to_json())

        # Bob은 수신해야 함
        received = await asyncio.wait_for(ws_bob.recv(), timeout=2)
        assert "alice" in received

        # Alice는 자기 메시지를 다시 받지 않아야 함
        with pytest.raises(asyncio.TimeoutError):
            await asyncio.wait_for(ws_alice.recv(), timeout=0.5)


@pytest.mark.asyncio
async def test_client_disconnect_notification(chat_server):
    """클라이언트 퇴장 시 다른 클라이언트에게 알림"""
    uri = f"ws://{TEST_HOST}:{TEST_PORT}"

    async with websockets.connect(uri) as ws_alice:
        # Alice 입장
        await ws_alice.send(ChatMessage(type="join", sender="alice", content="").to_json())
        await asyncio.wait_for(ws_alice.recv(), timeout=2)  # alice 입장 알림

        # Bob 연결 후 즉시 해제
        ws_bob = await websockets.connect(uri)
        await ws_bob.send(ChatMessage(type="join", sender="bob", content="").to_json())
        await asyncio.wait_for(ws_alice.recv(), timeout=2)  # bob 입장 알림
        await asyncio.wait_for(ws_bob.recv(), timeout=2)    # bob 입장 알림

        await ws_bob.close()

        # Alice가 bob 퇴장 알림을 받아야 함
        leave_raw = await asyncio.wait_for(ws_alice.recv(), timeout=2)
        leave_msg = ChatMessage.from_json(leave_raw)
        assert leave_msg.type == "system"
        assert "퇴장" in leave_msg.content
