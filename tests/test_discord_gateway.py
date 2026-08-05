"""
FILE: tests/test_discord_gateway.py
DESCRIPTION: Discord Gateway binding 정규화, 출력 보안 필터, ACL 메시지 처리 테스트.

REVISION HISTORY:
- 2026-08-06 Claude: 대기 상한 역전(응답 유실)과 무음 구간 회귀 테스트 추가
- 2026-08-03 Codex: PTY 직접 접근 금지와 버스 상관 응답 회귀 테스트 추가
- 2026-08-03 Codex: Discord REST User-Agent 회귀 테스트 추가
- 2026-08-03 Codex: 최초 작성
"""

import asyncio
import json
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))
import discord_gateway as gateway_module


def test_discord_rest_request_has_user_agent(monkeypatch):
    captured = {}

    class Response:
        def __enter__(self):
            return self

        def __exit__(self, *_args):
            return None

        def read(self):
            return json.dumps({"url": "wss://gateway.discord.gg"}).encode()

    def urlopen(request, timeout):
        captured["request"] = request
        captured["timeout"] = timeout
        return Response()

    monkeypatch.setattr(gateway_module.urllib.request, "urlopen", urlopen)
    gateway = object.__new__(gateway_module.DiscordGateway)
    gateway.token = "test-token"

    assert gateway._request("GET", "/gateway/bot")["url"].startswith("wss://")
    assert captured["request"].get_header("User-agent") == gateway_module.USER_AGENT
    assert captured["timeout"] == 20


def test_binding_defaults_to_current_node():
    bindings = gateway_module.load_bindings('{"10":"T1"}', "pc-a")
    assert bindings == {"10": {"terminal_id": "T1", "project_id": "vibe-coding", "node_id": "pc-a"}}


def test_binding_rejects_invalid_terminal():
    with pytest.raises(ValueError):
        gateway_module.load_bindings('{"10":"T20"}', "pc-a")


def test_group_requires_members():
    with pytest.raises(ValueError):
        gateway_module.load_groups('{"room": {"members": []}}')


def test_output_removes_ansi_and_redacts_secrets():
    output = gateway_module.clean_output([
        {"text": "\u001b[31mhello\u001b[0m"},
        {"text": "token=abc123"},
    ])
    assert "\u001b" not in output
    assert "abc123" not in output
    assert "token=[REDACTED]" in output


def test_output_accepts_chat_bus_content_field():
    assert gateway_module.clean_output([{"content": "bus reply"}]) == "bus reply"


def test_capture_output_reads_correlated_bus_reply(monkeypatch):
    gateway = object.__new__(gateway_module.DiscordGateway)
    calls = []
    gateway._local_request = lambda *_args: {
        "latest_seq": 8,
        "messages": [{
            "seq": 8, "source": "connector", "role": "assistant",
            "content": "done", "reply_to_seq": 7,
        }],
    }

    async def send(channel, content, reply_id=""):
        calls.append((channel, content, reply_id))

    async def no_sleep(_seconds):
        return None

    gateway.send = send
    monkeypatch.setattr(gateway_module.asyncio, "sleep", no_sleep)
    asyncio.run(gateway._capture_output("c", "m", {"terminal_id": "T1"}, 7))
    assert calls == [("c", "```text\ndone\n```", "m")]


def test_capture_output_returns_relay_error(monkeypatch):
    gateway = object.__new__(gateway_module.DiscordGateway)
    gateway._local_request = lambda *_args, **_kwargs: {
        "messages": [{
            "source": "connector", "role": "assistant", "reply_to_seq": 7,
            "content": "전달 실패: not_running", "error": "not_running",
        }],
        "latest_seq": 8,
    }
    sent = []

    async def send(*args):
        sent.append(args)

    async def no_sleep(_seconds):
        return None

    gateway.send = send
    monkeypatch.setattr(gateway_module.asyncio, "sleep", no_sleep)

    error = asyncio.run(gateway._capture_output("c", "m", {"terminal_id": "T2"}, 7))

    assert error == "not_running"
    assert sent == [("c", "```text\n전달 실패: not_running\n```", "m")]


