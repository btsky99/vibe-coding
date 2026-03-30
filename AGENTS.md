# 🤖 하이브 에이전트 구성 (AGENTS.md)

이 파일은 하이브 마인드의 짧은 진입점입니다. 세부 규칙은 아래 문서를 source of truth로 사용합니다.

## 1. 공통 Source of Truth
- [RULES.md](./RULES.md): 모든 에이전트의 공통 행동 규칙
- [docs/HARNESS_V2.md](./docs/HARNESS_V2.md): Claude, Gemini, Codex 공통 하네스 계약 (V2 — Generator-Evaluator, 세션 프로토콜, Feature List)
- [docs/HARNESS_CHECKS.md](./docs/HARNESS_CHECKS.md): 저장소가 하네스를 계속 지키는지 확인하는 기계적 검사
- [PROJECT_MAP.md](./PROJECT_MAP.md): 코드베이스 지도
- [CLAUDE.md](./CLAUDE.md): Claude 전용 가이드
- [GEMINI.md](./GEMINI.md): Gemini 전용 가이드
- [CODEX_GUIDE.md](./CODEX_GUIDE.md): Codex 전용 가이드
- [ai_monitor_plan.md](./ai_monitor_plan.md): 현재 활성 계획과 작업 순서

## 2. 공통 실행 계약
1. 작업 시작 전 `RULES.md`, 관련 계획 문서, 관련 코드 경로를 먼저 읽습니다.
2. 코드 변경은 가능한 한 격리된 worktree에서 수행하고, worktree가 없으면 생성 가능한지 먼저 확인합니다.
3. 에이전트 간 지시와 결과 공유는 ITCP(`pg_messages`)를 우선 사용합니다.
4. 작업 완료 전에는 변경 범위에 맞는 최소 검증을 직접 실행합니다.
5. 반복되는 실패나 지침은 대화에만 남기지 말고 문서, 테스트, 스크립트, lint 규칙으로 승격합니다.

## 3. 역할

### 🔵 Gemini
- 역할: 전체 설계, 오케스트레이션, 계획 승인, 데이터/ML 전략
- 강점: 아키텍처 판단, 작업 분해, 흐름 조율
- 주 가이드: [GEMINI.md](./GEMINI.md)

### 🟠 Claude
- 역할: 정밀 구현, 프론트엔드 품질, UX, 고난도 로직 리팩터링
- 강점: UI/상호작용 품질, 시각적 완성도, 복잡한 구현 정리
- 주 가이드: [CLAUDE.md](./CLAUDE.md)

### 🟢 Codex
- 역할: 터미널 작업, 테스트 작성, 반복 리팩터링, 백그라운드 실행
- 강점: 빠른 수정, 검증 자동화, 스크립트/테스트 보강
- 주 가이드: [CODEX_GUIDE.md](./CODEX_GUIDE.md)

## 4. 하이브 오케스트레이션
1. ITCP: PostgreSQL `pg_messages` 기반 비동기 메시징
2. Auto Dispatcher: 작업 성격에 맞는 에이전트 자동 배정
3. Thought Logging: `vibe_agent_thoughts`에 사고 흐름 기록

## 5. 문서 원칙
- `AGENTS.md`는 길게 키우지 않습니다. 이 파일은 목차 역할만 합니다.
- 세부 지식은 `docs/`와 역할별 가이드에 둡니다.
- 새 규칙이 생기면 가능한 한 검증 스크립트나 테스트로 같이 고정합니다.
