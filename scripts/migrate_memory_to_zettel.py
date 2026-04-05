"""
FILE: scripts/migrate_memory_to_zettel.py
DESCRIPTION: 기존 hive_memory 데이터를 zettel_notes로 마이그레이션.
             원본 데이터는 보존하고 복사 방식으로 이전.
REVISION HISTORY:
    2026-04-05 — 초기 구현
"""

import sys
from pathlib import Path

_SCRIPT_DIR = Path(__file__).resolve().parent
_PROJECT_ROOT = _SCRIPT_DIR.parent
sys.path.insert(0, str(_PROJECT_ROOT / '.ai_monitor'))

from src.pg_store import ensure_schema, query_rows, execute, _sql_text
from src.zettelkasten import create_note, add_link

DATA_DIR = _PROJECT_ROOT / '.ai_monitor' / 'data'


def migrate():
    """hive_memory → zettel_notes 마이그레이션."""
    ensure_schema(DATA_DIR)

    # 이미 마이그레이션 했는지 확인
    check = query_rows(
        "SELECT COUNT(*) AS cnt FROM zettel_notes WHERE source_ref LIKE 'migrated:hive_memory:%';"
    )
    if check and check[0]['cnt'] > 0:
        print(f'[마이그레이션] 이미 {check[0]["cnt"]}개 마이그레이션됨. 중복 방지를 위해 건너뜁니다.')
        return

    # 기존 메모리 전체 조회
    memories = query_rows(
        "SELECT key, title, content, tags::text AS tags_text, author, project, "
        "created_at, updated_at FROM hive_memory ORDER BY created_at ASC;"
    )
    if not memories:
        print('[마이그레이션] 마이그레이션할 hive_memory 데이터 없음.')
        return

    print(f'[마이그레이션] {len(memories)}개 hive_memory 항목 발견. 변환 시작...')

    migrated = 0
    id_map = {}  # old key → new zettel_id 매핑

    for i, mem in enumerate(memories, 1):
        import json
        try:
            tags = json.loads(mem.get('tags_text', '[]'))
        except (json.JSONDecodeError, TypeError):
            tags = []

        note = create_note(
            title=mem.get('title', '') or mem.get('key', f'memo-{i}'),
            content=mem.get('content', ''),
            note_type='literature',  # 기존 메모리는 문헌 노트로 분류
            author=mem.get('author', 'unknown'),
            project=mem.get('project', ''),
            tags=tags,
            source_ref=f"migrated:hive_memory:{mem.get('key', '')}",
        )
        if note:
            id_map[mem['key']] = note['id']
            migrated += 1
            if migrated % 10 == 0:
                print(f'  ... {migrated}/{len(memories)} 완료')

    # 같은 프로젝트 내 노트끼리 기본 링크 생성
    by_project = {}
    for key, zid in id_map.items():
        mem = next((m for m in memories if m['key'] == key), None)
        if mem:
            proj = mem.get('project', '')
            by_project.setdefault(proj, []).append(zid)

    link_count = 0
    for proj, ids in by_project.items():
        if len(ids) < 2:
            continue
        # 시간순 인접 노트끼리 연결
        for j in range(len(ids) - 1):
            add_link(ids[j], ids[j + 1], link_type='relates_to', created_by='migration')
            link_count += 1

    print(f'[마이그레이션] 완료: {migrated}개 노트 생성, {link_count}개 링크 생성')
    print(f'[마이그레이션] ID 매핑: {len(id_map)}개')
    return id_map


if __name__ == '__main__':
    migrate()