def test_message_acl_and_dedupe_publish_bus_once(monkeypatch, tmp_path):
    monkeypatch.setenv("DISCORD_BOT_TOKEN", "token")
    monkeypatch.setenv("DISCORD_GUILD_IDS", "g")
    monkeypatch.setenv("DISCORD_CHANNEL_IDS", "c")
    monkeypatch.setenv("DISCORD_USER_IDS", "u")
    monkeypatch.setenv("DISCORD_CHANNEL_BINDINGS", '{"c":"T1"}')
    monkeypatch.setenv("VIBE_NODE_ID", "pc-a")
    gateway = gateway_module.DiscordGateway()
    calls = []
    gateway.claim_event = lambda *_args, **_kwargs: True
    gateway.mark_event = lambda *_args, **_kwargs: True

    def local(method, path, payload=None):
        calls.append((method, path, payload))
        return {"status": "ok", "seq": 5}

    gateway._local_request = local
    async def capture(*_args):
        return None
    gateway._capture_output = capture
    event = {"id": "e", "guild_id": "g", "channel_id": "c", "content": "테스트",
             "author": {"id": "u", "username": "user", "bot": False}}
    asyncio.run(gateway.handle_message(event))
    asyncio.run(gateway.handle_message(event))
    writes = [call for call in calls if call[1] == "/api/agent/chat/bus"]
    assert len(writes) == 1
    assert writes[0][2]["terminal_id"] == "T1"
    assert not [call for call in calls if call[1].startswith("/api/pty/")]


def test_unlisted_actor_is_ignored(monkeypatch):
    monkeypatch.setenv("DISCORD_BOT_TOKEN", "token")
    monkeypatch.setenv("DISCORD_GUILD_IDS", "g")
    monkeypatch.setenv("DISCORD_CHANNEL_IDS", "c")
    monkeypatch.setenv("DISCORD_USER_IDS", "allowed")
    monkeypatch.setenv("DISCORD_CHANNEL_BINDINGS", '{"c":"T1"}')
    monkeypatch.setenv("VIBE_NODE_ID", "pc-a")
    gateway = gateway_module.DiscordGateway()
    gateway._local_request = lambda *_args, **_kwargs: pytest.fail("should not inject")
    event = {"id": "e", "guild_id": "g", "channel_id": "c", "content": "테스트",
             "author": {"id": "blocked", "bot": False}}
    asyncio.run(gateway.handle_message(event))


def test_group_address_routes_only_to_matching_node(monkeypatch):
    monkeypatch.setenv("DISCORD_BOT_TOKEN", "token")
    monkeypatch.setenv("DISCORD_GUILD_IDS", "g")
    monkeypatch.setenv("DISCORD_CHANNEL_IDS", "room")
    monkeypatch.setenv("DISCORD_USER_IDS", "u")
    monkeypatch.setenv("DISCORD_CHANNEL_BINDINGS", '{}')
    monkeypatch.setenv("DISCORD_GROUP_BINDINGS", '{"room":{"project_id":"vibe","members":['
                       '{"node_id":"pc-a","terminal_id":"T1","orchestrator":true},'
                       '{"node_id":"pc-b","terminal_id":"T2"}]}}')
    monkeypatch.setenv("VIBE_NODE_ID", "pc-b")
    gateway = gateway_module.DiscordGateway()
    gateway.claim_event = lambda *_args, **_kwargs: True
    gateway.mark_event = lambda *_args, **_kwargs: True
    calls = []
    gateway._local_request = lambda method, path, payload=None: (
        calls.append((method, path, payload)) or
        ({"messages": [], "latest_seq": 0} if "/chat/feed" in path
         else {"status": "ok", "seq": 1}))
    async def capture(*_args):
        return None
    gateway._capture_output = capture
    event = {"id": "e2", "guild_id": "g", "channel_id": "room",
             "content": "@pc-b:T2 테스트", "author": {"id": "u", "bot": False}}
    asyncio.run(gateway.handle_message(event))
    writes = [call for call in calls if call[1] == "/api/agent/chat/bus"]
    assert writes[0][2]["terminal_id"] == "T2"
    assert writes[0][2]["content"] == "테스트"
