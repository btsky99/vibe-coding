# UI 개선 — 자율 에이전트 메뉴 단일화 및 T1 가시성 확보

## 목표
- 왼쪽 메뉴(ActivityBar)의 중복을 제거하고 역할을 명확히 함.
- 자율 에이전트 상황판을 2열 그리드로 복구하여 T1 등 주요 터미널이 한눈에 보이게 함.

## 날짜: 2026-03-07

---

- [x] Task 1: ActivityBar.tsx 최상단 번개 아이콘 클릭 기능 제거
    파일: .ai_monitor/vibe-view/src/components/ActivityBar.tsx
    방법: 최상단 `Zap` 아이콘의 `onClick` 핸들러를 제거하고 `cursor-default` 스타일로 변경 (상태 표시등 전용).
    완료 조건: 최상단 번개 아이콘 클릭 시 아무런 탭 변화가 없을 것.

- [x] Task 2: ActivityBar.tsx 하단 하이브 진단 아이콘 변경
    파일: .ai_monitor/vibe-view/src/components/ActivityBar.tsx
    방법: 189번 줄의 `Zap` 아이콘을 `Activity` 아이콘으로 교체하여 최상단과 시각적 중복 제거.
    완료 조건: 하단 메뉴에 번개 모양 대신 `Activity` 아이콘이 보일 것.

- [x] Task 3: AgentPanel.tsx 상황판 탭 2열 그리드로 복구
    파일: .ai_monitor/vibe-view/src/components/panels/AgentPanel.tsx
    방법: `workflow` 탭의 카드 리스트 컨테이너를 `flex flex-col`에서 `grid grid-cols-2 gap-1.5`로 수정.
    완료 조건: 자율 에이전트 상황판에서 T1, T2 카드가 가로로 나란히 보일 것.

- [x] Task 4: TerminalCard 높이 최적화 및 폰트 크기 조정
    파일: .ai_monitor/vibe-view/src/components/panels/AgentPanel.tsx
    방법: 카드 패딩(py-1.5 -> py-1) 및 폰트 크기를 미세 조정하여 한 화면에 더 많이 보이게 함.
    완료 조건: T1~T4가 스크롤 없이 한 화면에 안정적으로 들어올 것.

- [x] Task 5: 프론트엔드 빌드 및 UI 최종 검증
    파일: .ai_monitor/vibe-view/package.json
    방법: `npm run build`를 실행하여 빌드 오류 여부 확인 및 실제 렌더링 확인.
    완료 조건: 빌드 성공 및 UI 개선 확인.

---

## 검증 시나리오
1. 왼쪽 메뉴 최상단 번개 아이콘 클릭 시 아무 반응 없음 확인.
2. 하단 "하이브 진단" 아이콘이 번개가 아닌 다른 모양으로 변경됨 확인.
3. 자율 에이전트 탭 진입 시 T1, T2가 나란히 보임 확인.
