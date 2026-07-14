# -*- coding: utf-8 -*-
"""
FILE: scripts/migrate_vault_consolidate.py
DESCRIPTION: 지식 창고 재점검 일회성 정리 마이그레이션 (2026-07-14).
             ① project_id 슬러그 분열 통합(vibe-coding → D--vibe-coding)
             ② 통합 후 발생하는 중복 노트 병합(최신 1건 유지, 나머지 archived)
             ③ 활성 노트 임베딩 구멍 백필(회상 v2 커버리지 복구)

REVISION HISTORY:
    2026-07-14 Claude(2): step2 dedup을 수렴 루프로 수정 — 슬러그 병합이 (title,project_id)
      키를 재편해 단일 패스가 중복 10그룹 놓치던 버그(재점검 2회차 발견). dry는 1패스 고정.
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

    def _archive_group(where_clause: str):
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

    # [WHY 수렴 루프] step1 슬러그 병합으로 (title, project_id) 키가 바뀌면
    #   병합 前 스냅샷으로 GROUP BY한 중복 그룹이 재편됨(예: vibe-coding 1건 + D-- 1건이
    #   병합 後 D-- 2건으로 뭉침). 단일 패스는 재편된 그룹을 못 봐서 중복이 남는다
    #   (실측: 1패스 후 10그룹 잔존 → 2패스에서 청산). dry-run에서는 실제 archive를
    #   안 하니 무한 재검출 → 1회만 스캔.
    passes = 0
    while True:
        passes += 1
        ref_dups = query_rows(
            "SELECT source_ref, project_id FROM zettel_notes "
            "WHERE archived = false AND (source_ref LIKE 'file-role:%' OR source_ref = 'project-map') "
            "GROUP BY source_ref, project_id HAVING count(*) > 1;"
        )
        title_dups = query_rows(
            "SELECT title, project_id FROM zettel_notes "
            "WHERE archived = false AND note_type = 'permanent' "
            "AND (source_ref IS NULL OR (source_ref NOT LIKE 'file-role:%' AND source_ref <> 'project-map')) "
            "GROUP BY title, project_id HAVING count(*) > 1;"
        )
        if passes == 1:
            print(f"[②] 중복 그룹: source_ref {len(ref_dups)}개 + title {len(title_dups)}개")
        if not ref_dups and not title_dups:
            break
        for d in ref_dups:
            _archive_group(
                f"archived = false AND source_ref = {_sql_text(d['source_ref'])} "
                f"AND project_id = {_sql_text(d['project_id'])}"
            )
        for d in title_dups:
            _archive_group(
                f"archived = false AND note_type = 'permanent' "
                f"AND title = {_sql_text(d['title'])} AND project_id = {_sql_text(d['project_id'])} "
                f"AND (source_ref IS NULL OR (source_ref NOT LIKE 'file-role:%' AND source_ref <> 'project-map'))"
            )
        if dry:
            break  # dry는 archive 미적용 → 같은 그룹 무한 재검출 방지

    print(f"    {'(dry) ' if dry else '✓ '}중복 아카이브: {archived_total}건"
          + (f" ({passes}패스 수렴)" if not dry and passes > 1 else ""))
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


def step2b_sync_vault(dry: bool) -> int:
    """②b PG 아카이브 상태를 vault에 반영 — 부활 방지의 핵심.

    [과거사고/근본원인] PG에서만 archived=true로 바꾸면, 활성 폴더(작업기록/영구지식)에
      남은 stale .md(frontmatter archived:false)를 백그라운드 zettel_sync 데몬의
      import_from_vault가 다시 읽어 PG를 archived=false로 되살린다(재점검 2회차 실측:
      21:05 부활 이벤트). export_to_vault(include_archived=False)의 _cleanup_stale_note_files가
      활성 export 집합에서 빠진 아카이브 노트의 .md를 삭제 → 부활 소스 제거 → 아카이브 고착.
    [불변식] project_id 스코프 export만 — GDrive 공유 볼트에서 타 프로젝트 파일 오삭제 방지.
    """
    sys.path.insert(0, str(_SCRIPT_DIR))
    from zettel_sync import export_to_vault, DEFAULT_VAULT_DIR
    if dry:
        print(f"[②b] (dry) vault 동기화 생략 — 실적용 시 {DEFAULT_VAULT_DIR} 정리")
        return 0
    export_to_vault(DEFAULT_VAULT_DIR, project_id=STD_PROJECT, include_archived=False)
    print(f"[②b] ✓ vault 동기화 완료 — stale .md 제거로 아카이브 고착")
    return 1


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--apply', action='store_true', help='실제 적용(미지정 시 dry-run)')
    ap.add_argument('--skip-embed', action='store_true', help='③ 임베딩 백필 생략')
    ap.add_argument('--skip-vault', action='store_true', help='②b vault 동기화 생략')
    args = ap.parse_args()
    dry = not args.apply

    print("=" * 56)
    print(f"지식 창고 정리 마이그레이션 — {'DRY-RUN (미적용)' if dry else 'APPLY (실적용)'}")
    print("=" * 56)

    step1_consolidate_slug(dry)
    step2_dedup(dry)
    if not args.skip_vault:
        step2b_sync_vault(dry)
    if not args.skip_embed:
        step3_backfill_embeddings(dry)

    print("=" * 56)
    print("완료." + ("  실제 적용하려면 --apply 붙여서 재실행." if dry else ""))


if __name__ == '__main__':
    main()