def test_terminal_specific_gateway_filters_other_bindings(monkeypatch):
    monkeypatch.setenv("DISCORD_BOT_TOKEN", "token")
    monkeypatch.setenv("DISCORD_TERMINAL_ID", "T2")
    monkeypatch.setenv("DISCORD_CHANNEL_BINDINGS", '{"11":"T1","22":"T2"}')
    gateway = gateway_module.DiscordGateway()
    assert set(gateway.bindings) == {"22"}


def test_gateway_waits_longer_than_server_relay():
    """[재발방지 2026-08-06] 게이트웨이가 서버보다 먼저 포기하면, 서버가 그 뒤에 버스로
    돌려주는 답변을 수거할 주체가 사라져 답이 DB에만 남고 사용자에겐 영원히 안 간다.
    이전에는 게이트웨이 180초 하드코딩 vs 릴레이 600초로 어긋나 3분 넘는 요청이
    정상 응답에도 전부 response_timeout으로 버려졌다.
    """
    from src.connector_core import GATEWAY_WAIT_SEC, RELAY_TIMEOUT_SEC

    assert GATEWAY_WAIT_SEC > RELAY_TIMEOUT_SEC
    assert gateway_module.GATEWAY_WAIT_SEC == GATEWAY_WAIT_SEC


def test_slow_reply_shows_one_progress_message_then_overwrites_it(monkeypatch):
    """무음 구간에 경과 표시가 나오되 채널을 도배하지 않고, 결과가 그 자리를 덮는다."""
    gateway = object.__new__(gateway_module.DiscordGateway)
    clock = {"now": 0.0}
    polls = {"count": 0}
    monkeypatch.setattr(gateway_module.time, "monotonic", lambda: clock["now"])

    def local_request(*_args):
        polls["count"] += 1
        clock["now"] += 15.0                     # 폴링 1회를 15초로 가속
        if polls["count"] < 5:
            return {"latest_seq": 1, "messages": []}
        return {"latest_seq": 8, "messages": [{
            "seq": 8, "source": "connector", "role": "assistant",
            "content": "done", "reply_to_seq": 7,
        }]}

    sent, edited = [], []

    async def send(_channel, content, _reply_id=""):
        sent.append(content)
        return "progress-1"

    async def edit(_channel, message_id, content):
        edited.append((message_id, content))

    async def no_sleep(_seconds):
        return None

    gateway._local_request = local_request
    gateway.send = send
    gateway._edit = edit
    monkeypatch.setattr(gateway_module.asyncio, "sleep", no_sleep)
    asyncio.run(gateway._capture_output("c", "m", {"terminal_id": "T1"}, 7))

    assert len(sent) == 1 and sent[0].startswith("⏳")
    assert edited[-1] == ("progress-1", "```text\ndone\n```")


def test_progress_failure_does_not_lose_the_reply(monkeypatch):
    """[불변식] 진행 표시 실패가 응답 수거를 죽이면 원래 고치려던 유실 사고와 같아진다."""
    gateway = object.__new__(gateway_module.DiscordGateway)
    clock = {"now": 0.0}
    polls = {"count": 0}
    monkeypatch.setattr(gateway_module.time, "monotonic", lambda: clock["now"])

    def local_request(*_args):
        polls["count"] += 1
        clock["now"] += 25.0
        if polls["count"] < 3:
            return {"latest_seq": 1, "messages": []}
        return {"latest_seq": 8, "messages": [{
            "seq": 8, "source": "connector", "role": "assistant",
            "content": "done", "reply_to_seq": 7,
        }]}

    delivered = []

    async def send(_channel, content, _reply_id=""):
        if content.startswith("⏳"):
            raise RuntimeError("discord 5xx")
        delivered.append(content)
        return "msg-1"

    async def no_sleep(_seconds):
        return None

    gateway._local_request = local_request
    gateway.send = send
    monkeypatch.setattr(gateway_module.asyncio, "sleep", no_sleep)
    asyncio.run(gateway._capture_output("c", "m", {"terminal_id": "T1"}, 7))

    assert delivered == ["```text\ndone\n```"]
