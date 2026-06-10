#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
FILE: scripts/lesson.py
DESCRIPTION: 세션 교훈 증류 CLI — propose(후보 적재) / list / approve(승인 시
             .claude/rules/lessons.md append) / reject. 자가 치유 2.0 ③ (Task 16).

REVISION HISTORY:
- 2026-06-10 Claude: 최초 구현
  - [불변식] lessons.md 쓰기는 approve 경로 단 하나 — 승인 게이트.
    CLAUDE.md 본문 자동 수정은 어떤 경로로도 금지 (brainstorm 승인 결정).

사용법:
  python scripts/lesson.py propose "WebView 리로드 안내는 앱 재시작으로" --why "브라우저 아님"
  python scripts/lesson.py list
  python scripts/lesson.py approve 3
  python scripts/lesson.py reject 3
"""
import argparse
import sys
import time
from pathlib import Path

_PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_PROJECT_ROOT / '.ai_monitor'))

_LESSONS_MD = _PROJECT_ROOT / '.claude' / 'rules' / 'lessons.md'
_KEY_PREFIX = 'lesson-candidate:'


def _store():
    from src.pg_schema import ensure_schema
    if not ensure_schema():
        print('[!] PostgreSQL 연결 실패')
        sys.exit(1)
    from src.pg_base import query_rows, execute, _sql_text
    return query_rows, execute, _sql_text


def _candidates(query_rows, _sql_text):
    return query_rows(
        f"SELECT key, content, created_at FROM hive_memory "
        f"WHERE key LIKE {_sql_text(_KEY_PREFIX + '%')} ORDER BY key;"
    )


def main():
    parser = argparse.ArgumentParser(description='세션 교훈 증류 — 승인된 것만 lessons.md로')
    sub = parser.add_subparsers(dest='cmd', required=True)
    p_prop = sub.add_parser('propose', help='교훈 후보 제안 (파일 미변경)')
    p_prop.add_argument('lesson', help='교훈 본문 (1~3줄)')
    p_prop.add_argument('--why', default='', help='이 교훈이 나온 근거(사건)')
    sub.add_parser('list', help='대기 중인 후보 목록')
    p_appr = sub.add_parser('approve', help='후보 승인 → lessons.md append')
    p_appr.add_argument('num', type=int, help='list에 표시된 번호')
    p_rej = sub.add_parser('reject', help='후보 폐기')
    p_rej.add_argument('num', type=int)

    args = parser.parse_args()
    query_rows, execute, _sql_text = _store()

    if args.cmd == 'propose':
        from src.pg_store import set_memory
        from infra.project_context import slugify
        now = time.strftime('%Y-%m-%dT%H:%M:%S')
        key = f"{_KEY_PREFIX}{time.strftime('%Y%m%d%H%M%S')}"
        body = args.lesson.strip()
        if args.why:
            body += f"\n근거: {args.why.strip()}"
        set_memory(key=key, title=f'교훈 후보: {args.lesson[:50]}', content=body,
                   tags=['lesson-candidate'], author='claude',
                   project_id=slugify(_PROJECT_ROOT), created_at=now, updated_at=now)
        print(f"📥 교훈 후보 적재 완료 — 사용자 승인 대기. 승인: lesson.py list → approve <번호>")
        return

    cands = _candidates(query_rows, _sql_text)
    if args.cmd == 'list':
        if not cands:
            print('대기 중인 교훈 후보 없음')
            return
        for i, c in enumerate(cands, 1):
            first = str(c['content']).split('\n')[0]
            print(f"  [{i}] {first[:80]}")
        print(f"\n승인: python scripts/lesson.py approve <번호> / 폐기: reject <번호>")
        return

    if not (1 <= args.num <= len(cands)):
        print(f'[!] 번호 범위 밖: 1~{len(cands)}')
        sys.exit(1)
    target = cands[args.num - 1]

    if args.cmd == 'approve':
        # [불변식] lessons.md 쓰기는 이 블록이 유일한 경로 — 승인 게이트
        date = time.strftime('%Y-%m-%d')
        entry = f"\n## {date} — {str(target['content']).splitlines()[0][:60]}\n"
        for line in str(target['content']).splitlines():
            entry += f"{line}\n"
        with open(_LESSONS_MD, 'a', encoding='utf-8') as f:
            f.write(entry)
        execute(f"DELETE FROM hive_memory WHERE key = {_sql_text(target['key'])};")
        print(f"✅ 교훈 승인 → {_LESSONS_MD.relative_to(_PROJECT_ROOT)} 추가 완료 (매 세션 자동 로드)")

    elif args.cmd == 'reject':
        execute(f"DELETE FROM hive_memory WHERE key = {_sql_text(target['key'])};")
        print('🗑️ 후보 폐기 완료')


if __name__ == '__main__':
    main()
