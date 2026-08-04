"""
FILE: scripts/discord_gateway.py
DESCRIPTION: 단일 Discord 봇 연결로 허가된 채널 메시지를 백그라운드 대화 버스에
             게시하고, 같은 버스의 상관 응답을 Discord 채널로 반환한다.

REVISION HISTORY:
- 2026-08-04 Codex: relay error를 completed로 오기록하지 않고 connector event를 failed로 마감
- 2026-08-03 Codex: Discord의 PTY 직접 접근을 제거하고 대화 버스 전용 client로 전환
- 2026-08-03 Codex: Discord REST 요청에 명시적 User-Agent를 추가해 Cloudflare 1010 차단 수정
- 2026-08-03 Codex: Gateway heartbeat, ACL, PostgreSQL dedupe, PTY 양방향 연결 최초 구현
"""

from __future__ import annotations

import asyncio
import json
import os
import re
import socket
import sys
import time
import urllib.parse
import urllib.request
from collections import deque
from pathlib import Path
from typing import Any

import websockets


API = "https://discord.com/api/v10"
USER_AGENT = "VibeCoding-DiscordGateway/1.0"
INTENTS = (1 << 9) | (1 << 15)
ANSI = re.compile(r"\x1B(?:[@-Z\\-_]|\[[0-?]*[ -/]*[@-~])")
SECRET = re.compile(r"(?i)(token|secret|password|authorization)(\s*[:=]\s*)(\S+)")


def _csv(name: str) -> frozenset[str]:
    return frozenset(value.strip() for value in os.environ.get(name, "").split(",") if value.strip())


def load_bindings(raw: str, node_id: str) -> dict[str, dict]:
    """channel ID별 binding을 정규화한다. 문자열 값은 현재 node의 터미널 ID다."""
    try:
        parsed = json.loads(raw or "{}")
    except json.JSONDecodeError as error:
        raise ValueError("invalid_discord_channel_bindings") from error
    if not isinstance(parsed, dict):
        raise ValueError("invalid_discord_channel_bindings")
    result = {}
    for channel, value in parsed.items():
        item = {"terminal_id": value} if isinstance(value, str) else dict(value or {})
        terminal = str(item.get("terminal_id") or "").upper()
        if not re.fullmatch(r"T[1-9]", terminal):
            raise ValueError(f"invalid_terminal_binding:{channel}")
        result[str(channel)] = {
            "terminal_id": terminal,
            "project_id": str(item.get("project_id") or "vibe-coding"),
            "node_id": str(item.get("node_id") or node_id).lower(),
        }
    return result


def load_groups(raw: str) -> dict[str, dict]:
    try:
        parsed = json.loads(raw or "{}")
    except json.JSONDecodeError as error:
        raise ValueError("invalid_discord_group_bindings") from error
    if not isinstance(parsed, dict):
        raise ValueError("invalid_discord_group_bindings")
    result = {}
    for channel, value in parsed.items():
        item = dict(value or {})
        if not isinstance(item.get("members"), list) or not item["members"]:
            raise ValueError(f"group_members_required:{channel}")
        result[str(channel)] = item
    return result


def clean_output(entries: list[dict], max_chars: int = 6000) -> str:
    lines = []
    for entry in entries:
        value = ANSI.sub("", str(entry.get("content") or entry.get("text") or "")).strip()
        value = SECRET.sub(r"\1\2[REDACTED]", value)
        if value and value not in lines[-3:]:
            lines.append(value)
    return "\n".join(lines)[-max_chars:]


def chunks(text: str, size: int = 1900) -> list[str]:
    return [text[index:index + size] for index in range(0, len(text), size)] or [""]


