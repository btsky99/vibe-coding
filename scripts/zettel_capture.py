# -*- coding: utf-8 -*-
"""
FILE: scripts/zettel_capture.py
DESCRIPTION: 제텔카스텐 자동 캡처 엔진.
             에이전트 작업 이벤트(커밋, 버그수정, 설계결정, 세션종료)를 감지하여
             자동으로 zettel_notes에 지식 노트를 생성하고 Obsidian vault에 동기화한다.

REVISION HISTORY:
    2026-04-06 Claude: 초기 구현 — 이벤트별 자동 캡처 + 유사 노트 연결 + vault 동기화
"""

import argparse
import json
import os
import re
import sys
import io
from datetime import datetime, timezone, timedelta
from pathlib import Path

# Windows UTF-8 보정
if sys.stdout.encoding and sys.stdout.encoding.lower() not in ("utf-8", "utf8"):
    try:
        sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8', errors='replace')
        sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding='utf-8', errors='replace')
    except Exception:
        pass

# 프로젝트 경로 설정
_SCRIPT_DIR = Path(__file__).resolve().parent
_PROJECT_ROOT = _SCRIPT_DIR.parent
_MONITOR_DIR = _PROJECT_ROOT / '.ai_monitor'

sys.path.insert(0, str(_MONITOR_DIR))
sys.path.insert(0, str(_SCRIPT_DIR))

from src.pg_store import ensure_schema, query_rows, _sql_text
from src.zettelkasten import create_note, auto_link, find_similar


# ── 설정 ──────────────────────────────────────────────────────────────────

_appdata = os.environ.get('APPDATA') or str(Path.home())
_default_global_vault = Path(_appdata) / 'VibeCoding' / 'vault' if os.name == 'nt'     else Path.home() / '.vibe-coding' / 'vault'
DEFAULT_VAULT_DIR = Path(os.environ.get('VIBE_VAULT_DIR', str(_default_global_vault)))
_gdrive_env = os.environ.get('VIBE_GDRIVE_VAULT', '')
GDRIVE_VAULT_DIR = Path(_gdrive_env) if _gdrive_env else None
DEFAULT_PROJECT = os.environ.get('VIBE_PROJECT', _PROJECT_ROOT.name)

# 커밋 타입 → 노트 유형 매핑
_COMMIT_TYPE_MAP = {
    'feat':     'fleeting',
    'fix':      'permanent',    # 버그 수정은 영구 지식
    'refactor': 'literature',
    'docs':     'literature',
    'build':    'fleeting',
    'chore':    'fleeting',
    'test':     'fleeting',
}

# 커밋 타입 → 한글 태그 매핑
_COMMIT_TAG_KO = {
    'feat':     '기능',
    'fix':      '수정',
    'refactor': '리팩터링',
    'docs':     '문서',
    'build':    '빌드',
    'chore':    '잡일',
    'test':     '테스트',
}

# 영역 태그 한글 매핑
_AREA_TAG_KO = {
    'ui':       'UI',
    'backend':  '백엔드',
    'db':       'DB',
    'scripts':  '스크립트',
    'hooks':    '훅',
    'test':     '테스트',
}


# ── 캡처 함수 ─────────────────────────────────────────────────────────────

def capture_commit(commit_msg: str, files: list[str] | None = None,
                   agent: str = 'claude') -> dict | None:
    """git commit 감지 → 커밋 유형별 노트 자동 생성.

    커밋 메시지에서 타입(feat/fix/refactor)을 파싱하여 적절한 note_type으로 생성.
    """
    ensure_schema()
    if not commit_msg:
        return None

    # Conventional Commit 타입 파싱: feat(scope): 메시지
    m = re.match(r'^(\w+)(?:\([^)]*\))?[!]?:\s*(.+)', commit_msg.split('\n')[0])
    if m:
        commit_type = m.group(1).lower()
        title = m.group(2).strip()
    else:
        commit_type = 'chore'
        title = commit_msg.split('\n')[0][:80]

    note_type = _COMMIT_TYPE_MAP.get(commit_type, 'fleeting')
    files = files or []

    # 태그 생성 (한글)
    tags = [_COMMIT_TAG_KO.get(commit_type, commit_type)]
    if files:
        # 파일 경로에서 영역 태그 추출 (예: vibe-view → UI, api → 백엔드)
        tags.extend(_extract_area_tags(files))

    # 본문 생성
    content_lines = [f"## 커밋: {commit_type}"]
    content_lines.append(f"\n{commit_msg}")
    if files:
        content_lines.append("\n## 수정 파일")
        for f in files[:20]:  # 최대 20개
            content_lines.append(f"- `{f}`")
    content = '\n'.join(content_lines)

    # 노트 생성
    note = create_note(
        title=title,
        content=content,
        note_type=note_type,
        author=agent,
        project_id=DEFAULT_PROJECT,
        tags=tags,
        source_ref=f"git-commit:{commit_type}",
    )

    if note:
        # 유사 노트 자동 연결
        auto_link(note['id'], content=content, tags=tags, created_by=agent)
        _sync_vault()
        print(f"[zettel_capture] 커밋 노트 생성: {note['id']} — {title} ({note_type})")

    # 변경 파일의 역할 카드 자동 생성/업데이트
    if files:
        capture_file_roles(commit_msg, files=files, agent=agent)

    return note


