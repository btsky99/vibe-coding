"""
FILE: scripts/zettel_sync.py
DESCRIPTION: Hive Zettelkasten ↔ Obsidian Vault 동기화 스크립트.
             PostgreSQL의 zettel_notes를 마크다운 파일로 export하여
             Obsidian에서 그래프 뷰 + 편집이 가능하도록 한다.
REVISION HISTORY:
    2026-04-06 — Obsidian → PG 역동기화 (import_from_vault) 추가
    2026-04-05 — 초기 구현 (PG → Obsidian 단방향 동기화)
"""

import argparse
import json
import os
import re
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

# 프로젝트 루트에서 import 가능하도록 경로 추가
_SCRIPT_DIR = Path(__file__).resolve().parent
_PROJECT_ROOT = _SCRIPT_DIR.parent
sys.path.insert(0, str(_PROJECT_ROOT / '.ai_monitor'))

from src.pg_store import ensure_schema, query_rows, _sql_text, execute
from src.zettelkasten import (
    list_notes, get_links, get_backlinks,
    create_note, update_note, _get_note_raw,
)


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
    """Obsidian 위키링크 형식의 연결 섹션 생성. (단일 노트용 — 소량 호출 시 사용)"""
    links = get_links(note_id)
    backlinks = get_backlinks(note_id)
    return _render_links_section(links, backlinks)


def _load_all_links(note_ids: list[str]) -> dict:
    """전체 링크를 한 번에 로드하여 {note_id: {'links': [...], 'backlinks': [...]}} 반환.
    export_to_vault에서 N+1 쿼리를 방지한다."""
    if not note_ids:
        return {}
    from src.pg_store import _sql_text as _st
    id_list = ', '.join(_st(nid) for nid in note_ids)
    # 모든 관련 링크를 한 번에 조회
    rows = query_rows(
        f"SELECT l.source_id, l.target_id, l.link_type, n1.title AS src_title, n2.title AS tgt_title "
        f"FROM zettel_links l "
        f"LEFT JOIN zettel_notes n1 ON l.source_id = n1.id "
        f"LEFT JOIN zettel_notes n2 ON l.target_id = n2.id "
        f"WHERE l.source_id IN ({id_list}) OR l.target_id IN ({id_list});"
    )
    result = {}
    for nid in note_ids:
        result[nid] = {'links': [], 'backlinks': []}
    for r in rows:
        src, tgt = r['source_id'], r['target_id']
        if src in result:
            result[src]['links'].append({
                'id': tgt, 'title': r.get('tgt_title', ''), 'link_type': r['link_type']
            })
        if tgt in result:
            result[tgt]['backlinks'].append({
                'id': src, 'title': r.get('src_title', ''), 'link_type': r['link_type']
            })
    return result


def _format_links_section_cached(note_id: str, all_links: dict) -> str:
    """사전 로드된 링크 데이터로 연결 섹션 생성. (배치 export용)"""
    data = all_links.get(note_id, {})
    return _render_links_section(data.get('links', []), data.get('backlinks', []))


def _render_links_section(links: list, backlinks: list) -> str:
    """링크/백링크를 Obsidian 위키링크 마크다운으로 렌더링."""
    if not links and not backlinks:
        return ''

    sections = []
    link_labels = {'relates_to': '관련', 'extends': '확장', 'contradicts': '반박', 'implements': '구현'}
    backlink_labels = {'relates_to': '관련', 'extends': '확장됨', 'contradicts': '반박됨', 'implements': '구현됨'}

    if links:
        sections.append('\n## 연결된 노트')
        for link in links:
            label = link_labels.get(link.get('link_type', ''), link.get('link_type', ''))
            sections.append(f'- [[{link["id"]}]] {link.get("title", "")} ({label})')

    if backlinks:
        sections.append('\n## 백링크')
        for bl in backlinks:
            label = backlink_labels.get(bl.get('link_type', ''), bl.get('link_type', ''))
            sections.append(f'- [[{bl["id"]}]] {bl.get("title", "")} ({label})')

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

    # 전체 링크를 한 번에 로드 (N+1 쿼리 방지)
    all_links = _load_all_links([n['id'] for n in notes])

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
        links_section = _format_links_section_cached(note['id'], all_links)

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

    # 프로젝트 문서 동기화
    doc_count = _sync_project_docs(vault_dir)

    # 인덱스 파일 생성 (MOC — Map of Content)
    _generate_moc(vault_dir, notes)

    print(f'[zettel_sync] {exported}개 노트 + {doc_count}개 문서를 {vault_dir}에 동기화 완료')
    return exported


# ── 프로젝트 문서 동기화 ──────────────────────────────────────────────────

