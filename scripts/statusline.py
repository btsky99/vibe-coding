#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
FILE: scripts/statusline.py
DESCRIPTION: Claude Code 커스텀 상태줄 — 컨텍스트 그리드+모델+토큰(라인1), 세션 I/O(라인2).
             install_statusline.py가 이 파일을 ~/.claude/statusline.py로 복사해 설치한다.
             (원본은 저장소에서 버전 관리 — 어느 PC에서든 설치 가능하게 하기 위함)

REVISION HISTORY:
- 2026-06-21 Claude: Braille 스파크라인(⣀⣤⣶⣿) + 위치별 그라데이션 색(사용자 선택/요청).
                     칸 위치 누적%로 녹→황→적 칠해 화려함+위험구간 가시화. 빈칸은 ⣀ dim baseline.
                     (도트 ●◐○ → Braille로 재교체: 사용자 미리보기 비교 후 Braille 선택)
- 2026-06-21 Claude: 도트 그래프(●◐○)로 교체 — 가로 부분 블록이 폰트 따라 렌더 실패해
                     "안 뜬다/안 이쁘다" 피드백. 이전 v3.4.3 도트 스타일 복원 시도.
                     (후속: 사용자가 Braille 스파크라인 선택해 재교체)
- 2026-06-21 Claude: 사용량 바 미세 해상도화 + 2줄 가독성 개선 (사용자 요청).
                     [WHY] 기존 8칸 ⛁/⛀/⛶ 그리드는 1칸=12.5%(125k). 1M 컨텍스트에선 실사용이
                     거의 늘 1칸 미만이라 "사용량이 늘어도 바가 안 변한다"고 느껴졌음.
                     해법: 가로 1/8 블록(▏▎▍▌▋▊▉█)으로 칸당 8단계 → 5%↔6%도 눈에 보임.
                     (후속: 블록 폰트 렌더 문제로 도트로 재교체)
                     [참고] 우측 'Sh: …' 배지는 Claude Code CLI 네이티브 출력 — 이 스크립트
                     stdout에 없음. 스크립트로는 제거 불가(설정/CLI 영역).
- 2026-06-11 Claude: 라인1 복원 (사용자 요청 — 제거가 아니라 정상 표시가 목표였음).
                     [1m] 모델에서 Claude Code가 창 크기를 200k로 잘못 보고해 135% 오표시되던
                     문제는 사용량>창 크기일 때 분모를 사용량 기준으로 보정해 해결.
                     .status_cache.json 쓰기는 계속 제거 상태 유지 (terminal_header.py 유령 의존)
