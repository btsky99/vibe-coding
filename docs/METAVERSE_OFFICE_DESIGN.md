<!--
FILE: docs/METAVERSE_OFFICE_DESIGN.md
DESCRIPTION: Vibe Coding용 가상 메타버스 오피스 시스템 상세 설계 문서.
             기존 Office 모드와 에이전트 협업 구조를 확장하는 제품 방향,
             공간 모델, 데이터 모델, API/프론트엔드/백엔드 구현 단계를 정의한다.

REVISION HISTORY:
- 2026-04-06 Codex: 초기 작성 — 2.5D 협업 운영실 방향의 메타버스 오피스 상세 설계 수립
-->

# Vibe Coding 메타버스 오피스 상세 설계

## 1. 목적

이 문서는 Vibe Coding 프로젝트에 추가할 `메타버스 오피스 시스템`의 제품 방향과 구현 설계를 정의한다.
핵심 목표는 "게임 같은 가상 공간"이 아니라, **멀티 AI 에이전트 협업 상태를 공간으로 시각화하고 제어하는 운영실**을 만드는 것이다.

현재 프로젝트에는 이미 `OfficeApp.tsx`, `OfficeWorld.tsx` 기반의 2D 오피스 모드가 존재한다.
따라서 본 설계는 완전 신규 시스템이 아니라, **기존 Office 모드를 2.5D 협업 오피스로 확장**하는 방향을 기준으로 한다.

---

## 2. 제품 정의

### 2-1. 한 줄 정의

Vibe Coding 메타버스 오피스는 각 AI 에이전트, 태스크, 메모리, Git 상태를 하나의 가상 사무실에 배치하여
사람이 "누가 어디서 무엇을 하고 있고, 어디가 막혔는지"를 즉시 파악할 수 있게 하는 협업 인터페이스다.

### 2-2. 핵심 가치

1. 에이전트 상태를 공간으로 즉시 이해할 수 있다.
2. 터미널/메시지/태스크/메모리/Git를 분리된 패널이 아니라 하나의 운영 공간으로 묶는다.
3. 사용자는 개별 로그를 뒤지지 않고 병목, 토론, 검증, 대기 상태를 시각적으로 파악할 수 있다.
4. 자동 오케스트레이션 결과를 사람이 쉽게 개입 가능한 방식으로 노출한다.

### 2-3. 비목표

1. MMO 형태의 다중 사용자 3D 게임을 만들지 않는다.
2. 자유 이동/충돌/물리 엔진 중심의 플레이 경험을 목표로 하지 않는다.
3. 기존 패널 UI를 폐기하지 않는다. 메타버스 오피스는 기존 패널의 상위 운영 뷰다.
4. 초기 단계에서 실시간 음성 채팅, 네트워크 멀티플레이, 복잡한 아바타 커스터마이징은 다루지 않는다.

---

## 3. 방향 선택

### 3-1. 고려 가능한 옵션

1. 풀 3D 메타버스
2. 2D/2.5D 협업 오피스
3. 기존 대시보드에 공간 테마만 추가

### 3-2. 권장 방향

권장 방향은 `2D/2.5D 협업 오피스`다.

이유:

1. 현재 코드베이스에 이미 Canvas 2D 기반 Office 모드가 있다.
2. 프로젝트의 본질은 게임이 아니라 에이전트 운영과 협업 관찰이다.
3. 3D 엔진 도입은 렌더링/입력/에셋/카메라/성능 비용이 크고 핵심 가치와 거리가 멀다.
4. 2.5D 방식이면 시각적 임팩트와 운영 효율을 동시에 얻을 수 있다.

결론적으로 이 시스템은 "가상 사무실"이라기보다 **에이전트 협업 운영실 + 메타포 공간 UI**로 설계해야 한다.

---

## 4. 제품 원칙

### 4-1. 상태 우선

공간은 꾸미기용 배경이 아니라 시스템 상태의 표현이어야 한다.

예:

1. 작업 시작 → 책상 착석
2. 토론 시작 → 회의실 이동
3. 검증 단계 → QA 존 이동
4. 실패/중단 → 복구 존 강조
5. 완료 → 라운지 또는 대기석 복귀

