<!--
FILE: ai_monitor_plan.md
DESCRIPTION: 오피스 모드 부서 시스템 Phase 1 — 코딩 부서 구축
REVISION HISTORY:
- 2026-04-08 Claude: Phase 1 코딩 부서 시스템 계획
-->

# 오피스 부서 시스템 Phase 1: 코딩 부서

**상태:** 실행 중
**목표:** 하드코딩 제거, 부서 기반 조직 구조, 코딩 부서 기본 인재 구성
**원칙:** 클래식 완전 분리, 부서/직원 동적 추가 가능, 최신 모델 사용

---

## Phase 1-A: 데이터 구조 개편

[ ] Task 1: useWorkspaceProfiles 부서(Department) 구조로 개편
    파일: .ai_monitor/vibe-view/src/hooks/useWorkspaceProfiles.ts
    방법:
    - TerminalSlotConfig → AgentSlot (name, role, cli, model, skills, avatar)
    - WorkspaceProfile → CompanyProfile (departments 배열)
    - Department 타입 추가 (id, name, color, icon, agents)
    - 기본 프로필: "코딩 부서" (9명)
      - 기획자: claude opus-4-6, skills: [brainstorm, write-plan]
      - 아키텍트: claude opus-4-6, skills: [brainstorm]
      - 프론트엔드: gemini 2.5-pro, skills: [code]
      - 백엔드: claude sonnet-4-6, skills: [code]
      - 풀스택: gemini 2.5-flash, skills: [code]
      - 코드 리뷰어: claude opus-4-6, skills: [code-review]
      - QA 테스터: codex o4-mini, skills: [tdd]
      - 보안 담당: claude opus-4-6, skills: [security]
      - DevOps: codex gpt-4.1, skills: [release]
    - localStorage 마이그레이션 (기존 flat slots → department 구조)
    검증: 새 구조로 localStorage 저장/로드 정상

[ ] Task 2: useOfficeState에 부서 정보 반영
    파일: .ai_monitor/vibe-view/src/hooks/useOfficeState.ts
    의존: Task 1
    방법:
    - profileSlots 대신 departments 배열 받기
    - presences에 department, role, skills 필드 추가
    - 존(zone) 매핑: department → 해당 부서 공간
    검증: presences에 부서/역할 정보 포함 확인

---

## Phase 1-B: UI 개편

[ ] Task 3: 에이전트 사이드바를 부서별 그룹으로 변경
    파일: .ai_monitor/vibe-view/src/components/office/OfficeApp.tsx
    의존: Task 1
    방법:
    - 사이드바: 부서명 헤더 + 하위 에이전트 목록
    - 부서 색상으로 시각 구분
    - 에이전트에 역할(role) + 아이콘 표시
    - 편집 모달에 역할/스킬 편집 추가
    - 부서 추가/삭제 기능
    검증: 부서별 그룹핑 표시, 편집 작동

[ ] Task 4: OfficeWorld 부서 공간 시각화
    파일: .ai_monitor/vibe-view/src/components/office/OfficeWorld.tsx
    의존: Task 2
    방법:
    - ZONE_LAYOUT의 하드코딩 존 → 동적 부서 공간
    - 각 부서 영역에 부서명 + 색상 표시
    - 에이전트를 소속 부서 공간에 배치
    - 회의실은 공용 공간으로 유지
    검증: 부서별 공간에 에이전트 정확히 배치

[ ] Task 5: 채팅 패널 부서 연동
    파일: .ai_monitor/vibe-view/src/components/office/OfficeChatPanel.tsx
    의존: Task 1
    방법:
    - 1:1 모드: 에이전트 역할 표시 (예: "시니어 백엔드")
    - 회의실: 부서 단위 그룹챗 지원
    - 에이전트 아바타에 역할 아이콘 반영
    검증: 채팅에서 부서/역할 정보 표시
