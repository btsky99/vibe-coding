#!/usr/bin/env python3
# =============================================================================
# FILE: gemini_statusline.py
# DESCRIPTION: Gemini CLI 전용 커스텀 상태줄 (Claude 스타일 그리드 완벽 재현)
# AUTHOR: Gemini (Statusline Architect)
# =============================================================================

import sys
import json
import os
import pathlib
import datetime

# ANSI 색상 코드 (Claude 스타일과 동일하게 설정)
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

# 블록 문자 (사용자 요청 스타일)
BLOCK_FULL  = "⛁"
BLOCK_HALF  = "⛀"
BLOCK_EMPTY = "⛶"
GRID_SIZE = 8

def build_grid(used_pct: float) -> str:
    cells = []
    ratio = max(0.0, min(100.0, used_pct)) / 100.0
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
    if used_pct < 60: color = FG_GREEN
    elif used_pct < 85: color = FG_YELLOW
    else: color = FG_RED
    return f"{color}{grid_str}{RESET}"

def format_tokens(n: int) -> str:
    if n >= 1_000_000: return f"{n/1_000_000:.1f}M"
    if n >= 1_000: return f"{n/1_000:.1f}k"
    return str(n)

def main():
    # 1. 컨텍스트 데이터 로드 (실제 Gemini 세션 정보를 읽어오거나 시뮬레이션)
    # Gemini CLI는 세션 정보를 환경 변수나 특정 파일에 저장할 수 있습니다.
    used_tokens = int(os.environ.get("GEMINI_USED_TOKENS", 12000)) # 예시값
    total_tokens = int(os.environ.get("GEMINI_MAX_TOKENS", 1000000))
    used_pct = (used_tokens / total_tokens * 100) if total_tokens > 0 else 0
    
    model_name = "gemini-2.0-flash-exp" # 현재 모델

    # 2. 첫 번째 라인: 그리드 + 모델명 + 토큰 정보
    grid1 = build_grid(used_pct)
    colored_grid1 = colorize_grid(grid1, used_pct)
    used_str = format_tokens(used_tokens)
    max_str = format_tokens(total_tokens)
    pct_str = f"{used_pct:.1f}%"

    model_colored = f"{FG_CYAN}{BOLD}{model_name}{RESET}"
    token_info = f"{FG_WHITE}{used_str}/{max_str} tokens{RESET} {DIM}({pct_str}){RESET}"
    
    line1 = f"{colored_grid1}   {model_colored} {DIM}·{RESET} {token_info}"

    # 3. 두 번째 라인: 하이브 상태 및 누적 정보
    # 여기서는 예시로 세션 누적 In/Out을 표시 (프로젝트 상태 연동)
    total_in = used_tokens
    total_out = int(used_tokens * 0.15)
    
    grid2 = build_grid(used_pct * 0.5) # 출력 비율은 입력보다 작게 표시
    grid2_colored = f"{FG_MAGENTA}{grid2}{RESET}"
    
    parts = [
        f"{FG_GREEN}In:{RESET} {FG_WHITE}{format_tokens(total_in)}{RESET}",
        f"{FG_BLUE}Out:{RESET} {FG_WHITE}{format_tokens(total_out)}{RESET}",
        f"{FG_GRAY}HIVE:{RESET} {FG_MAGENTA}ACTIVE{RESET}"
    ]
    sep = f"  {DIM}·{RESET}  "
    line2 = f"{grid2_colored}   {sep.join(parts)}"

    # 최종 출력
    print(f"\n{line1}")
    print(f"{line2}\n")

if __name__ == "__main__":
    main()
