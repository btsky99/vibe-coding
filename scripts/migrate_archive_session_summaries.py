# -*- coding: utf-8 -*-
"""
FILE: scripts/migrate_archive_session_summaries.py
DESCRIPTION: 일회성 마이그레이션 — 이미 permanent로 오승격된 세션요약 노트를 archived=true로 내린다.
             영구지식/Obsidian/GDrive에서 제외되지만 DB에는 남아 회상/검색에 계속 쓰이고, 되돌림 가능.

REVISION HISTORY:
- 2026-07-12 Claude: 신규. 세션요약이 auto_promote 허브형 조건에 걸려 영구지식 65%(817건)를 점령한
  사고 청소. 승격 차단(pg_memory.py)과 짝. --dry로 대상만 미리보기.
"""
from __future__ import annotations

import sys
from pathlib import Path

# 프로젝트 경로 — 절대경로 하드코딩 금지(이식성). 이 스크립트 위치 기준으로 해석.
_SCRIPT_DIR = Path(__file__).resolve().parent
_MONITOR_DIR = _SCRIPT_DIR.parent / '.ai_monitor'
sys.path.insert(0, str(_MONITOR_DIR))
sys.path.insert(0, str(_MONITOR_DIR / 'src'))

from src.pg_store import query_rows, execute  # noqa: E402

# [불변식] 세션요약 판별 = source_ref 또는 제목 접두. run_zettel_refine/export_to_vault/
#   auto_promote 배제와 동일 기준 — 세 곳이 어긋나면 일부만 걸러지므로 항상 함께 유지.
_WHERE_SESSION = (
    "(source_ref = 'session-summary' OR title LIKE '세션 요약%')"
)


def preview() -> int:
    """아카이브 대상(아직 archived 아닌 세션요약) 건수 반환 + 표본 출력."""
    rows = query_rows(
        f"SELECT count(*) AS c FROM zettel_notes "
        f"WHERE {_WHERE_SESSION} AND archived IS NOT TRUE;"
    )
    n = int(rows[0]['c']) if rows else 0
    sample = query_rows(
        f"SELECT title, note_type, created_at FROM zettel_notes "
        f"WHERE {_WHERE_SESSION} AND archived IS NOT TRUE "
        f"ORDER BY created_at DESC LIMIT 5;"
    )
    print(f"[migrate] 아카이브 대상 세션요약: {n}건")
    for r in sample:
        print(f"  - [{r.get('note_type')}] {str(r.get('title'))[:50]} ({r.get('created_at')})")
    return n


def apply_archive() -> int:
    """대상을 archived=true로 갱신. 반환: 사전 COUNT(실제 갱신 추정)."""
    n = preview()
    if n == 0:
        print("[migrate] 대상 없음 — 종료.")
        return 0
    execute(
        f"UPDATE zettel_notes SET archived = TRUE, updated_at = NOW() "
        f"WHERE {_WHERE_SESSION} AND archived IS NOT TRUE;"
    )
    print(f"[migrate] {n}건 아카이브 완료. "
          f"되돌림: UPDATE zettel_notes SET archived=FALSE WHERE {_WHERE_SESSION};")
    return n


if __name__ == '__main__':
    dry = '--dry' in sys.argv
    if dry:
        print("[migrate] --dry: 대상 미리보기만 (변경 없음)")
        preview()
    else:
        apply_archive()
