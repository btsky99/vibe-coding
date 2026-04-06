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

DEFAULT_VAULT_DIR = _PROJECT_ROOT / '.zettel-vault'
DEFAULT_PROJECT = os.environ.get('VIBE_PROJECT', 'D--vibe-coding')

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

    # 태그 생성
    tags = [commit_type]
    if files:
        # 파일 경로에서 영역 태그 추출 (예: vibe-view → ui, api → backend)
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
        project=DEFAULT_PROJECT,
        tags=tags,
        source_ref=f"git-commit:{commit_type}",
    )

    if note:
        # 유사 노트 자동 연결
        auto_link(note['id'], content=content, tags=tags, created_by=agent)
        _sync_vault()
        print(f"[zettel_capture] 커밋 노트 생성: {note['id']} — {title} ({note_type})")

    return note


def capture_fix(file_path: str, old_code: str, new_code: str,
                agent: str = 'claude') -> dict | None:
    """버그 수정 감지 → permanent 노트 (원인 + 해결법)."""
    ensure_schema()
    if not file_path:
        return None

    rel_path = _rel_path(file_path)
    title = f"버그 수정: {rel_path}"
    tags = ['fix', 'bug']
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
        project=DEFAULT_PROJECT,
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
    tags = ['decision', 'architecture']

    content = f"## 맥락\n{context}\n\n## 선택\n{choice}\n\n## 이유\n{reason}"

    note = create_note(
        title=title,
        content=content,
        note_type='permanent',
        author=agent,
        project=DEFAULT_PROJECT,
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
    tags = ['session']

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
        project=DEFAULT_PROJECT,
        tags=tags,
        source_ref='session-summary',
    )

    if note:
        auto_link(note['id'], content=content, tags=tags, created_by=agent)
        _sync_vault()
        print(f"[zettel_capture] 세션 요약 노트 생성: {note['id']} — {title}")

    return note


# ── 유틸리티 ──────────────────────────────────────────────────────────────

def _extract_area_tags(files: list[str]) -> list[str]:
    """파일 경로에서 영역 태그를 추출한다."""
    tags = set()
    for f in files:
        f_lower = f.lower().replace('\\', '/')
        if 'vibe-view' in f_lower or '.tsx' in f_lower or '.ts' in f_lower:
            tags.add('ui')
        if '/api/' in f_lower:
            tags.add('backend')
        if 'pg_store' in f_lower or 'zettelkasten' in f_lower:
            tags.add('db')
        if '/scripts/' in f_lower:
            tags.add('scripts')
        if 'hook' in f_lower:
            tags.add('hooks')
        if 'test' in f_lower:
            tags.add('test')
    return list(tags)


def _rel_path(file_path: str) -> str:
    """절대 경로를 프로젝트 루트 기준 상대 경로로 변환."""
    try:
        return str(Path(file_path).relative_to(_PROJECT_ROOT))
    except ValueError:
        return Path(file_path).name


def _sync_vault():
    """Obsidian vault에 동기화 (에러 무시)."""
    try:
        from zettel_sync import export_to_vault
        export_to_vault(DEFAULT_VAULT_DIR)
    except Exception as e:
        print(f"[zettel_capture] vault 동기화 실패 (무시): {e}")


# ── CLI 엔트리포인트 ──────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(description='제텔카스텐 자동 캡처 엔진')
    parser.add_argument('--mode', required=True,
                        choices=['commit', 'fix', 'decision', 'session'],
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


if __name__ == '__main__':
    main()
