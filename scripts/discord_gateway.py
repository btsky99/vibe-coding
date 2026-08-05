"""
FILE: scripts/discord_gateway.py
DESCRIPTION: 단일 Discord 봇 연결로 허가된 채널 메시지를 백그라운드 대화 버스에
             게시하고, 같은 버스의 상관 응답을 Discord 채널로 반환한다.

REVISION HISTORY:
- 2026-08-06 Claude: 응답 대기 180초 하드코딩 제거(서버 600초와 어긋나 답변 유실) + 경과 표시
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

# [제약] .ai_monitor는 설치된 패키지가 아니라 프로젝트 내부 디렉터리다. 데몬은 cwd를
#   프로젝트 루트로 바꿔 띄우므로 cwd가 아닌 __file__ 기준으로 넣어야 한다.
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / ".ai_monitor"))

from src.connector_core import GATEWAY_WAIT_SEC   # noqa: E402 — 위 sys.path 주입 이후여야 한다


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

    async def send(self, channel_id: str, content: str, reply_id: str = "") -> str:
        """보낸 메시지 id를 돌려준다 — 진행 표시를 나중에 편집으로 갱신하기 위해 필요하다."""
        payload: dict[str, Any] = {"content": content, "allowed_mentions": {"parse": []}}
        if reply_id:
            payload["message_reference"] = {"message_id": reply_id, "fail_if_not_exists": False}
        result = await asyncio.to_thread(
            self._request, "POST", f"/channels/{channel_id}/messages", payload)
        return str(result.get("id") or "")

    async def _edit(self, channel_id: str, message_id: str, content: str) -> None:
        await asyncio.to_thread(
            self._request, "PATCH", f"/channels/{channel_id}/messages/{message_id}",
            {"content": content, "allowed_mentions": {"parse": []}})

    def _allowed(self, event: dict) -> bool:
        author = event.get("author") or {}
        return (str(event.get("guild_id")) in self.guilds
                and str(event.get("channel_id")) in self.channels
                and str(author.get("id")) in self.actors
                and not author.get("bot") and not event.get("webhook_id"))

    async def _progress(self, channel: str, reply_to: str, progress_id: str,
                        elapsed: float) -> str:
        """경과 표시를 한 건만 만들고 그 뒤로는 편집한다 — 채널을 알림으로 도배하지 않는다.

        [WHY 예외를 삼키나] 진행 표시는 편의 기능이다. 여기서 예외가 위로 올라가면
          본 응답 수거 루프가 통째로 죽어 답변이 유실된다 — 원래 고치려던 사고와 같은
          결과가 되므로, 표시에 실패해도 대기는 계속한다.
        """
        text = f"⏳ 작업 중… {int(elapsed)}초 경과"
        try:
            if progress_id:
                await self._edit(channel, progress_id, text)
                return progress_id
            return await self.send(channel, text, reply_to)
        except Exception:                                # noqa: BLE001 — 위 [WHY] 참조
            return progress_id

    async def _deliver(self, channel: str, reply_to: str, progress_id: str,
                       output: str) -> None:
        """진행 표시가 있으면 그 자리를 첫 청크로 덮어 메시지 수를 늘리지 않는다."""
        for index, part in enumerate(chunks(output)):
            body = f"```text\n{part}\n```"
            if index == 0 and progress_id:
                try:
                    await self._edit(channel, progress_id, body)
                    continue
                except Exception:                        # noqa: BLE001
                    pass                                 # 편집 실패는 새 메시지로 흘린다 — 중복이 유실보다 낫다
            await self.send(channel, body, reply_to if index == 0 else "")

    async def _capture_output(self, channel: str, message_id: str, binding: dict,
                              request_seq: int) -> str:
        """버스에 상관 응답이 실릴 때까지 폴링하고 Discord로 되돌린다.

        [불변식] GATEWAY_WAIT_SEC > 서버 RELAY_TIMEOUT_SEC — connector_core가 보장한다.
          역전되면 서버가 답을 남기기 전에 여기서 포기해 답변이 DB에만 남고 유실된다.
        [WHY 진행 표시] 헤드리스 claude는 턴이 끝나야 답을 남기므로 도구를 여러 번 쓰는
          요청은 수 분간 완전 무음이다. 무음은 '연결이 끊겼다'로 읽혀 같은 요청을 다시
          보내게 만들고, 그러면 터미널 직렬 락에 걸려 실제로 더 느려진다.
        """
        terminal = binding["terminal_id"]
        since = request_seq
        started = time.monotonic()
        deadline = started + GATEWAY_WAIT_SEC
        progress_id = ""
        next_ping = 20.0
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
            elapsed = time.monotonic() - started
            if elapsed >= next_ping:
                next_ping = elapsed + 30
                progress_id = await self._progress(channel, message_id, progress_id, elapsed)
        else:
            output = f"요청은 전달됐지만 {int(GATEWAY_WAIT_SEC // 60)}분 안에 응답이 오지 않았습니다."
            relay_error = "response_timeout"
        if not output:
            output = "요청은 전달됐지만 아직 응답이 없습니다."
        await self._deliver(channel, message_id, progress_id, output)
        return relay_error

    async def _handle_recycle(self, channel: str, event_id: str, terminal: str,
                              project: str, content: str) -> None:
        """세션 리사이클 명령 처리. 판정·실행은 전부 서버 API가 한다.

        [제약] '--force'는 승인 대기·플래핑 가드만 뚫는다. 동시 실행(already_running)은
          force로도 안 뚫리며, 그건 서버 쪽 plan_recycle의 불변식이다.
        """
        args = content.split()[1:]
        force = "--force" in args or "강제" in args
        try:
            res = await asyncio.to_thread(
                self._local_request, "POST", "/api/session/recycle",
                {"terminal_id": terminal, "project_id": project,
                 "trigger": "manual", "force": force})
        except Exception as exc:
            await asyncio.to_thread(self.mark_event, f"discord:{self.node_id}",
                                    event_id, "failed", {"error": str(exc)})
            await self.send(channel, f"리사이클 호출 실패: `{exc}`", event_id)
            return

        if res.get("ok"):
            note = " (재정박 축약됨)" if res.get("truncated") else ""
            msg = (f"✅ `{terminal}` 세션을 교체했습니다{note}.\n"
                   f"재정박 {res.get('reanchor_chars')}자 주입 완료 — 이어서 진행하면 됩니다.")
        else:
            reason = res.get("reason") or "unknown"
            msg = f"⏸ 리사이클하지 않았습니다 — `{reason}`"
            if res.get("fallback_path"):
                # 세션은 잃었지만 재정박 프롬프트는 건졌다 — 수동 복구 경로를 알려준다.
                msg += f"\n재정박 내용은 `{res['fallback_path']}`에 보존했습니다."
        await asyncio.to_thread(self.mark_event, f"discord:{self.node_id}", event_id,
                                "completed" if res.get("ok") else "ignored", res)
        await self.send(channel, msg, event_id)

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

        # [WHY 명시 명령] "세션 마감해" 같은 자연어 매칭은 쓰지 않는다 — 오탐 한 번이
        #   곧 세션 파괴다. 되돌릴 수 없는 동작은 오직 명시 토큰으로만 연다.
        if content.split()[0].lower() in ("!recycle", "!리사이클"):
            await self._handle_recycle(channel, event_id, terminal, project, content)
            return

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
