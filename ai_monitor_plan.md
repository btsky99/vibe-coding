# 🤖 AI 모니터링 및 UI 개선 계획 (AI Monitor & UI Improvement Plan)

## 🎯 목표
- 터미널 상단의 중복된 3단계(분석/수정/검증) 파이프라인 표시를 왼쪽 메뉴(Activity Bar)로 통합.
- 새로 추가된 엔진(자가 치유, 하이브 코어)의 상태를 한눈에 볼 수 있는 통합 인디케이터 구현.
- 터미널 슬롯의 모니터링 뷰를 슬림화하여 작업 공간 극대화.

## 📅 일정 (2026-03-06)

### 1단계: 데이터 파이프라인 및 상태 통합
- [ ] `App.tsx`: 모든 터미널의 `agentTerminals` 데이터를 분석하여 글로벌 엔진 상태(최고 우선순위 단계) 계산 로직 추가.
- [ ] `App.tsx`: `hive_health.json`을 폴링하여 자가 치유 엔진의 활성 상태 확인.

### 2단계: ActivityBar 통합 인디케이터 구현
- [ ] `ActivityBar.tsx`: 최상단에 `HiveEngineStatus` 영역 추가.
- [ ] `ActivityBar.tsx`: 3단계 LED 링(Cyan/Yellow/Purple) 및 자가 치유 Live Dot 구현.
- [ ] `ActivityBar.tsx`: 엔진 아이콘 클릭 시 '중앙 통제실(AgentPanel)'로 즉시 이동하는 기능.

### 3단계: TerminalSlot UI 슬림화 리팩토링
- [ ] `TerminalSlot.tsx`: 상단 `showMonitor` 영역(파이프라인 단계 표시부) 제거 또는 선택적 최소화.
- [ ] `TerminalSlot.tsx`: 헤더 디자인을 더 얇고 간결하게 수정하여 터미널 가로/세로 공간 확보.

### 4단계: 검증 및 기록
- [ ] 전체 레이아웃에서 상태 동기화 확인 (에이전트 실행 시 ActivityBar LED 반응 테스트).
- [ ] `PROJECT_MAP.md` 업데이트 및 작업 완료 보고.

## 🛠️ 기술 스택
- React (TypeScript)
- Tailwind CSS
- Lucide React (Icons)
- Framer Motion (Animations)