def capture_fix(file_path: str, old_code: str, new_code: str,
                agent: str = 'claude') -> dict | None:
    """버그 수정 감지 → permanent 노트 (원인 + 해결법)."""
    ensure_schema()
    if not file_path:
        return None

    rel_path = _rel_path(file_path)
    title = f"버그 수정: {rel_path}"
    tags = ['수정', '버그']
    tags.extend(_extract_area_tags([file_path]))

    content = f"## 수정 파일\n`{rel_path}`\n\n"
    if old_code:
        content += f"## 변경 전\n```\n{old_code[:500]}\n```\n\n"
    if new_code:
        content += f"## 변경 후\n```\n{new_code[:500]}\n```\n"

    note = create_note(
        title=title,
        content=content,
        note_type='permanent',
        author=agent,
        project_id=DEFAULT_PROJECT,
        tags=tags,
        source_ref=f"fix:{rel_path}",
    )

    if note:
        auto_link(note['id'], content=content, tags=tags, created_by=agent)
        _sync_vault()
        print(f"[zettel_capture] 버그수정 노트 생성: {note['id']} — {title}")

    return note


def capture_decision(context: str, choice: str, reason: str,
                     agent: str = 'claude') -> dict | None:
    """설계/아키텍처 결정 → permanent 노트."""
    ensure_schema()
    if not choice:
        return None

    title = f"결정: {choice[:60]}"
    tags = ['결정', '아키텍처']

    content = f"## 맥락\n{context}\n\n## 선택\n{choice}\n\n## 이유\n{reason}"

    note = create_note(
        title=title,
        content=content,
        note_type='permanent',
        author=agent,
        project_id=DEFAULT_PROJECT,
        tags=tags,
        source_ref='decision',
    )

    if note:
        auto_link(note['id'], content=content, tags=tags, created_by=agent)
        _sync_vault()
        print(f"[zettel_capture] 결정 노트 생성: {note['id']} — {title}")

    return note


def capture_session(agent: str = 'claude') -> dict | None:
    """세션 종료 → pg_logs 요약 fleeting 노트.

    이번 세션(최근 활동)의 pg_logs를 분석하여 세션 요약 노트를 생성한다.
    """
    ensure_schema()

    # 최근 세션의 pg_logs 조회 (최근 3시간 기준)
    rows = query_rows(
        f"SELECT agent, task, status, created_at "
        f"FROM pg_logs "
        f"WHERE created_at > NOW() - INTERVAL '3 hours' "
        f"AND project_id = {_sql_text(DEFAULT_PROJECT)} "
        f"ORDER BY created_at ASC;"
    )

    if not rows:
        print("[zettel_capture] 세션 활동 없음 — 노트 생성 스킵")
        return None

    # 활동 요약 생성
    now = datetime.now(timezone(timedelta(hours=9)))
    title = f"세션 요약: {now.strftime('%Y-%m-%d %H:%M')}"

    # 활동 카테고리별 그룹핑
    categories = {}
    for row in rows:
        task = row.get('task', '')
        if '[생성 완료]' in task or '[수정 완료]' in task:
            categories.setdefault('파일 변경', []).append(task)
        elif '[커밋]' in task:
            categories.setdefault('커밋', []).append(task)
        elif '[빌드]' in task:
            categories.setdefault('빌드', []).append(task)
        elif '[작업 시작]' in task:
            categories.setdefault('작업 시작', []).append(task)
        elif '세션 종료' in task:
            pass  # 제외
        else:
            categories.setdefault('기타', []).append(task)

    content_lines = [f"## 세션 활동 요약 ({len(rows)}건)"]
    tags = ['세션']

    for cat, items in categories.items():
        content_lines.append(f"\n### {cat} ({len(items)}건)")
        for item in items[:10]:  # 카테고리당 최대 10건
            content_lines.append(f"- {item}")
        if len(items) > 10:
            content_lines.append(f"- ... 외 {len(items) - 10}건")

    content_lines.append(f"\n---\n에이전트: {agent} | 기간: 최근 3시간 | 총 {len(rows)}건 활동")
    content = '\n'.join(content_lines)

    note = create_note(
        title=title,
        content=content,
        note_type='fleeting',
        author=agent,
        project_id=DEFAULT_PROJECT,
        tags=tags,
        source_ref='session-summary',
    )

    if note:
        auto_link(note['id'], content=content, tags=tags, created_by=agent)
        _sync_vault()
        print(f"[zettel_capture] 세션 요약 노트 생성: {note['id']} — {title}")

    return note


