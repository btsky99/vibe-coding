---
name: 프론트엔드 코딩 컨벤션
description: vibe-view React/TS 코드베이스의 실제 관찰된 패턴 — 인라인 style과 Tailwind 혼용, 폴링 cleanup 패턴
type: project
---

- 스타일: 인라인 style 객체(AgentMonitorPanel)와 Tailwind className(TaskBoardPanel)을 파일 단위로 혼용 중. 통일 기준 없음.
- 폴링 패턴: `let active = true` 플래그 + `clearInterval` 조합으로 cleanup. 일부 파일(TaskBoardPanel 구형 폴링)은 active 플래그 없이 clearInterval만 사용.
- 파생 상태: useMemo로 heartbeatMap, offlineAgents, activeTerminals 등 계산. 단, 렌더 함수 본문 내에서 useMemo 없이 직접 계산하는 사례도 혼재.
- 테스트: 컴포넌트 수준 테스트 거의 없음 (FileExplorer.test.tsx 1개만 확인).

**Why:** 다수 에이전트(Claude/Gemini)가 각자 방식으로 코드를 추가한 결과로 스타일 불일치 발생.
**How to apply:** 리뷰 시 일관성 위반을 Info 수준으로 기록, Critical/Warning은 실제 버그/성능 문제에 집중.
