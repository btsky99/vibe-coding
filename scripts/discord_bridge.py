# -*- coding: utf-8 -*-
"""
# ------------------------------------------------------------------------
# 📄 파일명: scripts/discord_bridge.py
# 📝 설명: Discord Multi-Terminal Bridge.
#          8개 Discord 채널(#terminal-1~8)을 8개 터미널과 1:1 매핑하여
#          디스코드 메시지 → cli_agent 자동 실행 → 결과 채널 전송.
#
# 🕒 변경 이력 (REVISION HISTORY):
# [2026-03-04] Gemini: 최초 구현 — 채널 매핑, 큐 처리, API 서버 (8008포트)
# [2026-03-04] Claude: Task 12 구현 — discord 메시지 수신 시 cli_agent 자동 실행
#   - 터미널별 CLI 우선순위: T1=gemini, T2=claude, T3+=auto
#   - asyncio.create_subprocess_exec으로 cli_agent.py 비동기 실행
#   - 출력 라인 누적 후 코드블록으로 Discord 전송 (rate limit 고려)
#   - 터미널별 실행 중 플래그 (_running_terminals) — 중복 실행 방지
#   - messages.jsonl 로깅 유지 (하이브 메모리 연동)
# ------------------------------------------------------------------------
"""

import os
import sys
import asyncio
import json
import collections
import time
from pathlib import Path

import discord
from discord.ext import commands
from dotenv import load_dotenv
from aiohttp import web

load_dotenv()

# ─── 경로 설정 ────────────────────────────────────────────────────────────────
_SCRIPTS_DIR = Path(__file__).resolve().parent
_PROJECT_ROOT = _SCRIPTS_DIR.parent
_CLI_AGENT    = _SCRIPTS_DIR / "cli_agent.py"
_LOG_FILE     = _PROJECT_ROOT / ".ai_monitor" / "data" / "messages.jsonl"

# ─── 터미널별 CLI 우선순위 테이블 ─────────────────────────────────────────────
# T1 → Gemini (설계/분석 전담), T2 → Claude (코드/구현 전담), 나머지 → auto
TERMINAL_CLI_MAP = {
    1: 'gemini',
    2: 'claude',
}

# ─── Discord 메시지 최대 길이 (2000자 제한) ───────────────────────────────────
DISCORD_MAX_LEN = 1900