def capture_file_roles(commit_msg: str, files: list[str] | None = None,
                       agent: str = 'claude') -> list[dict]:
    """커밋 시 변경된 파일의 역할 카드를 자동 생성/업데이트한다.

    - 기존 역할 카드가 없는 파일 → 새 permanent 노트 생성
    - 기존 역할 카드가 있는 파일 → "최근 변경" 섹션에 커밋 기록 추가
    - 코드는 저장하지 않음 — 역할/맥락/변경 이력만 기록
    """
    ensure_schema()
    files = files or []
    if not files:
        return []

    from datetime import datetime, timezone, timedelta
    now = datetime.now(timezone(timedelta(hours=9)))
    today = now.strftime('%Y-%m-%d')
    results = []

    for file_path in files:
        rel = _rel_path(file_path)
        # 테스트/빌드 산출물 등 노이즈 파일은 스킵 (원본 경로도 함께 체크)
        if _is_noise_file(rel) or _is_noise_file(file_path):
            continue

        # source_ref로 기존 역할 카드 검색
        source_ref = f"file-role:{rel}"
        existing = query_rows(
            f"SELECT id, content FROM zettel_notes "
            f"WHERE source_ref = {_sql_text(source_ref)} "
            f"AND project_id = {_sql_text(DEFAULT_PROJECT)} "
            f"LIMIT 1;"
        )

        if existing:
            # 기존 카드에 "최근 변경" 이력 추가
            note_id = existing[0]['id']
            old_content = existing[0].get('content', '')
            change_line = f"- [{today}] {commit_msg.split(chr(10))[0][:80]}"

            if '## 최근 변경' in old_content:
                # 기존 변경 이력에 추가 (최대 10건 유지)
                parts = old_content.split('## 최근 변경')
                before = parts[0]
                after_lines = parts[1].strip().split('\n') if len(parts) > 1 else []
                # 기존 이력 항목만 필터 (- 로 시작하는 줄)
                history = [l for l in after_lines if l.strip().startswith('-')]
                history.insert(0, change_line)
                history = history[:10]  # 최신 10건만 유지
                new_content = before + '## 최근 변경\n' + '\n'.join(history)
            else:
                new_content = old_content + f"\n\n## 최근 변경\n{change_line}"

            from src.zettelkasten import update_note
            updated = update_note(note_id, content=new_content)
            if updated:
                results.append(updated)
        else:
            # 새 역할 카드 생성
            role_desc = _guess_file_role(rel)
            tags = ['파일역할']
            tags.extend(_extract_area_tags([file_path]))

            content = f"## 역할\n{role_desc}\n\n"
            content += f"## 파일 경로\n`{rel}`\n\n"
            content += f"## 최근 변경\n- [{today}] {commit_msg.split(chr(10))[0][:80]}"

            note = create_note(
                title=f"📄 {Path(rel).name} — {role_desc[:40]}",
                content=content,
                note_type='permanent',
                author=agent,
                project_id=DEFAULT_PROJECT,
                tags=tags,
                source_ref=source_ref,
            )
            if note:
                auto_link(note['id'], content=content, tags=tags, created_by=agent)
                results.append(note)

    if results:
        _sync_vault()
        print(f"[zettel_capture] 파일 역할 카드 {len(results)}건 생성/업데이트")

    return results


def _is_noise_file(rel_path: str) -> bool:
    """노이즈 파일 필터 — 역할 카드 생성 대상에서 제외."""
    noise_patterns = [
        'dist/', 'node_modules/', '__pycache__/', '.pyc',
        'package-lock.json', 'yarn.lock', '.spec.',
        '_version.py', '.gitignore', '.env',
    ]
    rel_lower = rel_path.lower().replace('\\', '/')
    return any(p in rel_lower for p in noise_patterns)


