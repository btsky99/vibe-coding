# -*- coding: utf-8 -*-
"""
FILE: .ai_monitor/voice-server/engines/tts_split.py
DESCRIPTION: 긴 글을 낭독 단위로 자른다 — 이어 굽기(첫 문장부터 틀고 뒤를 잇는 것)의 재료.

             [🔴 규칙이 뒤집혔다 — 묶어 굽기가 산수를 바꿨다(2026-08-16, 보드 실측 이식)]
               예전 이 파일은 "뒤 조각은 길어도 된다(60자)"고 적혀 있었다. 근거는
               '어차피 재생이 굽기를 앞지르니 조각을 늘려 봐야 총 시간만 는다' 였는데,
               그것은 **하나씩 차례로** 구울 때의 산수다. 지금은 뒤 조각을 **한 번에 묶어**
               굽는다(engines/tts_qwen.py 의 say_parts). 묶음 하나가 걸리는 시간은
               자기회귀라 **묶음 안에서 가장 긴 조각**이 정한다 — 60자 하나가 끼면
               나머지 일곱 개가 다 그 하나를 기다린다(보드 af_stream_sim 실측: 53자 하나가
               낀 배치 55.5초). 그래서 지금은 **모든 조각을 고르게 짧게** 만드는 것이 곧
               속도다. FIRST 14 / 나머지 24.

             [🔴 글자 수보다 '어디서 끊느냐'가 먼저다 — 사장 지적] 상한만 보고 아무
               띄어쓰기에서나 끊으면 "학습이 삼십 분 뒤에 끝날 / 예정입니다." 처럼 말이
               두 동강 난다. 사람은 **문장 끝 → 쉼표 → 어절** 순으로 쉰다. 그 순서로
               찾고, 상한 안에 쉬는 자리가 하나도 없으면 **자르지 않는다**(통째로 굽는
               편이 낫다). 상한 바로 뒤에 쉬는 자리가 있으면 거기까지는 봐준다.

             [🔴 토막을 만들지 않는다 — 실측이 시킨 규칙] Qwen 은 4자짜리도 1.7초가
               걸린다(굽는 시간이 글자 수에 비례하지 않는다). 예전 판은 첫 조각을 조인
               뒤 남은 꼬리를 그대로 조각으로 세워 '됩니다.'(4자) 같은 토막을 만들었다
               (조이는 코드가 '짧은 조각 붙이기'보다 뒤에 있어 아무도 다시 안 붙였다).
               지금은 꼬리가 MIN_CHARS 밑이면 자르지 않는다.

             [제약] 소수점·줄임표·따옴표를 마침표로 오인하면 문장이 엉뚱하게 갈린다.
               숫자 사이의 점과 연속된 점(…, ..)은 자르지 않는다.

REVISION HISTORY:
- 2026-08-16 Claude: 최초 작성 — 이어 굽기용 문장 나누기
- 2026-08-16 Claude: 보드(G:\\apix-voice2 ad_split2+ah_split3) 규칙 이식 — 묶어 굽기에 맞춰
  모든 조각에 상한(첫 14/뒤 24), 자를 자리를 '문장 끝 > 쉼표' 우선으로, 토막 금지
"""

from __future__ import annotations

import re

# 이보다 짧은 조각은 앞/뒤에 붙인다. [WHY 12인가] 12자면 굽는 데 1~2초, 소리는 1.8초쯤이다.
# 그보다 짧게 잘라 봐야 기다림은 그대로고 조각 수만 는다.
MIN_CHARS = 12
# 문장 나누기 단계의 상한. 여기서 걸린 것은 아래 CHUNK_MAX_CHARS 가 다시 조인다.
MAX_CHARS = 60
# 첫 조각 상한. [WHY 14인가] 첫 소리까지 걸리는 시간이 곧 체감이고, 첫 조각은 홀로 굽는다.
# 14자면 5초 안팎이다(보드 실측 — 그래프 켠 뒤).
FIRST_MAX_CHARS = 14
# 뒤 조각 상한. [WHY 24인가] 24자면 소리 3.5초쯤이고, 묶음 안에서 가장 긴 것이 24자면
# 그 묶음은 20초 안쪽에 끝난다(보드 ae_batch_lowmem 실측 표에서 고른 값).
CHUNK_MAX_CHARS = 24
# 첫 조각이 이보다 짧아지면 얻는 것이 없다. 그럴 바엔 안 자른다.
FIRST_MIN_CHARS = 8
# 뒤 조각을 쪼갤 때의 바닥. 이보다 앞에서 끊으면 낱말 하나가 뚝 떨어진다.
CUT_MIN_CHARS = 10

# 문장 끝. 뒤에 따옴표가 붙는 경우까지 한 덩어리로 본다.
_END = re.compile(r'(?<=[.!?。！？])["\'”’)\]]*\s+|\n+')
# 숫자 사이의 점(3.14)과 줄임표는 문장 끝이 아니다.
_NOT_END = re.compile(r'(\d)\.(\d)|\.{2,}|…')

