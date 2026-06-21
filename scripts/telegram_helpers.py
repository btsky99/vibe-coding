# -*- coding: utf-8 -*-
"""
FILE: scripts/telegram_helpers.py
DESCRIPTION: telegram_bridge.py에서 분리한 순수 IO/포맷 유틸리티 모음.
             서버/PTY HTTP 래퍼, PTY 출력 노이즈 필터, 이모지/길이 포맷터.
             상태(GROUP_CHAT_ID, TERMINAL_CLI_MAP 등)는 가변 전역이라 bridge에 잔류 — 여기엔 무상태 함수만.

             [분리 이유] telegram_bridge.py가 1622줄로 1500줄 규칙(RULES.md §2) 위반.
             AgentBot 클래스(~1015줄)는 self 결합이 강해 쪼개면 깨질 위험이 커,
             가장 안전한 무상태 헬퍼만 떼어내 bridge를 1500줄 아래로 낮춤.

REVISION HISTORY:
- 2026-06-21 Claude: telegram_bridge.py에서 무상태 헬퍼 추출 (1500줄 규칙 준수)
"""
from __future__ import annotations
import json
import os
import re
import urllib.request
from pathlib import Path
from typing import Optional

# [제약] bridge가 .env를 먼저 로드하지만, import 순서와 무관하게 포트를 읽도록
# 여기서도 멱등 로드 — 이미 로드됐으면 no-op.
try:
    from dotenv import load_dotenv
    load_dotenv(Path(__file__).parent.parent / ".env")
except ImportError:
    pass

SERVER_PORT: int = int(os.environ.get("VIBE_SERVER_PORT", "9000"))
PTY_PORT: int = int(os.environ.get("PTY_PORT", "9001"))  # Node PTY 서버 포트

# ── 에이전트 이모지 ──
AGENT_EMOJI = {
    "claude": "\U0001f916",   # 🤖
    "antigravity": "\U0001f7e2",   # 🟢
    "codex": "\U0001f535",    # 🔵
    "user": "\U0001f464",     # 👤
    "system": "⚙️", # ⚙️
}

MSG_TYPE_EMOJI = {
    "info": "ℹ️", "request": "\U0001f4cb",
    "response": "✅", "alert": "⚠️",
    "summary": "\U0001f4dd", "handoff": "\U0001f91d",
    "status": "\U0001f4e1", "broadcast": "\U0001f4e2",
}


def _get_emoji(agent: str) -> str:
    """에이전트 이름에서 이모지 반환"""
    agent_lower = agent.lower().split(":")[0] if agent else "system"
    return AGENT_EMOJI.get(agent_lower, "\U0001f916")


def _truncate(text: str, max_len: int = 4000) -> str:
    """텔레그램 메시지 길이 제한 (4096자 한도)"""
    return text if len(text) <= max_len else text[:max_len] + "\n... (잘림)"


def _api_get(path: str) -> Optional[dict]:
    """서버 API GET 요청"""
    try:
        url = f"http://127.0.0.1:{SERVER_PORT}{path}"
        with urllib.request.urlopen(url, timeout=5) as resp:
            return json.loads(resp.read().decode("utf-8"))
    except Exception:
        return None


def _api_post(path: str, data: dict) -> Optional[dict]:
    """서버 API POST 요청"""
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
    try:
        url = f"http://127.0.0.1:{PTY_PORT}{path}"
        with urllib.request.urlopen(url, timeout=5) as resp:
            return json.loads(resp.read().decode("utf-8"))
    except Exception:
        return None


def _pty_post(path: str, data: dict) -> Optional[dict]:
    """Node PTY server API POST."""
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
    """PTY 출력에서 노이즈 패턴 제거.

    Claude Code 스피너/상태 표시줄, MCP 로그, 디버그 메시지 등
    텔레그램에 전달할 필요 없는 터미널 아티팩트를 모두 제거한다.
    """
    # Claude Code 스피너 단어 목록 (상태 표시줄에 랜덤으로 표시되는 단어들)
    _SPINNER_WORDS = (
        "Gallivanting", "Thinking", "Pondering", "Reasoning",
        "Considering", "Analyzing", "Processing", "Computing",
        "Reflecting", "Cogitating", "Deliberating", "Contemplating",
        "Musing", "Ruminating", "Brainstorming", "Evaluating",
        "Synthesizing", "Formulating", "Deducing", "Inferring",
    )

    # 유니코드 스피너 문자 + 단어 + "…" 패턴 (원본 이스케이프 보존 — 동작 동일성 보장)
    _spinner_re = re.compile(
        r'^[\s·•✦✧✻✼✽✶●○✵✳✴]*'
        r'(?:' + '|'.join(_SPINNER_WORDS) + r')…'
    )

    # Claude Code 하단 상태 표시줄 관련 패턴
    _statusbar_re = re.compile(
        r'(?:Opus|Sonnet|Haiku|Claude)\s*\d[\d.]*.*tokens|'   # "Opus 4.6 … tokens"
        r'bypass\s+permissions|'                                # "bypass permissions on"
        r'⛶|'                                              # ⛶
        r'⏵⏵|'                                        # ⏵⏵
        r'^\s*\d{1,5}\s*$|'                                     # 단독 숫자 (시퀀스 번호)
        r'^\s*[─-╿]{10,}'                             # 긴 구분선 (────…)
    )

    # 터미널 제목 시퀀스 (0;…)
    _title_re = re.compile(r'^0;')
    _ansi_escape_re = re.compile(
        r'\x1b(?:'
        r'\[[0-?]*[ -/]*[@-~]'
        r'|\][^\x07\x1b]*(?:\x07|\x1b\\)'
        r'|[@-Z\\-_]'
        r')'
    )
    _codex_noise_re = re.compile(
        r'^(?:'
        r'Working(?:\s*\(\d+s\s+esc to interrupt\))?'
        r'|Wor(?:k(?:i(?:n(?:g\d*)?)?)?)?'
        r'|gpt-[\w.\-]+\s+\w+\s+\d+%\s+left\s+.+'
        r'|\d+;\s*vibe-coding'
        r')\s*$',
        re.IGNORECASE,
    )

    lines = []
    for line in text.splitlines():
        stripped = _ansi_escape_re.sub('', line).strip()
        if not stripped:
            continue
        # 기존 prefix 필터
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
            "(running stop hooks",
            "(running start hooks",
        )):
            continue
        # 스피너 패턴 (Gallivanting…, Thinking… 등)
        if _spinner_re.match(stripped):
            continue
        # 상태 표시줄 패턴 (토큰 정보, bypass, 구분선 등)
        if _statusbar_re.search(stripped):
            continue
        # 터미널 제목 시퀀스 (0;⠂ Korean greeting conversation 등)
        if _title_re.match(stripped):
            continue
        if stripped == "Find and fix a bug in @filename" or _codex_noise_re.match(stripped):
            continue
        # ANSI 이스케이프 제거 후 빈 줄이면 스킵
        clean = re.sub(r'\x1b\[[0-9;]*[a-zA-Z]', '', stripped)
        if not clean.strip():
            continue
        lines.append(clean)
    return "\n".join(lines)
