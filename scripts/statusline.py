#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
FILE: scripts/statusline.py
DESCRIPTION: Claude Code 커스텀 상태줄 — 컨텍스트 그리드+모델+토큰(라인1), 세션 I/O(라인2).
             install_statusline.py가 이 파일을 ~/.claude/statusline.py로 복사해 설치한다.
             (원본은 저장소에서 버전 관리 — 어느 PC에서든 설치 가능하게 하기 위함)

REVISION HISTORY:
- 2026-06-21 Claude: 라인1·2를 '연속된 한 바'로 변경 — 윗줄(0~50%)+아랫줄(50~100%)=20칸.
                     [WHY] 두 줄에 '똑같은 바'를 복붙해 2행 공간이 낭비된다는 지적. 같은
                     컨텍스트를 칸 2배(칸당 10%→5%)로 펼쳐 채움이 더 정밀하게 보이게 함.
                     윗줄이 먼저 차고 넘치면 아랫줄로 이어짐(위→아래 연속). 색도 전체에 걸쳐
                     녹(좌상)→적(우하)으로 흐름. 채움 꽉참 임계 5%→2.5%로 2배 민감.
- 2026-06-21 Claude: 히트맵 박스 그리드(■/□)로 최종 확정 — 사용자가 스크린샷으로 지정.
                     칸마다 위치별 색이 녹→노랑→빨강(256색 HEAT 램프)으로 변하고 0%에서도
                     색 스케일이 항상 보임. 채움 ■/빈 □으로 사용량. 라인1·2 같은 바 → 2행
                     그리드처럼 크게(이전 "너무 작다" 해결). (Braille → 박스 재교체)
- 2026-06-21 Claude: Braille 스파크라인(⣀⣤⣶⣿) + 위치별 그라데이션 색(중간본, 박스로 교체됨).
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

# [WHY] 히트맵 박스 그리드(사용자가 스크린샷으로 지정한 최종 스타일).
# 칸마다 '위치별' 색이 녹색→노랑→빨강으로 변하고(아래 HEAT 256색 램프), 이 색 스케일은
# 사용량 0%에서도 항상 보인다. 채움 ⛁ / 빈칸 ⛶ 으로 사용량을 표시 — 색은 위치, 모양은 채움.
# [핵심] 라인1·2는 '같은 바 복붙'이 아니라 '연속된 한 바'다. 0~100%를 TOTAL_CELLS칸으로
# 펼쳐 앞 절반은 윗줄(0~50%), 뒤 절반은 아랫줄(50~100%)에 그린다. 같은 컨텍스트지만
# 칸이 2배라 채움이 더 정밀하게 보인다(이전 "10%=100k 단위라 1M에선 안 변함" 완화).
# [참고] ⛁⛶ 글리프는 사용자 터미널 폰트에서 렌더 확인됨(스크린샷). 256색은 터미널 지원 전제.
HEAT = [46, 82, 118, 154, 190, 226, 220, 214, 208, 196]   # 녹→연두→노랑→주황→빨강
# [사용자 지정] 글리프 ⛶(빈칸)·⛀(반칸)·⛁(채움) — 스크린샷에서 직접 고른 네모서리 박스 계열.
DOT_FILLED = "⛁"
DOT_HALF   = "⛀"
DOT_EMPTY  = "⛶"

# [불변식] TOTAL_CELLS 짝수 — 윗줄/아랫줄로 정확히 반씩 나뉜다. HALF가 한 줄의 칸 수.
TOTAL_CELLS = 20        # 윗줄10 + 아랫줄10 = 연속 한 바, 칸당 5%
HALF_CELLS  = TOTAL_CELLS // 2


def _fg256(n: int) -> str:
    return f"\033[38;5;{n}m"


