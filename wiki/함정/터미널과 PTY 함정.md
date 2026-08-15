---
title: 터미널과 PTY 함정
type: 함정
sources:
  - .ai_monitor/infra/app_boot.py:193
  - .ai_monitor/vibe-view/src/components/TerminalSlot.tsx:377
related: []
confidence: high
updated: 2026-08-15
---

# 터미널과 PTY 함정

## 한 줄

pywebview 6.x _add_edit_menu는 NSMenuItem엔 title을 안 주고

> 코드 주석에서 자동 합성 (원료 2건 · 파일 2개 · 추출 7cbf195).
> 🔴 **여기를 고치기 전에** 원본 주석을 먼저 고칠 것 — 다음 빌드에 덮어써진다.

## `.ai_monitor/infra/app_boot.py`

### _install_mac_edit_menu `[과거사고]`

[과거사고 2026-07-22] pywebview 6.x _add_edit_menu는 NSMenuItem엔 title을 안 주고
서브메뉴에만 'Edit'을 준다 — 아이템 title만 검사하면 탐색이 항상 실패해 중복 '편집'
메뉴를 만들고, 정작 keyEquivalent(⌘C/⌘V)를 소비하는 진짜 Edit 메뉴는 autoenables
그대로 남아 회색 항목이 키를 삼켰다(전 플랫폼 무반응). 서브메뉴 title도 함께 검사.

출처: `.ai_monitor/infra/app_boot.py:193`

## `.ai_monitor/vibe-view/src/components/TerminalSlot.tsx`

### connectPath `[WHY]` `[과거사고]` `[제약]`

[WHY] TUI(claude 등)가 마우스 리포팅(DECSET 1000/1002)을 켜면 xterm이 좌클릭 드래그를
TUI로 전달해 로컬 선택이 아예 안 생긴다 → "드래그→우클릭 복사"가 통째로 죽음(2026-07-04 사고).
xterm 내부 SelectionService는 shiftKey 이벤트만 마우스 리포팅 중에도 로컬 선택으로 처리하므로,
capture 단계에서 일반 좌클릭 mousedown을 shiftKey=true 합성 이벤트로 재디스패치해 선택을 강제한다.
[제약] 이로 인해 마우스 리포팅 중 좌클릭은 TUI에 전달되지 않는다 — claude CLI는 좌클릭을
쓰지 않고(스크롤 휠은 별도 경로라 영향 없음) 사용자 워크플로우(드래그 복사)가 우선.
합성 이벤트는 shiftKey=true라 첫 가드에서 통과 → 재귀 없음. 일반 셸(리포팅 OFF)은 미개입.
[과거사고] v3.7.243은 mousedown만 shift로 합성 → 선택 앵커(시작점)만 생기고
드래그 이동분(mousemove)이 shift 없이 TUI로 새어나가 리포팅 응답이 선택을 즉시 초기화.
증상(2026-07-05 리포트): "복사는 되는데 드래그하면 하이라이트가 바로 사라짐".
해결: 드래그 세션 전체(mousedown→mousemove→mouseup)를 shift 이벤트로 재디스패치해
xterm 로컬 선택 확장을 유지하고 원본 이벤트는 stopImmediatePropagation으로 리포팅 경로 차단.

출처: `.ai_monitor/vibe-view/src/components/TerminalSlot.tsx:377`

## 확인법

```bash
python scripts/wiki_lint.py        # 이 페이지의 출처가 아직 살아 있는지
python scripts/wiki_build.py       # 원본 주석 변경분 재합성
```

<!-- tags: WHY, 과거사고, 제약 -->
