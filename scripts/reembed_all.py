#!/usr/bin/env python3
"""
FILE: scripts/reembed_all.py
DESCRIPTION: 회상 v2의 전체 임베딩을 현재 모델/라이브러리 기준으로 다시 생성한다.
             임베딩 라이브러리가 계산 방식을 바꾸면 저장된 벡터와 질의 벡터의 좌표계가
             어긋나 회상이 조용히 무의미해진다 — 그때 이 스크립트로 복구한다.

             [🔴 2026-08-07 사고] fastembed 업그레이드로 pooling이 CLS→mean으로 바뀌면서
             저장된 3878건이 전부 무효화됐다. 같은 텍스트를 재임베딩해 저장분과 비교하니
             자기 자신과의 유사도가 0.066까지 떨어졌다(정상이면 1.0).
             모델 '이름'은 그대로였기 때문에 ensure_vector_schema의 불일치 감지가 못 잡았다.
             → 이름뿐 아니라 **라이브러리 버전**까지 지문에 넣어야 재발을 잡는다(--stamp).

사용:
  python scripts/reembed_all.py --check          # 좌표계 어긋남 진단만
  python scripts/reembed_all.py --run            # 전체 재임베딩
  python scripts/reembed_all.py --run --table zettel_notes

REVISION HISTORY:
- 2026-08-07 Claude: 최초 작성 — fastembed pooling 변경 사고 복구용.
"""
from __future__ import annotations

import argparse
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / '.ai_monitor'))

from infra.embed_service import EMBED_MODEL_NAME, embed_floats  # noqa: E402
from src.pg_base import execute_raw, query_rows, _sql_text, _now_iso  # noqa: E402
from src.pg_vector_search import _TABLES, _vec_literal, ensure_vector_schema  # noqa: E402


def _lib_version() -> str:
    """임베딩 라이브러리 버전 — 좌표계 지문의 일부."""
    try:
        import fastembed
        return f"fastembed {getattr(fastembed, '__version__', '?')}"
    except Exception:
        return 'unknown'


def check() -> bool:
    """저장된 임베딩이 현재 계산 방식과 같은 좌표계인지 본다. True면 정상.

    [WHY 자기 자신과 비교하나] 같은 텍스트를 다시 임베딩하면 같은 벡터가 나와야 한다.
      안 나오면 계산 방식이 바뀐 것이고, 그 상태로는 어떤 검색 결과도 신뢰할 수 없다.
      검색 품질을 보는 것보다 훨씬 빠르고 명확한 진단이다.
    """
    print(f'모델: {EMBED_MODEL_NAME}')
    print(f'라이브러리: {_lib_version()}\n')
    print('저장분 vs 재계산 — 같은 텍스트끼리 (정상이면 1.000)\n')

    worst = 1.0
    checked = 0
    for table, cfg in _TABLES.items():
        pk, text_expr = cfg['pk'], cfg['text']
        rows = query_rows(
            f"SELECT {pk} AS pk, ({text_expr}) AS body FROM {table} "
            f"WHERE embedding IS NOT NULL AND length(btrim(({text_expr}))) BETWEEN 20 AND 300 "
            f"LIMIT 3"
        )
        for r in rows or []:
            vec = embed_floats(r['body'])
            if not vec:
                continue
            got = query_rows(
                f"SELECT (1-(embedding <=> {_vec_literal(vec)})) AS sim "
                f"FROM {table} WHERE {pk} = {_sql_text(str(r['pk']))}"
            )
            if got:
                sim = float(got[0]['sim'])
                worst = min(worst, sim)
                checked += 1
                print(f"  {sim:.4f}  {'OK  ' if sim > 0.98 else '어긋남'}  [{table}]")

    print()
    if checked == 0:
        print('→ 비교할 표본이 없다. 임베딩이 비어 있는지 확인하라.')
        return False
    if worst > 0.98:
        print(f'→ 좌표계 일치(최저 {worst:.4f}). 재임베딩 불필요.')
        return True
    print(f'→ 좌표계 어긋남(최저 {worst:.4f}). --run 으로 재임베딩이 필요하다.')
    return False


