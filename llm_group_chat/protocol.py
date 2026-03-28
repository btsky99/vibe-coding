"""메시지 프로토콜 정의 - 모든 통신의 기본 포맷"""
import json
from dataclasses import dataclass, asdict
from datetime import datetime, timezone
from typing import Literal

# 메시지 타입 정의
MessageType = Literal["message", "join", "leave", "system"]


@dataclass
class ChatMessage:
    """채팅 메시지 데이터 클래스"""
    type: MessageType          # 메시지 종류
    sender: str                # 보낸 사람 이름 (예: "claude", "gemini")
    content: str               # 메시지 내용
    room: str = "default"      # 채팅방 이름
    timestamp: str = ""        # ISO 8601 타임스탬프

    def __post_init__(self):
        """타임스탬프 자동 생성"""
        if not self.timestamp:
            self.timestamp = datetime.now(timezone.utc).isoformat()

    def to_json(self) -> str:
        """JSON 문자열로 직렬화"""
        return json.dumps(asdict(self), ensure_ascii=False)

    @classmethod
    def from_json(cls, data: str) -> "ChatMessage":
        """JSON 문자열에서 역직렬화"""
        parsed = json.loads(data)
        return cls(**parsed)

    def display(self) -> str:
        """터미널 출력용 포맷"""
        time_short = self.timestamp[11:19] if len(self.timestamp) > 19 else ""
        if self.type == "system":
            return f"[{time_short}] ** {self.content} **"
        elif self.type == "join":
            return f"[{time_short}] >> {self.sender} 입장"
        elif self.type == "leave":
            return f"[{time_short}] << {self.sender} 퇴장"
        else:
            return f"[{time_short}] {self.sender}: {self.content}"
