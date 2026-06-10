#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
FILE: scripts/checkpoint.py
DESCRIPTION: 의도 단위 세션 체크포인트 CLI — "왜/어디까지 결정/다음 뭐" 3요소를
             active_session_context에 기록. 크래시 복구 브리핑이 파일 목록 대신
             의도를 보여주게 한다. 자가 치유 2.0 ② (Task 13).

REVISION HISTORY:
- 2026-06-10 Claude: 최초 구현

사용법:
  python scripts/checkpoint.py "server.py 분할 단계 9 진행"            # 의도만
  python scripts/checkpoint.py "분할 진행" --decided "DaemonEnv 주입 방식 채택" --next "spec 동기 후 커밋"
"""
import argparse
import os
import sys
from pathlib import Path

_PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_PROJECT_ROOT / '.ai_monitor'))


def main():
    parser = argparse.ArgumentParser(description='의도 단위 체크포인트 — 튕겨도 설명 없이 이어받기')
    parser.add_argument('intent', help='지금 하는 작업의 의도 (왜)')
    parser.add_argument('--decided', default='', help='이번 단계에서 내린 결정 (누적 기록)')
    parser.add_argument('--next', dest='next_step', default='', help='다음 할 일')
    parser.add_argument('--terminal', default='', help='터미널 ID (기본: env TERMINAL_ID)')
    args = parser.parse_args()

    from src.pg_schema import ensure_schema
    if not ensure_schema():
        print('[!] PostgreSQL 연결 실패 — 체크포인트 기록 불가')
        sys.exit(1)
    from src.pg_store import set_session_checkpoint
    from infra.project_context import slugify

    # 훅(hive_hook)과 동일 규칙 — TERMINAL_ID env가 세션 식별의 단일 진실
    terminal_id = args.terminal or os.environ.get('TERMINAL_ID', 'T0')
    ok = set_session_checkpoint(
        terminal_id=terminal_id,
        intent=args.intent,
        decision=args.decided,
        next_step=args.next_step,
        project_id=slugify(_PROJECT_ROOT),
    )
    if ok:
        parts = [f"✅ 체크포인트 [{terminal_id}] 의도: {args.intent[:60]}"]
        if args.decided:
            parts.append(f"결정: {args.decided[:60]}")
        if args.next_step:
            parts.append(f"다음: {args.next_step[:60]}")
        print(' | '.join(parts))
    else:
        print('[!] 체크포인트 기록 실패')
        sys.exit(1)


if __name__ == '__main__':
    main()
