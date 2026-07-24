<!--
FILE: ai_monitor_plan.md
DESCRIPTION: 터미널 슬롯마다 다른 프로젝트 실행 구현 계획 — 단일 앱 내 슬롯별 프로젝트 + 활성 슬롯 따라 패널 전환.

REVISION HISTORY:
- 2026-07-24 Claude: 신규. 슬롯별 프로젝트 브레인스토밍 승인 → 계획.
                     이전 계획(텔레그램 그룹방 허브화)은 완료(c768e7b, 검증 test_telegram_hub.py) → 교체.
-->

# 터미널 슬롯마다 다른 프로젝트 실행

**상태: 구현 완료 (2026-07-24)** — Task 1~6 전부 완료. tsc+vite 빌드 PASS.
실물 2슬롯 전환 E2E는 앱 재빌드+재시작 후 확인 필요(아래 Task 6 참조).

승인: 2026-07-24 (vibe-brainstorm). 설계 메모리: `project_per_slot_project`.
**결정: ①패널은 활성 슬롯 프로젝트 따라 전환 ②전환은 명시적 "이 프로젝트 보기" 버튼.**
백엔드 무변경 — PTY는 이미 `/pty/slot{id}?cwd=` 슬롯별 cwd 수신, 서버는 `?project_id=` override 지원,
로그 경계는 `b5ded87`에서 수정 완료([[project-hook-cross-project-boundary]]).

## 배경 (왜)
`currentPath`가 App.tsx 전역 상태 하나(83행) → 모든 TerminalSlot·FileExplorer·Git·태스크가 공유 →
앱 전체가 단일 프로젝트. 슬롯을 여러 개 열어도 전부 같은 프로젝트 cwd로 뜬다. 각 터미널을 다른
프로젝트로 돌리려면 슬롯별 프로젝트 오버라이드가 필요하다.

## 대상 파일 현황
- `App.tsx` — `currentPath,setCurrentPath`(83행, 훅 destructure). `slots`=useMemo[0..count](447행).
  FileExplorer `onPathChange={setCurrentPath}`(662행). TerminalSlot 렌더(809행).
- `TerminalSlot.tsx` — 🔴사고다발(lessons.md 3건, 단 이 변경 유형은 신규). props(100~108행),
  WS cwd/projectId(417·420행), 연결배너 CWD(435행).

---

## 태스크

### [ ] Task 1: App.tsx — 슬롯 프로젝트 상태 + localStorage 배선
- **파일**: `.ai_monitor/vibe-view/src/App.tsx`
- **방법**: `slotProjects: Record<number,string>` useState(초기값 localStorage `hive_slot_projects` 파싱,
  실패 시 `{}`) + `activeProjectSlot: number|null` useState. slotProjects 변경 시 localStorage 저장 useEffect.
  핸들러 `setSlotProject(id,path)`, `activateSlotProject(id)`(=`setCurrentPath(slotProjects[id] ?? currentPath)`
  + `setActiveProjectSlot(id)`).
- **검증**: `npx tsc --noEmit` 통과. localStorage `hive_slot_projects` 저장 확인.
- **의존성**: 없음

### [ ] Task 2: App.tsx — TerminalSlot 배선 + FileExplorer 동기
- **파일**: `.ai_monitor/vibe-view/src/App.tsx`
- **방법**: 809행 렌더에 `slotProject={slotProjects[slotId] ?? currentPath}`,
  `isActiveProject={activeProjectSlot===slotId}`, `onActivateProject={()=>activateSlotProject(slotId)}`,
  `onPickProject={(p)=>setSlotProject(slotId,p)}` 전달. FileExplorer onPathChange(662행)를 래퍼로:
  `setCurrentPath(p)` + `activeProjectSlot!=null`이면 `setSlotProject(activeProjectSlot,p)` (뱃지↔패널 동기).
- **검증**: `npx tsc --noEmit`. 슬롯 활성화 시 currentPath 전환 동작.
- **의존성**: Task 1