# 자를 자리의 **우선순위**. 앞의 것일수록 사람이 쉬는 자리다.
_END_MARK = re.compile(r'[.!?。！？]["\'”’)\]]*\s+')
_COMMA_MARK = re.compile(r'[,，·]\s*')
_SPACE_MARK = re.compile(r'\s+')


def _best(rx: re.Pattern, head: str, limit: int, floor: int) -> int:
    """limit 안에서 rx 가 잡히는 **가장 뒤** 자리. 없으면 -1.
    [WHY 가장 뒤인가] 같은 등급이면 상한에 가까운 쪽이 '더 긴 한 마디'라 자연스럽다."""
    best = -1
    for m in rx.finditer(head[:limit + 1]):
        if m.end() >= floor:
            best = max(best, m.end())
    return best


def _natural_cut(head: str, limit: int, floor: int) -> int:
    """가장 자연스러운 자를 자리. 없으면 -1(= 자르지 않는다).

    [🔴 어절에서는 억지로 끊지 않는다] 상한 안에 문장 끝도 쉼표도 없는데 아무
      띄어쓰기에서나 끊으면 말이 두 동강 난다. 그럴 바엔 한 마디를 통째로 굽는다.
    [넓혀 보는 자리] 상한 바로 뒤에 문장 끝·쉼표가 있으면 거기까지는 봐준다 —
      조금 늦더라도 쉬는 자리에서 끊는 것이 낫다."""
    for rx in (_END_MARK, _COMMA_MARK):
        b = _best(rx, head, limit, floor)
        if b >= floor:
            return b
    for rx in (_END_MARK, _COMMA_MARK):
        b = _best(rx, head, min(len(head), limit * 2 + 4), floor)
        if b >= floor:
            return b
    return -1


def _cut_at(head: str, limit: int) -> int:
    """뒤 조각을 쪼갤 자리. 쉼표를 먼저 보고, 없으면 띄어쓰기. 없으면 -1.
    [WHY 여기서는 띄어쓰기까지 보나] 뒤 조각은 이미 문장 중간이라 '한 마디'가 아니다 —
      상한을 넘겨 두면 묶음 전체가 그 하나를 기다린다(파일 헤더의 배치 산수)."""
    best = -1
    for m in _COMMA_MARK.finditer(head[:limit]):
        best = max(best, m.end())
    if best >= CUT_MIN_CHARS:
        return best
    for m in _SPACE_MARK.finditer(head[:limit]):
        if m.end() >= CUT_MIN_CHARS:
            best = max(best, m.end())
    return best


def _chop(p: str, limit: int) -> list[str]:
    """한 조각을 limit 안으로 쪼갠다. 자를 자리가 없으면 통째로 돌려준다."""
    out: list[str] = []
    while len(p) > limit:
        cut = _cut_at(p, limit)
        if cut < CUT_MIN_CHARS:
            break                                   # 자를 자리가 없다 — 그냥 둔다
        tail = p[cut:].strip()
        if len(tail.replace(' ', '')) < MIN_CHARS:
            break                                   # 꼬리가 토막이 된다 — 자르지 않는다
        out.append(p[:cut].strip())
        p = tail
    out.append(p)
    return out


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

    # 아주 긴 문장을 1차로 눕힌다(아래 조이기가 상대할 크기로).
    rough: list[str] = []
    for p in merged:
        rough.extend(_chop(p, MAX_CHARS))

    def _restore(s: str) -> str:
        return re.sub(r'\x00(\d+)\x00', lambda m: holes[int(m.group(1))], s)

    # [🔴 되돌린 뒤에 조인다] 자리 표식(\x00N\x00)은 원문보다 글자 수가 달라 상한 계산을
    #   흔든다. 문장 나누기까지만 표식 위에서 하고, 조각 크기는 원문 위에서 잰다.
    rough = [_restore(s) for s in rough if s.strip()]
    if not rough:
        return []

    head, rest = rough[0], rough[1:]
    out: list[str] = []
    if len(head) > FIRST_MAX_CHARS:
        cut = _natural_cut(head, FIRST_MAX_CHARS, FIRST_MIN_CHARS)
        tail = head[cut:].strip() if cut > 0 else ''
        # [🔴 꼬리가 토막이면 자르지 않는다] 4자짜리를 따로 굽느니 첫 소리가 조금 늦는
        #   편이 낫다(4자 1.7초 — 소리 0.4초).
        if cut > 0 and tail and len(tail.replace(' ', '')) >= MIN_CHARS:
            out.append(head[:cut].strip())
            head = tail
    out.append(head)
    first_n = len(out)

    for p in rest:
        out.extend(_chop(p, CHUNK_MAX_CHARS))
    # 첫 조각이 잘렸다면 그 꼬리도 뒤 규칙으로 다시 나눈다 — 한 마디가 지나치게 길면
    # 묶음 전체가 그것을 기다린다.
    if first_n == 2:
        out = out[:1] + _chop(out[1], CHUNK_MAX_CHARS) + out[2:]

    return [s.strip() for s in out if s.strip()]
