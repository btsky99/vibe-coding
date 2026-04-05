"""
FILE: scripts/zettel_sync.py
DESCRIPTION: Hive Zettelkasten ↔ Obsidian Vault 동기화 스크립트.
             PostgreSQL의 zettel_notes를 마크다운 파일로 export하여
             Obsidian에서 그래프 뷰 + 편집이 가능하도록 한다.
REVISION HISTORY:
    2026-04-05 — 초기 구현 (PG → Obsidian 단방향 동기화)
"""

import argparse
import json
import os
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

# 프로젝트 루트에서 import 가능하도록 경로 추가
_SCRIPT_DIR = Path(__file__).resolve().parent
_PROJECT_ROOT = _SCRIPT_DIR.parent
sys.path.insert(0, str(_PROJECT_ROOT / '.ai_monitor'))

from src.pg_store import ensure_schema, query_rows
from src.zettelkasten import list_notes, get_links, get_backlinks


# ── 기본 설정 ──────────────────────────────────────────────────────────────

DEFAULT_VAULT_DIR = _PROJECT_ROOT / '.zettel-vault'
DATA_DIR = _PROJECT_ROOT / '.ai_monitor' / 'data'


def _format_frontmatter(note: dict) -> str:
    """Obsidian 호환 YAML 프론트매터 생성."""
    tags_list = note.get('tags', [])
    if isinstance(tags_list, str):
        try:
            tags_list = json.loads(tags_list)
        except (json.JSONDecodeError, TypeError):
            tags_list = []

    lines = [
        '---',
        f'zettel_id: "{note["id"]}"',
        f'title: "{_escape_yaml(note.get("title", ""))}"',
        f'note_type: {note.get("note_type", "fleeting")}',
        f'author: {note.get("author", "unknown")}',
        f'project: {note.get("project", "")}',
        'tags: [{}]'.format(', '.join('"{}"'.format(t) for t in tags_list)),
        f'source_ref: "{_escape_yaml(note.get("source_ref", ""))}"',
        f'access_count: {note.get("access_count", 0)}',
        f'created: {_format_ts(note.get("created_at", ""))}',
        f'updated: {_format_ts(note.get("updated_at", ""))}',
    ]
    if note.get('last_rescued_at'):
        lines.append(f'last_rescued: {_format_ts(note["last_rescued_at"])}')
    if note.get('archived'):
        lines.append('archived: true')
    lines.append('---')
    return '\n'.join(lines)


def _format_links_section(note_id: str) -> str:
    """Obsidian 위키링크 형식의 연결 섹션 생성."""
    links = get_links(note_id)
    backlinks = get_backlinks(note_id)

    if not links and not backlinks:
        return ''

    sections = []
    if links:
        sections.append('\n## 연결된 노트')
        for link in links:
            link_type_label = {
                'relates_to': '관련',
                'extends': '확장',
                'contradicts': '반박',
                'implements': '구현',
            }.get(link.get('link_type', ''), link.get('link_type', ''))
            sections.append(f'- [[{link["id"]}]] {link.get("title", "")} ({link_type_label})')

    if backlinks:
        sections.append('\n## 백링크')
        for bl in backlinks:
            bl_type_label = {
                'relates_to': '관련',
                'extends': '확장됨',
                'contradicts': '반박됨',
                'implements': '구현됨',
            }.get(bl.get('link_type', ''), bl.get('link_type', ''))
            sections.append(f'- [[{bl["id"]}]] {bl.get("title", "")} ({bl_type_label})')

    return '\n'.join(sections)


def _escape_yaml(s: str) -> str:
    """YAML 문자열 이스케이프."""
    return s.replace('"', '\\"').replace('\n', ' ')


def _format_ts(ts) -> str:
    """타임스탬프 포맷."""
    if not ts:
        return ''
    if hasattr(ts, 'isoformat'):
        return ts.strftime('%Y-%m-%d %H:%M')
    return str(ts)[:16]


def _safe_filename(note_id: str, title: str) -> str:
    """Obsidian에서 사용 가능한 안전한 파일명 생성. 경로 트래버설 방어."""
    import re
    # 위험 문자 제거: .., /, \, 제어문자
    safe = re.sub(r'[\\/:*?"<>|\x00-\x1f]', '', note_id)
    safe = safe.replace('..', '')
    return safe or 'unnamed'


