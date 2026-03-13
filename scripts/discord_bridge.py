# -*- coding: utf-8 -*-
"""
Discord Multi-Terminal Bridge.

Revision history:
- 2026-03-12 Claude: PTY-first remote control with server API integration
- 2026-03-04 Gemini/Claude: Initial Discord channel mapping and relay server
"""

from __future__ import annotations

import asyncio
import collections
import json
import os
import time
from pathlib import Path
from typing import Any

import aiohttp
import discord
from aiohttp import web
from discord.ext import commands
from dotenv import load_dotenv

load_dotenv()

_SCRIPTS_DIR = Path(__file__).resolve().parent
_PROJECT_ROOT = _SCRIPTS_DIR.parent
_LOG_FILE = _PROJECT_ROOT / '.ai_monitor' / 'data' / 'messages.jsonl'

TERMINAL_CLI_MAP = {
    1: 'gemini',
    2: 'claude',
}

DISCORD_MAX_LEN = 1900
SERVER_PORT = int(os.getenv('VIBE_SERVER_PORT', '9000'))
API_TIMEOUT = aiohttp.ClientTimeout(total=10)
SERVER_PORT_SCAN_LIMIT = 12


class DiscordBridge(commands.Bot):
    def __init__(self):
        intents = discord.Intents.default()
        intents.message_content = True
        super().__init__(command_prefix='!', intents=intents)

        self.terminal_map: dict[int, int] = {}
        self.channel_to_terminal: dict[int, int] = {}
        for i in range(1, 9):
            channel_id = os.getenv(f'DISCORD_CHANNEL_T{i}')
            if channel_id and channel_id.isdigit():
                cid = int(channel_id)
                self.terminal_map[i] = cid
                self.channel_to_terminal[cid] = i

        self.message_queues: dict[int, asyncio.Queue] = collections.defaultdict(asyncio.Queue)
        self.running = True
        self.http_session: aiohttp.ClientSession | None = None
        self.server_api_base = f'http://127.0.0.1:{SERVER_PORT}'
        self._api_server_started = False
        self._ready_announced = False
        self._output_poll_started = False
        self._last_output_seq: dict[int, int] = {tid: 0 for tid in range(1, 9)}
        self._output_bootstrap_done: set[int] = set()

    async def setup_hook(self):
        self.http_session = aiohttp.ClientSession(timeout=API_TIMEOUT)
        await self._discover_server_api_base()

    async def close(self):
        self.running = False
        if self.http_session and not self.http_session.closed:
            await self.http_session.close()
        await super().close()

    async def on_ready(self):
        print(f'[*] Discord Bridge connected as {self.user}')

        if not self._api_server_started:
            for tid in self.terminal_map:
                asyncio.create_task(self.process_queue(tid))
            asyncio.create_task(self.start_api_server())
            self._api_server_started = True
        if not self._output_poll_started:
            asyncio.create_task(self.poll_pty_output())
            self._output_poll_started = True

        if self._ready_announced:
            return

        for tid, cid in self.terminal_map.items():
            channel = await self._resolve_channel(cid)
            if not channel:
                continue
            cli_hint = TERMINAL_CLI_MAP.get(tid, 'auto')
            await channel.send(
                '\n'.join([
                    f'**Terminal-{tid}** 연결 완료',
                    f'- 기본 fallback CLI: `{cli_hint}`',
                    '- 일반 메시지: PTY가 살아 있으면 직접 입력, 없으면 새 작업 시작',
                    '- `!status`, `!stop`, `!kill`, `!run <task>`, `!send <text>`, `!help`',
                ])
            )

        self._ready_announced = True

    async def on_message(self, message: discord.Message):
        if message.author == self.user or message.author.bot:
            return

        tid = self.channel_to_terminal.get(message.channel.id)
        if tid is None:
            return

        content = (message.content or '').strip()
        if not content:
            return

        self._log_message(tid, message.author.name, content)

        if content.startswith('!'):
            await self._handle_command(tid, message.channel, content)
            return

        await message.add_reaction('🛰️')
        await self._route_regular_message(tid, message.channel, content)

    async def _handle_command(self, tid: int, channel: discord.abc.Messageable, content: str):
        parts = content.split(maxsplit=1)
        command = parts[0].lower()
        argument = parts[1].strip() if len(parts) > 1 else ''

        if command == '!help':
            await channel.send(
                '\n'.join([
                    '`!status` 현재 채널 터미널 상태',
                    '`!status all` 전체 T1~T8 상태',
                    '`!send <text>` 살아 있는 PTY에 직접 입력',
                    '`!run <task>` PTY와 무관하게 새 agent/run 시작',
                    '`!stop` 살아 있는 PTY는 Ctrl+C, 아니면 백그라운드 run stop',
                    '`!kill` 살아 있는 PTY 세션 강제 종료',
                    '일반 메시지는 PTY 우선 제어입니다.',
                ])
            )
            return

        if command == '!status':
            if argument.lower() == 'all':
                await channel.send(await self._format_all_status())
            else:
                await channel.send(await self._format_terminal_status(tid))
            return

        if command == '!send':
            if not argument:
                await channel.send('사용법: `!send <text>`')
                return
            await self._send_to_pty(tid, channel, argument, require_live=True)
            return

        if command == '!run':
            if not argument:
                await channel.send('사용법: `!run <task>`')
                return
            await self._start_agent_run(tid, channel, argument)
            return

        if command == '!stop':
            await self._stop_terminal(tid, channel)
            return

        if command == '!kill':
            await self._kill_terminal(tid, channel)
            return

        await channel.send(f'알 수 없는 명령입니다: `{command}`. `!help`를 확인하세요.')

    async def _route_regular_message(self, tid: int, channel: discord.abc.Messageable, content: str):
        pty_state, agent_state = await self._get_terminal_states(tid)

        if pty_state.get('running'):
            await self._send_to_pty(tid, channel, content, require_live=False)
            return

        if agent_state.get('status') == 'running':
            await channel.send(
                f'`T{tid}` 는 현재 백그라운드 작업 중입니다. '
                'PTY가 연결돼 있지 않아 직접 주입은 못 합니다. `!stop` 후 다시 시도하세요.'
            )
            return

        await self._start_agent_run(tid, channel, content)

    async def _format_all_status(self) -> str:
        rows = []
        for tid in range(1, 9):
            pty_state, agent_state = await self._get_terminal_states(tid)
            rows.append(self._status_line(tid, pty_state, agent_state))
        return '```text\n' + '\n'.join(rows) + '\n```'

    async def _format_terminal_status(self, tid: int) -> str:
        pty_state, agent_state = await self._get_terminal_states(tid)
        lines = [
            f'T{tid} 상태',
            self._status_line(tid, pty_state, agent_state),
        ]

        if pty_state.get('running'):
            if pty_state.get('cwd'):
                lines.append(f'cwd: {self._trim(pty_state.get("cwd", ""), 120)}')
            if pty_state.get('last_line'):
                lines.append(f'last: {self._trim(pty_state.get("last_line", ""), 120)}')
        elif agent_state.get('status') == 'running':
            if agent_state.get('task'):
                lines.append(f'task: {self._trim(agent_state.get("task", ""), 120)}')
            if agent_state.get('last_line'):
                lines.append(f'last: {self._trim(agent_state.get("last_line", ""), 120)}')

        return '```text\n' + '\n'.join(lines) + '\n```'

    def _status_line(self, tid: int, pty_state: dict[str, Any], agent_state: dict[str, Any]) -> str:
        if pty_state.get('running'):
            agent = pty_state.get('agent', '') or '?'
            last_line = self._trim(pty_state.get('last_line', ''), 60)
            suffix = f' | {last_line}' if last_line else ''
            return f'T{tid}: PTY {agent}{suffix}'

        if agent_state.get('status') == 'running':
            cli = agent_state.get('cli', '') or '?'
            task = self._trim(agent_state.get('task', ''), 60)
            suffix = f' | {task}' if task else ''
            return f'T{tid}: agent {cli}{suffix}'

        return f'T{tid}: idle'

    async def _stop_terminal(self, tid: int, channel: discord.abc.Messageable):
        pty_state, agent_state = await self._get_terminal_states(tid)

        if pty_state.get('running'):
            response = await self._api_post_json('/api/pty/interrupt', {'target': tid})
            if response.get('status') == 'interrupted':
                await channel.send(f'`T{tid}` PTY에 Ctrl+C를 보냈습니다.')
            else:
                await channel.send(self._format_api_error('PTY interrupt 실패', response))
            return

        if agent_state.get('status') == 'running':
            response = await self._api_post_json('/api/agent/stop', {})
            if response.get('status') == 'stopped':
                await channel.send(f'`T{tid}` 백그라운드 작업 정지를 요청했습니다.')
            else:
                await channel.send(self._format_api_error('agent stop 실패', response))
            return

        await channel.send(f'`T{tid}` 는 현재 idle 입니다.')

    async def _kill_terminal(self, tid: int, channel: discord.abc.Messageable):
        response = await self._api_post_json('/api/pty/terminate', {'target': tid})
        if response.get('status') == 'terminated':
            await channel.send(f'`T{tid}` PTY 세션을 종료했습니다.')
            return
        await channel.send(self._format_api_error('PTY 종료 실패', response))

    async def _send_to_pty(
        self,
        tid: int,
        channel: discord.abc.Messageable,
        content: str,
        require_live: bool,
    ):
        pty_state = await self._get_pty_state(tid)
        if require_live:
            if not pty_state.get('running'):
                await channel.send(f'`T{tid}` 에 살아 있는 PTY가 없습니다.')
                return

        submit_count = 2 if str(pty_state.get('agent', '')).lower() in ('gemini', 'codex') else 1
        normalized = content.replace('\r\n', '\r').replace('\n', '\r').rstrip('\r')
        submit_text = normalized + ('\r' * submit_count)

        response = await self._api_post_json('/api/send-command', {
            'target': tid,
            'command': submit_text,
        })

        if response.get('status') == 'success':
            await channel.send(f'`T{tid}` PTY로 전달했습니다.')
            return

        if not require_live:
            await self._start_agent_run(tid, channel, content)
            return

        await channel.send(self._format_api_error('PTY 전달 실패', response))

    async def _start_agent_run(self, tid: int, channel: discord.abc.Messageable, task: str):
        response = await self._api_post_json('/api/agent/run', {
            'task': task,
            'cli': TERMINAL_CLI_MAP.get(tid, 'auto'),
            'terminal_id': f'T{tid}',
        })

        if response.get('status') == 'started':
            cli = response.get('cli', TERMINAL_CLI_MAP.get(tid, 'auto'))
            await channel.send(
                f'`T{tid}` 새 작업을 시작했습니다. '
                f'CLI=`{cli}` task=`{self._trim(task, 100)}`'
            )
            return

        if response.get('error') == 'already_running':
            await channel.send(f'현재 다른 백그라운드 작업이 이미 실행 중입니다. `!status`로 확인하세요.')
            return

        await channel.send(self._format_api_error('agent/run 실패', response))

    async def _get_terminal_states(self, tid: int) -> tuple[dict[str, Any], dict[str, Any]]:
        pty_state = await self._get_pty_state(tid)
        agent_state = await self._get_agent_state(tid)
        return pty_state, agent_state

    async def _get_pty_state(self, tid: int) -> dict[str, Any]:
        payload = await self._api_get_json('/api/pty/terminals')
        return payload.get(f'T{tid}', {}) if isinstance(payload, dict) else {}

    async def _get_agent_state(self, tid: int) -> dict[str, Any]:
        payload = await self._api_get_json('/api/agent/terminals')
        return payload.get(f'T{tid}', {}) if isinstance(payload, dict) else {}

    async def _get_pty_output(self, tid: int, since: int) -> dict[str, Any]:
        return await self._api_get_json(f'/api/pty/output?terminal_id=T{tid}&since={since}&limit=120')

    async def _api_get_json(self, path: str) -> dict[str, Any]:
        if self.http_session is None:
            return {'error': 'http_session_unavailable'}

        return await self._api_request_json('get', path)

    async def _api_post_json(self, path: str, payload: dict[str, Any]) -> dict[str, Any]:
        if self.http_session is None:
            return {'error': 'http_session_unavailable'}

        return await self._api_request_json('post', path, payload)

    async def _api_request_json(
        self,
        method: str,
        path: str,
        payload: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        if self.http_session is None:
            return {'error': 'http_session_unavailable'}

        for attempt in range(2):
            try:
                if method == 'get':
                    request = self.http_session.get(self._api_url(path))
                else:
                    request = self.http_session.post(self._api_url(path), json=payload)
                async with request as response:
                    data = await self._read_json_response(response)
                    if isinstance(data, dict):
                        data['_http_status'] = response.status
                    return data if isinstance(data, dict) else {'data': data, '_http_status': response.status}
            except Exception as exc:
                if attempt == 0 and await self._discover_server_api_base(force=True):
                    continue
                return {'error': 'request_failed', 'detail': str(exc)}

        return {'error': 'request_failed', 'detail': 'unreachable'}

    async def _read_json_response(self, response: aiohttp.ClientResponse) -> Any:
        try:
            return await response.json(content_type=None)
        except Exception:
            return {'error': 'invalid_response', 'detail': await response.text()}

    def _format_api_error(self, prefix: str, response: dict[str, Any]) -> str:
        message = (
            response.get('message')
            or response.get('error')
            or response.get('detail')
            or json.dumps(response, ensure_ascii=False)
        )
        return f'{prefix}: {self._trim(str(message), 180)}'

    def _trim(self, text: str, limit: int) -> str:
        text = (text or '').replace('\r', ' ').replace('\n', ' ').strip()
        if len(text) <= limit:
            return text
        return text[: limit - 3] + '...'

    def _api_url(self, path: str) -> str:
        return f'{self.server_api_base}{path}'

    async def _discover_server_api_base(self, force: bool = False) -> bool:
        if self.http_session is None:
            return False

        if not force:
            try:
                async with self.http_session.get(self._api_url('/api/heartbeat')) as response:
                    if response.status == 200:
                        return True
            except Exception:
                pass

        for port in self._candidate_server_ports():
            base = f'http://127.0.0.1:{port}'
            try:
                async with self.http_session.get(f'{base}/api/heartbeat') as response:
                    if response.status == 200:
                        if base != self.server_api_base:
                            print(f'[discord_bridge] server api -> {base}')
                        self.server_api_base = base
                        return True
            except Exception:
                continue

        return False

    def _candidate_server_ports(self) -> list[int]:
        ports: list[int] = []
        for start in (SERVER_PORT, 9000):
            for port in range(start, start + SERVER_PORT_SCAN_LIMIT):
                if port not in ports:
                    ports.append(port)
        return ports

    async def _resolve_channel(self, channel_id: int | None) -> discord.abc.Messageable | None:
        if not channel_id:
            return None

        channel = self.get_channel(channel_id)
        if channel:
            return channel

        try:
            return await self.fetch_channel(channel_id)
        except Exception as exc:
            print(f'[discord_bridge] channel resolve failed ({channel_id}): {exc}')
            return None

    async def poll_pty_output(self):
        while self.running:
            try:
                for tid in sorted(self.terminal_map):
                    payload = await self._get_pty_output(tid, self._last_output_seq.get(tid, 0))
                    if payload.get('error'):
                        continue

                    latest_seq = int(payload.get('latest_seq', 0) or 0)
                    entries = payload.get('entries') or []

                    if tid not in self._output_bootstrap_done:
                        self._last_output_seq[tid] = latest_seq
                        self._output_bootstrap_done.add(tid)
                        continue

                    if not entries:
                        self._last_output_seq[tid] = max(self._last_output_seq.get(tid, 0), latest_seq)
                        continue

                    self._last_output_seq[tid] = max(
                        self._last_output_seq.get(tid, 0),
                        max(int(entry.get('seq', 0) or 0) for entry in entries),
                    )

                    channel = await self._resolve_channel(self.terminal_map.get(tid))
                    if not channel:
                        continue

                    lines = [self._trim(str(entry.get('text', '')), 300) for entry in entries if entry.get('text')]
                    if not lines:
                        continue

                    chunk = ''
                    for line in lines:
                        next_chunk = f'{chunk}\n{line}' if chunk else line
                        if len(next_chunk) > DISCORD_MAX_LEN - 8:
                            await channel.send(f'```text\n{chunk}\n```')
                            chunk = line
                        else:
                            chunk = next_chunk
                    if chunk:
                        await channel.send(f'```text\n{chunk}\n```')
            except Exception as exc:
                print(f'[discord_bridge] output poll failed: {exc}')

            await asyncio.sleep(1.0)

    async def process_queue(self, tid: int):
        queue = self.message_queues[tid]
        while self.running:
            msg = await queue.get()
            channel = await self._resolve_channel(self.terminal_map.get(tid))
            if channel:
                if len(msg) > DISCORD_MAX_LEN:
                    msg = msg[:DISCORD_MAX_LEN] + '...'
                if msg.startswith(('**', '`', 'T', '[', '!', '- ')):
                    await channel.send(msg)
                else:
                    await channel.send(f'```\n{msg}\n```')
            queue.task_done()
            await asyncio.sleep(0.2)

    async def start_api_server(self):
        app = web.Application()
        app.router.add_post('/send', self.handle_api_send)
        runner = web.AppRunner(app)
        await runner.setup()
        site = web.TCPSite(runner, 'localhost', 8008)
        await site.start()
        print('[*] Discord Bridge relay server: http://localhost:8008')

    async def handle_api_send(self, request: web.Request) -> web.Response:
        data = await request.json()
        tid = int(data.get('terminal_id', 1))
        text = data.get('content', '')
        await self.send_to_discord(tid, text)
        return web.json_response({'status': 'sent'})

    async def send_to_discord(self, tid: int, text: str):
        if tid in self.terminal_map:
            await self.message_queues[tid].put(text)

    def _log_message(self, tid: int, author: str, content: str):
        try:
            _LOG_FILE.parent.mkdir(parents=True, exist_ok=True)
            message = {
                'id': str(int(time.time() * 1000)),
                'timestamp': __import__('datetime').datetime.now().isoformat(),
                'from': f'discord_{author}',
                'to': 'agent',
                'terminal': tid,
                'content': f'[Terminal {tid}] {content}',
                'read': False,
            }
            with _LOG_FILE.open('a', encoding='utf-8') as file:
                file.write(json.dumps(message, ensure_ascii=False) + '\n')
        except Exception as exc:
            print(f'[discord_bridge] log write failed: {exc}')


async def main():
    token = os.getenv('DISCORD_BOT_TOKEN')
    if not token:
        print('[!] DISCORD_BOT_TOKEN is missing in .env')
        return

    bridge = DiscordBridge()
    async with bridge:
        await bridge.start(token)


if __name__ == '__main__':
    asyncio.run(main())
