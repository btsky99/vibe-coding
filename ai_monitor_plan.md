# 🏛️ 바이브 오피스 2.5D 메타버스 구현 계획 (Vibe Office 2.5D)

## 🎯 목표
기존의 2D 평면도 스타일 오피스를 사용자 요청에 따라 **아이소메트릭(2.5D)** 스타일로 전면 개편합니다.
대표실, 작업실, 회의실, 탕비실, 복도를 구분하고 로봇 직원들이 상태에 따라 이동하는 생동감 넘치는 공간을 만듭니다.

## 🛠️ 태스크 리스트

### Phase 1: 좌표계 및 방 레이아웃 (Grid & Rooms)
- [x] **Task 1: `IsoRoom.tsx` 그리드 정의 확장** ✅
    - 파일: `D:\vibe-coding\.ai_monitor\vibe-view\src\components\office\IsoRoom.tsx`
    - 방법: 16x16 이상의 그리드를 정의하고, 각 방(CEO, Workspace, Meeting, Pantry)의 타일 범위를 상수로 선언합니다.
    - 검증: 각 구역별로 다른 바닥 색상이 렌더링되는지 확인.

- [x] **Task 2: `IsometricOffice.tsx`를 진짜 아이소메트릭으로 전환** ✅
    - 파일: `D:\vibe-coding\.ai_monitor\vibe-view\src\components\office\IsometricOffice.tsx`
    - 방법: 현재의 2D SVG 코드를 제거하고, `IsoRoom`의 `isoToScreen`을 사용하는 SVG 그룹 구조로 변경합니다. Z-sorting(뒤에서 앞으로)을 적용합니다.
    - 검증: 타일맵이 다이아몬드 형태로 올바르게 출력되는지 확인.

### Phase 2: 가구 및 오브젝트 (Furniture & Objects)
- [x] **Task 3: `IsoFurniture.tsx`에 신규 가구 추가** ✅
    - 파일: `D:\vibe-coding\.ai_monitor\vibe-view\src\components\office\IsoFurniture.tsx`
    - 방법: 사용자가 요청한 **컴퓨터**, **파티션이 있는 책상**, **회의 테이블**, **탕비실 집기** SVG를 추가합니다.
    - 검증: 각 가구가 아이소메트릭 각도에 맞게 렌더링되는지 확인.

- [x] **Task 4: 가구 자동 배치 로직 구현** ✅
    - 파일: `D:\vibe-coding\.ai_monitor\vibe-view\src\components\office\IsometricOffice.tsx`
    - 방법: 방 레이아웃에 맞춰 책상과 가구들을 특정 좌표에 고정 배치합니다.
    - 검증: 작업실에 파티션과 컴퓨터가 있는 책상들이 정렬되어 나타나는지 확인.

### Phase 3: 에이전트 및 캐릭터 (Agents & Avatars)
- [x] **Task 5: `IsoAgent.tsx` 로봇 및 사람 캐릭터 완성** ✅
    - 파일: `D:\vibe-coding\.ai_monitor\vibe-view\src\components\office\IsoAgent.tsx`
    - 방법: CEO(사람) 캐릭터와 LLM 로봇 캐릭터의 8방향(또는 4방향) 뷰 및 상태 애니메이션(Idle, Working, Meeting)을 보강합니다.
    - 검증: 캐릭터들이 애니메이션과 함께 올바른 방향을 보는지 확인.

- [x] **Task 6: 상태 기반 자동 이동 로직 연동** ✅
    - 파일: `D:\vibe-coding\.ai_monitor\vibe-view\src\components\office\IsometricOffice.tsx`
    - 방법: 에이전트의 상태(`working` -> 작업실, `meeting` -> 회의실, `idle` -> 탕비실)에 따라 목표 좌표로 부드럽게 이동(CSS transition 또는 Framer Motion)하게 합니다.
    - 검증: 에이전트 상태 변경 시 캐릭터가 방을 이동하는지 확인.

### Phase 4: 상호작용 및 마무리 (Interactions & Polish)
- [x] **Task 7: 클릭 인터렉션 및 말풍선 최적화** ✅
    - 파일: `D:\vibe-coding\.ai_monitor\vibe-view\src\components\office\IsometricOffice.tsx`
    - 방법: 책상 클릭 시 해당 터미널 슬롯 선택 기능 연동 및 에이전트 머리 위 말풍선 위치 조정.
    - 검증: 클릭 시 우측 패널 연동 및 말풍선이 캐릭터를 따라다니는지 확인.

## ⚠️ 예상 위험 및 대응
- **성능 저하**: 타일과 가구가 많아질 경우 SVG 렌더링 부하가 생길 수 있음 -> `memo` 사용 및 필요한 부분만 업데이트.
- **Z-Index 문제**: 캐릭터가 가구 뒤로 가거나 앞으로 나오는 레이어 순서 오류 -> Y 좌표 기반으로 정렬하여 렌더링.

---
**작성일:** 2026-04-10
**상태:** ✅ 완료 (2026-04-10)