def export_to_vault(vault_dir: Path, project: str = '', include_archived: bool = False):
    """PostgreSQL → Obsidian Vault 전체 동기화."""
    ensure_schema(DATA_DIR)
    vault_dir.mkdir(parents=True, exist_ok=True)

    # 노트 유형별 폴더 생성
    for subdir in ('fleeting', 'literature', 'permanent', '_archived'):
        (vault_dir / subdir).mkdir(exist_ok=True)

    # 전체 노트 조회
    notes = list_notes(
        project=project,
        include_archived=include_archived,
        limit=10000,
    )

    exported = 0
    for note in notes:
        # 폴더 결정
        if note.get('archived'):
            folder = vault_dir / '_archived'
        else:
            note_type = note.get('note_type', 'fleeting')
            folder = vault_dir / note_type if note_type in ('fleeting', 'literature', 'permanent') else vault_dir / 'fleeting'

        # 마크다운 생성
        frontmatter = _format_frontmatter(note)
        content = note.get('content', '')
        links_section = _format_links_section(note['id'])

        md_content = f"{frontmatter}\n\n# {note.get('title', '')}\n\n{content}"
        if links_section:
            md_content += f"\n\n{links_section}"
        md_content += '\n'

        # 파일 쓰기 (경로 트래버설 방어)
        filename = _safe_filename(note['id'], note.get('title', ''))
        filepath = folder / f"{filename}.md"
        if not filepath.resolve().is_relative_to(vault_dir.resolve()):
            print(f'[zettel_sync] 경로 인젝션 탐지, 건너뜀: {note["id"]}')
            continue
        filepath.write_text(md_content, encoding='utf-8')
        exported += 1

    # 인덱스 파일 생성 (MOC — Map of Content)
    _generate_moc(vault_dir, notes)

    print(f'[zettel_sync] {exported}개 노트를 {vault_dir}에 동기화 완료')
    return exported


def _generate_moc(vault_dir: Path, notes: list):
    """MOC(Map of Content) 인덱스 파일 생성."""
    lines = [
        '---',
        'title: "Hive Zettelkasten Index"',
        f'updated: {datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M")}',
        '---',
        '',
        '# Hive Zettelkasten',
        '',
        f'총 {len(notes)}개 노트',
        '',
    ]

    # 유형별 그룹핑
    by_type = {}
    for n in notes:
        t = n.get('note_type', 'fleeting')
        by_type.setdefault(t, []).append(n)

    type_labels = {'permanent': '영구 노트', 'literature': '문헌 노트', 'fleeting': '일시 노트'}
    for note_type in ('permanent', 'literature', 'fleeting'):
        group = by_type.get(note_type, [])
        if not group:
            continue
        lines.append(f'## {type_labels.get(note_type, note_type)} ({len(group)})')
        lines.append('')
        for n in group[:50]:  # 유형당 최대 50개
            lines.append(f'- [[{n["id"]}]] {n.get("title", "")}')
        if len(group) > 50:
            lines.append(f'- ... 외 {len(group) - 50}개')
        lines.append('')

    (vault_dir / 'INDEX.md').write_text('\n'.join(lines), encoding='utf-8')


def watch_and_sync(vault_dir: Path, project: str = '', interval: int = 60):
    """주기적 동기화 루프. 데몬 모드로 실행."""
    print(f'[zettel_sync] 감시 모드 시작 — {interval}초 간격, vault={vault_dir}')
    while True:
        try:
            export_to_vault(vault_dir, project=project)
        except Exception as e:
            print(f'[zettel_sync] 동기화 오류: {e}')
        time.sleep(interval)


def main():
    parser = argparse.ArgumentParser(description='Hive Zettelkasten ↔ Obsidian Vault 동기화')
    parser.add_argument('--vault', type=str, default=str(DEFAULT_VAULT_DIR),
                        help='Obsidian vault 경로 (기본: .zettel-vault/)')
    parser.add_argument('--project', type=str, default='',
                        help='프로젝트 ID 필터')
    parser.add_argument('--archived', action='store_true',
                        help='아카이브된 노트도 포함')
    parser.add_argument('--watch', action='store_true',
                        help='감시 모드 (주기적 동기화)')
    parser.add_argument('--interval', type=int, default=60,
                        help='감시 간격 (초, 기본 60)')
    args = parser.parse_args()

    vault_path = Path(args.vault)

    if args.watch:
        watch_and_sync(vault_path, project=args.project, interval=args.interval)
    else:
        export_to_vault(vault_path, project=args.project, include_archived=args.archived)


if __name__ == '__main__':
    main()
