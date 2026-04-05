---
name: 반복 발견 안티패턴
description: 여러 리뷰에서 반복적으로 발견된 안티패턴 목록 — 향후 리뷰 시 우선 점검 대상
type: project
---

## 오프라인 에이전트 감지 로직 중복 (2026-04-05 최초 발견)
- AgentMonitorPanel과 TaskBoardPanel 양쪽에 `(Date.now() - new Date(last_beat).getTime()) / 1000 > 300` 로직이 독립적으로 존재.
- TaskBoardPanel은 렌더 내 JSX 표현식에서 `.some()` + `.filter()` 두 번 호출 (동일 연산 반복).
- 권장: 공유 훅 `useOfflineAgents(agents)` 또는 유틸 함수로 추출.

## 렌더 중 고비용 연산 (2026-04-05 최초 발견)
- TaskBoardPanel `OrgAgentCard` 컴포넌트 내 `color` 계산을 즉시실행함수(IIFE)로 인라인 처리.
- useMemo/상수 맵 대신 렌더마다 Date 객체 생성 + 산술 연산 수행.

## key={index} 사용 (2026-04-05 최초 발견)
- AgentMonitorPanel RECENT ACTIVITY 섹션: `key={\`log-\${i}\`}` — 인덱스 기반 키.
- 로그 목록이 갱신되면 불필요한 DOM 재생성 발생 가능.

## useMemo 훅 규칙 위반 (2026-04-05 최초 발견)
- AgentMonitorPanel: `offlineAgents` useMemo가 얼리 리턴(loading/empty 분기) 이후에 선언됨.
- React Hooks 규칙 위반 — 조건부 실행 경로에 따라 훅 호출 순서가 달라질 수 있음.
