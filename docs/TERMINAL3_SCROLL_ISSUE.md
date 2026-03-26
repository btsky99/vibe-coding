# Terminal 3 Scroll/Visibility Issue

## Summary

`3분할(layoutMode='3')` 상태에서 `Terminal 3`가 잘 보이지 않거나, 스크롤해서 접근할 수 없는 현상이 발생할 수 있다.

이 문제는 `xterm` 자체의 스크롤 기능보다 먼저, 상위 레이아웃이 가로 오버플로를 숨기는 구조 때문에 발생할 가능성이 높다.

## Observed Code Paths

- 터미널 개수/레이아웃 결정:
  - `.ai_monitor/vibe-view/src/App.tsx`
  - `layoutMode === '3' ? 'grid-cols-3' : ...`
- 터미널 영역 상위 컨테이너:
  - `.ai_monitor/vibe-view/src/App.tsx`
  - `className="flex-1 p-2 bg-[#1e1e1e] overflow-hidden"`
- 터미널 그리드:
  - `.ai_monitor/vibe-view/src/App.tsx`
  - `className="h-full w-full gap-2 grid ..."`
- 각 터미널 슬롯 루트:
  - `.ai_monitor/vibe-view/src/components/TerminalSlot.tsx`
  - `className="h-full ... flex flex-col overflow-hidden ..."`
- xterm 래퍼:
  - `.ai_monitor/vibe-view/src/components/TerminalSlot.tsx`
  - `className="flex-1 relative min-h-0 overflow-hidden"`

## Likely Root Cause

문제는 한 군데가 아니라 조합이다.

1. `3분할`은 고정적으로 `grid-cols-3`를 사용한다.
2. 상위 `main` 컨테이너가 `overflow-hidden`이라 가로 초과분을 숨긴다.
3. 터미널 슬롯과 그리드 아이템에 `min-w-0`이 없어서, 내부 콘텐츠 길이에 따라 슬롯이 충분히 줄어들지 못할 수 있다.
4. 그 상태에서 오른쪽 끝 슬롯(`Terminal 3`)이 화면 밖으로 밀려도, 부모가 오버플로를 숨기므로 사용자가 스크롤해서 볼 수 없다.

즉, 사용자가 느끼는 증상은 "터미널 3 스크롤 안 됨"이지만, 실제 1차 원인은 "스크롤이 막힌 레이아웃 + 축소 불가 슬롯"일 가능성이 높다.

## Why This Looks Like a Scroll Bug

`TerminalSlot` 내부의 xterm은 원래 자체 스크롤백을 가진다. 하지만 현재 구조에서는:

- 바깥 레이아웃이 먼저 잘리고,
- `Terminal 3` 자체가 부분적으로 가려질 수 있고,
- 사용자는 이를 xterm 스크롤 문제로 인식하게 된다.

즉, xterm 내부 휠 스크롤 문제라기보다, 그 전에 슬롯 접근 자체가 막히는 레이아웃 문제에 가깝다.

## Concrete Risk Points

다음 조건이 겹치면 재현 가능성이 높다.

- 사이드바가 열린 상태
- 창 너비가 충분히 넓지 않은 상태
- `3분할`, `4분할`, `6분할`, `8분할`, `9분할`처럼 가로 분할 수가 많은 상태
- 터미널 헤더/입력창/배지/긴 텍스트가 있는 상태

## Recommended Fix Order

### 1. Grid/slot shrinking 허용

우선순위가 가장 높다.

- `.ai_monitor/vibe-view/src/App.tsx`
  - 터미널 그리드 래퍼에 `min-w-0 min-h-0` 추가
- `.ai_monitor/vibe-view/src/components/TerminalSlot.tsx`
  - 슬롯 루트에 `min-w-0 min-h-0` 추가

예상 효과:

- 각 슬롯이 그리드 셀 안으로 정상 축소됨
- `Terminal 3`가 오른쪽으로 밀려 잘릴 가능성 감소

### 2. Terminal area에 가로 스크롤 fallback 추가

레이아웃이 넘치더라도 사용자가 접근 가능해야 한다.

- `.ai_monitor/vibe-view/src/App.tsx`
  - 현재 `main`의 `overflow-hidden`을 상황에 따라 `overflow-auto` 또는 `overflow-x-auto overflow-y-hidden`으로 조정 검토

예상 효과:

- 레이아웃이 넘치더라도 최소한 `Terminal 3`에 접근 가능

### 3. 좁은 화면에서 `3분할` 강제 완화

반응형 fallback이 필요하다.

- 일정 폭 이하에서는 `3분할`을 자동으로 `2분할` 또는 `1분할`로 강등
- 또는 수평 탭/캐러셀 방식으로 전환

예상 효과:

- 좁은 화면에서 잘림 자체를 방지

## Suggested Implementation Notes

### App.tsx

검토 포인트:

- 터미널 그리드 바깥 래퍼
- `main`
- 그리드 컨테이너

권장 방향:

- `main`: `min-w-0 min-h-0`
- grid wrapper: `min-w-0 min-h-0`

### TerminalSlot.tsx

검토 포인트:

- 최상위 루트
- xterm wrapper
- 하단 입력 영역

권장 방향:

- 루트에 `min-w-0 min-h-0`
- 헤더 내부 긴 요소는 이미 일부 `truncate/overflow-hidden` 처리되어 있으나, 슬롯 루트 축소 허용이 먼저 필요

## Non-Goals

이번 이슈의 1차 대응은 아래를 건드리지 않아도 된다.

- xterm scrollback 설정 튜닝
- 마우스 휠 이벤트 커스텀 처리
- WebSocket/PTy 로직 수정
- agent 상태 폴링 로직 수정

이들은 현재 증상과 직접 관련성이 낮다.

## Minimal Patch Strategy

가장 작은 수정 단위는 아래 순서다.

1. `App.tsx` 터미널 영역 래퍼에 `min-w-0 min-h-0` 추가
2. `TerminalSlot.tsx` 루트에 `min-w-0 min-h-0` 추가
3. 그래도 재현되면 `main`을 `overflow-x-auto`로 변경

## Conclusion

현재 코드 기준으로는 `Terminal 3`가 안 보이거나 스크롤 접근이 안 되는 이유를 `xterm 고장`으로 보기 어렵다.

더 가능성 높은 원인은 다음 조합이다.

- `3분할` 고정 그리드
- 상위 컨테이너의 `overflow-hidden`
- 그리드 아이템/슬롯의 `min-w-0` 부재

따라서 수정도 xterm보다 레이아웃부터 손보는 것이 맞다.
