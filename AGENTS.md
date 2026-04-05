<!--
FILE: AGENTS.md
DESCRIPTION: Hive agent entrypoint with principles only
REVISION HISTORY:
- 2026-04-05 Codex: Reduced AGENTS.md to a short index of core principles and source-of-truth docs
-->

# Hive Agents

이 파일은 요약 진입점이다. 상세 설명은 넣지 않고 원문 문서를 source of truth로 사용한다.

## Read First
- [RULES.md](./RULES.md): 공통 규칙, 실행 원칙, 커밋 규칙
- [docs/HARNESS_V2.md](./docs/HARNESS_V2.md): 하네스 계약, 세션 프로토콜, 기능 범위
- [docs/HARNESS_CHECKS.md](./docs/HARNESS_CHECKS.md): 하네스 준수 검사
- [PROJECT_MAP.md](./PROJECT_MAP.md): 코드베이스 지도
- [CODEX_GUIDE.md](./CODEX_GUIDE.md): Codex 전용 가이드
- [CLAUDE.md](./CLAUDE.md): Claude 전용 가이드
- [GEMINI.md](./GEMINI.md): Gemini 전용 가이드
- [ai_monitor_plan.md](./ai_monitor_plan.md): 현재 활성 계획과 작업 순서
- [docs/API_SPEC.md](./docs/API_SPEC.md): API 목록과 계약

## Core Principles
1. 작업 전에는 `RULES.md`, 관련 계획, 관련 코드 경로를 먼저 읽는다.
2. `AGENTS.md`는 짧게 유지하고 세부 지식은 개별 문서에 둔다.
3. 코드 변경은 가능한 한 격리된 git worktree에서 수행한다.
4. 에이전트 간 협업과 결과 공유는 ITCP(`pg_messages`)를 우선 사용한다.
5. 로그, 메모리, 상태 저장은 프로젝트의 PostgreSQL 중심 흐름을 따른다.
6. 아키텍처 상세와 API 계약은 이 파일에 복제하지 않고 원문 문서를 따른다.
7. 역할 분담은 Gemini=설계/조율, Claude=정밀 구현/UI, Codex=터미널/테스트/자동화로 본다.
8. 작업 완료 전에는 변경 범위에 맞는 최소 검증을 직접 실행한다.
9. 반복 실패와 운영 규칙은 대화에만 남기지 말고 문서, 테스트, 스크립트, lint로 승격한다.
10. 커밋 규칙은 `RULES.md`의 Conventional Commits + 상세 본문 요구사항을 따른다.

## Document Rule
- 프로젝트 소개, 규칙, 아키텍처 상세, API 목록, 하이브 절차, 커밋 규칙을 이 파일 하나에 장문으로 합치지 않는다.
- 이 파일은 "어디를 읽어야 하는지"만 알려주는 1차 인덱스 역할을 한다.
