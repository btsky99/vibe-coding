#!/usr/bin/env python3
"""
FILE: scripts/recall_quality.py
DESCRIPTION: 회상 v2의 **품질**을 측정한다. 커버리지·건수가 아니라 "관련된 걸 찾고
             무관한 건 거르는가"를 잰다. 임계값(min_similarity) 조정의 유일한 근거.

             [🔴 왜 필요한가 — 2026-08-08]
             heal_report는 "임베딩 커버리지 100% 🟢"를 띄우고 있었지만, 실제로는
             아무 질문에나 무관한 커밋 메시지가 딸려 나오는 상태였다. 커버리지는
             품질을 재지 못한다. 관측이 거짓이면 판단도 거짓이 된다.

             측정 방식: 프로젝트와 명백히 관련된 질의 / 명백히 무관한 질의를 각각 던져
             최고 유사도를 비교한다. 관련 최저 > 무관 최고 여야 임계값 하나로 갈라진다.

사용:
  python scripts/recall_quality.py              # 현재 임계값으로 판정
  python scripts/recall_quality.py --sweep      # 임계값 후보별 통과/차단 표

REVISION HISTORY:
- 2026-08-08 Claude: 최초 작성 — 임계값 0.45→0.62 상향의 근거 도구.
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / '.ai_monitor'))

from infra.embed_service import embed_floats  # noqa: E402
from src.pg_vector_search import _TABLES, ensure_vector_schema, vector_search  # noqa: E402

# [주의] 이 목록이 곧 측정의 정의다. 프로젝트가 다루는 주제가 바뀌면 함께 갱신할 것.
#   관련 질의는 '실제로 겪은 문제'를 쓴다 — 회상이 도와야 할 바로 그 상황이기 때문.
RELATED = [
    'RustDesk 설정이 두 곳에 있어서 한쪽만 고치면 실패',
    '업데이트 진행률 바가 뒤로 간다',
    'PyInstaller 빌드에서 모듈이 누락된다',
    '설치본에서 패널이 비어 보인다',
    'PostgreSQL 포트가 어긋나 연결이 안 된다',
]
# 무관 질의 = 프로젝트와 아무 접점이 없어야 한다. 여기서 걸리는 것이 곧 노이즈다.
UNRELATED = [
    '오늘 점심 뭐 먹지',
    '고양이가 귀엽다',
    '주말 날씨 어때',
    '영화 추천해줘',
]


def best_sim(query: str, min_sim: float = 0.0) -> tuple[float, str]:
    # [🔴 e5 비대칭] 검색어는 'query:' 쪽으로 임베딩해야 저장분(passage:)과 짝이 맞는다.
    #   섞으면 숫자는 그럴듯한데 순위만 조용히 나빠져 이 도구가 거짓 판정을 낸다.
    vec = embed_floats(query, kind='query')
    if not vec:
        return 0.0, '(임베딩 실패)'
    best, label = 0.0, ''
    for table in _TABLES:
        try:
            rows = vector_search(table, vec, limit=3, min_similarity=min_sim)
        except Exception:
            continue
        for r in rows or []:
            s = float(r.get('sim') or 0)
            if s > best:
                best = s
                label = (r.get('title') or r.get('description')
                         or r.get('error_text') or '')[:46]
    return best, label


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument('--sweep', action='store_true', help='임계값 후보별 표')
    args = ap.parse_args()

    if not ensure_vector_schema():
        print('[!] vector 확장 없음 — 회상 v2 비활성')
        return 1

    print('회상 품질 측정 — 관련은 찾고 무관은 걸러야 한다\n')

    rel = [(q, *best_sim(q)) for q in RELATED]
    unrel = [(q, *best_sim(q)) for q in UNRELATED]

    print('[관련 질의]')
    for q, s, lab in rel:
        print(f'  {s:.3f}  {q[:34]:34s} → {lab}')
    print('\n[무관 질의]')
    for q, s, lab in unrel:
        print(f'  {s:.3f}  {q[:34]:34s} → {lab}')

    rel_lo = min(s for _, s, _ in rel)
    unrel_hi = max(s for _, s, _ in unrel)
    print(f'\n관련 최저 {rel_lo:.3f} / 무관 최고 {unrel_hi:.3f} / 간격 {rel_lo - unrel_hi:+.3f}')

    if args.sweep:
        print('\n[임계값 후보]')
        print(f'  {"임계":>6} | {"관련통과":>8} | {"무관통과":>8} | 판정')
        print('  ' + '-' * 44)
        for th in (0.45, 0.50, 0.55, 0.58, 0.60, 0.62, 0.65, 0.70):
            rp = sum(1 for _, s, _ in rel if s >= th)
            up = sum(1 for _, s, _ in unrel if s >= th)
            if up == 0 and rp > 0:
                verdict = '노이즈 0 — 권장'
            elif up == 0:
                verdict = '노이즈 0 (관련도 전멸)'
            else:
                verdict = f'노이즈 {up}건 통과'
            print(f'  {th:>6.2f} | {rp:>4}/{len(rel):<3} | {up:>4}/{len(unrel):<3} | {verdict}')
        print('\n  → 무관 통과 0이면서 관련 통과가 가장 많은 값을 고른다.')
        print('    노이즈 1건도 매 프롬프트마다 반복되면 회상 신뢰를 무너뜨린다.')

    # 현재 코드 기본값으로 실제 동작 확인
    print('\n[현재 기본 임계값으로 실제 호출]')
    noisy = 0
    for q, _, _ in unrel:
        s, lab = best_sim(q, min_sim=0.62)
        if s > 0:
            noisy += 1
            print(f'  통과됨 {s:.3f}  {q} → {lab}')
    print(f'  무관 질의 {len(unrel)}건 중 {noisy}건이 회상됨'
          + ('  ← 노이즈 없음' if noisy == 0 else '  ← 임계값 재검토 필요'))
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