### [ ] Task 3: TerminalSlot.tsx — WS cwd/projectId를 slotProject 기준으로
- **파일**: `.ai_monitor/vibe-view/src/components/TerminalSlot.tsx`
- **방법**: props 인터페이스(100~104)·destructure(108)에 `slotProject?`/`isActiveProject?`/
  `onActivateProject?`/`onPickProject?` 추가. 417·420·435행의 `currentPath` → `slotProject || currentPath`.
- **검증**: 슬롯별 cwd로 WS 연결 — 연결배너 `> CWD:`가 슬롯 프로젝트 반영. `npx tsc --noEmit`. `wc -l` ≤ 1500.
- **의존성**: Task 1 (props 계약)

### [ ] Task 4: TerminalSlot.tsx — 헤더 UI(프로젝트 뱃지 + 선택 + "보기")
- **파일**: `.ai_monitor/vibe-view/src/components/TerminalSlot.tsx`
- **방법**: 헤더에 슬롯 프로젝트명 뱃지 + "📁 프로젝트"(폴더 선택 → `onPickProject`) +
  "이 프로젝트 보기"(→ `onActivateProject`). `isActiveProject`일 때 테두리/뱃지 하이라이트. 최소 diff.
- **검증**: 버튼 클릭 시 콜백 발화, 활성 슬롯 하이라이트. `wc -l` ≤ 1500.
- **의존성**: Task 3

### [ ] Task 5: 실행 중 슬롯 프로젝트 변경 → 재시작 확인 팝업
- **파일**: `.ai_monitor/vibe-view/src/components/TerminalSlot.tsx`
- **방법**: onPickProject 처리 시 `hasAttachedTerminal`이면 `confirm("프로젝트를 바꾸려면 터미널을
  재시작해야 합니다. 진행할까요?")` → 확인 시 기존 재시작(WS 재연결) 로직으로 새 cwd 재연결.
  PTY cwd는 spawn 시 고정이라 필수(조용히 무시 금지).
- **검증**: 실행 중 슬롯 프로젝트 변경 → 팝업 → 확인 시 새 cwd로 재연결(배너 CWD 갱신).
- **의존성**: Task 4

### [ ] Task 6: 활성화 후 패널 재조회 검증 + E2E
- **파일**: `.ai_monitor/vibe-view/src/App.tsx` (필요 시 폴링 코디네이터)
- **방법**: `activateSlotProject` 후 패널 폴링이 새 project_id로 즉시 재조회되는지 확인. 스테일 window
  있으면 `?project_id=` 명시 전달(Phase 2-5.2 race 방지). Playwright로 2슬롯(ons/vibe-coding) 각각
  활성화 시 파일탐색기·Git 내용이 해당 프로젝트로 전환되는지 E2E([[feedback_use_playwright]]).
- **검증**: Playwright E2E PASS. `npx tsc --noEmit`. 2파일 `wc -l` ≤ 1500.
- **의존성**: Task 2, 4

---

## 의존성 요약
- Task 1 → (Task 2, Task 3)
- Task 3 → Task 4 → Task 5
- Task 2 + Task 4 → Task 6

## 완료 기준
- [ ] 슬롯마다 다른 프로젝트로 터미널 실행(연결배너 CWD가 슬롯별로 다름)
- [ ] "이 프로젝트 보기" 클릭 시 파일·Git·태스크 패널이 그 슬롯 프로젝트로 전환
- [ ] 프로젝트 미지정 슬롯은 전역 프로젝트 사용(하위호환)
- [ ] 앱 재시작 후 슬롯별 프로젝트 복원(localStorage)
- [ ] 실행 중 프로젝트 변경 시 재시작 확인 후 새 cwd 반영

## 완료 후 기록할 메모리
- `project_per_slot_project`: "계획/구현 대기" → "구현 완료(커밋)". 실제 배선 파일·라인·E2E 결과 추가.