- 2026-06-11 Claude: 저장소로 편입 — ~/.claude에만 있던 파일이 PC 간 이식 불가했던 문제 해결
- 2026-02-27 Claude: 최초 생성 (statusline-setup agent). 블록 그리드 + ANSI 색상
"""

import sys
import json

# [제약] 이 스크립트는 Claude Code가 stdin으로 JSON을 넘겨 호출한다 —
# 직접 실행 시 빈 입력이면 빈 그리드를 출력하고 정상 종료해야 한다 (에러 출력 금지,
# 상태줄에 트레이스백이 찍히면 터미널이 깨진다).
RESET = "\033[0m"
BOLD  = "\033[1m"
DIM   = "\033[2m"

FG_WHITE   = "\033[97m"
FG_CYAN    = "\033[96m"
FG_YELLOW  = "\033[93m"
FG_GREEN   = "\033[92m"
FG_RED     = "\033[91m"
FG_MAGENTA = "\033[95m"
FG_BLUE    = "\033[94m"
FG_GRAY    = "\033[90m"

# [WHY] Braille 스파크라인(사용자 선택) — 폰트에서 잘 렌더되고 가장 '그래프'다움.
# 가로 부분 블록(▏▎▍)·원형 도트(●○)는 폰트/취향 문제로 반려됨. Braille는 한 칸을
# 아래→위 4단계로 채울 수 있어(⣀⣤⣶⣿) 적은 사용량도 첫 칸이 차오르는 게 보인다.
# 빈 칸은 baseline ⣀를 dim 처리 → 그래프 가로축처럼 보이게(빈 네모보다 덜 휑함).
FILL_LEVELS = ("⣀", "⣤", "⣶", "⣿")   # 1/4·2/4·3/4·4/4 (아래→위 채움)
EMPTY_GLYPH = "⣀"                       # 빈 칸 baseline (dim)

GRID_SIZE = 10          # 칸 10개 × 4단계 = 40스텝(2.5% 단위)


def _cells(used_pct: float):
    """각 칸을 (채워짐?, 글리프)로. 채움은 아래→위 4단계로 양자화."""
    pct = max(0.0, min(100.0, used_pct))
    filled = pct / 100.0 * GRID_SIZE            # 채워질 칸 수(소수)
    out = []
    for i in range(GRID_SIZE):
        level = filled - i                      # 이 칸이 얼마나 찼나 (0~1+)
        if level <= 0.0:
            out.append((False, EMPTY_GLYPH))
        else:
            h = min(4, max(1, int(round(level * 4))))   # 1..4 단계
            out.append((True, FILL_LEVELS[h - 1]))
    return out


def build_bar(used_pct: float) -> str:
    """색 없는 plain 바(공백 구분) — 들여쓰기 폭 계산용."""
    return " ".join(g for _, g in _cells(used_pct))


def _cell_color(cell_pct: float) -> str:
    """칸 '위치'(누적 %)별 색 — 그라데이션. 60%↓ 녹 · 80%↓ 황 · 이상 적."""
    if cell_pct <= 60:
        return FG_GREEN
    if cell_pct <= 80:
        return FG_YELLOW
    return FG_RED


def colorize_bar(used_pct: float) -> str:
    """[WHY] 단색 대신 칸 위치별 그라데이션 — 채워질수록 녹→황→적으로 변해 더 화려하고
    위험 구간이 색으로 드러남(사용자 '색상 추가' 요청). 빈 칸은 dim 회색 baseline."""
    cells = _cells(used_pct)
    n = len(cells)
    parts = []
    for i, (is_filled, g) in enumerate(cells):
        if not is_filled:
            parts.append(f"{FG_GRAY}{g}")
        else:
            cell_pct = (i + 1) / n * 100.0      # 이 칸이 대표하는 누적 %
            parts.append(f"{_cell_color(cell_pct)}{g}")
    return " ".join(parts) + RESET


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
    current = ctx.get("current_usage") or {}

    input_tokens = current.get("input_tokens", 0) or 0
    cache_read   = current.get("cache_read_input_tokens", 0) or 0
    cache_create = current.get("cache_creation_input_tokens", 0) or 0

    total_input  = ctx.get("total_input_tokens", 0) or 0
    total_output = ctx.get("total_output_tokens", 0) or 0

    # [WHY] 캐시 읽기는 input_tokens에 이미 포함 — 더하면 이중 계산
    used_tokens = input_tokens + cache_create
    ctx_size = ctx.get("context_window_size", 0) or 200_000

    # [과거사고 2026-06-11] [1m] 1M 컨텍스트 세션인데 Claude Code가 context_window_size를
    # 200k로 보고 → 270k/200k (135%) 오표시. 사용량이 보고된 창 크기를 넘으면 실제 창이
    # 더 큰 것이므로 분모를 1M으로 올려 보정한다 (200k 초과 = [1m] 모델만 가능).
    if used_tokens > ctx_size:
        ctx_size = 1_000_000

    used_pct = (used_tokens / ctx_size) * 100.0 if ctx_size else 0.0

    model_display = get_model_display(data.get("model", {}))

    # 라인 1: Braille 그래프(그라데이션) + 모델 + 토큰 — 예) ⣤ ⣀ ⣀ …  Opus 4.8 (1M) · 56.5k / 1M (6%)
    plain_bar     = build_bar(used_pct)
    bar_colored   = colorize_bar(used_pct)
    model_colored = f"{FG_CYAN}{BOLD}{model_display}{RESET}"
    token_info    = (f"{FG_WHITE}{format_tokens(used_tokens)} / {format_tokens(ctx_size)}{RESET}"
                     f" {DIM}({used_pct:.0f}%){RESET}")
    line1 = f"{bar_colored}  {model_colored} {DIM}·{RESET} {token_info}"

    # 라인 2: 세션 누적 I/O — 라인1 텍스트 아래로 들여써 한 묶음으로 읽히게.
    # [WHY] 과거의 마젠타 '출력/창 비율' 바는 의미가 모호해 가독성을 해쳤음 → 제거하고
    # 바 표시 너비만큼 들여쓰기로 정렬 (2줄 구조 자체는 유지). 들여쓰기는 색 없는
    # plain_bar 길이 기준 — ANSI 코드를 세지 않으려고.
    indent = " " * (len(plain_bar) + 2)

    parts = []
    if total_input > 0:
        parts.append(f"{FG_GREEN}In{RESET} {FG_WHITE}{format_tokens(total_input)}{RESET}")
    if total_output > 0:
        parts.append(f"{FG_BLUE}Out{RESET} {FG_WHITE}{format_tokens(total_output)}{RESET}")
    # [WHY] Cache+/Cache~ 라벨이 암호 같다는 피드백 → 한글로. 캐시저장=새로 캐시에 쓴 토큰(1.25x),
    # 캐시재사용=캐시에서 읽어 재사용한 토큰(0.1x, 비용 절약 핵심). In/Out은 짧고 익숙해 유지.
    if cache_create > 0:
        parts.append(f"{FG_YELLOW}캐시저장{RESET} {FG_WHITE}{format_tokens(cache_create)}{RESET}")
    if cache_read > 0:
        parts.append(f"{FG_GRAY}캐시재사용{RESET} {FG_WHITE}{format_tokens(cache_read)}{RESET}")

    if parts:
        sep = f"  {DIM}·{RESET}  "
        line2 = f"{indent}{sep.join(parts)}"
    else:
        line2 = f"{indent}{DIM}No usage data yet{RESET}"

    print(line1)
    print(line2)


if __name__ == "__main__":
    main()
