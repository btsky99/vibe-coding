#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
FILE: scripts/statusline.py
DESCRIPTION: Claude Code 커스텀 상태줄 — 컨텍스트 사용량 블록 그리드 + 모델명 + 토큰 수.
             install_statusline.py가 이 파일을 ~/.claude/statusline.py로 복사해 설치한다.
             (원본은 저장소에서 버전 관리 — 어느 PC에서든 설치 가능하게 하기 위함)

REVISION HISTORY:
- 2026-06-11 Claude: 저장소로 편입 — ~/.claude에만 있던 파일이 PC 간 이식 불가했던 문제 해결
- 2026-02-27 Claude: 최초 생성 (statusline-setup agent). 블록 그리드 + ANSI 색상
"""

import sys
import json
import pathlib

# [제약] 이 스크립트는 Claude Code가 stdin으로 JSON을 넘겨 호출한다 —
# 직접 실행 시 빈 입력이면 빈 그리드를 출력하고 정상 종료해야 한다 (에러 출력 금지,
# 상태줄에 트레이스백이 찍히면 터미널이 깨진다).
RESET   = "\033[0m"
BOLD    = "\033[1m"
DIM     = "\033[2m"

FG_WHITE   = "\033[97m"
FG_CYAN    = "\033[96m"
FG_YELLOW  = "\033[93m"
FG_GREEN   = "\033[92m"
FG_RED     = "\033[91m"
FG_MAGENTA = "\033[95m"
FG_BLUE    = "\033[94m"
FG_GRAY    = "\033[90m"

BLOCK_FULL  = "⛁"
BLOCK_HALF  = "⛀"
BLOCK_EMPTY = "⛶"

GRID_SIZE = 8


def build_grid(used_pct: float) -> str:
    """사용 비율(0~100)을 8칸 블록 그리드로 변환. 경계 구간은 절반 블록."""
    cells = []
    ratio = used_pct / 100.0
    filled_float = ratio * GRID_SIZE

    for i in range(GRID_SIZE):
        threshold = filled_float - i
        if threshold >= 1.0:
            cells.append(BLOCK_FULL)
        elif threshold >= 0.4:
            cells.append(BLOCK_HALF)
        else:
            cells.append(BLOCK_EMPTY)

    return " ".join(cells)


def colorize_grid(grid_str: str, used_pct: float) -> str:
    """60% 미만 초록, 80% 미만 노랑, 이상 빨강."""
    if used_pct < 60:
        color = FG_GREEN
    elif used_pct < 80:
        color = FG_YELLOW
    else:
        color = FG_RED
    return f"{color}{grid_str}{RESET}"


def format_tokens(n: int) -> str:
    """24000 -> '24k', 1500000 -> '1.5M'"""
    if n >= 1_000_000:
        val = n / 1_000_000
        return f"{val:.1f}M" if val != int(val) else f"{int(val)}M"
    elif n >= 1_000:
        val = n / 1_000
        return f"{val:.1f}k" if val != int(val) else f"{int(val)}k"
    return str(n)


def get_model_display(model_obj) -> str:
    # [호환성] Claude Code 버전에 따라 model이 문자열 또는 {display_name, id} 객체로 옴
    if isinstance(model_obj, str):
        return model_obj
    if isinstance(model_obj, dict):
        return model_obj.get("display_name") or model_obj.get("id") or "unknown"
    return "unknown"


def main():
    try:
        raw = sys.stdin.read()
        data = json.loads(raw) if raw.strip() else {}
    except (json.JSONDecodeError, Exception):
        data = {}

    ctx = data.get("context_window", {})

    used_pct   = ctx.get("used_percentage")
    ctx_size   = ctx.get("context_window_size", 0)
    current    = ctx.get("current_usage") or {}

    input_tokens  = current.get("input_tokens", 0) or 0
    cache_read    = current.get("cache_read_input_tokens", 0) or 0
    cache_create  = current.get("cache_creation_input_tokens", 0) or 0
    output_tokens = current.get("output_tokens", 0) or 0

    # [WHY] 캐시 읽기는 input_tokens에 이미 포함 — 더하면 이중 계산
    used_tokens = input_tokens + cache_create

    if used_pct is None and ctx_size and ctx_size > 0:
        used_pct = (used_tokens / ctx_size) * 100.0
    elif used_pct is None:
        used_pct = 0.0

    total_input  = ctx.get("total_input_tokens", 0) or 0
    total_output = ctx.get("total_output_tokens", 0) or 0

    model_display = get_model_display(data.get("model", {}))

    if used_tokens > 0:
        display_used = used_tokens
        display_max  = ctx_size if ctx_size else 0
    elif total_input > 0:
        display_used = total_input
        display_max  = ctx_size if ctx_size else 0
    else:
        display_used = 0
        display_max  = ctx_size if ctx_size else 200000

    # 라인 1: 그리드 + 모델 + 토큰 — 예) ⛁ ⛁ ⛀ ⛶ …  Opus 4.7 · 24k/200k tokens (12%)
    grid_colored = colorize_grid(build_grid(used_pct), used_pct)

    used_str = format_tokens(display_used)
    max_str  = format_tokens(display_max) if display_max else "?"
    pct_str  = f"{used_pct:.0f}%"

    model_colored = f"{FG_CYAN}{BOLD}{model_display}{RESET}"
    token_info    = f"{FG_WHITE}{used_str}/{max_str} tokens{RESET} {DIM}({pct_str}){RESET}"

    line1 = f"{grid_colored}   {model_colored} {DIM}·{RESET} {token_info}"

    # 라인 2: 세션 누적 I/O — 마젠타 그리드는 출력 토큰 비율
    if display_max and display_max > 0 and total_output > 0:
        out_pct = (total_output / display_max) * 100.0
    else:
        out_pct = 0.0

    grid2_colored = f"{FG_MAGENTA}{build_grid(out_pct)}{RESET}"

    parts = []
    if total_input > 0:
        parts.append(f"{FG_GREEN}In:{RESET} {FG_WHITE}{format_tokens(total_input)}{RESET}")
    if total_output > 0:
        parts.append(f"{FG_BLUE}Out:{RESET} {FG_WHITE}{format_tokens(total_output)}{RESET}")
    if cache_create > 0:
        parts.append(f"{FG_YELLOW}Cache+:{RESET} {FG_WHITE}{format_tokens(cache_create)}{RESET}")
    if cache_read > 0:
        parts.append(f"{FG_GRAY}Cache~:{RESET} {FG_WHITE}{format_tokens(cache_read)}{RESET}")

    if parts:
        sep   = f"  {DIM}·{RESET}  "
        line2 = f"{grid2_colored}   {sep.join(parts)}"
    else:
        line2 = f"{grid2_colored}   {DIM}No usage data yet{RESET}"

    # [외부 의존] terminal_header.py가 이 캐시 파일을 읽어 상단 헤더에 재사용 —
    # 쓰기 실패는 무시 (상태줄 출력이 우선, 캐시는 부가 기능)
    cache_path = pathlib.Path.home() / ".claude" / ".status_cache.json"
    try:
        cache_path.write_text(json.dumps({
            "used_pct":    round(used_pct, 1),
            "model":       model_display,
            "used_tokens": display_used,
            "max_tokens":  display_max,
        }))
    except Exception:
        pass

    print(line1)
    print(line2)


if __name__ == "__main__":
    main()
