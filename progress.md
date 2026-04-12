<!--
FILE: progress.md
DESCRIPTION: 프로젝트 진행 상황 추적 파일. 모든 에이전트가 세션 시작 시 읽고, 작업 완료 시 갱신한다.

REVISION HISTORY:
- 2026-03-30 Claude: 최초 생성 — HARNESS_V2 세션 프로토콜의 핵심 구성 요소
-->

# Progress

## 최종 업데이트: 2026-04-12 by Claude

### 완료된 작업
- [F001] 터미널 실시간 모니터링 — v3.5 Claude
- [F002] 에이전트 상태 패널 — v3.6 Claude
- [F007] EXE 빌드 파이프라인 — v3.6 Claude
- [F008] 하이브 마인드 통합 — v3.7 Claude
- [F004] 하네스 검증 시스템 V2 — harness_verify.py 10개 검사 완료
- HARNESS V2 설계 + 구현 + 자동화(CI + Claude 훅) — 2026-03-30
- 코드 품질 감사 Phase 1+2 수정 완료 — 2026-03-30
- 메타버스 오피스 모드 구현 — v3.7.180+ Claude
- 클래식 모드 안정성 전면 개선 — v3.7.193
- 로컬 EXE smoke test 자동화 — v3.7.194
- 하네스를 AI 도구 목록에 통합 — 2026-04-12

### 진행 중
- [F003] LLM 그룹 채팅 — 기본 구현 완료
- [F005] Generator-Evaluator 파이프라인 — 솔로 모드에서는 harness_verify.py로 대체
- [F006] 세션 시작 프로토콜 — Claude 자동(훅), Gemini/Codex 수동
- 하네스 경량화 — 도구 목록에서 원클릭 설치 가능하도록 개선 중

### 미수정 잔여 이슈
- server.py 6046줄 → 모듈 분리 필요 (HARNESS 경고, 5000줄 초과)
- AgentPanel.tsx 2934줄 → 컴포넌트 분리 필요 (HARNESS 경고, 2500줄 초과)
- TerminalSlot.tsx 1243줄 → 경고 수준 (1200줄 초과)
- hook_bridge.py 중복 등록 수정 완료 (2026-04-12)

### 다음 세션 시작 시 참고사항
- 하네스 V2 가동 중. 검증은 매 프롬프트마다 자동 실행됨.
- AI 도구 목록에 harness 카테고리 3개 항목 추가됨 (hooks, rules, verify)
- install_harness.py로 다른 프로젝트에도 경량 하네스 설치 가능