def render_split_bar(used_pct: float):
    """0~100%를 TOTAL_CELLS칸 '연속 한 바'로 그려 (윗줄, 아랫줄) 두 글리프열로 반환.
    [WHY] 두 줄에 같은 바를 복붙하던 걸 폐기 — 같은 컨텍스트를 칸 2배로 펼쳐 윗줄이 먼저
    차고 넘치면 아랫줄로 이어지게. 칸당 5%(이전 10%)라 채움 변화가 더 정밀하게 보인다.
    [채움 단계] 반칸 ⛀ + 민감 임계값으로 조금만 써도 첫 칸이 켜짐: 0보다 크면 반칸,
    칸 절반(2.5%) 넘으면 꽉 참. 색=칸 위치별 HEAT(녹 좌상→적 우하), 모양=채움."""
    pct = max(0.0, min(100.0, used_pct))
    filled = pct / 100.0 * TOTAL_CELLS          # 채워질 칸 수(소수, 0~TOTAL_CELLS)
    cells = []
    for i in range(TOTAL_CELLS):
        level = filled - i                      # 이 칸이 얼마나 찼나 (0~1+)
        if level >= 0.5:
            glyph = DOT_FILLED
        elif level > 0.0005:                    # 칸의 0.05%만 써도 반칸(미세 사용량도 보임)
            glyph = DOT_HALF
        else:
            glyph = DOT_EMPTY
        heat = HEAT[int(i / TOTAL_CELLS * len(HEAT))]   # 20칸을 10색 HEAT 램프에 매핑
        cells.append(f"{_fg256(heat)}{glyph}")
    top = " ".join(cells[:HALF_CELLS]) + RESET
    bot = " ".join(cells[HALF_CELLS:]) + RESET
    return top, bot


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

    # [과거사고 2026-06-23] 바가 턴마다 "확 찼다가 1칸으로" 깜빡이던 버그.
    # [근본원인] Anthropic usage의 세 필드는 '서로 배타적'이다 — input_tokens는 캐시
    # 미적중분만, cache_read/cache_create는 별도 버킷. 컨텍스트 점유량 = 셋의 합.
    # 직전(틀린) 코드는 cache_read를 "input에 포함"이라 가정해 빼버렸는데, current_usage는
    # 직전 호출 1건의 분해라 캐시적중 턴엔 cache_read만 크고 input/create가 0 → used≈0(1칸),
    # 캐시생성 턴엔 cache_create만 큼 → used 급등. 셋을 다 더해 실제 점유량으로 안정화.
    used_tokens = input_tokens + cache_create + cache_read
    ctx_size = ctx.get("context_window_size", 0) or 200_000

    # [과거사고 2026-06-11] [1m] 1M 컨텍스트 세션인데 Claude Code가 context_window_size를
    # 200k로 보고 → 270k/200k (135%) 오표시. 사용량이 보고된 창 크기를 넘으면 실제 창이
    # 더 큰 것이므로 분모를 1M으로 올려 보정한다 (200k 초과 = [1m] 모델만 가능).
    if used_tokens > ctx_size:
        ctx_size = 1_000_000

    used_pct = (used_tokens / ctx_size) * 100.0 if ctx_size else 0.0

    model_display = get_model_display(data.get("model", {}))

    # 라인 1·2: 0~100%를 한 바로 펼쳐 윗줄(앞 절반)·아랫줄(뒤 절반)에 나눠 그린다.
    # 윗줄이 먼저 차고 넘치면 아랫줄로 이어짐 → 같은 컨텍스트를 더 정밀하게(칸당 5%).
    bar_top, bar_bot = render_split_bar(used_pct)
    model_colored = f"{FG_CYAN}{BOLD}{model_display}{RESET}"
    token_info    = (f"{FG_WHITE}{format_tokens(used_tokens)} / {format_tokens(ctx_size)}{RESET}"
                     f" {DIM}({used_pct:.0f}%){RESET}")
    line1 = f"{bar_top}  {model_colored} {DIM}·{RESET} {token_info}"

    # 라인 2: 바 뒷부분(50~100%) + 세션 누적 I/O.
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

    sep = f"  {DIM}·{RESET}  "
    tail = sep.join(parts) if parts else f"{DIM}No usage data yet{RESET}"
    line2 = f"{bar_bot}  {tail}"

    print(line1)
    print(line2)


if __name__ == "__main__":
    main()