def reembed(only_table: str = '', batch: int = 200) -> None:
    """전 테이블 재임베딩. 진행률을 표시하며, 실패한 행은 건너뛰고 계속한다.

    [불변식] 한 행씩 UPDATE 한다. 중간에 끊겨도 이미 갱신된 행은 유효하므로
      재실행하면 이어서 진행된다(--run은 멱등하다).
    """
    tables = [only_table] if only_table else list(_TABLES.keys())
    total_done = total_fail = 0

    for table in tables:
        cfg = _TABLES.get(table)
        if not cfg:
            print(f'[!] 알 수 없는 테이블: {table}')
            continue
        pk, text_expr = cfg['pk'], cfg['text']

        cnt = query_rows(f"SELECT count(*) AS n FROM {table}")
        n_total = cnt[0]['n'] if cnt else 0
        print(f'\n[{table}] {n_total}건')

        done = fail = 0
        offset = 0
        t0 = time.time()
        while True:
            rows = query_rows(
                f"SELECT {pk} AS pk, ({text_expr}) AS body FROM {table} "
                f"ORDER BY {pk} LIMIT {batch} OFFSET {offset}"
            )
            if not rows:
                break
            for r in rows:
                body = (r.get('body') or '').strip()
                if not body:
                    # [WHY 비우나] 빈 텍스트를 placeholder로 임베딩하면 그 벡터가
                    #   아무 질의와도 중간 정도로 매칭돼 회상 노이즈가 된다.
                    #   차라리 NULL로 두어 검색에서 빠지게 한다.
                    execute_raw(
                        f"UPDATE {table} SET embedding = NULL "
                        f"WHERE {pk} = {_sql_text(str(r['pk']))}"
                    )
                    continue
                vec = embed_floats(body)
                if not vec:
                    fail += 1
                    continue
                ok = execute_raw(
                    f"UPDATE {table} SET embedding = {_vec_literal(vec)}::vector "
                    f"WHERE {pk} = {_sql_text(str(r['pk']))}"
                )
                done += 1 if ok else 0
                fail += 0 if ok else 1
            offset += batch
            el = time.time() - t0
            rate = done / el if el > 0 else 0
            print(f'  {min(offset, n_total)}/{n_total}  ({rate:.0f}건/초)', flush=True)

        print(f'  완료: {done}건 갱신 / {fail}건 실패')
        total_done += done
        total_fail += fail

    # 좌표계 지문 기록 — 다음 실행에서 변경을 감지할 수 있게.
    stamp = f'{{"model": "{EMBED_MODEL_NAME}", "lib": "{_lib_version()}"}}'
    execute_raw(
        "INSERT INTO hive_state (state_key, payload, updated_at) VALUES ('embed_fingerprint', "
        + _sql_text(stamp) + "::jsonb, " + _sql_text(_now_iso()) + ") "
        "ON CONFLICT (state_key) DO UPDATE SET payload = EXCLUDED.payload, "
        "updated_at = EXCLUDED.updated_at;"
    )
    print(f'\n총 {total_done}건 갱신 / {total_fail}건 실패')
    print(f'좌표계 지문 기록: {stamp}')


def main() -> int:
    ap = argparse.ArgumentParser(description='회상 v2 임베딩 재생성')
    ap.add_argument('--check', action='store_true', help='좌표계 진단만')
    ap.add_argument('--run', action='store_true', help='재임베딩 실행')
    ap.add_argument('--table', default='', help='특정 테이블만')
    args = ap.parse_args()

    if not ensure_vector_schema():
        print('[!] vector 확장이 없다. 회상 v2 비활성 상태.')
        return 1

    if args.run:
        reembed(args.table)
        print('\n재검증:')
        return 0 if check() else 2
    return 0 if check() else 2


if __name__ == '__main__':
    raise SystemExit(main())
