<!--
FILE: .codex/rules/hive-sync.md
DESCRIPTION: Codex-side hive synchronization procedure and agent role guide
REVISION HISTORY:
- 2026-04-05 Codex: Added Codex-side hive sync procedure split from top-level guide
-->

# Codex Hive Sync

## Session Start
```bash
python scripts/memory.py list
python scripts/analyze_hive.py
python scripts/orchestrator.py --summary
Get-Content ai_monitor_plan.md
```

## Operating Rules
1. 시작 전에 shared memory, current plan, hive summary를 확인한다.
2. 다른 에이전트와의 지시/결과 공유는 ITCP(`pg_messages`)를 우선 사용한다.
3. 장기 작업이나 충돌 위험이 있으면 git worktree 사용 가능 여부를 먼저 본다.
4. 완료 전에 변경 범위 기준 최소 검증을 실행한다.
5. 완료 후 필요한 로그, 메모, 결과는 PostgreSQL 중심 흐름에 남긴다.

## Agent Roles
- Gemini: 전체 설계, 작업 분해, 오케스트레이션, 데이터/ML 방향.
- Claude: 정밀 구현, UI/UX 품질, 복잡한 리팩터링.
- Codex: 터미널 실행, 테스트 보강, 자동화, 반복 수정, 빠른 검증.

## Codex Workflow
1. 요구사항과 관련 소스 문서를 읽는다.
2. 관련 코드와 테스트를 먼저 찾는다.
3. 필요한 경우 ITCP로 맥락이나 검증을 요청한다.
4. 구현 후 로컬 검증을 수행한다.
5. 결과를 짧게 요약하고 다음 에이전트가 이어받을 수 있게 남긴다.
