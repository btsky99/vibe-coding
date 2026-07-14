# -*- coding: utf-8 -*-
"""
FILE: scripts/migrate_vault_consolidate.py
DESCRIPTION: 지식 창고 재점검 일회성 정리 마이그레이션 (2026-07-14).
             ① project_id 슬러그 분열 통합(vibe-coding → D--vibe-coding)
             ② 통합 후 발생하는 중복 노트 병합(최신 1건 유지, 나머지 archived)
             ③ 활성 노트 임베딩 구멍 백필(회상 v2 커버리지 복구)

REVISION HISTORY:
    2026-07-14 Claude: 재점검 결과 근본원인(슬러그 분열)이 고아 49건 + dedup 실패
      중복 + 임베딩 구멍의 공통 뿌리로 확인 → 3-in-1 정리. 비파괴(archived 플래그만,
      삭제 없음)라 zettel_backup_20260714.json으로 즉시 롤백 가능.

주의:
- [비파괴 원칙] 중복 제거는 DELETE가 아니라 archived=true. 링크/백링크 row가 살아있어
  그래프 무결성 유지 + 백업 없이도 UPDATE archived=false로 되돌릴 수 있음.
- [슬러그 표준] 서버/제텔 조회 표준은 project_id='D--vibe-coding' (경로 slug).
  'vibe-coding'(폴더명 slug)은 2026-05-02 이전 캡처 잔재 — 하이브 조회에서 영구 누락됨.
- [dedup 키 선택] file-role/project-map은 source_ref가 의미적 식별자라 그걸로 그룹핑.
  git-commit 노트는 source_ref가 타입 공유(git-commit:fix 등)라 식별 불가 → 정확한 title로 그룹핑.
"""

import argparse
import sys
import io
from pathlib import Path

if sys.stdout.encoding and sys.stdout.encoding.lower() not in ("utf-8", "utf8"):
    try:
        sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8', errors='replace')
        sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding='utf-8', errors='replace')
    except Exception:
        pass

_SCRIPT_DIR = Path(__file__).resolve().parent
_PROJECT_ROOT = _SCRIPT_DIR.parent
sys.path.insert(0, str(_PROJECT_ROOT / '.ai_monitor'))

from src.pg_store import query_rows, _sql_text
from src.pg_base import execute_raw

STD_PROJECT = 'D--vibe-coding'
LEGACY_PROJECT = 'vibe-coding'


def step1_consolidate_slug(dry: bool) -> int:
    """① 레거시 슬러그 → 표준 슬러그 통합."""
    rows = query_rows(
        f"SELECT count(*) c FROM zettel_notes WHERE project_id = {_sql_text(LEGACY_PROJECT)}"
    )
    n = rows[0]['c'] if rows else 0
    print(f"[①] 슬러그 통합 대상: {n}건 ({LEGACY_PROJECT} → {STD_PROJECT})")
    if n and not dry:
        execute_raw(
            f"UPDATE zettel_notes SET project_id = {_sql_text(STD_PROJECT)} "
            f"WHERE project_id = {_sql_text(LEGACY_PROJECT)};"
        )
        print(f"    ✓ {n}건 통합 완료")
    return n


def step2_dedup(dry: bool) -> int:
    """② 활성 permanent 중복 병합 — 최신 1건 유지, 나머지 archived."""
    archived_total = 0

    # 2a: source_ref 기반(file-role/project-map) 중복
    ref_dups = query_rows(
        "SELECT source_ref, project_id, count(*) c FROM zettel_notes "
        "WHERE archived = false AND (source_ref LIKE 'file-role:%' OR source_ref = 'project-map') "
        "GROUP BY source_ref, project_id HAVING count(*) > 1;"
    )
    # 2b: 정확한 title 기반(그 외 permanent) 중복 — source_ref로 못 잡는 커밋/설계 노트
    title_dups = query_rows(
        "SELECT title, project_id, count(*) c FROM zettel_notes "
        "WHERE archived = false AND note_type = 'permanent' "
        "AND (source_ref IS NULL OR (source_ref NOT LIKE 'file-role:%' AND source_ref <> 'project-map')) "
        "GROUP BY title, project_id HAVING count(*) > 1;"
    )

    print(f"[②] 중복 그룹: source_ref {len(ref_dups)}개 + title {len(title_dups)}개")

    def _archive_group(where_clause: str, label: str):
        nonlocal archived_total
        # 최신(updated_at, id) 1건만 남기고 나머지 archived
        members = query_rows(
            f"SELECT id FROM zettel_notes WHERE {where_clause} "
            f"ORDER BY updated_at DESC NULLS LAST, id DESC;"
        )
        losers = [m['id'] for m in members[1:]]
        if not losers:
            return
        if not dry:
            ids_sql = ",".join(_sql_text(i) for i in losers)
            execute_raw(
                f"UPDATE zettel_notes SET archived = true WHERE id IN ({ids_sql});"
            )
        archived_total += len(losers)

    for d in ref_dups:
        _archive_group(
            f"archived = false AND source_ref = {_sql_text(d['source_ref'])} "
            f"AND project_id = {_sql_text(d['project_id'])}",
            d['source_ref'],
        )
    for d in title_dups:
        _archive_group(
            f"archived = false AND note_type = 'permanent' "
            f"AND title = {_sql_text(d['title'])} AND project_id = {_sql_text(d['project_id'])} "
            f"AND (source_ref IS NULL OR (source_ref NOT LIKE 'file-role:%' AND source_ref <> 'project-map'))",
            d['title'][:40],
        )

    print(f"    {'(dry) ' if dry else '✓ '}중복 아카이브: {archived_total}건")
    return archived_total


def step3_backfill_embeddings(dry: bool) -> int:
    """③ 활성 노트 임베딩 백필 — 회상 v2 커버리지 복구."""
    from infra.embed_service import embed_floats, is_available
    from src.pg_vector_search import upsert_embedding, vector_available, ensure_vector_schema

    if not vector_available():
        ensure_vector_schema()
    if not vector_available():
        print("[③] pgvector 비활성 — 백필 건너뜀")
        return 0
    if not is_available():
        print("[③] 임베딩 모델 사용 불가(sentence-transformers 미설치?) — 백필 건너뜀")
        return 0

    pending = query_rows(
        "SELECT id, title || ' ' || LEFT(content, 400) AS text FROM zettel_notes "
        "WHERE archived = false AND embedding IS NULL;"
    )
    print(f"[③] 임베딩 구멍(활성): {len(pending)}건")
    if dry:
        return len(pending)

    done = 0
    for r in pending:
        vec = embed_floats(r['text'] or '')
        if vec and upsert_embedding('zettel_notes', r['id'], vec):
            done += 1
        if done and done % 20 == 0:
            print(f"    ... {done}/{len(pending)}")
    print(f"    ✓ 임베딩 채움: {done}/{len(pending)}건")
    return done


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--apply', action='store_true', help='실제 적용(미지정 시 dry-run)')
    ap.add_argument('--skip-embed', action='store_true', help='③ 임베딩 백필 생략')
    args = ap.parse_args()
    dry = not args.apply

    print("=" * 56)
    print(f"지식 창고 정리 마이그레이션 — {'DRY-RUN (미적용)' if dry else 'APPLY (실적용)'}")
    print("=" * 56)

    step1_consolidate_slug(dry)
    step2_dedup(dry)
    if not args.skip_embed:
        step3_backfill_embeddings(dry)

    print("=" * 56)
    print("완료." + ("  실제 적용하려면 --apply 붙여서 재실행." if dry else ""))


if __name__ == '__main__':
    main()
