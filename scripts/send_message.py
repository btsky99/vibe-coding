# -*- coding: utf-8 -*-
"""
FILE: scripts/send_message.py
DESCRIPTION: 터미널 간 메시지 전송 헬퍼 스크립트.
             ITCP(Inter-Terminal Communication Protocol)의 CLI 래퍼입니다.
             PostgreSQL pg_messages 테이블을 PRIMARY 저장소로 사용합니다.

             [이전 방식과의 차이]
             이전: HTTP API → 서버 미실행 시 messages.jsonl 폴백
             현재: PostgreSQL pg_messages FIRST → 불가 시 messages.jsonl 폴백
             서버(server.py)가 꺼져 있어도 PostgreSQL만 살아 있으면 메시지 전달 가능.

REVISION HISTORY:
- 2026-03-08 Claude: ITCP(itcp.py) 기반으로 전면 재작성
  - PostgreSQL pg_messages를 PRIMARY 저장소로 사용
  - HTTP API 의존성 제거 (서버 없이도 통신 가능)
  - CLI 인터페이스 유지 (기존 호출 코드 호환)
- 2026-03-01 Claude: 최초 구현 — HTTP API + messages.jsonl 폴백
"""

import sys
import os
from pathlib import Path

# itcp 모듈 임포트 (같은 scripts/ 디렉토리에 위치)
_SCRIPT_DIR = Path(__file__).parent
if str(_SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(_SCRIPT_DIR))

from itcp import send, broadcast


def send_message(
    from_agent: str,
    to_agent: str,
    msg_type: str,
    content: str,
    channel: str = "general",
) -> bool:
    """터미널 간 메시지 전송 (ITCP를 통해 PostgreSQL에 저장).

    [인자]
    - from_agent : 발신자 (예: "claude", "gemini")
    - to_agent   : 수신자 (예: "claude", "gemini", "all")
    - msg_type   : 메시지 유형 (info, request, response, alert, summary)
    - content    : 메시지 내용
    - channel    : 채널 분류 (general/task/debug/review/broadcast/hive)
    """
    terminal_id = os.environ.get("TERMINAL_ID", "")
    return send(
        from_terminal=from_agent,
        to_terminal=to_agent,
        content=content,
        channel=channel,
        msg_type=msg_type,
        terminal_id=terminal_id,
    )


if __name__ == "__main__":
    args = sys.argv[1:]
    if len(args) < 4:
        print("사용법: send_message.py <from> <to> <type> <content> [channel]")
        print("예시:   send_message.py claude gemini info '버그 발견됨' debug")
        sys.exit(1)

    from_a = args[0]
    to_a = args[1]
    m_type = args[2]
    content_str = args[3] if len(args) == 4 else " ".join(args[3:])
    channel = args[4] if len(args) > 4 else "general"

    ok = send_message(from_a, to_a, m_type, content_str, channel)
    print(f"{'✅' if ok else '❌'} [{from_a} → {to_a}] {content_str[:60]}")