# 동기화 대상 문서 탐색 패턴 (프로젝트 루트 기준)
# {proj} 는 _sync_project_docs에서 프로젝트 이름으로 치환됨
_DOC_SCAN_PATTERNS = [
    ('*.md', '_project/{proj}'),                        # 루트 .md 파일
    ('docs/*.md', '_project/{proj}/docs'),              # docs/ 하위 문서
    ('.claude/rules/*.md', '_project/{proj}/rules'),     # 에이전트 규칙
    ('.claude/skills/*/skill.md', '_project/{proj}/skills'),  # 스킬 문서
]

# 제외 패턴 (vault 자체, node_modules 등)
_DOC_EXCLUDE = {'.zettel-vault', 'node_modules', '.git', 'dist', 'build'}

# 문서 제목 한글 매핑
_DOC_TITLE_KO = {
    'CLAUDE': '클로드 에이전트 설정',
    'GEMINI': '제미나이 에이전트 설정',
    'CODEX_GUIDE': '코덱스 에이전트 가이드',
    'AGENTS': '에이전트 목록',
    'HIVEMIND': '하이브 마인드 설계',
    'RULES': '프로젝트 규칙',
    'README': '프로젝트 소개',
    'PROJECT_MAP': '프로젝트 구조 지도',
    'CHANGELOG': '변경 이력',
    'ai_monitor_plan': '현재 작업 계획',
    'memory': '공유 메모리',
    'progress': '진행 상황',
    'API_SPEC': 'API 명세서',
    'HARNESS_V2': '하네스 V2 계약',
    'HARNESS_V1': '하네스 V1 (레거시)',
    'HARNESS_CHECKS': '하네스 점검 항목',
    'VIBE_PROJECT_GUIDE': '프로젝트 개발 가이드',
    'CODEX_HARDENING': '코덱스 보안 강화',
    'CODEX_RUNTIME_SETUP': '코덱스 런타임 설정',
    'CLAUDE_CODE_AGENT_TEAMS_ANALYSIS': '에이전트 팀 분석',
    'METAVERSE_OFFICE_DESIGN': '메타버스 오피스 설계',
    'TERMINAL3_SCROLL_ISSUE': '터미널3 스크롤 이슈',
    'architecture': '아키텍처 규칙',
    'commit-rules': '커밋 메시지 규칙',
    'hive-sync': '하이브 동기화 프로토콜',
    'vibe-zettel': '제텔카스텐 스킬',
    'vibe-heal': '자기치유 스킬',
    'vibe-brainstorm': '브레인스토밍 스킬',
    'vibe-code-review': '코드 리뷰 스킬',
    'vibe-debug': '디버그 스킬',
    'vibe-execute-plan': '계획 실행 스킬',
    'vibe-write-plan': '계획 작성 스킬',
    'vibe-orchestrate': '오케스트레이터 스킬',
    'vibe-release': '릴리즈 스킬',
    'vibe-security': '보안 점검 스킬',
    'vibe-tdd': 'TDD 스킬',
    'vibe-dispatcher': '디스패처 스킬',
    'SKILL': '스킬 정의',
}


def _sync_project_docs(vault_dir: Path) -> int:
    """프로젝트 핵심 문서를 vault의 _project/{프로젝트명}/ 폴더에 자동 동기화한다.

    프로젝트별 하위 폴더로 분리하여 멀티 프로젝트 vault에서 충돌을 방지한다.
    """
    # 프로젝트 이름 추출 (폴더명에서)
    proj_name = _PROJECT_ROOT.name  # 'vibe-coding'
    synced = 0

    for glob_pattern, dest_subdir_tmpl in _DOC_SCAN_PATTERNS:
        dest_subdir = dest_subdir_tmpl.replace('{proj}', proj_name)
        dest_dir = vault_dir / dest_subdir
        dest_dir.mkdir(parents=True, exist_ok=True)

        for src in _PROJECT_ROOT.glob(glob_pattern):
            if not src.is_file():
                continue
            # 제외 패턴 체크
            if any(excl in str(src) for excl in _DOC_EXCLUDE):
                continue

            try:
                content = src.read_text(encoding='utf-8')
            except Exception:
                continue

            # 상대 경로 계산
            try:
                rel_path = str(src.relative_to(_PROJECT_ROOT)).replace('\\', '/')
            except ValueError:
                continue

            # 스킬 문서는 폴더명을 파일명에 포함 (skill.md → vibe-zettel.md)
            if 'skills' in rel_path and src.name == 'skill.md':
                filename = src.parent.name + '.md'
            else:
                filename = src.name

            # 프론트매터 생성 (제목은 한글 매핑 우선)
            title = _DOC_TITLE_KO.get(Path(filename).stem, Path(filename).stem)
            fm = '\n'.join([
                '---',
                f'title: "{title}"',
                'note_type: project-doc',
                f'source: "{rel_path}"',
                f'updated: {datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M")}',
                '---',
                '',
            ])

            # 기존 프론트매터 제거 후 새로 추가
            if content.startswith('---'):
                m = re.match(r'^---\s*\n.*?\n---\s*\n', content, re.DOTALL)
                if m:
                    content = content[m.end():]
            # HTML 주석 프론트매터도 제거 (<!-- FILE: ... -->)
            if content.startswith('<!--'):
                m = re.match(r'^<!--.*?-->\s*\n', content, re.DOTALL)
                if m:
                    content = fm + content  # 주석은 유지하되 앞에 FM 추가
                    fm = ''  # 이미 추가했으므로 아래에서 다시 추가하지 않음

            dest = dest_dir / filename
            # 경로 트래버설 방어
            if not dest.resolve().is_relative_to(vault_dir.resolve()):
                continue

            dest.write_text((fm + content) if fm else content, encoding='utf-8')
            synced += 1

    return synced