### 4-2. 자동 배치 우선

초기 버전은 사용자가 직접 조종하는 메타버스보다,
시스템이 에이전트 상태를 읽어 자동으로 배치하는 방식이 더 적합하다.

사용자 수동 개입은 다음 수준으로 제한한다.

1. 특정 에이전트 포커스
2. 회의실로 소집
3. 리뷰 존으로 이동
4. 책상 고정/해제

### 4-3. 기존 기능 재사용

기존 패널과 API를 그대로 활용하고, 공간 레이어만 추가한다.

예:

1. 책상 클릭 → `TerminalSlot`
2. 회의실 클릭 → `MessagesPanel` / `GroupChatPanel`
3. 메모리룸 클릭 → `MemoryPanel` / `ZettelkastenPanel`
4. 배포존 클릭 → `GitPanel` / `TasksPanel`

### 4-4. 공간은 협업 단위를 드러내야 한다

에이전트 개별 상태뿐 아니라, 같은 태스크/같은 토론/같은 skill chain에 속한 에이전트 집합을
"어느 방에 같이 있는가"로 보여줘야 한다.

---

## 5. 공간 모델

## 5-1. 공간 구성

초기 오피스는 다음 존으로 구성한다.

1. Desk Zone
2. Meeting Room
3. Review / QA Zone
4. Memory Room
5. Git / Release Zone
6. Lounge / Idle Zone
7. Recovery Zone
8. User Desk

### Desk Zone

- 각 T1~T8 에이전트의 기본 자리
- 기본 작업 위치
- 터미널 중심 작업 상태 표시

### Meeting Room

- 토론, 합의, 디스패치, 사회자 라운드
- 여러 에이전트가 동시에 모이는 공간
- 대화 흐름, 최근 메시지, 회의 주제 표시

### Review / QA Zone

- 검증, 테스트, 코드 리뷰, 안전성 검사
- Claude/Codex/검증 담당 에이전트가 이동
- 실패 테스트, 린트 경고, 재검증 요청을 시각화

### Memory Room

- Zettelkasten, shared memory, project docs, notes
- 최근 생성/업데이트 노트와 링크 흐름을 표시

### Git / Release Zone

- 커밋, 브랜치, 충돌, 빌드, 배포 상태 표현
- 릴리즈 전후 흐름을 시각적으로 노출

### Lounge / Idle Zone

- 유휴 상태의 에이전트 대기 공간
- 사람 개입 대기, 승인 대기, 다음 작업 대기 표시

### Recovery Zone

- hang, crash, timeout, 반복 실패 에이전트의 격리/복구 공간
- watchdog, self-healing 이벤트를 집약 표시

### User Desk

- 사용자의 현재 포커스 지점
- 선택된 프로젝트, 현재 보고 있는 작업, 최근 개입 액션을 표시

---

## 6. 에이전트 상태 → 공간 매핑

## 6-1. 기본 매핑 규칙

| 상태 | 공간 |
|------|------|
| idle | Lounge |
| started/running + analyze | Desk 또는 Meeting Room |
| started/running + modifying | Desk |
| started/running + verifying | Review / QA Zone |
| group chat / debate | Meeting Room |
| memory sync / zettel capture | Memory Room |
| git commit / release | Git / Release Zone |
| error / hang / repeated failure | Recovery Zone |

## 6-2. 우선순위 규칙

한 에이전트가 여러 상태를 동시에 가질 수 있으므로 우선순위를 둔다.

1. Recovery
2. Meeting
3. Review
4. Git / Release
5. Memory
6. Desk
7. Lounge

즉, 검증 중이면서 회의에도 참여 중이면 회의실이 우선이다.

## 6-3. 그룹 배치 규칙

다음 경우 같은 공간에 묶는다.

1. 동일 `task_id`
2. 동일 `skill chain session`
3. 동일 debate / group chat thread
4. 동일 리뷰 대상 파일 집합

---

## 7. 사용자 경험 설계

## 7-1. 핵심 UX 시나리오

