<!--
FILE: ai_monitor_plan.md
DESCRIPTION: DeskRPG-Lite 가상 오피스 모드 구현 계획
REVISION HISTORY:
- 2026-04-03 Claude: DeskRPG-Lite 오피스 모드 계획 수립 (기존 Paperclip 계획 완료 후 교체)
- 2026-03-30 Claude: Paperclip 스타일 오케스트레이션 전환 (Phase 1-5 완료)
-->

# DeskRPG-Lite: 가상 오피스 모드 구현 계획

**상태:** Phase 2 완료 (Task 1-6)
**목표:** 기존 클래식 뷰 유지 + 오피스 월드 뷰 추가 (백엔드 변경 제로)
**원칙:** 기존 App.tsx 코드 삭제 없음. 데이터 폴링 훅 공유. 패널 컴포넌트 재활용.

---

## Phase 1: 기본 구조 (Day 1-3)

[x] Task 1: 데이터 폴링 커스텀 훅 추출 (useVibeData)
    파일: .ai_monitor/vibe-view/src/hooks/useVibeData.ts (신규)
    방법: App.tsx의 모든 useEffect 폴링 + 상태를 커스텀 훅으로 추출
          App(ClassicApp)과 OfficeApp이 동일 훅 사용
    검증: 기존 기능 100% 정상 동작

[x] Task 2: App.tsx에 viewMode 토글 + OfficeApp 쉘 생성
    파일: .ai_monitor/vibe-view/src/App.tsx, OfficeApp.tsx (신규)
    방법: Root에서 viewMode 상태 관리, 토글 버튼으로 전환
          OfficeApp은 중앙(오피스)+우측(HUD) 레이아웃 쉘
    검증: 토글 전환 시 두 모드 간 매끄러운 전환

[x] Task 3: 오피스 월드 Canvas 렌더링
    파일: .ai_monitor/vibe-view/src/components/office/OfficeWorld.tsx (신규)
    방법: Canvas 2D — 야간 오피스 배경 + T1~T8 책상 고정 배치
          유저 책상 + 회의실 + 휴게실 오브젝트
    검증: 어두운 오피스 배경 + 클릭 가능한 책상 렌더링

## Phase 2: 에이전트 아바타 (Day 4-5)

[x] Task 4: 에이전트 아바타 스프라이트 생성 + 렌더링
    파일: .ai_monitor/vibe-view/src/components/office/AgentAvatar.tsx (신규)
    방법: Claude(보라)/Gemini(초록)/Codex(시안) 3종 픽셀 아바타
          idle/working 애니메이션, 상태 버블(IDLE/WORKING/DONE)
    검증: agentTerminals 상태 변경 → 아바타 애니메이션 전환

[x] Task 5: 책상 클릭 → HUD 패널 연동
    파일: .ai_monitor/vibe-view/src/components/office/HudPanel.tsx (신규)
    방법: 책상 클릭 → 해당 터미널 슬롯을 HUD에 표시
          탭: 터미널 | 태스크 | 메시지 | 메모리 | Git
    검증: T1 책상 클릭 → HUD에 T1 터미널 + 상태 표시

## Phase 3: 인터랙션 + 폴리싱 (Day 6-7)

[x] Task 6: 인월드 이벤트 시스템
    방법: 태스크 완료 → 아바타 유저 책상으로 이동 + 말풍선
          미니 토스트 알림
    검증: 태스크 완료 이벤트 → 아바타 이동 + 말풍선

[ ] Task 7: 네온 로그인 + 모드 전환 메뉴
    방법: View 메뉴에 클래식/오피스 전환 추가
          야간 도시 네온 프로젝트 선택 화면
    검증: 전체 흐름 매끄러움

---
작성: 2026-04-03 Claude
