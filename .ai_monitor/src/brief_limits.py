#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
FILE: src/brief_limits.py
DESCRIPTION: 프롬프트 계열 텍스트(재정박·워커 브리프·체크포인트)의 글자 수 상한과
             중간 절단 축약기. CLAUDE.md 규칙 9의 유일한 강제 지점.
             session_recycle의 REANCHOR 단계가 이 모듈을 반드시 경유한다.

REVISION HISTORY:
- 2026-08-05 Claude: 최초 구현 — 하네스 v2.1 분석에서 도출(② 브리프 상한)
"""
from __future__ import annotations

# [WHY] '줄'이 아니라 '글자' 기준인 이유 — 규칙 2(1500줄)는 코드 파일용이다.
#   프롬프트는 개행이 거의 없어 줄 수가 크기의 프록시로 무의미하고,
#   한글은 토큰당 글자 수가 영어보다 작아 char가 토큰 추정에 더 가깝다.
# [불변식] 이 표를 늘릴 때 .claude/rules/context-limits.md도 같이 고칠 것 —
#   두 곳이 어긋나면 규칙 문서가 거짓말을 하게 된다.
LIMITS: dict[str, int] = {
    'reanchor': 1500,   # 리사이클 후 새 세션에 주입하는 재정박 프롬프트
    'brief': 1200,      # 에이전트 간 위임 지시(worker brief)
    'intent': 200,      # active_session_context.intent
    'next_step': 200,   # active_session_context.next_step
}

_ELLIPSIS = '\n…({n}자 생략)…\n'


def limit_for(kind: str) -> int:
    """종류별 상한. 미등록 종류는 가장 관대한 값으로 폴백한다.

    [WHY] 미등록 kind에 0을 주면 호출부가 전체를 잘라버려 리사이클이 빈 프롬프트로
      성공한 것처럼 보인다 — 조용한 실패보다 관대한 폴백이 안전하다.
    """
    return LIMITS.get(kind, max(LIMITS.values()))


def check_len(kind: str, text: str) -> tuple[bool, int, int]:
    """(상한 이내인가, 실제 글자수, 상한)."""
    limit = limit_for(kind)
    count = len(text or '')
    return count <= limit, count, limit


def truncate_smart(text: str, limit: int) -> str:
    """상한 초과 시 '뒤'가 아니라 '중간'을 잘라낸다.

    [WHY] 재정박 프롬프트는 앞(목표·의도)과 뒤(다음 할 일)가 둘 다 필수다.
      통상적인 tail 절단은 next_step을 통째로 날려 리사이클의 목적 자체를 파괴한다.
      버릴 수 있는 건 중간(경과 서술)뿐이라 앞뒤를 남기고 가운데를 접는다.
    [불변식] 반환 길이는 항상 limit 이하 — 생략 표기까지 예산에 포함해 계산한다.
    """
    text = text or ''
    if len(text) <= limit:
        return text
    if limit <= 0:
        return ''

    dropped = len(text) - limit
    marker = _ELLIPSIS.format(n=dropped)
    # 생략 표기 자체가 예산을 먹으므로 본문 예산에서 먼저 뺀다.
    budget = limit - len(marker)
    if budget <= 0:
        # 상한이 표기보다도 짧은 극단 — 표기를 포기하고 앞부분만 남긴다.
        return text[:limit]

    # 앞을 뒤보다 넉넉히(6:4) — 목표 진술이 다음 단계보다 재구성 비용이 크다.
    head = (budget * 6) // 10
    tail = budget - head
    marker = _ELLIPSIS.format(n=len(text) - head - tail)
    if head + tail + len(marker) > limit:
        tail = max(0, limit - head - len(marker))
    return text[:head] + marker + (text[-tail:] if tail else '')


def enforce(kind: str, text: str) -> tuple[str, dict]:
    """상한을 적용한 텍스트와 계측 정보를 돌려준다.

    [불변식] 위반해도 예외를 던지지 않고 '축약'한다 — 차단하면 REANCHOR가 실패해
      세션을 되살리지 못하고, 이는 통합 계획의 보안 불변식 10
      ('체크포인트 저장 실패 시 현재 세션을 파괴하지 않는다')과 정면 충돌한다.
      위반 사실은 반환 dict의 truncated 플래그로만 알리고 판단은 호출부에 맡긴다.
    """
    ok, count, limit = check_len(kind, text)
    if ok:
        return (text or ''), {'kind': kind, 'chars': count, 'limit': limit, 'truncated': False}
    return truncate_smart(text, limit), {
        'kind': kind, 'chars': count, 'limit': limit, 'truncated': True, 'dropped': count - limit,
    }