### 시나리오 A: 작업 진행 관찰

1. 사용자가 Office 모드 진입
2. 각 에이전트가 자기 존에 배치됨
3. 진행 중인 작업이 말풍선/카드로 표시됨
4. 병목이 생기면 해당 존이 강조됨
5. 사용자는 클릭으로 해당 패널 상세 진입

### 시나리오 B: 회의 소집

1. 사용자가 2개 이상의 에이전트 선택
2. "회의실로 이동" 실행
3. 선택 에이전트가 Meeting Room으로 이동
4. 관련 메시지 패널/사회자 워크플로우 열림
5. 회의 종료 후 각자 기본 존 복귀

### 시나리오 C: 코드 리뷰 추적

1. 수정 담당 에이전트는 Desk에서 작업
2. 검증 담당 에이전트는 QA Zone으로 이동
3. 실패 테스트가 발생하면 붉은 상태 배지/경고 노출
4. 리뷰 완료 시 Git Zone으로 흐름 전환

### 시나리오 D: 메모리 생성 추적

1. 커밋 또는 결정 기록 발생
2. Memory Room에 새 노트 카드가 반짝이며 생성
3. 관련 에이전트가 잠시 Memory Room에 표시됨
4. 사용자는 클릭해 관련 노트/링크 확인

## 7-2. 상호작용 방식

초기 버전의 직접 조작:

1. 클릭: 패널 포커스 열기
2. 더블클릭: 해당 에이전트 고정 추적
3. 우클릭 또는 액션 메뉴:
   - 회의 소집
   - 리뷰 요청
   - 책상으로 복귀
   - 라운지로 이동
   - 사용자에게 핸드오프
4. 줌/팬: 오피스 전체 탐색

## 7-3. 정보 밀도 원칙

한 화면에서 보여줄 정보는 다음 순서로 압축한다.

1. 위치
2. 상태색
3. 짧은 배지
4. 최근 액션 한 줄
5. 상세 정보는 선택 시 패널에서

즉, 메인 월드는 요약이고 상세는 기존 패널이 담당한다.

---

## 8. 시각 설계 방향

## 8-1. 비주얼 톤

권장 톤은 "사이버 오피스 운영실"이다.

특징:

1. 어두운 바닥 + 네온 라인
2. 책상/회의실/메모리룸이 시각적으로 명확히 구분됨
3. 에이전트별 고유 색상 유지
4. 지나친 게임풍 캐릭터보다 상태 식별이 쉬운 픽셀/아이소메트릭 스타일

## 8-2. 권장 표현 레이어

1. 바닥 레이어: 존 구분
2. 오브젝트 레이어: 책상, 회의 테이블, 메모리 스테이션
3. 에이전트 레이어: 아바타/아이콘
4. 상태 레이어: 배지, 진행바, 경고
5. 이벤트 레이어: 토스트, 말풍선, 이동선

## 8-3. 향후 확장 가능한 시각 요소

1. 존별 히트맵
2. 병목 애니메이션
3. 태스크 흐름 라우팅 라인
4. 릴리즈 카운트다운
5. 회의실의 발언권 강조 효과

---

## 9. 데이터 모델 설계

초기 버전에서는 새 영속 스키마를 최소화하고,
기존 API 응답을 조합한 `파생 공간 상태 모델`을 사용한다.

## 9-1. 핵심 파생 모델

```ts
type OfficeZone =
  | 'desk'
  | 'meeting'
  | 'review'
  | 'memory'
  | 'git'
  | 'lounge'
  | 'recovery'
  | 'user';

interface OfficeAgentPresence {
  terminalId: string;
  agent: 'claude' | 'gemini' | 'codex' | 'unknown';
  status: string;
  pipelineStage: string;
  liveTask: string;
  zone: OfficeZone;
  anchorId: string;
  seatIndex?: number;
  priority: number;
  badges: string[];
  groupId?: string;
  updatedAt: string;
}

interface OfficeEventCard {
  id: string;
  type: 'task' | 'message' | 'memory' | 'git' | 'warning';
  zone: OfficeZone;
  title: string;
  subtitle?: string;
  relatedTerminalIds?: string[];
  severity?: 'info' | 'success' | 'warning' | 'error';
  createdAt: string;
}
```

