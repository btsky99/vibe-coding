<!--
FILE: progress.md
DESCRIPTION: 프로젝트 진행 상황 추적 파일. 모든 에이전트가 세션 시작 시 읽고, 작업 완료 시 갱신한다.

REVISION HISTORY:
- 2026-03-30 Claude: 최초 생성 — HARNESS_V2 세션 프로토콜의 핵심 구성 요소
- 2026-04-19 Claude: Platform Phase 2 완료 + 잔여 이슈 현실 반영
-->

# Progress

## 최종 업데이트: 2026-04-19 by Claude

### 완료된 작업 (대시보드 대청소 ~ Platform Phase 2)
- [F001] 터미널 실시간 모니터링 — v3.5 Claude
- [F002] 에이전트 상태 패널 — v3.6 Claude
- [F004] 하네스 검증 시스템 V2 — harness_verify.py 10개 검사
- [F007] EXE 빌드 파이프라인 — v3.6 Claude
- [F008] 하이브 마인드 통합 — v3.7 Claude (hive_tasks 기반으로 재정의)
- HARNESS V2 설계 + 구현 + 자동화(CI + Claude 훅) — 2026-03-30
- 메타버스 오피스 모드 구현 — v3.7.180+
- 하이브 5단계 개선 계획(A/B/C) — 2026-04-15~17 (C.4 포함 전부 완료)
- 제텔카스텐 파이프라인 가동 — 242건 누적
- **UI 대청소** (2026-04-18): MessagesPanel/MessageComposer, CODEWIKI, CodeSearch/CodeGraph, DispatcherPanel, AgentPanel 제거. 실사용 0 기반 정리
- **Platform Phase 1** (2026-04-19): docs/PLATFORM_LAYERS.md — 3-Layer 모델(Host / Common Runtime / Project Extension) 정의 + 경계 불변식 5개
- **Platform Phase 2** (2026-04-19): Layer 1 16개 테이블 project_id 스코프 통일
  - 단계 1: 값 정규화 1,825건 UPDATE
  - 단계 2: 3개 테이블 컬럼 RENAME (project → project_id), 깊은 코드 관통 15개 파일
  - 단계 3: 11개 테이블 컬럼 신설 + 2,358건 backfill
- 하네스 꼬리 정리 — 폐기된 auto_dispatcher/AgentPanel 등록 해제

### 진행 중
- [F003] LLM 그룹 채팅 — 기본 구현 완료, 컨텍스트 메뉴 검증 대기. sprint_contracts/sprint_F003_20260419.md
- [F005] Generator-Evaluator 파이프라인 — 솔로 모드에서 harness_verify.py로 기계적 대체 동작 중. sprint_contracts/sprint_F005_20260419.md
- [F006] 세션 시작 프로토콜 — Claude 자동(훅), Gemini/Codex 수동. sprint_contracts/sprint_F006_20260419.md

### 남은 작업 (Platform Phase 3 이후)
- **Phase 3**: `.vibe/` 컨벤션 스캐너 — 프로젝트 루트의 `.vibe/skills`, `.vibe/agents` 자동 로드
- **Phase 4**: Obsidian Vault 연동 — `zettel_notes` ↔ Markdown 양방향
- **Phase 5**: 플랫폼 빌드 분리 — 리포 개발 코드와 배포 IDE 런타임 분리

### 남은 하네스 WARN
- `hot-file-large:.ai_monitor/server.py:6344>5000` — 모듈 분리 필요 (별도 스프린트)
- `hot-file-large:.ai_monitor/vibe-view/src/components/TerminalSlot.tsx:1243>1200` — 43줄만 초과, 소폭 리팩터링으로 가능

### 다음 세션 시작 시 참고사항
- 하네스 V2 가동 중. `status=ok` (34 passes, 2 warnings — 위 hot-file만).
- Platform Layer 경계 준수: 모든 DB 쓰기는 `project_id` 스코프 강제됨.
- 상위 로드맵은 [docs/PLATFORM_LAYERS.md](docs/PLATFORM_LAYERS.md) 참조.
- 세부 실행 계획은 [ai_monitor_plan.md](ai_monitor_plan.md) 참조.