def _guess_file_role(rel_path: str) -> str:
    """파일 경로에서 역할을 추측한다. 코드를 읽지 않고 경로 패턴만으로 판단."""
    p = rel_path.lower().replace('\\', '/')
    if 'server.py' in p:
        return 'HTTP 서버 — 라우팅, SSE, WebSocket, 정적 파일 서빙'
    if '/api/' in p:
        name = Path(rel_path).stem
        return f'API 모듈 — {name} 관련 엔드포인트'
    if 'pg_store' in p:
        return 'PostgreSQL 데이터 계층 — 스키마 + CRUD'
    if 'zettelkasten' in p:
        return '제텔카스텐 지식 관리 모듈'
    if '.tsx' in p or '.ts' in p:
        name = Path(rel_path).stem
        return f'React 컴포넌트/모듈 — {name}'
    if '/scripts/' in p:
        name = Path(rel_path).stem
        return f'유틸리티 스크립트 — {name}'
    if 'hook' in p:
        return 'Claude Code 훅 핸들러'
    if 'test' in p:
        return '테스트 코드'
    return f'프로젝트 파일 — {Path(rel_path).name}'


# ── 유틸리티 ──────────────────────────────────────────────────────────────

def _extract_area_tags(files: list[str]) -> list[str]:
    """파일 경로에서 영역 태그를 추출한다."""
    tags = set()
    for f in files:
        f_lower = f.lower().replace('\\', '/')
        if 'vibe-view' in f_lower or '.tsx' in f_lower or '.ts' in f_lower:
            tags.add(_AREA_TAG_KO.get('ui', 'UI'))
        if '/api/' in f_lower:
            tags.add(_AREA_TAG_KO.get('backend', '백엔드'))
        if 'pg_store' in f_lower or 'zettelkasten' in f_lower:
            tags.add(_AREA_TAG_KO.get('db', 'DB'))
        if '/scripts/' in f_lower:
            tags.add(_AREA_TAG_KO.get('scripts', '스크립트'))
        if 'hook' in f_lower:
            tags.add(_AREA_TAG_KO.get('hooks', '훅'))
        if 'test' in f_lower:
            tags.add(_AREA_TAG_KO.get('test', '테스트'))
    return list(tags)


def _rel_path(file_path: str) -> str:
    """절대 경로를 프로젝트 루트 기준 상대 경로로 변환."""
    try:
        return str(Path(file_path).relative_to(_PROJECT_ROOT))
    except ValueError:
        return Path(file_path).name


def _sync_vault():
    """Obsidian vault에 동기화 (로컬 + Google Drive, 에러 무시)."""
    try:
        from zettel_sync import export_to_vault
        export_to_vault(DEFAULT_VAULT_DIR, project_id=DEFAULT_PROJECT)
        # Google Drive vault도 동기화 (존재할 때만)
        if GDRIVE_VAULT_DIR and GDRIVE_VAULT_DIR.exists():
            export_to_vault(GDRIVE_VAULT_DIR, project_id=DEFAULT_PROJECT)
    except Exception as e:
        print(f"[zettel_capture] vault 동기화 실패 (무시): {e}")


# ── CLI 엔트리포인트 ──────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(description='제텔카스텐 자동 캡처 엔진')
    parser.add_argument('--mode', required=True,
                        choices=['commit', 'fix', 'decision', 'session', 'file-roles'],
                        help='캡처 모드')
    parser.add_argument('--agent', default='claude', help='에이전트 이름')
    parser.add_argument('--data', default='{}', help='이벤트 데이터 (JSON 문자열)')
    args = parser.parse_args()

    try:
        data = json.loads(args.data)
    except json.JSONDecodeError:
        data = {}

    if args.mode == 'commit':
        capture_commit(
            commit_msg=data.get('message', ''),
            files=data.get('files', []),
            agent=args.agent,
        )
    elif args.mode == 'fix':
        capture_fix(
            file_path=data.get('file_path', ''),
            old_code=data.get('old_code', ''),
            new_code=data.get('new_code', ''),
            agent=args.agent,
        )
    elif args.mode == 'decision':
        capture_decision(
            context=data.get('context', ''),
            choice=data.get('choice', ''),
            reason=data.get('reason', ''),
            agent=args.agent,
        )
    elif args.mode == 'session':
        capture_session(agent=args.agent)
    elif args.mode == 'file-roles':
        capture_file_roles(
            commit_msg=data.get('message', ''),
            files=data.get('files', []),
            agent=args.agent,
        )


if __name__ == '__main__':
    main()
