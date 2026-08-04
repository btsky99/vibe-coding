"""
FILE: tests/test_connector_core.py
DESCRIPTION: connector ACL과 기본 3터미널·그룹 라우팅 계약 테스트.

REVISION HISTORY:
- 2026-08-03 Codex: 최초 작성
"""

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / ".ai_monitor"))
from src.connector_core import (ConnectorACL, RoomMember, TerminalAddress,
                                default_addresses, route_group_message)


def _members():
    return [
        RoomMember(TerminalAddress("pc-a", "T1"), "claude", orchestrator=True),
        RoomMember(TerminalAddress("pc-a", "T2"), "codex"),
        RoomMember(TerminalAddress("pc-b", "T1"), "codex"),
    ]


def test_default_is_three_and_can_expand():
    assert [item.terminal_id for item in default_addresses("pc-a")] == ["T1", "T2", "T3"]
    assert len(default_addresses("pc-a", 8)) == 8
    assert len(default_addresses("pc-a", 99)) == 9


def test_address_rejects_untrusted_identifiers():
    with pytest.raises(ValueError):
        TerminalAddress("../pc", "T1")
    with pytest.raises(ValueError):
        TerminalAddress("pc", "T10")


def test_acl_requires_all_three_dimensions():
    acl = ConnectorACL(frozenset({"g"}), frozenset({"c"}), frozenset({"u"}))
    assert acl.allows("g", "c", "u")
    assert not acl.allows("g", "other", "u")


def test_no_mention_routes_to_orchestrator():
    result = route_group_message("상태 알려줘", _members())
    assert [target.key for target in result.targets] == ["pc-a:T1"]
    assert not result.requires_approval


def test_specific_address_routes_across_pcs():
    result = route_group_message("@pc-b:T1 테스트해줘", _members())
    assert [target.key for target in result.targets] == ["pc-b:T1"]
    assert result.body == "테스트해줘"


def test_agent_mention_can_fan_out_and_requires_approval():
    result = route_group_message("@codex 검토해줘", _members())
    assert {target.key for target in result.targets} == {"pc-a:T2", "pc-b:T1"}
    assert result.requires_approval


def test_all_broadcast_requires_approval():
    result = route_group_message("@all 상태 점검", _members())
    assert len(result.targets) == 3
    assert result.requires_approval