## 9-2. 존 상태 모델

```ts
interface OfficeZoneState {
  zone: OfficeZone;
  occupancy: number;
  loadScore: number;
  warningCount: number;
  activeTaskIds: string[];
  activeAgentIds: string[];
}
```

## 9-3. 선택적 영속 모델

사용자 커스터마이징이 필요해지면 별도 테이블 추가를 고려한다.

예:

1. `office_layouts`
2. `office_pins`
3. `office_room_presets`
4. `office_user_preferences`

초기 버전에서는 `localStorage` 또는 기존 설정 파일 수준으로 충분하다.

---

## 10. 프론트엔드 설계

## 10-1. 현재 자산

이미 존재:

1. `OfficeApp.tsx`
2. `OfficeWorld.tsx`
3. `useVibeData.ts`
4. 기존 패널 컴포넌트들

즉, 새 뷰 모드 프레임은 이미 있으므로 월드와 상태 파생 로직을 확장하면 된다.

## 10-2. 권장 프론트 구조

```text
components/office/
  OfficeApp.tsx
  OfficeWorld.tsx
  OfficeHUD.tsx
  OfficeMiniMap.tsx
  OfficeInspector.tsx
  OfficeZoneOverlay.tsx
  OfficeEventRail.tsx
hooks/
  useOfficeState.ts
  useOfficeLayout.ts
types/
  office.ts
```

## 10-3. 핵심 hook

### `useOfficeState`

역할:

1. `useVibeData()` 결과를 받아 존 배치 계산
2. 에이전트별 공간 상태 도출
3. 존별 부하/경고 계산
4. 최근 이벤트 카드 목록 생성

입력:

1. `agentTerminals`
2. `skillChain`
3. `messages`
4. `memory`
5. `locks`
6. `hiveHealth`

출력:

1. `presences`
2. `zones`
3. `events`
4. `focusSuggestions`

### `useOfficeLayout`

역할:

1. 좌표, 방 크기, 좌석 위치 관리
2. 줌/팬/스크린 비율 대응
3. 향후 사용자 커스텀 레이아웃 지원

## 10-4. UI 구성

### 메인 월드

- Canvas 2D 유지
- 존별 배경/가구/테이블/책상 추가
- 에이전트 이동 애니메이션 추가

### 우측 HUD

현재 Office 모드의 우측 HUD는 유지하되, 다음 순서로 개선한다.

1. Inspector 카드
2. 현재 존 상세
3. 관련 패널 탭
4. 최근 이벤트 로그

### 하단 상태바

추가 정보:

1. 현재 활성 존 수
2. 병목 존
3. 회의실 점유
4. 복구 필요 에이전트 수

---

## 11. 백엔드/API 설계

초기 단계에서는 기존 API 조합으로 충분하지만, 구조를 단순화하려면 전용 집계 API를 추가하는 것이 좋다.

## 11-1. 초기 방식

프론트에서 기존 API를 병합:

1. `/api/agent/terminals`
2. `/api/messages`
3. `/api/memory`
4. `/api/orchestrator/skill-chain`
5. `/api/hive/health`
6. `/api/hive/activity`

장점:

1. 빠르게 시작 가능
2. 백엔드 변경 최소화

단점:

1. 화면 전용 파생 계산이 프론트에 과도하게 집중될 수 있음

## 11-2. 권장 추가 API

### `GET /api/office/state`

목적:

메타버스 오피스 전용 집계 상태를 반환한다.

응답 예시:

```json
{
  "generated_at": "2026-04-06T23:00:00+09:00",
  "agents": [],
  "zones": [],
  "events": [],
  "summary": {
    "active_agents": 3,
    "busy_zones": ["desk", "review"],
    "blocked_agents": ["terminal_4"]
  }
}
```

### `POST /api/office/action`

초기 액션:

1. `move_to_meeting`
2. `pin_to_zone`
3. `return_to_default`
4. `focus_agent`
5. `handoff_to_user`

