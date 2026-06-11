#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
FILE: scripts/statusline.py
DESCRIPTION: Claude Code 커스텀 상태줄 — 세션 누적 I/O 토큰 한 줄 (In/Out/Cache).
             install_statusline.py가 이 파일을 ~/.claude/statusline.py로 복사해 설치한다.
             (원본은 저장소에서 버전 관리 — 어느 PC에서든 설치 가능하게 하기 위함)

REVISION HISTORY:
- 2026-06-11 Claude: 라인1(모델+컨텍스트 %) 제거 — [1m] 모델에서 200k 기준 135% 오표시 +
                     Claude Code 네이티브 컨텍스트 표시와 중복. .status_cache.json 쓰기도 제거
                     (소비자 terminal_header.py가 어디에도 존재하지 않는 유령 의존이었음)
- 2026-06-11 Claude: 저장소로 편입 — ~/.claude에만 있던 파일이 PC 간 이식 불가했던 문제 해결
- 2026-02-27 Claude: 최초 생성 (statusline-setup agent). 블록 그리드 + ANSI 색상
"""

import sys
import json

# [제약] 이 스크립트는 Claude Code가 stdin으로 JSON을 넘겨 호출한다 —
# 직접 실행 시 빈 입력이면 빈 그리드를 출력하고 정상 종료해야 한다 (에러 출력 금지,
# 상태줄에 트레이스백이 찍히면 터미널이 깨진다).
RESET = "\033[0m"
DIM   = "\033[2m"

FG_WHITE   = "\033[97m"
FG_YELLOW  = "\033[93m"
FG_GREEN   = "\033[92m"
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


def format_tokens(n: int) -> str:
    """24000 -> '24k', 1500000 -> '1.5M'"""
    if n >= 1_000_000:
        val = n / 1_000_000
        return f"{val:.1f}M" if val != int(val) else f"{int(val)}M"
    elif n >= 1_000:
        val = n / 1_000
        return f"{val:.1f}k" if val != int(val) else f"{int(val)}k"
    return str(n)


def main():
    try:
        raw = sys.stdin.read()
        data = json.loads(raw) if raw.strip() else {}
    except (json.JSONDecodeError, Exception):
        data = {}

    ctx = data.get("context_window", {})
    current = ctx.get("current_usage") or {}

    cache_read   = current.get("cache_read_input_tokens", 0) or 0
    cache_create = current.get("cache_creation_input_tokens", 0) or 0

    total_input  = ctx.get("total_input_tokens", 0) or 0
    total_output = ctx.get("total_output_tokens", 0) or 0

    # [WHY] 컨텍스트 사용률 표시는 Claude Code 네이티브 UI가 담당 — 여기서는
    # 네이티브가 안 보여주는 세션 누적 I/O만 표시한다. 마젠타 그리드는 출력 토큰 비율.
    ctx_size = ctx.get("context_window_size", 0) or 200_000
    out_pct = (total_output / ctx_size) * 100.0 if total_output > 0 else 0.0

    grid_colored = f"{FG_MAGENTA}{build_grid(out_pct)}{RESET}"

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
        sep = f"  {DIM}·{RESET}  "
        print(f"{grid_colored}   {sep.join(parts)}")
    else:
        print(f"{grid_colored}   {DIM}No usage data yet{RESET}")


if __name__ == "__main__":
    main()
