"""protocol.py 단위 테스트"""
import json
from llm_group_chat.protocol import ChatMessage


def test_create_message():
    """메시지 생성 시 타임스탬프 자동 생성"""
    msg = ChatMessage(type="message", sender="alice", content="안녕!")
    assert msg.sender == "alice"
    assert msg.content == "안녕!"
    assert msg.room == "default"
    assert msg.timestamp != ""


def test_json_roundtrip():
    """JSON 직렬화 → 역직렬화 왕복 테스트"""
    original = ChatMessage(type="message", sender="bob", content="테스트 메시지")
    json_str = original.to_json()
    restored = ChatMessage.from_json(json_str)

    assert restored.type == original.type
    assert restored.sender == original.sender
    assert restored.content == original.content
    assert restored.room == original.room
    assert restored.timestamp == original.timestamp


def test_json_contains_korean():
    """한글이 이스케이프 없이 JSON에 포함되는지 확인"""
    msg = ChatMessage(type="message", sender="claude", content="한글 테스트")
    json_str = msg.to_json()
    assert "한글 테스트" in json_str


def test_display_message():
    """일반 메시지 출력 포맷"""
    msg = ChatMessage(
        type="message", sender="alice", content="안녕!",
        timestamp="2026-03-28T10:30:00+00:00"
    )
    assert "alice: 안녕!" in msg.display()
    assert "10:30:00" in msg.display()


def test_display_system():
    """시스템 메시지 출력 포맷"""
    msg = ChatMessage(
        type="system", sender="server", content="환영합니다",
        timestamp="2026-03-28T10:00:00+00:00"
    )
    display = msg.display()
    assert "**" in display
    assert "환영합니다" in display


def test_display_join_leave():
    """입장/퇴장 출력 포맷"""
    join = ChatMessage(type="join", sender="gemini", content="",
                       timestamp="2026-03-28T10:00:00+00:00")
    leave = ChatMessage(type="leave", sender="gemini", content="",
                        timestamp="2026-03-28T10:00:00+00:00")

    assert "입장" in join.display()
    assert "퇴장" in leave.display()


def test_custom_room():
    """커스텀 룸 이름"""
    msg = ChatMessage(type="message", sender="a", content="hi", room="crypto")
    restored = ChatMessage.from_json(msg.to_json())
    assert restored.room == "crypto"
