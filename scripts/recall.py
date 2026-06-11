#!/usr/bin/env python3
"""
FILE: scripts/recall.py
DESCRIPTION: 경험 회상 스크립트 — 현재 작업과 유사한 과거 경험을 검색하여 출력.
             하네스 훅이나 CLI에서 호출하여 에이전트 컨텍스트에 주입할 수 있다.

REVISION HISTORY:
- [2026-04-10] Claude: 최초 구현 — 진화하는 LLM Phase 2

사용법:
  python scripts/recall.py "오피스 채팅 버그"
  python scripts/recall.py "프론트엔드 리팩토링" --domain frontend --limit 3
"""

import argparse
import sys
from pathlib import Path

# 프로젝트 루트 → ai_monitor 패키지 경로 추가
_PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_PROJECT_ROOT / '.ai_monitor'))


def main():
    parser = argparse.ArgumentParser(description='경험 회상 — 유사 과거 작업 검색')
    parser.add_argument('query', help='검색할 작업 설명')
    parser.add_argument('--domain', default='', help='도메인 필터 (frontend/backend/db/infra)')
    parser.add_argument('--agent', default='', help='에이전트 필터 (claude/antigravity/codex)')
    parser.add_argument('--limit', type=int, default=5, help='결과 수 (기본: 5)')
    parser.add_argument('--json', action='store_true', help='JSON 형식 출력')
    args = parser.parse_args()

    from src.pg_store import ensure_schema, recall_similar_experience, recall_context_summary
    ensure_schema()

    if args.json:
        import json
        results = recall_similar_experience(
            args.query, domain=args.domain, agent_id=args.agent, limit=args.limit
        )
        print(json.dumps(results, ensure_ascii=False, default=str, indent=2))
    else:
        summary = recall_context_summary(args.query, domain=args.domain, limit=args.limit)
        if summary:
            print(summary)
        else:
            print(f"'{args.query}'와 관련된 과거 경험이 없습니다.")


if __name__ == '__main__':
    main()
