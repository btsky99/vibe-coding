"""
FILE: src/connector_core.py
DESCRIPTION: Discord 등 외부 connector가 공통으로 사용하는 ACL, 터미널 주소,
             개인/그룹 메시지 라우팅 계약. 네트워크와 저장소에 의존하지 않는다.

REVISION HISTORY:
- 2026-08-06 Claude: 릴레이/게이트웨이 대기 상한을 한 곳으로 통합 (응답 유실 사고 수정)
- 2026-08-03 Codex: 기본 3터미널과 다중 PC room 라우팅 최초 구현
"""

from __future__ import annotations

import re
from dataclasses import dataclass


DEFAULT_TERMINAL_COUNT = 3
MAX_TERMINAL_COUNT = 9

# [불변식] GATEWAY_WAIT_SEC > RELAY_TIMEOUT_SEC — 절대 역전 금지.
#   커넥터 응답은 "서버가 버스에 남기고, 게이트웨이가 폴링해 수거한다" 2단 구조다.
#   게이트웨이가 먼저 포기하면 서버가 그 뒤에 남긴 답변을 수거할 주체가 사라져
#   답변이 DB에만 남고 사용자에겐 영원히 안 간다.
# [과거사고] ~v3.7.319: 게이트웨이 180초 하드코딩 vs 릴레이 600초로 어긋나 있었다.
#   3분 넘는 요청은 claude가 정상 응답해도 전부 response_timeout으로 버려졌다
#   (2026-08-04 connector_events 3건 실측). 두 값이 서로를 모르던 것이 근본 원인이라
#   상수를 각자 두지 말고 반드시 여기서 import 한다.
RELAY_TIMEOUT_SEC = 600
GATEWAY_WAIT_SEC = RELAY_TIMEOUT_SEC + 60
_TERMINAL_RE = re.compile(r"^T([1-9])$", re.IGNORECASE)
_TARGET_RE = re.compile(r"@(?P<target>all|[a-z0-9_-]+(?::T[1-9])?|T[1-9])\b", re.IGNORECASE)


@dataclass(frozen=True)
class TerminalAddress:
    node_id: str
    terminal_id: str

    def __post_init__(self):
        node = self.node_id.strip().lower()
        terminal = self.terminal_id.strip().upper()
        if not node or not re.fullmatch(r"[a-z0-9_-]+", node):
            raise ValueError("invalid_node_id")
        if not _TERMINAL_RE.fullmatch(terminal):
            raise ValueError("invalid_terminal_id")
        object.__setattr__(self, "node_id", node)
        object.__setattr__(self, "terminal_id", terminal)

    @property
    def key(self) -> str:
        return f"{self.node_id}:{self.terminal_id}"


@dataclass(frozen=True)
class ConnectorACL:
    guild_ids: frozenset[str]
    channel_ids: frozenset[str]
    actor_ids: frozenset[str]

    def allows(self, guild_id: str, channel_id: str, actor_id: str) -> bool:
        return (str(guild_id) in self.guild_ids and str(channel_id) in self.channel_ids
                and str(actor_id) in self.actor_ids)


@dataclass(frozen=True)
class RoomMember:
    address: TerminalAddress
    agent_type: str = ""
    orchestrator: bool = False


@dataclass(frozen=True)
class RouteDecision:
    targets: tuple[TerminalAddress, ...]
    body: str
    requires_approval: bool
    reason: str


def default_addresses(node_id: str, count: int = DEFAULT_TERMINAL_COUNT) -> tuple[TerminalAddress, ...]:
    safe_count = min(MAX_TERMINAL_COUNT, max(1, int(count)))
    return tuple(TerminalAddress(node_id, f"T{index}") for index in range(1, safe_count + 1))


def route_group_message(text: str, members: list[RoomMember],
                        reply_target: TerminalAddress | None = None) -> RouteDecision:
    """멘션 > reply > orchestrator 순으로 대상을 고른다. 실행 fan-out은 승인을 요구한다."""
    body = text.strip()
    match = _TARGET_RE.search(body)
    target = match.group("target").lower() if match else ""
    if match:
        body = (body[:match.start()] + body[match.end():]).strip()

    selected: list[RoomMember]
    reason = ""
    if target == "all":
        selected = list(members)
        reason = "broadcast"
    elif target.startswith("t") and target[1:].isdigit():
        selected = [m for m in members if m.address.terminal_id.lower() == target]
        reason = "terminal_mention"
    elif ":t" in target:
        selected = [m for m in members if m.address.key.lower() == target]
        reason = "address_mention"
    elif target:
        selected = [m for m in members
                    if m.address.node_id == target or m.agent_type.lower() == target]
        reason = "node_or_agent_mention"
    elif reply_target:
        selected = [m for m in members if m.address == reply_target]
        reason = "reply"
    else:
        selected = [m for m in members if m.orchestrator]
        if not selected and members:
            selected = [members[0]]
        reason = "orchestrator_default"

    unique = tuple(dict.fromkeys(member.address for member in selected))
    return RouteDecision(
        targets=unique,
        body=body,
        requires_approval=len(unique) > 1,
        reason=reason if unique else "target_not_found",
    )
