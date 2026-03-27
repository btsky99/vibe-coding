# -*- coding: utf-8 -*-
"""
FILE: scripts/telegram_bridge.py
DESCRIPTION: Telegram Multi-Bot Bridge — 터미널당 독립 봇 + 그룹채팅 협업.
             각 터미널(T1~T8)이 별도의 텔레그램 봇으로 존재하며,
             개인 채팅에서 1:1 PTY 스트리밍, 그룹 채팅에서 봇끼리 대화합니다.

             [핵심 설계 — "에이전트 = 봇" 패턴]
             - T1~T8 각각 독립된 텔레그램 봇 (BotFather에서 8개 생성)
             - 개인 채팅: claude CLI stream-json 직접 spawn → 실시간 스트리밍
             - 그룹 채팅: 모든 봇이 초대된 공용 공간
               → ITCP 메시지가 발신자 봇의 이름으로 그룹에 표시
               → 봇끼리 대화하듯 보이는 협업 UX
               → 사용자가 관전 + @멘션으로 개입

             [텔레그램 명령어 (개인채팅)]
             /start   — 봇 활성화 + 채팅 ID 저장
             /status  — 이 터미널의 에이전트 상태
             /run <task> — 이 터미널에서 작업 시작
             /stop    — 이 터미널 중지

             [텔레그램 명령어 (그룹채팅)]
             /status  — 전체 에이전트 상태
             /tasks   — 태스크 목록
             /history — 최근 ITCP 대화 이력
             /send <agent> <msg> — 특정 에이전트에게 메시지
             /broadcast <msg> — 전체 브로드캐스트

             [프로세스 구조]
             1개 프로세스에서 asyncio로 최대 8개 봇 동시 구동.
             python-telegram-bot v22의 Application.start() + updater.start_polling()을
             비동기로 병렬 실행합니다.

REVISION HISTORY:
- 2026-03-25 Claude: 동시 입출력 교착(deadlock) 해결 — 3대 병목 제거
  - concurrent_updates(256): 핸들러 병렬 실행 허용 (미설정 시 순차 실행 → 이벤트 루프 차단)
  - stderr=DEVNULL: stderr 버퍼 풀 → 자식 프로세스 block → stdout 멈춤 데드락 근절
  - asyncio.gather(): 봇 폴링 병렬 시작 (순차 await 대비 N배 빠름)
- 2026-03-24 Claude: cokacdir 패턴 적용 — stream-json 직접 spawn 방식으로 전환
  - _handle_text(): /api/agent/run API → claude --print --output-format stream-json
  - _stream_claude_response(): stdin/stdout 파이프로 실시간 스트리밍 + 텔레그램 메시지 편집
  - --resume SESSION_ID: 멀티턴 대화 컨텍스트 유지
  - poll_pty_output/poll_agent_result 제거 (stream-json이 완전 대체)
  - /stop: Windows taskkill /T /F로 프로세스 트리 종료
- 2026-03-23 Claude: 완전 재설계 — 중계기 패턴 → 에이전트=봇 패턴
  - AgentBot 클래스: 터미널 1개 = 봇 1개, 개인채팅+그룹채팅 이중 동작
  - BotManager: 최대 8봇 asyncio 병렬 구동
  - ITCP → 그룹채팅 미러링 (발신자 봇이 직접 발화)
  - rate limit 대응: 3초 버퍼링 + 4096자 제한
  - 개인채팅 자동 감지 (chat_type == 'private')
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
import sys
import time
from collections import defaultdict
from datetime import datetime
from pathlib import Path
from typing import Optional

# 경로 설정: scripts/ 폴더 기준
_SCRIPT_DIR = Path(__file__).parent
_PROJECT_ROOT = _SCRIPT_DIR.parent
_DATA_DIR = _PROJECT_ROOT / ".ai_monitor" / "data"

# ITCP 모듈 임포트
sys.path.insert(0, str(_SCRIPT_DIR))
try:
    import itcp
except ImportError:
    itcp = None  # type: ignore

# python-telegram-bot 임포트
try:
    from telegram import Update, Bot
    from telegram.ext import (
        Application,
        CommandHandler,
        MessageHandler,
        ContextTypes,
        filters,
    )
    from telegram.constants import ParseMode, ChatType
except ImportError:
    print("[telegram_bridge] python-telegram-bot 패키지 필요: pip install python-telegram-bot")
    sys.exit(1)

# 로깅 설정
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [TG] %(message)s",
    datefmt="%H:%M:%S",
)
log = logging.getLogger("telegram_bridge")

# ── .env 로드 ──
try:
    from dotenv import load_dotenv
    load_dotenv(_PROJECT_ROOT / ".env")
except ImportError:
    pass

SERVER_PORT: int = int(os.environ.get("VIBE_SERVER_PORT", "9000"))
PTY_PORT: int = int(os.environ.get("PTY_PORT", "9001"))  # Node PTY 서버 포트

# ── 터미널별 기본 CLI 매핑 (서버에서 실제 정보 가져오기 실패 시 폴백) ──
_DEFAULT_CLI_MAP = {
    1: "claude", 2: "gemini", 3: "codex", 4: "gemini",
    5: "codex", 6: "claude", 7: "gemini", 8: "codex",
}

def _get_terminal_cli_map() -> dict[int, str]:
    """서버 /api/agent/terminals에서 실제 실행 중인 CLI 정보를 가져옵니다.
    실패 시 기본 매핑 반환."""
    result = _api_get("/api/agent/terminals")
    if not result:
        return dict(_DEFAULT_CLI_MAP)
    cli_map = {}
    for key, info in result.items():
        try:
            tid = int(key.replace("T", "").replace("t", ""))
            cli = info.get("cli", "") if isinstance(info, dict) else ""
            if not cli:  # 빈 문자열이면 기본값 사용
                cli = _DEFAULT_CLI_MAP.get(tid, "claude")
            cli_map[tid] = cli
        except (ValueError, TypeError):
            continue
    # 빠진 터미널은 기본값으로 채움
    for tid in range(1, 9):
        if tid not in cli_map:
            cli_map[tid] = _DEFAULT_CLI_MAP.get(tid, "claude")
    return cli_map


def _get_terminal_cli(tid: int) -> str:
    """Fetch the current CLI bound to one terminal slot."""
    return _get_terminal_cli_map().get(tid, _DEFAULT_CLI_MAP.get(tid, "claude"))

TERMINAL_CLI_MAP = _DEFAULT_CLI_MAP  # 초기값 (BotManager.load_bots()에서 동적 업데이트)

# ── 에이전트 이모지 ──
AGENT_EMOJI = {
    "claude": "\U0001f916",   # 🤖
    "gemini": "\U0001f7e2",   # 🟢
    "codex": "\U0001f535",    # 🔵
    "user": "\U0001f464",     # 👤
    "system": "\u2699\ufe0f", # ⚙️
}

MSG_TYPE_EMOJI = {
    "info": "\u2139\ufe0f", "request": "\U0001f4cb",
    "response": "\u2705", "alert": "\u26a0\ufe0f",
    "summary": "\U0001f4dd", "handoff": "\U0001f91d",
    "status": "\U0001f4e1", "broadcast": "\U0001f4e2",
}

# ── 그룹 채팅 ID ──
GROUP_CHAT_ID: Optional[int] = None
_group_str = os.environ.get("TELEGRAM_GROUP_CHAT_ID", "")
if _group_str:
    try:
        GROUP_CHAT_ID = int(_group_str)
    except ValueError:
        pass


# ═══════════════════════════════════════════════════════════════════
#  유틸리티
# ═══════════════════════════════════════════════════════════════════

def _get_emoji(agent: str) -> str:
    """에이전트 이름에서 이모지 반환"""
    agent_lower = agent.lower().split(":")[0] if agent else "system"
    return AGENT_EMOJI.get(agent_lower, "\U0001f916")


def _truncate(text: str, max_len: int = 4000) -> str:
    """텔레그램 메시지 길이 제한 (4096자 한도)"""
    return text if len(text) <= max_len else text[:max_len] + "\n... (잘림)"


def _api_get(path: str) -> Optional[dict]:
    """서버 API GET 요청"""
    import urllib.request
    try:
        url = f"http://127.0.0.1:{SERVER_PORT}{path}"
        with urllib.request.urlopen(url, timeout=5) as resp:
            return json.loads(resp.read().decode("utf-8"))
    except Exception:
        return None


def _api_post(path: str, data: dict) -> Optional[dict]:
    """서버 API POST 요청"""
    import urllib.request
    try:
        url = f"http://127.0.0.1:{SERVER_PORT}{path}"
        body = json.dumps(data).encode("utf-8")
        req = urllib.request.Request(url, data=body, method="POST")
        req.add_header("Content-Type", "application/json")
        with urllib.request.urlopen(req, timeout=10) as resp:
            return json.loads(resp.read().decode("utf-8"))
    except Exception:
        return None


def _pty_get(path: str) -> Optional[dict]:
    """Node PTY server API GET."""
    import urllib.request
    try:
        url = f"http://127.0.0.1:{PTY_PORT}{path}"
        with urllib.request.urlopen(url, timeout=5) as resp:
            return json.loads(resp.read().decode("utf-8"))
    except Exception:
        return None


def _pty_post(path: str, data: dict) -> Optional[dict]:
    """Node PTY server API POST."""
    import urllib.request
    try:
        url = f"http://127.0.0.1:{PTY_PORT}{path}"
        body = json.dumps(data).encode("utf-8")
        req = urllib.request.Request(url, data=body, method="POST")
        req.add_header("Content-Type", "application/json")
        with urllib.request.urlopen(req, timeout=10) as resp:
            return json.loads(resp.read().decode("utf-8"))
    except Exception:
        return None


def _filter_noise(text: str) -> str:
    """PTY 출력에서 노이즈 패턴 제거"""
    lines = []
    for line in text.splitlines():
        stripped = line.strip()
        if any(stripped.startswith(p) for p in (
            "Loaded cached credentials",
            "Registering notification handlers",
            "Server '", "Scheduling MCP",
            "Executing MCP", "MCP context refresh",
            "Created execution plan for",
            "Expanding hook command:",
            "Hook execution for",
            "ClearcutLogger:", "Error flushing log events",
            "Session ID:", "Loading extension:",
            "[DEBUG]",
        )):
            continue
        lines.append(line)
    return "\n".join(lines)


# ═══════════════════════════════════════════════════════════════════
#  AgentBot — 터미널 1개 = 봇 1개
# ═══════════════════════════════════════════════════════════════════

class AgentBot:
    """터미널 하나를 대표하는 텔레그램 봇.

    [동작 모드]
    - 개인 채팅 (chat_type == 'private'): PTY 출력 스트리밍, 사용자 명령 수신
    - 그룹 채팅 (GROUP_CHAT_ID): ITCP 메시지를 자기 이름으로 발화

    [인스턴스 변수]
    - tid: 터미널 번호 (1~8)
    - token: 봇 토큰
    - cli: 에이전트 이름 ("claude", "gemini", "codex")
    - app: python-telegram-bot Application
    - private_chat_id: /start로 감지된 개인 채팅 ID
    - _output_buffer: PTY 출력 버퍼 (3초 묶어보내기)
    - _last_output_seq: PTY 폴링 시퀀스 번호
    """

    def __init__(self, tid: int, token: str):
        self.tid = tid
        self.token = token
        self.cli = TERMINAL_CLI_MAP.get(tid, "claude")
        self.emoji = _get_emoji(self.cli)
        self.label = f"T{tid}({self.cli})"

        # 개인 채팅 ID — /start 시 자동 저장
        self.private_chat_id: Optional[int] = None

        # ── stream-json 방식 (cokacdir 패턴) ──
        # claude CLI를 직접 spawn하여 stdin/stdout 파이프로 통신
        self._session_id: Optional[str] = None      # --resume용 세션 ID
        self._claude_proc: Optional[asyncio.subprocess.Process] = None  # 취소용 프로세스 핸들
        self._streaming: bool = False                # 중복 실행 방지 플래그
        self._stream_msg_id: Optional[int] = None    # 텔레그램 메시지 편집용 msg_id

        # Application 빌드 — concurrent_updates=256으로 핸들러 병렬 실행 허용
        # 미설정 시 핸들러가 순차 실행되어 subprocess 대기 중 다른 메시지 처리 차단됨
        self.app = (
            Application.builder()
            .token(token)
            .concurrent_updates(256)
            .build()
        )
        self._register_handlers()

    def _apply_cli_binding(self, cli: str) -> bool:
        """Update local bot metadata when the terminal slot's CLI changed."""
        cli = (cli or "").strip().lower() or _DEFAULT_CLI_MAP.get(self.tid, "claude")
        if cli == self.cli:
            return False
        old_label = self.label
        self.cli = cli
        self.emoji = _get_emoji(cli)
        self.label = f"T{self.tid}({cli})"
        log.info(f"[TG] slot remap: {old_label} -> {self.label}")
        return True

    def _sync_live_cli(self) -> None:
        """Refresh this bot's CLI binding from the live terminal server."""
        try:
            self._apply_cli_binding(_get_terminal_cli(self.tid))
        except Exception as e:
            log.debug(f"[{self.label}] live CLI sync skipped: {e}")

    def _register_handlers(self) -> None:
        """명령어 + 텍스트 핸들러 등록"""
        self.app.add_handler(CommandHandler("start", self._cmd_start))
        self.app.add_handler(CommandHandler("status", self._cmd_status))
        self.app.add_handler(CommandHandler("run", self._cmd_run))
        self.app.add_handler(CommandHandler("stop", self._cmd_stop))
        self.app.add_handler(CommandHandler("tasks", self._cmd_tasks))
        self.app.add_handler(CommandHandler("history", self._cmd_history))
        self.app.add_handler(CommandHandler("send", self._cmd_send))
        self.app.add_handler(CommandHandler("broadcast", self._cmd_broadcast))
        self.app.add_handler(MessageHandler(
            filters.TEXT & ~filters.COMMAND,
            self._handle_text,
        ))

    # ── 안전 전송 ──

    async def _safe_send(self, chat_id: int, text: str) -> None:
        """텔레그램 메시지 전송 (Markdown 실패 시 plain text 폴백)"""
        text = _truncate(text)
        try:
            await self.app.bot.send_message(
                chat_id=chat_id, text=text, parse_mode=ParseMode.MARKDOWN,
            )
        except Exception:
            try:
                await self.app.bot.send_message(chat_id=chat_id, text=text)
            except Exception as e:
                log.error(f"[{self.label}] 전송 실패 (chat={chat_id}): {e}")

    async def send_to_group(self, text: str) -> None:
        """그룹 채팅에 이 봇 이름으로 메시지 전송"""
        if GROUP_CHAT_ID:
            await self._safe_send(GROUP_CHAT_ID, text)

    async def send_to_private(self, text: str) -> None:
        """개인 채팅에 메시지 전송"""
        if self.private_chat_id:
            await self._safe_send(self.private_chat_id, text)

    # ── stream-json 방식: claude CLI 직접 spawn + 실시간 스트리밍 ──

    async def _safe_edit(self, chat_id: int, msg_id: int, text: str) -> bool:
        """텔레그램 메시지 편집 (변경 없으면 무시, Markdown 실패 시 plain 폴백)"""
        text = _truncate(text)
        try:
            await self.app.bot.edit_message_text(
                chat_id=chat_id, message_id=msg_id,
                text=text, parse_mode=ParseMode.MARKDOWN,
            )
            return True
        except Exception:
            try:
                await self.app.bot.edit_message_text(
                    chat_id=chat_id, message_id=msg_id, text=text,
                )
                return True
            except Exception:
                return False

    async def _stream_claude_response(self, prompt: str, chat_id: int, placeholder_msg_id: int) -> None:
        """CLI 에이전트(claude/gemini/codex)를 spawn하고 실시간 텔레그램 전송.

        [cokacdir 패턴 Python 구현 — 멀티 에이전트 대응]
        1. claude/gemini/codex CLI를 spawn (--resume SESSION_ID)
        2. stdin에 프롬프트 write → close (EOF)
        3. stdout 한 줄씩 파싱 → 텔레그램 메시지 편집 (실시간 타이핑)
        4. done 수신 시 session_id 저장 (멀티턴 대화 유지)

        [에이전트별 CLI 명령]
        - claude: claude --print --output-format stream-json --resume SESSION_ID
        - gemini: gemini --output-format stream-json (또는 gemini-cli)
        - codex: codex --output-format stream-json

        [메시지 편집 전략]
        - 텔레그램 rate limit (분당 ~30회 편집) 대응: 2초 간격 편집
        - 4096자 초과 시 새 메시지로 분할 전송
        - 도구 사용(tool_use) 시 별도 알림
        """
        self._streaming = True
        self._stream_msg_id = placeholder_msg_id

        # ── 에이전트별 CLI 명령 구성 (cokacdir 패턴) ──
        # [핵심] shell=True + subprocess.list2cmdline()으로 안전 쿼팅
        #   → Windows에서 claude.CMD 등 .cmd 파일은 cmd.exe 경유 필수
        #   → list2cmdline()은 Python 표준 라이브러리가 제공하는 Windows 전용 안전 쿼팅
        #   → 공백/특수문자/따옴표 포함 인자도 올바르게 이스케이프
        # Claude: -p 인자로 메시지 직접 전달, stdin=DEVNULL
        # Gemini/Codex: stdin=PIPE로 메시지 전달
        import subprocess as _sp_mod
        cli = self.cli or "claude"
        use_stdin = (cli != "claude")
        if cli == "claude":
            cmd_parts = ["claude", "--verbose", "--output-format", "stream-json"]
            if self._session_id:
                cmd_parts += ["--resume", self._session_id]
            cmd_parts += ["-p", prompt]
        elif cli == "gemini":
            cmd_parts = ["gemini", "-m", "gemini-2.5-pro"]
            if self._session_id:
                cmd_parts += ["--resume", self._session_id]
        elif cli == "codex":
            cmd_parts = ["codex", "--full-auto"]
            if self._session_id:
                cmd_parts += ["--resume", self._session_id]
        else:
            cmd_parts = [cli]

        # subprocess.list2cmdline(): Windows cmd.exe용 안전 쿼팅 (공백/따옴표 자동 이스케이프)
        shell_cmd = _sp_mod.list2cmdline(cmd_parts)
        log.info(f"[{self.label}] cli spawn: {shell_cmd[:120]}...")

        try:
            # shell=True 필수 — Windows .CMD 파일 실행에 cmd.exe 경유 필요
            # stderr=DEVNULL: 버퍼 풀 데드락 방지
            proc = await asyncio.create_subprocess_shell(
                shell_cmd,
                stdin=asyncio.subprocess.PIPE if use_stdin else asyncio.subprocess.DEVNULL,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.DEVNULL,
                cwd=str(_PROJECT_ROOT),
            )
            self._claude_proc = proc

            # Gemini/Codex: stdin에 프롬프트 전달 후 EOF
            if use_stdin:
                proc.stdin.write(prompt.encode("utf-8"))
                await proc.stdin.drain()
                proc.stdin.close()

            # stdout 스트리밍 파싱
            full_text = ""           # 전체 누적 텍스트
            current_chunk = ""       # 현재 메시지에 표시할 텍스트
            last_edit_time = 0.0     # 마지막 메시지 편집 시각
            current_msg_id = placeholder_msg_id  # 현재 편집 중인 메시지 ID
            tool_info = ""           # 도구 사용 중 표시

            async for raw_line in proc.stdout:
                line = raw_line.decode("utf-8", errors="replace").strip()
                if not line:
                    continue

                try:
                    msg = json.loads(line)
                except json.JSONDecodeError:
                    continue

                msg_type = msg.get("type", "")

                # ── init: 세션 ID 수신 ──
                if msg_type == "system" and msg.get("subtype") == "init":
                    sid = msg.get("session_id", "")
                    if sid:
                        self._session_id = sid
                        log.info(f"[{self.label}] 세션 시작: {sid[:12]}...")

                # ── assistant 텍스트 (실시간 스트리밍) ──
                elif msg_type == "assistant":
                    content = msg.get("message", {}).get("content", "")
                    # content가 문자열이면 직접, 리스트면 text 블록 추출
                    if isinstance(content, str) and content:
                        full_text += content
                        current_chunk += content
                    elif isinstance(content, list):
                        for block in content:
                            if isinstance(block, dict) and block.get("type") == "text":
                                text_val = block.get("text", "")
                                full_text += text_val
                                current_chunk += text_val

                # ── content_block_delta: 스트리밍 텍스트 조각 ──
                elif msg_type == "content_block_delta":
                    delta = msg.get("delta", {})
                    if delta.get("type") == "text_delta":
                        text_val = delta.get("text", "")
                        full_text += text_val
                        current_chunk += text_val

                # ── tool_use: 도구 사용 알림 ──
                elif msg_type == "tool_use":
                    tool_name = msg.get("name", msg.get("tool", "?"))
                    tool_info = f"\n\U0001f527 `{tool_name}` 실행 중..."

                # ── tool_result: 도구 실행 결과 ──
                elif msg_type == "tool_result":
                    tool_info = ""  # 도구 완료, 알림 제거

                # ── result: 최종 결과 (claude --print 모드) ──
                elif msg_type == "result":
                    result_text = msg.get("result", "")
                    sid = msg.get("session_id", "")
                    if sid:
                        self._session_id = sid
                    if result_text and not full_text:
                        full_text = result_text
                        current_chunk = result_text

                # ── 주기적 텔레그램 메시지 편집 (2초 간격) ──
                now = time.time()
                if current_chunk and (now - last_edit_time >= 2.0):
                    display = current_chunk + tool_info
                    # 4096자 초과 시 새 메시지로 분할
                    if len(display) > 3900:
                        # 현재 메시지 확정
                        await self._safe_edit(chat_id, current_msg_id, current_chunk[:3900])
                        current_chunk = current_chunk[3900:]
                        # 새 메시지 생성
                        new_msg = await self.app.bot.send_message(
                            chat_id=chat_id, text="\u270d\ufe0f 계속..."
                        )
                        current_msg_id = new_msg.message_id
                    else:
                        await self._safe_edit(chat_id, current_msg_id, display)
                    last_edit_time = now

            # ── 스트리밍 종료: 최종 메시지 확정 ──
            await proc.wait()

            if current_chunk.strip():
                final_display = f"{self.emoji} *{self.label}*\n\n{current_chunk}"
                await self._safe_edit(chat_id, current_msg_id, final_display)
            elif not full_text.strip():
                # stdout에서 아무것도 안 왔으면 오류 메시지 표시
                await self._safe_edit(chat_id, current_msg_id, f"{self.emoji} {self.label} 작업 완료 (응답 없음)")

            # 그룹에 완료 알림
            summary = full_text[:100] + "..." if len(full_text) > 100 else full_text
            if summary.strip():
                await self.send_to_group(
                    f"\u2705 *{self.label}* 응답 완료 ({len(full_text)}자)"
                )

            # 메시지 버스에 에이전트 응답 기록 (대시보드 동기화)
            if full_text.strip():
                _api_post("/api/agent/chat/bus", {
                    "terminal_id": f"T{self.tid}", "source": "telegram",
                    "role": "assistant", "content": full_text,
                })

            log.info(f"[{self.label}] 스트리밍 완료: {len(full_text)}자, session={self._session_id and self._session_id[:12]}")

        except asyncio.CancelledError:
            log.info(f"[{self.label}] 스트리밍 취소됨")
            if self._claude_proc and self._claude_proc.returncode is None:
                self._claude_proc.terminate()
        except Exception as e:
            log.error(f"[{self.label}] stream-json 오류: {e}")
            await self._safe_edit(
                chat_id, placeholder_msg_id,
                f"\u274c {self.label} 오류: {str(e)[:200]}"
            )
        finally:
            self._streaming = False
            self._claude_proc = None

    # ── 명령어 핸들러 ──

    async def _cmd_start(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        """/start — 봇 활성화 + 개인 채팅 ID 자동 저장"""
        self._sync_live_cli()
        log.info(f"[{self.label}] /start 수신 (chat_id={update.effective_chat.id}, type={update.effective_chat.type})")
        chat = update.effective_chat
        chat_id = chat.id

        if chat.type == ChatType.PRIVATE:
            # 개인 채팅으로 인식 → 이 터미널 전용 1:1 채팅
            self.private_chat_id = chat_id
            await update.message.reply_text(
                f"\U0001f41d *{self.label}* 봇 활성화!\n\n"
                f"{self.emoji} 에이전트: *{self.cli}*\n"
                f"\U0001f4bb 터미널: *T{self.tid}*\n"
                f"\U0001f4ac 채팅 ID: `{chat_id}`\n\n"
                f"이 채팅에서 T{self.tid}의 PTY 출력을 실시간으로 받습니다.\n"
                f"텍스트를 입력하면 T{self.tid} 에이전트에게 직접 전달됩니다.\n\n"
                f"*명령어:*\n"
                f"/status — 에이전트 상태\n"
                f"/run <task> — 작업 시작\n"
                f"/stop — 터미널 중지",
                parse_mode=ParseMode.MARKDOWN,
            )
            log.info(f"[{self.label}] 개인채팅 등록: {chat_id}")
        else:
            # 그룹 채팅
            await update.message.reply_text(
                f"{self.emoji} *{self.label}* 그룹 참여!\n"
                f"이 봇은 T{self.tid} ({self.cli}) 에이전트입니다.",
                parse_mode=ParseMode.MARKDOWN,
            )

    async def _cmd_status(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        """/status — 에이전트 상태 조회"""
        self._sync_live_cli()
        chat = update.effective_chat

        if chat.type == ChatType.PRIVATE:
            # 개인 채팅: 이 터미널만
            result = _api_get("/api/agent/terminals")
            if not result:
                await update.message.reply_text("\u26a0\ufe0f 서버 응답 없음")
                return
            info = result.get(f"T{self.tid}", {})
            if isinstance(info, dict):
                status = info.get("status", info.get("state", "unknown"))
                task = info.get("task", "")[:80]
                status_icon = "\U0001f7e2" if status in ("running", "active") else "\u26aa"
                msg = f"{status_icon} *{self.label}* — {status}"
                if task:
                    msg += f"\n\U0001f4cb {task}"
                await update.message.reply_text(msg, parse_mode=ParseMode.MARKDOWN)
            else:
                await update.message.reply_text(f"\u26aa T{self.tid} 정보 없음")
        else:
            # 그룹 채팅: 전체 상태
            result = _api_get("/api/agent/terminals")
            if not result:
                await update.message.reply_text("\u26a0\ufe0f 서버 응답 없음")
                return
            lines = ["\U0001f4ca *전체 에이전트 상태*\n"]
            for tid_key, info in sorted(result.items()):
                if isinstance(info, dict):
                    agent = info.get("agent", info.get("cli", "?"))
                    status = info.get("status", info.get("state", "unknown"))
                    task = info.get("task", "")[:50]
                    emoji = _get_emoji(agent)
                    status_icon = "\U0001f7e2" if status in ("running", "active") else "\u26aa"
                    line = f"{status_icon} *{tid_key}* {emoji} {agent}"
                    if task:
                        line += f"\n   \u2514 {task}"
                    lines.append(line)
            await update.message.reply_text(
                "\n".join(lines), parse_mode=ParseMode.MARKDOWN,
            )

    async def _cmd_run(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        """/run <task> — 이 터미널에서 작업 시작"""
        self._sync_live_cli()
        args = context.args or []
        if not args:
            await update.message.reply_text("사용법: /run <작업 내용>")
            return
        task_text = " ".join(args)
        result = _api_post("/api/agent/run", {
            "terminal_id": f"T{self.tid}",
            "task": task_text,
        })
        if result and result.get("status") in ("started", "success"):
            await update.message.reply_text(
                f"\u25b6\ufe0f {self.emoji} {self.label} 시작: {task_text[:80]}"
            )
            # 그룹에도 알림
            await self.send_to_group(
                f"\u25b6\ufe0f *{self.label}* 작업 시작: {task_text[:80]}"
            )
        else:
            await update.message.reply_text(f"\u274c 시작 실패: {result}")

    async def _cmd_stop(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        """/stop — 진행 중인 claude 프로세스 종료 + PTY 인터럽트"""
        self._sync_live_cli()
        stopped = False

        # stream-json 프로세스 종료
        if self._claude_proc and self._claude_proc.returncode is None:
            try:
                pid = self._claude_proc.pid
                # Windows: 프로세스 트리 전체 종료 (자식 프로세스 포함)
                if sys.platform == "win32":
                    import subprocess as sp
                    sp.run(
                        ["taskkill", "/T", "/F", "/PID", str(pid)],
                        capture_output=True, timeout=5,
                        creationflags=0x08000000,
                    )
                else:
                    self._claude_proc.terminate()
                self._streaming = False
                self._claude_proc = None
                stopped = True
                log.info(f"[{self.label}] claude 프로세스 종료 (PID={pid})")
            except Exception as e:
                log.error(f"[{self.label}] 프로세스 종료 실패: {e}")

        # PTY 인터럽트도 시도 (폴백)
        result = _api_post("/api/pty/interrupt", {"terminal_id": f"T{self.tid}"})

        if stopped:
            await update.message.reply_text(f"\u23f9\ufe0f {self.label} claude 프로세스 종료됨")
        elif result:
            await update.message.reply_text(f"\u23f9\ufe0f {self.label} 중지됨")
        else:
            await update.message.reply_text(f"\u26aa {self.label} 실행 중인 작업 없음")

    async def _cmd_tasks(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        """/tasks — 태스크 목록"""
        tasks_file = _DATA_DIR / "tasks.json"
        if not tasks_file.exists():
            await update.message.reply_text("\U0001f4cb 활성 태스크 없음")
            return
        try:
            tasks = json.loads(tasks_file.read_text(encoding="utf-8"))
            if not tasks:
                await update.message.reply_text("\U0001f4cb 활성 태스크 없음")
                return
            lines = ["\U0001f4cb *태스크 목록*\n"]
            for t in tasks[-10:]:
                status = t.get("status", "?")
                title = t.get("title", "")[:60]
                assigned = t.get("assigned_to", "?")
                icon = {"done": "\u2705", "in_progress": "\U0001f504", "pending": "\u23f3"}.get(status, "\u2753")
                lines.append(f"{icon} {_get_emoji(assigned)} {assigned}: {title}")
            await update.message.reply_text(
                "\n".join(lines), parse_mode=ParseMode.MARKDOWN,
            )
        except Exception as e:
            await update.message.reply_text(f"\u274c 로드 실패: {e}")

    async def _cmd_history(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        """/history — 최근 ITCP 대화 이력"""
        if not itcp:
            await update.message.reply_text("\u274c ITCP 없음")
            return
        try:
            msgs = itcp.history(limit=10)
            if not msgs:
                await update.message.reply_text("\U0001f4ed 이력 없음")
                return
            lines = ["\U0001f4ac *최근 대화*\n"]
            for msg in reversed(msgs):
                f = msg.get("from_agent", "?")
                t = msg.get("to_agent", "all")
                c = msg.get("content", "")[:80]
                lines.append(f"{_get_emoji(f)} {f}\u2192{t}: {c}")
            await update.message.reply_text(
                _truncate("\n".join(lines)), parse_mode=ParseMode.MARKDOWN,
            )
        except Exception as e:
            await update.message.reply_text(f"\u274c 이력 실패: {e}")

    async def _cmd_send(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        """/send <agent> <msg> — ITCP로 특정 에이전트에게 메시지"""
        args = context.args or []
        if len(args) < 2:
            await update.message.reply_text("사용법: /send <claude|gemini|codex> <메시지>")
            return
        target = args[0].lower()
        content = " ".join(args[1:])
        if itcp:
            success = itcp.send(
                from_terminal="user",
                to_terminal=target,
                content=content,
                channel="task",
                msg_type="request",
                terminal_id=f"T{self.tid}",
            )
            if success:
                await update.message.reply_text(
                    f"\u2705 {_get_emoji(target)} {target}에게 전송"
                )
            else:
                await update.message.reply_text("\u274c ITCP 전송 실패")
        else:
            await update.message.reply_text("\u274c ITCP 없음")

    async def _cmd_broadcast(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        """/broadcast <msg> — 전체 브로드캐스트"""
        args = context.args or []
        if not args:
            await update.message.reply_text("사용법: /broadcast <메시지>")
            return
        content = " ".join(args)
        if itcp:
            success = itcp.broadcast(from_terminal="user", content=content, channel="broadcast")
            await update.message.reply_text(
                "\U0001f4e2 브로드캐스트 완료" if success else "\u274c 실패"
            )
        else:
            await update.message.reply_text("\u274c ITCP 없음")

    # ── 일반 텍스트 → claude CLI stream-json 직접 실행 ──

    async def _handle_text(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        """일반 텍스트 입력 처리 — 채팅 타입에 따라 동작 분기.

        [stream-json 방식 — cokacdir 패턴]
        개인채팅: claude CLI를 직접 spawn → stdin/stdout 파이프 → 실시간 스트리밍
        그룹채팅: ITCP로 전달 (기존 유지)
        """
        self._sync_live_cli()
        log.info(f"[{self.label}] 텍스트 수신: chat_id={update.effective_chat.id}, type={update.effective_chat.type}, text={update.message.text[:50]!r}")
        text = update.message.text.strip()
        if not text:
            return

        chat = update.effective_chat
        user = update.effective_user
        user_label = user.first_name if user else "User"

        if chat.type == ChatType.PRIVATE:
            # ── 개인 채팅: 모든 에이전트 cokacdir 패턴으로 직접 spawn ──
            # claude/gemini/codex 모두 CLI를 직접 spawn + --resume으로 세션 유지
            if self._is_terminal_alive():
                relayed = await self._relay_to_live_pty(text, chat.id, user_label)
                if relayed:
                    return
            await self._stream_agent_response(text, chat.id, user_label)
            return

        # ── 그룹 채팅: ITCP로 전달 (기존 유지) ──
        if chat.type != ChatType.PRIVATE:
            if itcp:
                itcp.send(
                    from_terminal="user",
                    to_terminal=self.cli,
                    content=f"[TG그룹/{user_label}\u2192T{self.tid}] {text}",
                    channel="task",
                    msg_type="request",
                    terminal_id=f"T{self.tid}",
                )
                await update.message.reply_text(
                    f"\U0001f4e8 {self.emoji} T{self.tid}에게 전달됨"
                )

    # ── 터미널 생존 확인 ──

    def _is_terminal_alive(self) -> bool:
        """이 터미널(T{tid})의 PTY 세션이 실행 중인지 확인합니다.
        Node PTY 서버(9001)에 직접 질의 — Python 서버(9000) 프록시 우회.
        """
        import urllib.request
        try:
            url = f"http://127.0.0.1:{PTY_PORT}/api/pty/sessions"
            with urllib.request.urlopen(url, timeout=3) as resp:
                result = json.loads(resp.read().decode("utf-8"))
        except Exception:
            return False
        # Node PTY 서버 응답: { "T1": { "running": true, ... }, "T2": ... }
        tid_key = f"T{self.tid}"
        entry = result.get(tid_key)
        if entry and entry.get("running"):
            return True
        return False

    # ── PTY 출력 폴링 → 응답을 개인채팅으로 전달 ──

    async def _poll_pty_response(self, chat_id: int) -> None:
        """PTY 출력을 폴링하여 에이전트 응답을 텔레그램으로 전달.

        [전략]
        - PTY write 후 에이전트가 응답하면 PTY 출력에 텍스트가 쌓임
        - 3초 간격으로 새 출력을 확인, 10초간 새 출력 없으면 완료로 간주
        - 최대 5분 대기
        """
        import urllib.request as _ur

        max_wait = 300  # 5분
        elapsed = 0
        last_seq = 0
        buffer = ""
        quiet_time = 0  # 새 출력 없는 시간
        sent_count = 0  # 전송한 메시지 수

        # 현재 시퀀스 번호 가져오기 (이전 출력 스킵)
        try:
            url = f"http://127.0.0.1:{SERVER_PORT}/api/pty/output?terminal_id=T{self.tid}&since=0"
            with _ur.urlopen(url, timeout=3) as resp:
                data = json.loads(resp.read().decode("utf-8"))
                last_seq = data.get("latest_seq", 0)
        except Exception:
            pass

        while elapsed < max_wait:
            await asyncio.sleep(3)
            elapsed += 3
            quiet_time += 3

            try:
                url = f"http://127.0.0.1:{SERVER_PORT}/api/pty/output?terminal_id=T{self.tid}&since={last_seq}"
                with _ur.urlopen(url, timeout=3) as resp:
                    data = json.loads(resp.read().decode("utf-8"))

                new_seq = data.get("latest_seq", last_seq)
                entries = data.get("entries", [])

                if entries:
                    quiet_time = 0
                    for entry in entries:
                        txt = entry.get("text", "")
                        if txt.strip():
                            buffer += txt + "\n"
                    last_seq = new_seq

                # 버퍼에 내용이 있고 조금 쌓였으면 전송
                if buffer.strip() and quiet_time >= 3:
                    filtered = _filter_noise(buffer)
                    if filtered.strip():
                        msg = _truncate(filtered, 3900)
                        await self._safe_send(chat_id, f"{self.emoji} *{self.label}:*\n{msg}")
                        sent_count += 1
                    buffer = ""

                # 10초간 새 출력 없으면 완료
                if quiet_time >= 10 and sent_count > 0:
                    log.info(f"[{self.label}] PTY 응답 전달 완료 ({sent_count}건)")
                    return

            except Exception as e:
                log.error(f"[{self.label}] PTY 폴링 오류: {e}")

        # 남은 버퍼 전송
        if buffer.strip():
            filtered = _filter_noise(buffer)
            if filtered.strip():
                await self._safe_send(chat_id, f"{self.emoji} *{self.label}:*\n{_truncate(filtered, 3900)}")

        if sent_count == 0:
            await self._safe_send(chat_id, f"\u23f0 {self.label} 응답 대기 시간 초과")

    # ── stream-json 폴백 (터미널 미실행 시) ──

    async def _relay_to_live_pty(self, text: str, chat_id: int, user_label: str) -> bool:
        """Write Telegram text into the live PTY slot and forward fresh PTY output back."""
        if self._streaming:
            await self._safe_send(
                chat_id,
                f"\u23f3 {self.emoji} {self.label} 이전 작업 전달 중입니다.\n/stop 으로 취소"
            )
            return True

        _api_post("/api/agent/chat/bus", {
            "terminal_id": f"T{self.tid}", "source": "telegram",
            "role": "user", "content": text, "tg_user": user_label,
        })

        baseline = _pty_get(f"/api/pty/output/T{self.tid}?since=0&limit=1") or {}
        last_seq = baseline.get("latest_seq", 0)
        write_result = _pty_post(f"/api/pty/write/T{self.tid}", {"text": text})
        if not write_result or write_result.get("status") != "written":
            return False

        self._streaming = True
        try:
            await self._safe_send(chat_id, f"{self.emoji} {self.label} 전달됨. PTY 응답 대기 중...")

            max_wait = 300
            elapsed = 0
            quiet_time = 0
            sent_count = 0
            buffer = ""

            while elapsed < max_wait:
                await asyncio.sleep(3)
                elapsed += 3
                quiet_time += 3

                data = _pty_get(f"/api/pty/output/T{self.tid}?since={last_seq}&limit=80") or {}
                new_seq = data.get("latest_seq", last_seq)
                entries = data.get("entries", [])

                if entries:
                    quiet_time = 0
                    for entry in entries:
                        txt = entry.get("text", "")
                        if txt.strip():
                            buffer += txt + "\n"
                    last_seq = new_seq

                if buffer.strip() and quiet_time >= 3:
                    filtered = _filter_noise(buffer)
                    if filtered.strip():
                        await self._safe_send(chat_id, f"{self.emoji} *{self.label}:*\n{_truncate(filtered, 3900)}")
                        sent_count += 1
                    buffer = ""

                if quiet_time >= 10 and sent_count > 0:
                    return True

            if buffer.strip():
                filtered = _filter_noise(buffer)
                if filtered.strip():
                    await self._safe_send(chat_id, f"{self.emoji} *{self.label}:*\n{_truncate(filtered, 3900)}")
                    return True

            await self._safe_send(chat_id, f"\u23f0 {self.label} 응답 대기 시간 초과")
            return True
        finally:
            self._streaming = False

    async def _stream_agent_response(self, text: str, chat_id: int, user_label: str) -> None:
        """cokacdir 패턴: 모든 에이전트(claude/gemini/codex)를 CLI spawn + 실시간 스트리밍."""
        if self._streaming:
            await self._safe_send(
                chat_id,
                f"\u23f3 {self.emoji} {self.label} 이전 작업 진행 중...\n/stop 으로 취소"
            )
            return

        # 메시지 버스에 텔레그램 사용자 메시지 기록 (대시보드 동기화)
        _api_post("/api/agent/chat/bus", {
            "terminal_id": f"T{self.tid}", "source": "telegram",
            "role": "user", "content": text, "tg_user": user_label,
        })

        placeholder = await self.app.bot.send_message(
            chat_id=chat_id, text=f"{self.emoji} {self.label} 생각 중... (독립 모드)"
        )
        await self.send_to_group(
            f"\U0001f680 *{self.label}* [TG/{user_label}]: {text[:80]}"
        )
        asyncio.create_task(
            self._stream_claude_response(text, chat_id, placeholder.message_id)
        )


    # ── 대시보드 메시지 버스 폴링 → 텔레그램 전달 ──

    async def _poll_dashboard_bus(self) -> None:
        """대시보드에서 발생한 메시지를 폴링하여 텔레그램 개인채팅에 전달.

        [동작]
        - 3초 간격으로 /api/agent/chat/feed?terminal_id=T{tid}&since={last_seq} 호출
        - source=="dashboard"인 메시지만 텔레그램에 전달
        - user 메시지: "📱 대시보드: {content}" 형태
        - assistant 메시지: 에이전트 응답 그대로 전달
        """
        last_seq = 0
        log.info(f"[{self.label}] 대시보드 버스 폴링 시작")

        while True:
            try:
                data = _api_get(f"/api/agent/chat/feed?terminal_id=T{self.tid}&since={last_seq}")
                if data and data.get("messages"):
                    for msg in data["messages"]:
                        seq = msg.get("seq", 0)
                        if seq > last_seq:
                            last_seq = seq
                        # 대시보드 발신 메시지만 전달 (텔레그램 발신은 무시 — 무한 루프 방지)
                        if msg.get("source") != "dashboard":
                            continue
                        if not self.private_chat_id:
                            continue  # 개인채팅 미설정 시 스킵

                        role = msg.get("role", "")
                        content = msg.get("content", "")
                        if not content.strip():
                            continue

                        if role == "user":
                            await self._safe_send(
                                self.private_chat_id,
                                f"\U0001f4f1 *대시보드:* {_truncate(content, 3800)}"
                            )
                        elif role == "assistant":
                            await self._safe_send(
                                self.private_chat_id,
                                f"{self.emoji} *{self.label} (대시보드):*\n{_truncate(content, 3800)}"
                            )

                    # latest_seq 업데이트
                    new_latest = data.get("latest_seq", last_seq)
                    if new_latest > last_seq:
                        last_seq = new_latest

            except Exception as e:
                log.error(f"[{self.label}] 대시보드 버스 폴링 오류: {e}")

            await asyncio.sleep(3.0)


# ═══════════════════════════════════════════════════════════════════
#  BotManager — 최대 8봇 생명주기 관리
# ═══════════════════════════════════════════════════════════════════

class BotManager:
    """여러 AgentBot을 asyncio로 동시 구동하고 ITCP 메시지를 그룹채팅에 라우팅.

    [동작 흐름]
    1. .env에서 TELEGRAM_BOT_T1~T8 토큰 로드
    2. 유효한 토큰이 있는 터미널만 AgentBot 생성
    3. asyncio.gather로 모든 봇 + ITCP 폴링 + PTY 폴링 동시 실행

    [ITCP → 그룹채팅 미러링]
    pg_messages에 새 메시지가 오면, 발신자 터미널의 봇이 그룹채팅에 해당 메시지를 자기 이름으로 발화.
    예: Claude(T1)이 Gemini(T2)에게 보낸 메시지 → T1봇이 그룹에 "T1(Claude): ..." 전송
    이로써 그룹채팅에서 봇끼리 대화하는 것처럼 보입니다.
    """

    def __init__(self):
        self.bots: dict[int, AgentBot] = {}
        # 터미널 번호 → AgentBot 매핑 (발신자 봇 찾기용)
        self._cli_to_bots: dict[str, list[AgentBot]] = defaultdict(list)
        self._last_pg_id: int = 0

    def load_bots(self) -> int:
        """.env에서 봇 토큰 로드, AgentBot 생성. 생성된 봇 수 반환.
        서버에서 실제 실행 중인 CLI 정보를 가져와서 동적 매핑합니다."""
        # 서버에서 실제 터미널 CLI 정보 가져오기
        global TERMINAL_CLI_MAP
        TERMINAL_CLI_MAP = _get_terminal_cli_map()
        log.info(f"  CLI 매핑: {TERMINAL_CLI_MAP}")

        count = 0
        for tid in range(1, 9):
            token = os.environ.get(f"TELEGRAM_BOT_T{tid}", "").strip()
            if token:
                bot = AgentBot(tid, token)
                self.bots[tid] = bot
                self._cli_to_bots[bot.cli].append(bot)
                count += 1
                log.info(f"  봇 로드: T{tid} ({bot.cli}) ✅")
            else:
                log.debug(f"  T{tid} 토큰 미설정 — 스킵")
        return count

    def _refresh_bot_bindings(self) -> None:
        """Refresh bot labels and lookup indexes from the live terminal map."""
        global TERMINAL_CLI_MAP
        TERMINAL_CLI_MAP = _get_terminal_cli_map()
        self._cli_to_bots = defaultdict(list)
        for tid, bot in self.bots.items():
            bot._apply_cli_binding(TERMINAL_CLI_MAP.get(tid, bot.cli))
            self._cli_to_bots[bot.cli].append(bot)

    def _find_bot_for_agent(self, agent_name: str, terminal_id: str = "") -> Optional[AgentBot]:
        """ITCP 메시지 발신자에 매핑되는 봇 찾기.

        [우선순위]
        1. terminal_id가 명시된 경우 → 해당 터미널의 봇
        2. 에이전트 이름으로 첫 번째 매칭 봇
        3. 없으면 None
        """
        # terminal_id로 직접 매핑
        self._refresh_bot_bindings()
        if terminal_id:
            try:
                tid_num = int(terminal_id.replace("T", "").replace("t", ""))
                if tid_num in self.bots:
                    return self.bots[tid_num]
            except ValueError:
                pass

        # 에이전트 이름으로 매핑
        agent_lower = agent_name.lower()
        candidates = self._cli_to_bots.get(agent_lower, [])
        if candidates:
            return candidates[0]

        # 아무거나 하나
        if self.bots:
            return next(iter(self.bots.values()))
        return None

    async def _poll_itcp_to_group(self) -> None:
        """ITCP 메시지를 폴링 → 발신자 봇이 그룹채팅에 발화.

        [핵심 메커니즘]
        이 루프가 에이전트 간 대화를 그룹채팅에 시각화하는 핵심입니다.
        pg_messages 새 메시지 → 발신자 터미널의 봇을 찾아 → 그 봇이 그룹에 발화
        → 텔레그램에서 봇끼리 대화하는 것처럼 보임
        """
        if not itcp or not GROUP_CHAT_ID:
            log.warning("ITCP 또는 GROUP_CHAT_ID 미설정 — 그룹 미러링 비활성화")
            return

        # 현재 최신 ID부터 시작 (과거 메시지 스킵)
        try:
            history = itcp.history(limit=1)
            if history:
                self._last_pg_id = int(history[0].get("id", 0))
        except Exception:
            pass

        log.info(f"ITCP→그룹 폴링 시작 (last_id={self._last_pg_id})")

        while True:
            try:
                msgs = itcp.history(limit=20)
                new_msgs = [m for m in msgs if int(m.get("id", 0)) > self._last_pg_id]
                new_msgs.sort(key=lambda m: int(m.get("id", 0)))

                for msg in new_msgs:
                    msg_id = int(msg.get("id", 0))
                    if msg_id > self._last_pg_id:
                        self._last_pg_id = msg_id

                    from_agent = msg.get("from_agent", msg.get("from", ""))
                    # 텔레그램 브릿지 자체 메시지는 스킵 (무한 루프 방지)
                    if from_agent == "telegram_bridge" or from_agent == "user":
                        continue

                    to_agent = msg.get("to_agent", "all")
                    terminal_id = msg.get("terminal_id", "")
                    content = msg.get("content", "")
                    msg_type = msg.get("msg_type", msg.get("type", "info"))
                    channel = msg.get("channel", "general")

                    # 텔레그램 응답 채널: 에이전트 응답 → 해당 봇의 개인채팅으로 전달
                    if channel == "telegram_response" and to_agent == "user":
                        target_bot = self._find_bot_for_agent(from_agent, terminal_id)
                        if target_bot and target_bot.private_chat_id:
                            response_text = (
                                f"{target_bot.emoji} *{target_bot.label} 응답:*\n"
                                f"{_truncate(content, 3800)}"
                            )
                            await target_bot.send_to_private(response_text)
                            log.info(f"[{target_bot.label}] 텔레그램 응답 전달 ({len(content)}자)")
                        continue  # 그룹에는 안 보냄

                    # 발신자 봇 찾기
                    sender_bot = self._find_bot_for_agent(from_agent, terminal_id)
                    if not sender_bot:
                        continue

                    # 메시지 포맷팅
                    type_emoji = MSG_TYPE_EMOJI.get(msg_type, "")
                    to_str = ""
                    if to_agent and to_agent != "all":
                        to_str = f" → {_get_emoji(to_agent)} {to_agent}"
                    ch_str = f" [{channel}]" if channel not in ("general", "") else ""

                    formatted = (
                        f"{sender_bot.emoji} *{sender_bot.label}*{to_str}"
                        f"{ch_str} {type_emoji}\n{content}"
                    )

                    # 발신자 봇이 그룹에 발화 → 해당 봇 이름으로 표시
                    await sender_bot.send_to_group(formatted)

            except Exception as e:
                log.error(f"ITCP 그룹 폴링 오류: {e}")

            await asyncio.sleep(2.0)

    async def run(self) -> None:
        """모든 봇 + 폴링 루프를 asyncio로 동시 실행.

        [실행 구조]
        python-telegram-bot v22에서 여러 Application을 하나의 이벤트 루프에서 실행하려면
        app.initialize() → app.start() → updater.start_polling()을 수동으로 호출하고,
        종료 시 역순으로 정리합니다.
        """
        if not self.bots:
            log.error("활성 봇 없음 — 종료")
            return

        # 1) 모든 봇 초기화 (순차 — 각 봇 내부 상태 셋업)
        for tid, bot in sorted(self.bots.items()):
            await bot.app.initialize()
            await bot.app.start()

        # 2) 모든 봇 폴링을 asyncio.gather로 병렬 시작 — 순차 await 대비 N배 빠름
        async def _start_polling(bot):
            await bot.app.updater.start_polling(drop_pending_updates=True)
            log.info(f"[{bot.label}] 폴링 시작 ✅")

        await asyncio.gather(*[_start_polling(bot) for bot in self.bots.values()])

        # 2) 백그라운드 태스크: ITCP→그룹 미러링 + 대시보드 버스 폴링
        tasks = []
        tasks.append(asyncio.create_task(self._poll_itcp_to_group()))

        # 3) 각 봇별 대시보드 메시지 버스 폴링 (대시보드 → 텔레그램 동기화)
        for tid, bot in sorted(self.bots.items()):
            tasks.append(asyncio.create_task(bot._poll_dashboard_bus()))

        log.info(f"전체 {len(self.bots)}봇 + {len(tasks)} 태스크 실행 중 (대시보드 버스 폴링 포함)")

        # 3) 무한 대기 (Ctrl+C로 종료)
        try:
            await asyncio.Event().wait()
        except (KeyboardInterrupt, SystemExit):
            pass
        finally:
            # 정리
            log.info("종료 중...")
            for t in tasks:
                t.cancel()
            for tid, bot in sorted(self.bots.items()):
                try:
                    await bot.app.updater.stop()
                    await bot.app.stop()
                    await bot.app.shutdown()
                except Exception:
                    pass
            log.info("종료 완료")


# ═══════════════════════════════════════════════════════════════════
#  메인 실행
# ═══════════════════════════════════════════════════════════════════

_LOCK_PORT = 19876  # 텔레그램 브릿지 싱글턴 포트 (사용하지 않는 포트)
_lock_socket = None

def _acquire_pid_lock() -> bool:
    """포트 바인딩 기반 중복 실행 방지 — OS-level 싱글턴.
    같은 포트에 두 프로세스가 동시에 bind할 수 없으므로 레이스컨디션 완전 차단."""
    import socket
    global _lock_socket
    try:
        _lock_socket = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        _lock_socket.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 0)
        _lock_socket.bind(("127.0.0.1", _LOCK_PORT))
        _lock_socket.listen(1)
        # PID 파일도 남겨놓음 (서버 코드가 참조)
        pid_file = _DATA_DIR / "telegram_bridge.pid"
        pid_file.parent.mkdir(parents=True, exist_ok=True)
        pid_file.write_text(str(os.getpid()))
        return True
    except OSError:
        return False  # 포트 이미 점유됨 = 이미 실행 중


def main() -> None:
    """텔레그램 멀티봇 브릿지 메인 진입점"""
    # 중복 실행 방지 (PID lock)
    if not _acquire_pid_lock():
        print("[telegram_bridge] 이미 실행 중 — 종료")
        sys.exit(0)

    log.info("=" * 55)
    log.info("Vibe Coding Telegram Multi-Bot Bridge")
    log.info(f"  서버: http://127.0.0.1:{SERVER_PORT}")
    log.info(f"  그룹 채팅: {GROUP_CHAT_ID or '미설정'}")
    log.info("=" * 55)

    manager = BotManager()
    count = manager.load_bots()

    if count == 0:
        log.error(
            "활성 봇 없음! .env에 TELEGRAM_BOT_T1~T8 토큰을 설정하세요.\n"
            "  예: TELEGRAM_BOT_T1=123456789:ABCdef...\n"
            "  BotFather에서 /newbot으로 봇 생성 후 토큰을 입력합니다."
        )
        sys.exit(1)

    log.info(f"총 {count}개 봇 로드 완료 — 시작합니다")

    asyncio.run(manager.run())


if __name__ == "__main__":
    main()
