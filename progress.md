<!--
FILE: progress.md
DESCRIPTION: 프로젝트 진행 상황 추적 파일. 모든 에이전트가 세션 시작 시 읽고, 작업 완료 시 갱신한다.

REVISION HISTORY:
- 2026-03-30 Claude: 최초 생성 — HARNESS_V2 세션 프로토콜의 핵심 구성 요소
-->

# Progress

## 최종 업데이트: 2026-03-30 by Claude

### 완료된 작업
- [F001] 터미널 실시간 모니터링 — v3.5 Claude
- [F002] 에이전트 상태 패널 — v3.6 Claude
- [F007] EXE 빌드 파이프라인 — v3.6 Claude
- [F008] 하이브 마인드 통합 — v3.7 Claude
- HARNESS V2 설계 + 구현 + 자동화(CI + Claude 훅) — 2026-03-30
- 코드 품질 감사 Phase 1+2 수정 완료 — 2026-03-30

### 진행 중
- [F003] LLM 그룹 채팅 — 기본 구현 완료, 컨텍스트 메뉴 검증 필요
- [F004] 하네스 검증 시스템 V2 — harness_verify.py V2 완료, CI 게이트 설정 완료
- [F005] Generator-Evaluator 파이프라인 — HARNESS_V2.md 설계 완료, 운영 단계 미적용
- [F006] 세션 시작 프로토콜 — Claude 자동(훅), Gemini/Codex 수동

### 코드 품질 감사 수정 이력 (2026-03-30)
- **Phase 1 (보안)**: SQL 인젝션 수정 (itcp.py send/receive/history, shared_history.py)
- **Phase 1 (버그)**: pg_store.py _HAS_PSYCOPG2 global 선언 누락 수정
- **Phase 1 (성능)**: pg_store.py 커넥션 락 과점유 → 락 범위 최소화
- **Phase 2 (프론트)**: TerminalSlot.tsx stale closure 재연결 버그 수정 (ref 기반)
- **Phase 2 (프론트)**: TerminalSlot.tsx window.resize 메모리 누수 수정

### 미수정 잔여 이슈 (Phase 3-4)
- server.py 5207줄 → 모듈 분리 필요 (HARNESS 경고)
- AgentPanel.tsx 2934줄 → 컴포넌트 분리 필요 (HARNESS 경고)
- 중복 API 폴링 (App.tsx + AgentPanel.tsx)
- any 타입 전파 (agentTerminals, hiveActivity)
- bare except 패턴 60회+ → 로깅 추가 필요

### 다음 세션 시작 시 참고사항
- HARNESS V2 완전 가동 중. 하네스 검증은 매 프롬프트마다 자동 실행됨.
- Phase 3(구조: server.py 분리, AgentPanel 분리)가 다음 우선순위.
- sprint_contracts/ 디렉토리 아직 미생성 (첫 스프린트 계약 시 생성 예정)
