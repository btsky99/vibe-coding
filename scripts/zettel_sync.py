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
import shutil
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

_appdata = os.environ.get('APPDATA') or str(Path.home())
_default_global_vault = Path(_appdata) / 'VibeCoding' / 'vault' if os.name == 'nt' \
    else Path.home() / '.vibe-coding' / 'vault'
DEFAULT_VAULT_DIR = Path(os.environ.get('VIBE_VAULT_DIR', str(_default_global_vault)))
DATA_DIR = _PROJECT_ROOT / '.ai_monitor' / 'data'


_NOTE_TYPE_EMOJI = {
    'permanent': '\U0001f48e',   # 💎
    'literature': '\U0001f4da',  # 📚
    'fleeting': '\U0001f4dd',    # 📝
}

# vault 폴더명 한글 매핑
_NOTE_TYPE_FOLDER = {
    'permanent': '영구지식',
    'literature': '참고문헌',
    'fleeting': '작업기록',
}

def _format_frontmatter(note: dict) -> str:
    """Obsidian 호환 YAML 프론트매터 생성.
    [v3.7.179] aliases + cssclasses 추가 — 그래프에서 타입별 이모지 + 짧은 제목 표시."""
    tags_list = note.get('tags', [])
    if isinstance(tags_list, str):
        try:
            tags_list = json.loads(tags_list)
        except (json.JSONDecodeError, TypeError):
            tags_list = []

    note_type = note.get('note_type', 'fleeting')
    title = note.get('title', '')
    emoji = _NOTE_TYPE_EMOJI.get(note_type, '')
    # aliases: 그래프에서 노드 이름으로 이모지+짧은 제목 표시
    short_title = title[:30] + ('...' if len(title) > 30 else '')
    alias = f'{emoji} {short_title}' if short_title else note.get('id', '')

    lines = [
        '---',
        f'zettel_id: "{note["id"]}"',
        f'title: "{_escape_yaml(title)}"',
        f'aliases: ["{_escape_yaml(alias)}"]',
        f'note_type: {note_type}',
        f'cssclasses: [zettel-{note_type}]',
        f'author: {note.get("author", "unknown")}',
        f'project_id: {note.get("project_id", "")}',
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
    """링크/백링크를 Obsidian 위키링크 마크다운으로 렌더링.
    [v3.7.179] [[ID 제목|표시명]] 형식으로 변경 — Obsidian이 파일명과 매칭할 수 있도록.
    이전: [[vibe-21]] → 파일명 'vibe-21 세션 요약...'과 매칭 실패 → 루트에 빈 파일 생성.
    수정: [[vibe-21 세션 요약...|vibe-21: 세션 요약...]] → 정확한 파일 매칭."""
    if not links and not backlinks:
        return ''

    sections = []
    link_labels = {'relates_to': '관련', 'extends': '확장', 'contradicts': '반박', 'implements': '구현'}
    backlink_labels = {'relates_to': '관련', 'extends': '확장됨', 'contradicts': '반박됨', 'implements': '구현됨'}

    if links:
        sections.append('\n## 연결된 노트')
        for link in links:
            label = link_labels.get(link.get('link_type', ''), link.get('link_type', ''))
            # [[파일명|표시명]] 형식 — Obsidian이 파일명으로 정확히 매칭
            fname = _safe_filename(link['id'], link.get('title', ''))
            display = f'{link["id"]}: {link.get("title", "")}' if link.get('title') else link['id']
            sections.append(f'- [[{fname}|{display}]] ({label})')

    if backlinks:
        sections.append('\n## 백링크')
        for bl in backlinks:
            label = backlink_labels.get(bl.get('link_type', ''), bl.get('link_type', ''))
            fname = _safe_filename(bl['id'], bl.get('title', ''))
            display = f'{bl["id"]}: {bl.get("title", "")}' if bl.get('title') else bl['id']
            sections.append(f'- [[{fname}|{display}]] ({label})')

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
    """Obsidian에서 사용 가능한 안전한 파일명 생성. 제목 포함 + 경로 트래버설 방어.

    예: vibe-3, "결정: 방식 C 선택" → "vibe-3 결정 — 방식 C 선택"
    """
    # 위험 문자 제거
    safe_id = re.sub(r'[\\/:*?"<>|\x00-\x1f]', '', note_id).replace('..', '')
    if not safe_id:
        safe_id = 'unnamed'

    if title:
        # 제목에서 파일명 불가 문자 제거, 콜론→대시
        safe_title = re.sub(r'[\\/:*?"<>|\x00-\x1f]', '', title)
        safe_title = safe_title.replace('..', '').strip()[:60]  # 최대 60자
        return f'{safe_id} {safe_title}' if safe_title else safe_id

    return safe_id


def _note_output_path(vault_dir: Path, note: dict) -> Path:
    """DB 노트 1건이 export되어야 하는 단일 표준 경로를 반환한다."""
    if note.get('archived'):
        folder = vault_dir / '_보관'
    else:
        note_type = note.get('note_type', 'fleeting')
        folder = vault_dir / _NOTE_TYPE_FOLDER.get(note_type, '작업기록')
    filename = _safe_filename(note['id'], note.get('title', ''))
    return folder / f"{filename}.md"


def _cleanup_stale_note_files(vault_dir: Path, notes: list[dict]) -> int:
    """export 대상 노트의 오래된 중복 파일을 제거한다.

    note_type이 바뀌면 같은 zettel_id가 작업기록/영구지식 양쪽에 남을 수 있다.
    PostgreSQL을 원본으로 보고 현재 DB 기준 표준 경로 1개만 유지한다.
    """
    expected = {
        str(note.get('id', '')): _note_output_path(vault_dir, note).resolve()
        for note in notes
        if note.get('id')
    }
    if not expected:
        return 0

    removed = 0
    for md_file in vault_dir.rglob('*.md'):
        if md_file.name == 'INDEX.md':
            continue
        try:
            if not md_file.resolve().is_relative_to(vault_dir.resolve()):
                continue
            text = md_file.read_text(encoding='utf-8')
            zettel_id = _parse_frontmatter(text).get('zettel_id', '')
        except Exception:
            continue
        target = expected.get(zettel_id)
        if not target or md_file.resolve() == target:
            continue
        try:
            md_file.unlink()
            removed += 1
        except Exception as exc:
            print(f'[zettel_sync] 오래된 중복 노트 삭제 실패: {md_file} ({exc})')
    return removed


def export_to_vault(vault_dir: Path, project_id: str = '', include_archived: bool = False):
    """PostgreSQL → Obsidian Vault 전체 동기화."""
    ensure_schema(DATA_DIR)
    vault_dir.mkdir(parents=True, exist_ok=True)

    # 노트 유형별 폴더 생성 (한글)
    for subdir in ('작업기록', '참고문헌', '영구지식', '_보관'):
        (vault_dir / subdir).mkdir(exist_ok=True)

    # 전체 노트 조회
    notes = list_notes(
        project_id=project_id,
        include_archived=include_archived,
        limit=10000,
    )
    # [2026-06-21] 역할 분리 — 휘발성 자동노트(세션 요약/머지 커밋)는 LLM 작업기억이라 PG에만 두고
    # 사람용 옵시디언 볼트엔 동기화하지 않는다. (옵시디언 = 정제된 지식만, 그래프 오염 방지)
    # PG에는 그대로 남아 회상/검색에 쓰임. [[project_installed_empty_panels]]
    def _is_ephemeral(n) -> bool:
        t = str(n.get('title', '') or '')
        return (n.get('source_ref') == 'session-summary'
                or t.startswith('세션 요약') or t.startswith('Merge '))
    notes = [n for n in notes if not _is_ephemeral(n)]
    removed = _cleanup_stale_note_files(vault_dir, notes)
    if removed:
        print(f'[zettel_sync] 오래된 중복 노트 {removed}개 삭제')

    # 전체 링크를 한 번에 로드 (N+1 쿼리 방지)
    all_links = _load_all_links([n['id'] for n in notes])

    exported = 0
    for note in notes:
        # 마크다운 생성
        frontmatter = _format_frontmatter(note)
        content = note.get('content', '')
        links_section = _format_links_section_cached(note['id'], all_links)

        md_content = f"{frontmatter}\n\n# {note.get('title', '')}\n\n{content}"
        if links_section:
            md_content += f"\n\n{links_section}"
        md_content += '\n'

        # 파일 쓰기 (경로 트래버설 방어)
        filepath = _note_output_path(vault_dir, note)
        filepath.parent.mkdir(parents=True, exist_ok=True)
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
# GDrive 크로스공유에서 제외할 노트 source_ref 접두 — 커밋덤프/세션요약은 잡음.
# [WHY] GDrive = 서로 다른 프로젝트가 지식을 나누는 허브. 커밋 원문 덤프는 프로젝트-지역적
#   소음이라 다른 프로젝트에 무가치. 파일카드/파일지도/결정/교훈/일반 지식은 유지(=삭제하지 않음).
_GDRIVE_NOISE_SREF_PREFIXES = ('git-commit:', 'session-summary')
_NOTE_FOLDERS = ('영구지식', '참고문헌', '작업기록', '_보관')


def _is_gdrive_worthy(src_path: Path, source_vault: Path) -> bool:
    """GDrive 미러 대상 여부 — 노이즈 노트(커밋덤프/세션요약)만 제외, 나머지 전부 허용.

    [설계] 화이트리스트가 아니라 노이즈 블랙리스트 — 일반 지식 노트를 실수로 떨구지 않기 위함.
      노트 폴더(영구지식 등)의 .md만 frontmatter source_ref로 판정, 구조/설정/문서는 그대로 복사.
    [보수적] frontmatter 파싱 실패/판단 불가 → True(복사). 잘못 빼는 것보다 잘못 넣는 게 안전.
    """
    try:
        rel = src_path.relative_to(source_vault)
    except ValueError:
        return True
    parts = rel.parts
    if not parts or parts[0] not in _NOTE_FOLDERS or src_path.suffix.lower() != '.md':
        return True  # 노트가 아닌 구조/문서/설정 파일은 항상 복사
    try:
        fm = _parse_frontmatter(src_path.read_text(encoding='utf-8'))
    except Exception:
        return True
    sref = str(fm.get('source_ref', '') or '')
    return not any(sref.startswith(p) for p in _GDRIVE_NOISE_SREF_PREFIXES)


def mirror_vault(source_vault: Path, target_vault: Path, note_filter=None) -> int:
    """Mirror the local Obsidian vault into a shared Google Drive vault.

    The mirror is non-destructive: it copies or updates files from the local vault
    but keeps target-only files so another project or device is not wiped.
    note_filter(src_path) 가 주어지면 False를 반환하는 파일은 미러에서 제외한다
    (GDrive 크로스공유 시 커밋덤프 등 노이즈 배제용). 제외돼도 로컬 vault는 그대로 유지.
    """
    source_vault = Path(source_vault).resolve()
    target_vault = Path(target_vault).resolve()
    if source_vault == target_vault or not source_vault.exists():
        return 0

    target_vault.mkdir(parents=True, exist_ok=True)
    copied = 0
    for src in source_vault.rglob('*'):
        try:
            if not src.resolve().is_relative_to(source_vault):
                continue
        except Exception:
            continue

        rel = src.relative_to(source_vault)
        dst = target_vault / rel
        if src.is_dir():
            dst.mkdir(parents=True, exist_ok=True)
            continue
        if not src.is_file():
            continue

        # [T7] GDrive 노이즈 필터 — 커밋덤프 노트 등은 허브로 내보내지 않음(로컬은 보존).
        if note_filter is not None and not note_filter(src):
            continue

        dst.parent.mkdir(parents=True, exist_ok=True)
        should_copy = True
        if dst.exists():
            try:
                src_stat = src.stat()
                dst_stat = dst.stat()
                should_copy = (
                    src_stat.st_size != dst_stat.st_size
                    or src_stat.st_mtime > dst_stat.st_mtime + 0.001
                )
            except OSError:
                should_copy = True
        if should_copy:
            shutil.copy2(src, dst)
            copied += 1

    print(f'[zettel_sync] vault mirror complete: {source_vault} -> {target_vault} ({copied} files)')
    return copied


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
    'ANTIGRAVITY': '안티그라비티 에이전트 설정',
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

            # 스킬 문서는 폴더명을 키로 사용 (skill.md → vibe-zettel)
            if 'skills' in rel_path and src.name == 'skill.md':
                file_key = src.parent.name
            else:
                file_key = src.stem

            # 한글 제목 → 파일명으로도 사용
            title = _DOC_TITLE_KO.get(file_key, file_key)
            filename = f'{title}.md'
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
            fname = _safe_filename(n['id'], n.get('title', ''))
            lines.append(f'- [[{fname}]]')
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
                    lines.append(f'- [[{doc.stem}]]')
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
                    lines.append(f'- [[{doc.stem}]]')
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


def _frontmatter_project_id(fm: dict) -> str:
    """구형 frontmatter(project)와 신형 project_id를 같은 값으로 취급한다."""
    return str(fm.get('project_id') or fm.get('project') or '').strip()


def _candidate_score(vault_dir: Path, md_file: Path, fm: dict,
                     existing: dict | None) -> tuple:
    """같은 zettel_id 중 DB 상태와 가장 잘 맞는 파일을 고르기 위한 점수."""
    note_type = fm.get('note_type', 'fleeting')
    archived = bool(fm.get('archived', False))
    expected_folder = '_보관' if archived else _NOTE_TYPE_FOLDER.get(note_type, '작업기록')
    folder_match = md_file.parent.name == expected_folder

    existing_type = existing.get('note_type') if existing else ''
    type_match = bool(existing_type and note_type == existing_type)
    try:
        mtime = md_file.stat().st_mtime
    except OSError:
        mtime = 0
    return (1 if type_match else 0, 1 if folder_match else 0, mtime)


def _same_note_payload(existing: dict, title: str, body: str, note_type: str,
                       tags: list, source_ref: str, archived: bool) -> bool:
    """export된 동일 내용 파일을 import하면서 updated_at만 밀어 올리는 일을 막는다."""
    existing_tags = existing.get('tags', [])
    if isinstance(existing_tags, str):
        try:
            existing_tags = json.loads(existing_tags)
        except (json.JSONDecodeError, TypeError):
            existing_tags = []
    existing_archived = existing.get('archived')
    if isinstance(existing_archived, str):
        existing_archived = existing_archived.lower() in ('t', 'true', '1')
    return (
        str(existing.get('title', '')) == str(title)
        and str(existing.get('content', '')).strip() == str(body).strip()
        and str(existing.get('note_type', '')) == str(note_type)
        and list(existing_tags or []) == list(tags or [])
        and str(existing.get('source_ref', '') or '') == str(source_ref or '')
        and bool(existing_archived) == bool(archived)
    )


def import_from_vault(vault_dir: Path, project_id: str = ''):
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

    # vault 내 모든 .md 파일 탐색 (INDEX.md 제외). 같은 zettel_id가 여러
    # 폴더에 남아 있으면 DB note_type과 맞는 후보 1개만 import한다.
    candidates = {}
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
        fm_project_id = _frontmatter_project_id(fm)
        if project_id and fm_project_id and fm_project_id != project_id:
            skipped += 1
            continue
        existing = existing_notes.get(zettel_id)
        if project_id and existing and existing.get('project_id') not in (project_id, '', None):
            skipped += 1
            continue

        score = _candidate_score(vault_dir, md_file, fm, existing)
        current = candidates.get(zettel_id)
        if not current or score > current[0]:
            candidates[zettel_id] = (score, md_file, text, fm)

    for zettel_id, (_, md_file, text, fm) in candidates.items():

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
            if _same_note_payload(existing, title, body, note_type,
                                  tags, source_ref, archived):
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
                author=author, project_id=project_id, tags=tags,
                source_ref=source_ref, custom_id=zettel_id,
            )
            # [크로스-PC 부활 방지] create_note는 archived 인자가 없다 → 다른 PC에서 아카이브된
            #   노트가 이 PC에 '처음' 들어오면 활성으로 생성돼 부활한다. 생성 직후 상태 보정.
            if archived:
                update_note(zettel_id, archived=True)

        imported += 1

    print(f'[zettel_sync] vault → DB: {imported}건 import, {skipped}건 스킵')
    return imported


def watch_and_sync(vault_dir: Path, project_id: str = '', interval: int = 60,
                   bidirectional: bool = False, include_archived: bool = False):
    """주기적 동기화 루프. 데몬 모드로 실행.
    include_archived=True면 export가 아카이브 노트도 _보관 폴더로 내보낸다 — GDrive 양방향에서
    아카이브 상태를 다른 PC로 전파하고, 두 동기화 루프가 _보관 파일을 두고 다투지 않게 하려면 필수.
    """
    mode_label = '양방향' if bidirectional else '단방향(PG→Vault)'
    print(f'[zettel_sync] 감시 모드 시작 — {interval}초 간격, {mode_label}, vault={vault_dir}')
    while True:
        try:
            if bidirectional:
                import_from_vault(vault_dir, project_id=project_id)
            export_to_vault(vault_dir, project_id=project_id,
                            include_archived=include_archived)
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
        import_from_vault(vault_path, project_id=args.project)
    elif args.watch:
        watch_and_sync(vault_path, project_id=args.project,
                       interval=args.interval, bidirectional=args.bidirectional)
    else:
        export_to_vault(vault_path, project_id=args.project, include_archived=args.archived)


if __name__ == '__main__':
    main()