주의:

초기에는 실제 프로세스 제어보다 UI 상태 또는 디스패치 요청 생성에 가까워야 한다.

### `GET /api/office/layout`

사용자 레이아웃/줌/존 커스터마이징이 필요해질 때 추가한다.

---

## 12. 구현 단계

## Phase 1. Office 2.0

목표:

기존 DeskRPG-Lite를 "방이 있는 운영실"로 확장

작업:

1. `OfficeWorld`에 존 개념 추가
2. Desk/Meeting/Review/Memory/Git/Lounge/Recovery 영역 렌더링
3. 에이전트 상태 기반 자동 이동
4. 책상 클릭 → 기존 `TerminalSlot` 연동 유지
5. 존 클릭 → 관련 패널 프리셋 열기

완료 기준:

사용자가 오피스 화면만 봐도 어떤 에이전트가 어떤 역할 공간에 있는지 즉시 이해 가능

## Phase 2. 협업 액션

작업:

1. 회의 소집
2. 리뷰 요청
3. 사람 개입 요청
4. 포커스 추적
5. 그룹 배치 표시

완료 기준:

오피스 화면에서 작업 흐름을 관찰하는 수준을 넘어, 협업 제어 액션이 가능해야 함

## Phase 3. 운영 분석 레이어

작업:

1. 존별 부하 지표
2. 병목 히트맵
3. 태스크 흐름선
4. 경고 오버레이
5. 복구 존 강화

완료 기준:

오피스 화면이 단순 시각화가 아니라 운영 판단 도구가 되어야 함

## Phase 4. 메타버스 강화

작업:

1. 사용자 아바타
2. 방 테마 전환
3. 커스텀 배치
4. 이벤트 연출
5. 회의실 특수 모드

완료 기준:

제품 차별화는 확보하되, 운영 효율을 해치지 않아야 함

---

## 13. 리스크와 대응

### 리스크 1. "예쁜데 쓸모없는 화면"이 될 수 있음

대응:

모든 시각 요소는 기존 운영 신호와 1:1로 대응시킨다.

### 리스크 2. 프론트 복잡도가 급증할 수 있음

대응:

`useOfficeState`로 파생 계산을 분리하고, Canvas 렌더링과 상태 계산을 분리한다.

### 리스크 3. 정보 과밀

대응:

메인 월드는 요약만, 상세는 Inspector/HUD/기존 패널로 넘긴다.

### 리스크 4. 자동 배치가 사용자의 기대와 다를 수 있음

대응:

초기에는 규칙 기반 자동 배치 + 핀 고정 기능을 제공한다.

### 리스크 5. 3D 요구가 다시 생길 수 있음

대응:

초기 모델을 "존/좌표/아바타/이벤트" 개념으로 추상화해 두면, 미래에 렌더러만 교체 가능하다.

---

## 14. 성공 지표

기능 성공 여부는 다음으로 판단한다.

1. 사용자가 특정 에이전트 상태를 찾는 시간이 줄어든다.
2. 작업 병목을 로그가 아니라 화면에서 먼저 발견할 수 있다.
3. 회의/리뷰/검증 흐름을 존 이동만으로 이해할 수 있다.
4. 기존 패널 진입 수는 유지하되, 진입 전 탐색 시간이 줄어든다.
5. 사용자가 Office 모드를 "시연용"이 아니라 "실사용 운영 화면"으로 사용한다.

---

## 15. 최종 권고

이 프로젝트의 메타버스 오피스는 "3D 가상 사무실"이 아니라
**멀티 AI 에이전트 협업을 공간으로 압축한 운영실**로 가야 한다.

가장 좋은 첫 구현은 다음과 같다.

1. 기존 Office 모드를 유지한다.
2. 존 개념을 도입한다.
3. 에이전트 자동 이동을 구현한다.
4. 기존 패널과 강하게 연결한다.
5. 분석/병목/복구 정보를 공간화한다.

즉, 방향성은 "게임화"보다 "운영 가시성 + 협업 제어"가 우선이다.
