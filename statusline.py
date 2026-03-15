#!/usr/bin/env python3
# =============================================================================
# FILE: statusline.py
# DESCRIPTION: Claude Code 커스텀 상태줄 스크립트
#              /context 명령 출력 스타일을 모방한 컨텍스트 사용량 시각화
# AUTHOR: Claude (statusline-setup agent)
# CREATED: 2026-02-27
# REVISION HISTORY:
#   v1.0.0 - 2026-02-27 - 초기 생성. 블록 문자 그리드 + ANSI 색상 표시
# =============================================================================

import sys
import json
import pathlib

# ANSI 색상 코드 정의
# 터미널에서 dimmed 모드로 표시되므로 밝은 색상 위주로 선택
RESET   = "\033[0m"
BOLD    = "\033[1m"
DIM     = "\033[2m"

# 전경색
FG_WHITE   = "\033[97m"
FG_CYAN    = "\033[96m"
FG_YELLOW  = "\033[93m"
FG_GREEN   = "\033[92m"
FG_RED     = "\033[91m"
FG_MAGENTA = "\033[95m"
FG_BLUE    = "\033[94m"
FG_GRAY    = "\033[90m"

# 블록 문자 상수
# ⛁ = 가득 찬 블록 (사용됨)
# ⛀ = 절반 찬 블록 (중간)
# ⛶ = 빈 블록 (미사용)
BLOCK_FULL  = "⛁"
BLOCK_HALF  = "⛀"
BLOCK_EMPTY = "⛶"

# 그리드 총 칸 수 (⛁/⛶ 8칸 기준, /context 명령 스타일 모방)
GRID_SIZE = 8


def build_grid(used_pct: float) -> str:
    """
    사용 비율(0.0~100.0)을 받아 8칸짜리 블록 그리드 문자열을 생성한다.
    - 0~12.5%  구간마다 칸 하나씩 채워짐
    - 경계 구간은 ⛀(절반) 블록으로 표시
    """
    cells = []
    ratio = used_pct / 100.0  # 0.0 ~ 1.0
    filled_float = ratio * GRID_SIZE  # 실수로 채워진 칸 수

    for i in range(GRID_SIZE):
        threshold = filled_float - i
        if threshold >= 1.0:
            # 완전히 채워진 칸
            cells.append(BLOCK_FULL)
        elif threshold >= 0.4:
            # 절반 채워진 칸 (경계 구간)
            cells.append(BLOCK_HALF)
        else:
            # 빈 칸
            cells.append(BLOCK_EMPTY)

    return " ".join(cells)


def colorize_grid(grid_str: str, used_pct: float) -> str:
    """
    사용량 비율에 따라 그리드에 ANSI 색상을 입힌다.
    - 0~60%  : 초록(정상)
    - 60~80% : 노랑(주의)
    - 80~100%: 빨강(위험)
    """
    if used_pct < 60:
        color = FG_GREEN
    elif used_pct < 80:
        color = FG_YELLOW
    else:
        color = FG_RED
    return f"{color}{grid_str}{RESET}"


def format_tokens(n: int) -> str:
    """
    토큰 수를 읽기 쉬운 형식으로 변환한다.
    예) 24000 -> "24k", 1500000 -> "1.5M"
    """
    if n >= 1_000_000:
        val = n / 1_000_000
        return f"{val:.1f}M" if val != int(val) else f"{int(val)}M"
    elif n >= 1_000:
        val = n / 1_000
        return f"{val:.1f}k" if val != int(val) else f"{int(val)}k"
    return str(n)


def get_model_display(model_obj) -> str:
    """
    model 필드에서 표시 이름을 추출한다.
    문자열이면 그대로, 객체면 display_name 또는 id를 사용한다.
    """
    if isinstance(model_obj, str):
        return model_obj
    if isinstance(model_obj, dict):
        return model_obj.get("display_name") or model_obj.get("id") or "unknown"
    return "unknown"


