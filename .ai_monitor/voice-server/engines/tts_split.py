# -*- coding: utf-8 -*-
"""
FILE: .ai_monitor/voice-server/engines/tts_split.py
DESCRIPTION: 긴 글을 낭독 단위로 자른다 — 이어 굽기(첫 문장부터 틀고 뒤를 잇는 것)의 재료.

             [🔴 짧은 조각을 만들지 않는다 — 실측이 시킨 규칙] Qwen 은 9자짜리도 12초가
               걸린다(굽는 시간이 글자 수에 비례하지 않는다). 잘게 자를수록 총 시간만
               늘고 이득이 없다. 그래서 MIN_CHARS 밑이면 다음 조각에 붙인다.

             [WHY 한글 문장 부호 기준인가] 이 앱이 읽는 말은 한국어다. 마침표·물음표·
               느낌표와 줄바꿈이 실제 쉬는 자리이고, 그 자리에서 자르면 이어 붙였을 때
               사람이 쉬는 자리와 겹쳐 티가 덜 난다. 쉼표는 자르지 않는다 — 거기서 끊으면
               문장이 반토막 난 것처럼 들린다.

             [제약] 소수점·줄임표·따옴표를 마침표로 오인하면 문장이 엉뚱하게 갈린다.
               숫자 사이의 점과 연속된 점(…, ..)은 자르지 않는다.

REVISION HISTORY:
- 2026-08-16 Claude: 최초 작성 — 이어 굽기용 문장 나누기
"""

from __future__ import annotations

import re

# 이보다 짧은 조각은 앞/뒤에 붙인다. [WHY 12인가] 12자면 굽는 데 12~13초, 소리는 1.8초쯤이다.
# 그보다 짧게 잘라 봐야 기다림은 그대로고 조각 수만 는다.
MIN_CHARS = 12
# 한 조각의 상한. [WHY 두나] 첫 조각이 길면 첫 소리가 그만큼 늦는다.
MAX_CHARS = 60
# 첫 조각만 더 짧게. [WHY] 첫 소리까지 걸리는 시간이 곧 체감이다(실측 42자 19.7초).
FIRST_MAX_CHARS = 24

# 문장 끝. 뒤에 따옴표가 붙는 경우까지 한 덩어리로 본다.
_END = re.compile(r'(?<=[.!?。！？])["\'”’)\]]*\s+|\n+')
# 숫자 사이의 점(3.14)과 줄임표는 문장 끝이 아니다.
_NOT_END = re.compile(r'(\d)\.(\d)|\.{2,}|…')


def split(text: str) -> list[str]:
    """낭독 단위 목록. 빈 글이면 빈 목록."""
    t = (text or '').strip()
    if not t:
        return []

    # 자르면 안 되는 점을 잠시 다른 글자로 바꿔 둔다(자른 뒤 되돌린다).
    holes: list[str] = []

    def _hide(m: re.Match) -> str:
        holes.append(m.group(0))
        return f'\x00{len(holes) - 1}\x00'

    t = _NOT_END.sub(_hide, t)

    raw = [p.strip() for p in _END.split(t) if p and p.strip()]

    # 너무 짧은 조각 붙이기 — 뒤에 붙이고, 마지막 조각이면 앞에 붙인다.
    merged: list[str] = []
    buf = ''
    for p in raw:
        buf = (buf + ' ' + p).strip() if buf else p
        if len(buf.replace(' ', '')) >= MIN_CHARS:
            merged.append(buf)
            buf = ''
    if buf:
        if merged:
            merged[-1] = (merged[-1] + ' ' + buf).strip()
        else:
            merged.append(buf)

    # 너무 긴 조각 쪼개기 — 자를 자리가 없으면 그냥 둔다(억지로 자르면 말이 끊긴다).
    out: list[str] = []
    for p in merged:
        while len(p) > MAX_CHARS:
            cut = p.rfind(' ', 0, MAX_CHARS)
            if cut < MIN_CHARS:
                break
            out.append(p[:cut].strip())
            p = p[cut:].strip()
        out.append(p)

    # [🔴 첫 조각만 짧게 — 첫 소리가 곧 체감이다] 굽는 시간이 글자 수를 따라간다(42자
    #   19.7초, 54자 28.4초 실측). 첫 조각이 길면 그만큼 기다린다. 그래서 첫 조각만
    #   FIRST_MAX 로 조인다. 뒤 조각은 조이지 않는다 — 어차피 재생이 굽기를 앞지르므로
    #   조각을 늘려 봐야 총 시간만 는다.
    if out and len(out[0]) > FIRST_MAX_CHARS:
        head = out[0]
        cut = head.rfind(' ', 0, FIRST_MAX_CHARS)
        if cut >= MIN_CHARS:
            out = [head[:cut].strip(), head[cut:].strip()] + out[1:]

    def _restore(s: str) -> str:
        return re.sub(r'\x00(\d+)\x00', lambda m: holes[int(m.group(1))], s)

    return [_restore(s) for s in out if s.strip()]