class DiscordBridge(commands.Bot):
    def __init__(self):
        intents = discord.Intents.default()
        intents.message_content = True
        super().__init__(command_prefix='!', intents=intents)

        # 환경변수에서 채널 ID 로드 → terminal_map, channel_to_terminal 구성
        self.terminal_map: dict[int, int] = {}          # tid → channel_id
        self.channel_to_terminal: dict[int, int] = {}   # channel_id → tid
        for i in range(1, 9):
            channel_id = os.getenv(f'DISCORD_CHANNEL_T{i}')
            if channel_id and channel_id.isdigit():
                cid = int(channel_id)
                self.terminal_map[i] = cid
                self.channel_to_terminal[cid] = i

        # 터미널별 출력 큐 (Discord 전송 속도 제한 대응)
        self.message_queues: dict[int, asyncio.Queue] = collections.defaultdict(asyncio.Queue)
        # 터미널별 실행 중 여부 플래그 — 동일 터미널 중복 실행 방지
        self._running_terminals: set[int] = set()
        self.running = True

    # ──────────────────────────────────────────────────────────────────────────
    # on_ready: 봇 준비 완료 시 큐 처리 태스크 + API 서버 + 인사 메시지 시작
    # ──────────────────────────────────────────────────────────────────────────
    async def on_ready(self):
        print(f'🚀 Discord Bridge 가동: {self.user}')
        for tid in self.terminal_map:
            asyncio.create_task(self.process_queue(tid))
        asyncio.create_task(self.start_api_server())

        for tid, cid in self.terminal_map.items():
            channel = self.get_channel(cid)
            if channel:
                cli_hint = TERMINAL_CLI_MAP.get(tid, 'auto')
                await channel.send(
                    f"🟢 **Terminal-{tid}** 연결 완료! "
                    f"CLI 우선순위: `{cli_hint}` — 메시지를 입력하면 에이전트가 자동 실행됩니다."
                )

    # ──────────────────────────────────────────────────────────────────────────
    # on_message: 채널 메시지 수신 → cli_agent 비동기 실행
    # ──────────────────────────────────────────────────────────────────────────
    async def on_message(self, message: discord.Message):
        # 봇 자신의 메시지는 무시 (무한 루프 방지)
        if message.author == self.user:
            return

        tid = self.channel_to_terminal.get(message.channel.id)
        if tid is None:
            return  # 등록된 터미널 채널이 아니면 무시

        # 명령어 처리 우선 (!help 등)
        await self.process_commands(message)

        # ── 수신 반응: 처리 시작 알림 ─────────────────────────────────────────
        await message.add_reaction('🧠')

        # ── messages.jsonl 하이브 로그 기록 (다른 에이전트와 공유) ────────────
        self._log_message(tid, message.author.name, message.content)

        # ── 중복 실행 방지 ────────────────────────────────────────────────────
        if tid in self._running_terminals:
            await message.channel.send(
                f"⚠️ **Terminal-{tid}** 에이전트 실행 중입니다. 완료 후 입력하세요."
            )
            await message.add_reaction('⏳')
            return

        # ── cli_agent 비동기 실행 태스크 생성 ────────────────────────────────
        # 비동기 태스크로 분리하여 on_message 블로킹 방지
        asyncio.create_task(
            self._run_agent(tid, message.channel, message.content)
        )

    # ──────────────────────────────────────────────────────────────────────────
    # _run_agent: cli_agent.py를 서브프로세스로 실행하고 출력을 Discord로 전송
    # ──────────────────────────────────────────────────────────────────────────
    async def _run_agent(self, tid: int, channel, task: str):
        """cli_agent.py를 비동기 서브프로세스로 실행합니다.

        asyncio.create_subprocess_exec으로 cli_agent.py를 가동하고
        stdout을 실시간으로 읽어 Discord 채널에 전송합니다.

        Args:
            tid: 터미널 ID (1~8)
            channel: Discord 채널 객체
            task: 실행할 지시 내용
        """
        self._running_terminals.add(tid)
        cli = TERMINAL_CLI_MAP.get(tid, 'auto')

        await channel.send(f"⚡ **Terminal-{tid}** `{cli}` 에이전트 시작...\n> {task[:100]}")

        try:
            # cli_agent.py를 비동기 서브프로세스로 실행
            # Python 실행 경로는 현재 인터프리터와 동일하게 사용
            # CLI_AGENT_JSON_STDOUT=1: cli_agent.py가 stdout에 JSON 이벤트 출력
            # (기본적으로 SSE Queue에만 넣는데, 이 플래그로 subprocess 캡처 가능)
            env = os.environ.copy()
            env['CLI_AGENT_JSON_STDOUT'] = '1'

            proc = await asyncio.create_subprocess_exec(
                sys.executable,       # 동일 Python 인터프리터
                str(_CLI_AGENT),      # scripts/cli_agent.py
                task,                 # 지시 내용
                cli,                  # CLI 선택 (claude|gemini|auto)
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.STDOUT,  # stderr를 stdout으로 합침
                cwd=str(_PROJECT_ROOT),
                env=env,
            )

            # ── 실시간 출력 수집 + Discord 전송 ──────────────────────────────
            # 50줄 또는 2초 타임아웃마다 Discord에 일괄 전송 (rate limit 대응)
            buffer: list[str] = []
            last_send_time = asyncio.get_event_loop().time()

            async def flush_buffer():
                """버퍼에 쌓인 출력을 Discord 코드블록으로 전송합니다."""
                nonlocal buffer, last_send_time
                if not buffer:
                    return
                chunk = '\n'.join(buffer)
                # Discord 2000자 제한 — 초과 시 잘라서 전송
                while chunk:
                    send_part = chunk[:DISCORD_MAX_LEN]
                    chunk = chunk[DISCORD_MAX_LEN:]
                    await channel.send(f"```\n{send_part}\n```")
                buffer = []
                last_send_time = asyncio.get_event_loop().time()

            async for line_bytes in proc.stdout:
                line = line_bytes.decode('utf-8', errors='replace').rstrip()
                # cli_agent의 내부 이벤트 JSON(started/done/error 타입)은 Discord에 표시 안 함
                # 일반 텍스트 출력만 전달
                try:
                    evt = json.loads(line)
                    if evt.get('type') == 'done':
                        await flush_buffer()
                        status = evt.get('status', 'done')
                        await channel.send(f"✅ **Terminal-{tid}** 완료 — 상태: `{status}`")
                    elif evt.get('type') == 'error':
                        await flush_buffer()
                        await channel.send(f"❌ **Terminal-{tid}** 오류: {evt.get('line', '')}")
                    elif evt.get('type') == 'output':
                        buffer.append(evt.get('line', ''))
                    # started 이벤트는 이미 위에서 안내 메시지 전송했으므로 무시
                except json.JSONDecodeError:
                    # JSON이 아닌 일반 텍스트 출력 (cli_agent 테스트 모드 출력 등)
                    buffer.append(line)

                # 50줄 누적 또는 2초 경과 시 Discord 전송
                now = asyncio.get_event_loop().time()
                if len(buffer) >= 50 or (buffer and now - last_send_time >= 2.0):
                    await flush_buffer()

            # 남은 버퍼 전송
            await flush_buffer()
            await proc.wait()

        except FileNotFoundError:
            await channel.send(f"❌ **Terminal-{tid}** cli_agent.py를 찾을 수 없습니다: {_CLI_AGENT}")
        except Exception as e:
            await channel.send(f"❌ **Terminal-{tid}** 에이전트 실행 오류: {e}")
        finally:
            # 실행 완료 후 플래그 해제 — 다음 명령 수신 가능
            self._running_terminals.discard(tid)

    # ──────────────────────────────────────────────────────────────────────────
    # process_queue: 터미널별 Discord 전송 큐 처리 (send_to_discord 경유 메시지)
    # ──────────────────────────────────────────────────────────────────────────
    async def process_queue(self, tid: int):
        """외부에서 send_to_discord()로 보낸 메시지를 Discord 채널로 전달합니다."""
        channel = self.get_channel(self.terminal_map.get(tid))
        queue = self.message_queues[tid]
        while self.running:
            msg = await queue.get()
            if channel:
                if len(msg) > DISCORD_MAX_LEN:
                    msg = msg[:DISCORD_MAX_LEN] + "..."
                # 이모지로 시작하는 상태 메시지는 코드블록 없이 전송
                if msg.startswith(('🟢', '🔴', '⚡', '✅', '❌', '⚠️')):
                    await channel.send(msg)
                else:
                    await channel.send(f"```\n{msg}\n```")
            queue.task_done()
            await asyncio.sleep(0.2)

    # ──────────────────────────────────────────────────────────────────────────
    # start_api_server: 외부에서 Discord 채널로 메시지를 보내는 API 서버 (8008포트)
    # 대시보드/다른 스크립트에서 POST /send → 특정 터미널 채널로 전송
    # ──────────────────────────────────────────────────────────────────────────
    async def start_api_server(self):
        app = web.Application()
        app.router.add_post('/send', self.handle_api_send)
        runner = web.AppRunner(app)
        await runner.setup()
        site = web.TCPSite(runner, 'localhost', 8008)
        await site.start()
        print("🌐 Bridge API Server: http://localhost:8008")

    async def handle_api_send(self, request: web.Request) -> web.Response:
        """POST /send { terminal_id: N, content: "..." } — 특정 터미널 채널로 메시지 전송."""
        data = await request.json()
        tid = data.get('terminal_id', 1)
        text = data.get('content', '')
        await self.send_to_discord(tid, text)
        return web.json_response({"status": "sent"})

    async def send_to_discord(self, tid: int, text: str):
        """외부 호출용: 특정 터미널 채널로 메시지를 큐에 넣습니다."""
        if tid in self.terminal_map:
            await self.message_queues[tid].put(text)

    # ──────────────────────────────────────────────────────────────────────────
    # _log_message: messages.jsonl에 하이브 메시지 로그 기록
    # ──────────────────────────────────────────────────────────────────────────
    def _log_message(self, tid: int, author: str, content: str):
        """수신 메시지를 messages.jsonl에 기록합니다 (하이브 메모리 연동)."""
        try:
            _LOG_FILE.parent.mkdir(parents=True, exist_ok=True)
            msg = {
                'id': str(int(time.time() * 1000)),
                'timestamp': __import__('datetime').datetime.now().isoformat(),
                'from': f'discord_{author}',
                'to': 'agent',
                'terminal': tid,
                'content': f"[Terminal {tid}] {content}",
                'read': False,
            }
            with _LOG_FILE.open('a', encoding='utf-8') as f:
                f.write(json.dumps(msg, ensure_ascii=False) + '\n')
        except Exception as e:
            print(f'[discord_bridge] 로그 기록 실패: {e}')


# ─── 진입점 ───────────────────────────────────────────────────────────────────
async def main():
    token = os.getenv('DISCORD_BOT_TOKEN')
    if not token:
        print("❌ DISCORD_BOT_TOKEN 환경변수가 설정되지 않았습니다. .env 파일을 확인하세요.")
        return
    bridge = DiscordBridge()
    async with bridge:
        await bridge.start(token)


if __name__ == "__main__":
    asyncio.run(main())