def _generate_moc(vault_dir: Path, notes: list):
    """MOC(Map of Content) 인덱스 파일 생성 — 한글화 + 프로젝트 문서 포함."""
    lines = [
        '---',
        'title: "하이브 지식 저장소"',
        f'updated: {datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M")}',
        '---',
        '',
        '# 하이브 지식 저장소',
        '',
        f'총 {len(notes)}개 지식 노트',
        '',
    ]

    # ── 지식 노트 (유형별 그룹핑) ──
    by_type = {}
    for n in notes:
        t = n.get('note_type', 'fleeting')
        by_type.setdefault(t, []).append(n)

    type_labels = {'permanent': '영구 지식', 'literature': '참고 문헌', 'fleeting': '작업 기록'}
    type_icons = {'permanent': '🏛️', 'literature': '📚', 'fleeting': '📝'}
    for note_type in ('permanent', 'literature', 'fleeting'):
        group = by_type.get(note_type, [])
        if not group:
            continue
        icon = type_icons.get(note_type, '')
        lines.append(f'## {icon} {type_labels.get(note_type, note_type)} ({len(group)})')
        lines.append('')
        for n in group[:50]:
            lines.append(f'- [[{n["id"]}]] {n.get("title", "")}')
        if len(group) > 50:
            lines.append(f'- ... 외 {len(group) - 50}개')
        lines.append('')

    # ── 프로젝트 문서 섹션 ──
    project_dir = vault_dir / '_project'
    if project_dir.exists():
        lines.append('---')
        lines.append('')
        for proj_folder in sorted(project_dir.iterdir()):
            if not proj_folder.is_dir():
                continue
            proj_name = proj_folder.name
            lines.append(f'## 📁 프로젝트: {proj_name}')
            lines.append('')

            # 루트 문서
            root_docs = sorted(proj_folder.glob('*.md'))
            if root_docs:
                for doc in root_docs:
                    title = _DOC_TITLE_KO.get(doc.stem, doc.stem)
                    lines.append(f'- [[{doc.stem}]] {title}')
                lines.append('')

            # 하위 폴더별
            sub_labels = {'docs': '📄 상세 문서', 'rules': '📏 규칙', 'skills': '🛠️ 스킬'}
            for subdir_name in ('docs', 'rules', 'skills'):
                subdir = proj_folder / subdir_name
                if not subdir.exists():
                    continue
                sub_docs = sorted(subdir.glob('*.md'))
                if not sub_docs:
                    continue
                lines.append(f'### {sub_labels.get(subdir_name, subdir_name)}')
                lines.append('')
                for doc in sub_docs:
                    title = _DOC_TITLE_KO.get(doc.stem, doc.stem)
                    lines.append(f'- [[{doc.stem}]] {title}')
                lines.append('')

    (vault_dir / 'INDEX.md').write_text('\n'.join(lines), encoding='utf-8')


# ── Obsidian → PostgreSQL 역동기화 ────────────────────────────────────────

def _parse_frontmatter(text: str) -> dict:
    """마크다운 파일에서 YAML 프론트매터를 파싱한다."""
    m = re.match(r'^---\s*\n(.*?)\n---\s*\n', text, re.DOTALL)
    if not m:
        return {}
    fm = {}
    for line in m.group(1).split('\n'):
        line = line.strip()
        if ':' not in line:
            continue
        key, _, val = line.partition(':')
        key = key.strip()
        val = val.strip().strip('"')
        if key == 'tags':
            # tags: ["a", "b"] 파싱
            try:
                val = json.loads(val.replace("'", '"'))
            except (json.JSONDecodeError, TypeError):
                val = []
        elif key == 'archived':
            val = val.lower() == 'true'
        elif key == 'access_count':
            try:
                val = int(val)
            except (ValueError, TypeError):
                val = 0
        fm[key] = val
    return fm