class DiscordGateway:
    def __init__(self):
        self.token = os.environ.get("DISCORD_BOT_TOKEN", "").strip()
        self.terminal_id = os.environ.get("DISCORD_TERMINAL_ID", "").strip().upper()
        self.server = os.environ.get("VIBE_SERVER_URL", "http://127.0.0.1:9000").rstrip("/")
        self.node_id = os.environ.get("VIBE_NODE_ID", socket.gethostname()).strip().lower()
        self.guilds = _csv("DISCORD_GUILD_IDS")
        self.channels = _csv("DISCORD_CHANNEL_IDS")
        self.actors = _csv("DISCORD_USER_IDS")
        self.bindings = load_bindings(os.environ.get("DISCORD_CHANNEL_BINDINGS", "{}"), self.node_id)
        if self.terminal_id:
            self.bindings = {channel: binding for channel, binding in self.bindings.items()
                             if binding["terminal_id"] == self.terminal_id}
        self.groups = load_groups(os.environ.get("DISCORD_GROUP_BINDINGS", "{}"))
        self.project_root = Path(__file__).resolve().parents[1]
        monitor = self.project_root / ".ai_monitor"
        sys.path.insert(0, str(monitor))
        from src.pg_connectors import claim_event, mark_event
        self.claim_event = claim_event
        self.mark_event = mark_event
        self._recent = deque(maxlen=1000)

    def ready(self) -> bool:
        return bool(self.token and self.guilds and self.channels and self.actors
                    and (self.bindings or self.groups))

    def _group_binding(self, channel: str, content: str) -> tuple[dict | None, bool, str]:
        raw = self.groups.get(channel)
        if not raw:
            return None, False, content
        from src.connector_core import RoomMember, TerminalAddress, route_group_message
        members = []
        for value in raw["members"]:
            member = dict(value or {})
            members.append(RoomMember(
                TerminalAddress(str(member.get("node_id") or ""), str(member.get("terminal_id") or "")),
                str(member.get("agent_type") or ""), bool(member.get("orchestrator"))))
        decision = route_group_message(content, members)
        if decision.requires_approval:
            return None, True, decision.body
        local = [target for target in decision.targets if target.node_id == self.node_id]
        if len(local) != 1:
            return None, False, decision.body
        return {
            "terminal_id": local[0].terminal_id,
            "project_id": str(raw.get("project_id") or "vibe-coding"),
            "node_id": local[0].node_id,
        }, False, decision.body

    def _request(self, method: str, path: str, payload: dict | None = None) -> dict:
        body = json.dumps(payload).encode() if payload is not None else None
        request = urllib.request.Request(
            f"{API}{path}", data=body, method=method,
            headers={"Authorization": f"Bot {self.token}", "Content-Type": "application/json",
                     "User-Agent": USER_AGENT})
        with urllib.request.urlopen(request, timeout=20) as response:
            raw = response.read()
        return json.loads(raw.decode()) if raw else {}

    def _local_request(self, method: str, path: str, payload: dict | None = None) -> dict:
        body = json.dumps(payload).encode() if payload is not None else None
        request = urllib.request.Request(
            f"{self.server}{path}", data=body, method=method,
            headers={"Content-Type": "application/json"})
        with urllib.request.urlopen(request, timeout=20) as response:
            raw = response.read()
        return json.loads(raw.decode()) if raw else {}

    async def send(self, channel_id: str, content: str, reply_id: str = "") -> None:
        payload: dict[str, Any] = {"content": content, "allowed_mentions": {"parse": []}}
        if reply_id:
            payload["message_reference"] = {"message_id": reply_id, "fail_if_not_exists": False}
        await asyncio.to_thread(self._request, "POST", f"/channels/{channel_id}/messages", payload)

    def _allowed(self, event: dict) -> bool:
        author = event.get("author") or {}
        return (str(event.get("guild_id")) in self.guilds
                and str(event.get("channel_id")) in self.channels
                and str(author.get("id")) in self.actors
                and not author.get("bot") and not event.get("webhook_id"))

    async def _capture_output(self, channel: str, message_id: str, binding: dict,
                              request_seq: int) -> str:
        terminal = binding["terminal_id"]
        since = request_seq
        deadline = time.monotonic() + 180
        while time.monotonic() < deadline:
            await asyncio.sleep(1.5)
            path = f"/api/agent/chat/feed?terminal_id={terminal}&since={since}"
            result = await asyncio.to_thread(self._local_request, "GET", path)
            messages = result.get("messages") or []
            since = int(result.get("latest_seq") or since)
            replies = [message for message in messages
                       if message.get("source") == "connector"
                       and message.get("role") == "assistant"
                       and int(message.get("reply_to_seq") or 0) == request_seq]
            if replies:
                output = clean_output(replies)
                relay_error = str(replies[-1].get("error") or "")
                break
        else:
            output = "요청은 전달됐지만 제한 시간 안에 응답이 오지 않았습니다."
            relay_error = "response_timeout"
        if not output:
            output = "요청은 전달됐지만 아직 응답이 없습니다."
        for index, part in enumerate(chunks(output)):
            await self.send(channel, f"```text\n{part}\n```", message_id if index == 0 else "")
        return relay_error

    async def handle_message(self, event: dict) -> None:
        if not self._allowed(event):
            return
        event_id = str(event.get("id") or "")
        channel = str(event.get("channel_id") or "")
        content = str(event.get("content") or "").strip()
        binding = self.bindings.get(channel)
        approval_required = False
        if not binding:
            binding, approval_required, content = self._group_binding(channel, content)
        if approval_required:
            await self.send(channel, "여러 터미널에 전달되는 요청입니다. 승인 기능이 연결될 때까지 실행하지 않습니다.", event_id)
            return
        if not event_id or not binding or binding["node_id"] != self.node_id:
            return
        if event_id in self._recent:
            return
        author = event.get("author") or {}
        claimed = await asyncio.to_thread(
            self.claim_event, f"discord:{self.node_id}", event_id, str(author.get("id") or ""), channel,
            binding["terminal_id"], binding["project_id"], {"node_id": self.node_id})
        if not claimed:
            return
        self._recent.append(event_id)
        if not content:
            await asyncio.to_thread(self.mark_event, f"discord:{self.node_id}", event_id, "ignored_empty")
            return
        terminal = binding["terminal_id"]
        project = binding["project_id"]
        result = await asyncio.to_thread(self._local_request, "POST", "/api/agent/chat/bus", {
            "terminal_id": terminal, "source": "connector", "role": "user",
            "content": content, "actor_name": author.get("global_name") or author.get("username") or "Discord",
            "project_id": project,
        })
        if result.get("error"):
            await asyncio.to_thread(self.mark_event, f"discord:{self.node_id}", event_id, "failed", result)
            await self.send(channel, f"터미널 전달 실패: `{result['error']}`", event_id)
            return
        await asyncio.to_thread(self.mark_event, f"discord:{self.node_id}", event_id, "injected")
        relay_error = await self._capture_output(
            channel, event_id, binding, int(result.get("seq") or 0))
        final_status = "failed" if relay_error else "completed"
        await asyncio.to_thread(
            self.mark_event, f"discord:{self.node_id}", event_id, final_status,
            {"error": relay_error} if relay_error else None)

    async def _heartbeat(self, websocket, interval: float, sequence_ref: list) -> None:
        while True:
            await asyncio.sleep(interval)
            await websocket.send(json.dumps({"op": 1, "d": sequence_ref[0]}))

    async def connect_once(self) -> None:
        gateway = await asyncio.to_thread(self._request, "GET", "/gateway/bot")
        async with websockets.connect(gateway["url"] + "/?v=10&encoding=json", max_size=2 ** 20) as ws:
            hello = json.loads(await ws.recv())
            interval = float(hello["d"]["heartbeat_interval"]) / 1000
            sequence = [None]
            heartbeat = asyncio.create_task(self._heartbeat(ws, interval, sequence))
            await ws.send(json.dumps({"op": 2, "d": {
                "token": self.token, "intents": INTENTS,
                "properties": {"os": os.name, "browser": "vibe-coding", "device": "vibe-coding"},
            }}))
            try:
                async for raw in ws:
                    message = json.loads(raw)
                    if message.get("s") is not None:
                        sequence[0] = message["s"]
                    if message.get("op") == 7:
                        return
                    if message.get("t") == "MESSAGE_CREATE":
                        asyncio.create_task(self.handle_message(message.get("d") or {}))
            finally:
                heartbeat.cancel()

    async def serve(self) -> None:
        delay = 2
        while True:
            try:
                await self.connect_once()
                delay = 2
            except Exception as error:
                print(f"[discord-gateway] reconnect: {type(error).__name__}", flush=True)
                await asyncio.sleep(delay)
                delay = min(60, delay * 2)


def main() -> int:
    gateway = DiscordGateway()
    if not gateway.ready():
        print("[discord-gateway] token, ACL, channel bindings are required", flush=True)
        return 0
    asyncio.run(gateway.serve())
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