def main():
    # stdin에서 JSON 입력을 읽는다
    try:
        raw = sys.stdin.read()
        data = json.loads(raw) if raw.strip() else {}
    except (json.JSONDecodeError, Exception):
        data = {}

    # 컨텍스트 윈도우 데이터 추출
    ctx = data.get("context_window", {})

    # used_percentage / remaining_percentage (미리 계산된 필드 우선 사용)
    used_pct   = ctx.get("used_percentage")      # None 가능
    # context_window_size와 current_usage로 직접 계산 시도
    ctx_size   = ctx.get("context_window_size", 0)
    current    = ctx.get("current_usage") or {}

    # 입력 토큰 수 계산 (캐시 포함)
    input_tokens  = current.get("input_tokens", 0) or 0
    cache_read    = current.get("cache_read_input_tokens", 0) or 0
    cache_create  = current.get("cache_creation_input_tokens", 0) or 0
    output_tokens = current.get("output_tokens", 0) or 0

    # 실제 사용 토큰 = 입력 + 캐시 생성 (캐시 읽기는 이미 포함)
    used_tokens = input_tokens + cache_create

    # used_percentage 가 없으면 직접 계산
    if used_pct is None and ctx_size and ctx_size > 0:
        used_pct = (used_tokens / ctx_size) * 100.0
    elif used_pct is None:
        used_pct = 0.0

    # 총 입력/출력 토큰 (세션 누적)
    total_input  = ctx.get("total_input_tokens", 0) or 0
    total_output = ctx.get("total_output_tokens", 0) or 0

    # 모델 정보
    model_display = get_model_display(data.get("model", {}))

    # 표시용 토큰 수: current_usage가 있으면 그것을, 없으면 total 사용
    if used_tokens > 0:
        display_used = used_tokens
        display_max  = ctx_size if ctx_size else 0
    elif total_input > 0:
        display_used = total_input
        display_max  = ctx_size if ctx_size else 0
    else:
        display_used = 0
        display_max  = ctx_size if ctx_size else 200000

    # -------------------------------------------------------------------------
    # 라인 1: 블록 그리드 + 모델명 + 토큰 수 + 비율
    # 예) ⛁ ⛁ ⛁ ⛁ ⛀ ⛶ ⛶ ⛶   claude-sonnet-4-6 · 24k/200k tokens (12%)
    # -------------------------------------------------------------------------
    grid_raw      = build_grid(used_pct)
    grid_colored  = colorize_grid(grid_raw, used_pct)

    used_str      = format_tokens(display_used)
    max_str       = format_tokens(display_max) if display_max else "?"
    pct_str       = f"{used_pct:.0f}%"

    # 모델명 색상: 시안
    model_colored = f"{FG_CYAN}{BOLD}{model_display}{RESET}"
    token_info    = f"{FG_WHITE}{used_str}/{max_str} tokens{RESET} {DIM}({pct_str}){RESET}"

    line1 = f"{grid_colored}   {model_colored} {DIM}·{RESET} {token_info}"

    # -------------------------------------------------------------------------
    # 라인 2: 세션 누적 정보 표시
    # current_usage 상세 분류가 없으므로 세션 I/O 토큰 요약 표시
    # 예) ⛁ ⛁ ⛀ ⛶ ⛶ ⛶ ⛶ ⛶   In: 24k · Out: 3k · Cache+: 1.2k · Cache~: 8k
    # -------------------------------------------------------------------------

    # 두 번째 라인용 그리드: 출력 토큰 비율 (세션 누적 출력/컨텍스트 크기)
    if display_max and display_max > 0 and total_output > 0:
        out_pct = (total_output / display_max) * 100.0
    else:
        out_pct = 0.0

    grid2_raw     = build_grid(out_pct)
    # 두 번째 그리드는 마젠타(출력 비율 표시)
    grid2_colored = f"{FG_MAGENTA}{grid2_raw}{RESET}"

    # 상세 분류 레이블 구성
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
        line2 = f"{grid2_colored}   {DIM}·{RESET} ".join(["", ""]).strip()
        # 파트들을 " · " 구분자로 이음
        sep   = f"  {DIM}·{RESET}  "
        line2 = f"{grid2_colored}   {sep.join(parts)}"
    else:
        # 데이터가 전혀 없을 때: 빈 그리드만 표시
        line2 = f"{grid2_colored}   {DIM}No usage data yet{RESET}"

    # 상태 캐시 파일에 저장 (terminal_header.py가 읽어서 상단에 표시)
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

    # 최종 출력 (두 줄)
    print(line1)
    print(line2)


if __name__ == "__main__":
    main()