def _extract_body(text: str) -> str:
    """마크다운 파일에서 프론트매터 제거 후 본문만 추출한다."""
    m = re.match(r'^---\s*\n.*?\n---\s*\n', text, re.DOTALL)
    if not m:
        return text
    body = text[m.end():]
    # 첫 번째 # 제목 줄 제거 (export 시 자동 생성된 것)
    body = re.sub(r'^# .+\n\n?', '', body, count=1)
    # 연결된 노트/백링크 섹션 제거 (자동 생성 섹션)
    body = re.sub(r'\n## 연결된 노트\n.*', '', body, flags=re.DOTALL)
    body = re.sub(r'\n## 백링크\n.*', '', body, flags=re.DOTALL)
    return body.strip()


def import_from_vault(vault_dir: Path, project: str = ''):
    """Obsidian Vault → PostgreSQL 역동기화.

    vault의 .md 파일을 읽어 YAML 프론트매터를 파싱하고,
    zettel_id 기준으로 DB에 upsert한다.
    """
    ensure_schema(DATA_DIR)
    if not vault_dir.exists():
        print(f'[zettel_sync] vault 디렉토리 없음: {vault_dir}')
        return 0

    imported = 0
    skipped = 0

    # 기존 노트를 한 번에 로드 (N+1 쿼리 방지)
    existing_notes = {}
    for note in list_notes(include_archived=True, limit=10000):
        existing_notes[note['id']] = note

    # vault 내 모든 .md 파일 탐색 (INDEX.md 제외)
    for md_file in vault_dir.rglob('*.md'):
        if md_file.name == 'INDEX.md':
            continue
        # 경로 트래버설 방어
        if not md_file.resolve().is_relative_to(vault_dir.resolve()):
            continue

        try:
            text = md_file.read_text(encoding='utf-8')
        except Exception:
            continue

        fm = _parse_frontmatter(text)
        zettel_id = fm.get('zettel_id', '')
        if not zettel_id:
            skipped += 1
            continue

        body = _extract_body(text)
        title = fm.get('title', md_file.stem)
        note_type = fm.get('note_type', 'fleeting')
        author = fm.get('author', 'obsidian')
        tags = fm.get('tags', [])
        if isinstance(tags, str):
            tags = []
        source_ref = fm.get('source_ref', '')
        archived = fm.get('archived', False)

        existing = existing_notes.get(zettel_id)

        if existing:
            # mtime 비교: vault 파일이 DB보다 새로운 경우만 업데이트
            file_mtime = datetime.fromtimestamp(md_file.stat().st_mtime, tz=timezone.utc)
            db_updated = existing.get('updated_at')
            if db_updated and hasattr(db_updated, 'timestamp'):
                if file_mtime.timestamp() <= db_updated.timestamp():
                    skipped += 1
                    continue

            # 업데이트
            update_note(zettel_id,
                        title=title, content=body, note_type=note_type,
                        tags=tags, source_ref=source_ref, archived=archived)
        else:
            # 신규 생성
            create_note(
                title=title, content=body, note_type=note_type,
                author=author, project=project, tags=tags,
                source_ref=source_ref, custom_id=zettel_id,
            )

        imported += 1

    print(f'[zettel_sync] vault → DB: {imported}건 import, {skipped}건 스킵')
    return imported


def watch_and_sync(vault_dir: Path, project: str = '', interval: int = 60,
                   bidirectional: bool = False):
    """주기적 동기화 루프. 데몬 모드로 실행."""
    mode_label = '양방향' if bidirectional else '단방향(PG→Vault)'
    print(f'[zettel_sync] 감시 모드 시작 — {interval}초 간격, {mode_label}, vault={vault_dir}')
    while True:
        try:
            if bidirectional:
                import_from_vault(vault_dir, project=project)
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
    parser.add_argument('--import', dest='do_import', action='store_true',
                        help='Obsidian vault → PostgreSQL 역동기화')
    parser.add_argument('--bidirectional', action='store_true',
                        help='감시 모드에서 양방향 동기화 활성화')
    args = parser.parse_args()

    vault_path = Path(args.vault)

    if args.do_import:
        import_from_vault(vault_path, project=args.project)
    elif args.watch:
        watch_and_sync(vault_path, project=args.project,
                       interval=args.interval, bidirectional=args.bidirectional)
    else:
        export_to_vault(vault_path, project=args.project, include_archived=args.archived)


if __name__ == '__main__':
    main()
