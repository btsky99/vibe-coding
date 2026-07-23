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
    """텔레그램 메시지 길이 제한 (4096자 한도).

    [주의] 초과분을 **버린다**. 내용 보존이 필요한 경로는 `_split_message`를 쓸 것.
    미리보기·에러 요약처럼 잘려도 무방한 자리에만 남겨둔다.
    """
    return text if len(text) <= max_len else text[:max_len] + "\n... (잘림)"


_FENCE = "```"


def _split_message(text: str, limit: int = 3900, max_parts: int = 4) -> list[str]:
    """긴 텍스트를 텔레그램 전송 가능한 조각들로 나눈다.

    [WHY] 기존엔 `_truncate`만 있어 4000자 초과분이 **조용히 유실**됐다
    (`_safe_send`가 항상 통과시킴). 에이전트 응답·리포트가 통째로 잘려나가
    "텔레그램이 쓸모없다"는 체감의 주원인이었다.

    [불변식] 유실 0 — 원문의 모든 문자가 어느 조각엔가 반드시 들어간다.
      (단 아래 펜스 보정으로 ``` 가 **추가**될 수 있어 완전한 역복원은 아니다.
       비교 검증은 "펜스를 제거한 뒤 이어붙이면 원문과 같다"로 한다.)
      호출부가 파일 전송 전환을 판단할 수 있도록 조각 수는 제한하지 않고 전부 반환한다.

    [제약] 줄 경계를 우선해 자른다. 코드펜스(```) 내부에서 잘리면 텔레그램이
      Markdown 파싱에 실패해 통째로 plain 폴백되므로, 조각마다 펜스를 닫고 다시 연다.

    max_parts는 판단 기준으로만 쓰이며 잘라내기에는 관여하지 않는다
    (호출부: len(parts) > max_parts 이면 파일 첨부로 전환).
    """
    if len(text) <= limit:
        return [text]

    parts: list[str] = []
    buf: list[str] = []
    size = 0

    def flush() -> None:
        nonlocal buf, size
        if buf:
            parts.append("\n".join(buf))
            buf, size = [], 0

    for line in text.split("\n"):
        # 한 줄이 통째로 limit을 넘으면 그 줄만 강제 분할 (URL·로그 한 줄 등)
        if len(line) > limit:
            flush()
            for i in range(0, len(line), limit):
                parts.append(line[i:i + limit])
            continue
        # +1은 join에 들어갈 개행
        if size + len(line) + (1 if buf else 0) > limit:
            flush()
        buf.append(line)
        size += len(line) + (1 if len(buf) > 1 else 0)
    flush()

    # 코드펜스 균형 보정 — 홀수 개의 펜스로 끝난 조각은 열린 채로 끝나므로
    # 그 조각을 닫고 다음 조각을 다시 열어준다.
    fixed: list[str] = []
    carry_open = False
    for p in parts:
        body = (_FENCE + "\n" + p) if carry_open else p
        opens = body.count(_FENCE)
        carry_open = (opens % 2 == 1)
        if carry_open:
            body = body + "\n" + _FENCE
        fixed.append(body)
    return fixed


# ── 문서 전송 가드 ──

# [WHY] 이 목록이 없으면 텔레그램으로 자격증명을 유출시킬 수 있다. 특히 `.env`에는
# **봇 토큰 자체**가 들어있어, 그것이 유출되면 공격자가 봇을 완전히 탈취한다
# (= 이 채팅방의 모든 권한). 파일 전송 기능의 존재 이유보다 이 가드가 우선한다.
_DENY_NAME_PATTERNS = (
    ".env", ".env.", "credentials", "id_rsa", "id_ed25519",
    ".pem", ".key", ".pfx", ".p12", ".ppk", "secret", "token",
    # [보안사고 2026-07-23] telegram_bridge.log에 봇 토큰이 평문으로 쌓여 있었다
    # (httpx가 `/bot<TOKEN>/...` URL을 INFO로 기록). 로그 쪽 근본 원인은 막았지만,
    # 로그·덤프는 성질상 언제든 비밀을 머금으므로 전송 대상에서 통째로 제외한다(이중 방어).
    # 당시 이 파일이 전송되지 않은 유일한 이유가 "80MB 초과"였다 — 크기에 의존한 우연.
    ".log", ".dump", ".sql", ".bak",
)
_DENY_DIR_PARTS = (".oci", ".ssh", ".aws", "node_modules", ".git")
MAX_DOC_BYTES = 45 * 1024 * 1024  # 봇 업로드 한도 50MB에 여유


def is_sendable_path(path, project_root) -> tuple[bool, str]:
    """텔레그램으로 보내도 되는 파일인지 판정. (허용여부, 사유) 반환.

    [불변식] 판정은 반드시 `resolve()` 이후에 한다 — `..`나 심볼릭 링크로
    프로젝트 밖(예: `~/.oci/config`, `~/Downloads/*.key`)을 가리키는 경로를
    문자열 검사만으로는 못 막는다.

    [제약] 차단은 이름·디렉토리 패턴 기반이라 완벽하지 않다. 그래서 프로젝트 루트
    하위로 범위를 먼저 좁힌 뒤(1차 방어) 패턴을 적용한다(2차 방어).
    """
    p = Path(path)
    root = Path(project_root)
    try:
        p = p.resolve()
        root = root.resolve()
    except OSError as e:
        return False, f"경로 해석 실패: {e}"

    if not p.exists() or not p.is_file():
        return False, "파일이 존재하지 않음"

    # 1차 방어: 프로젝트 루트 밖은 무조건 거부
    try:
        p.relative_to(root)
    except ValueError:
        return False, "프로젝트 폴더 밖의 파일은 보낼 수 없음"

    # 2차 방어: 민감 이름/디렉토리
    low = p.name.lower()
    if any(pat in low for pat in _DENY_NAME_PATTERNS):
        return False, f"민감 파일로 분류됨({p.name})"
    parts_low = {s.lower() for s in p.parts}
    hit = parts_low & set(_DENY_DIR_PARTS)
    if hit:
        return False, f"민감 디렉토리 포함({', '.join(sorted(hit))})"

    size = p.stat().st_size
    if size > MAX_DOC_BYTES:
        return False, f"파일이 너무 큼({size / 1024 / 1024:.1f}MB > 45MB)"
    if size == 0:
        return False, "빈 파일"

    return True, ""


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
