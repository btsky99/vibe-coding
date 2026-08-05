<!--
FILE: docs/DISCORD_HARNESS_INTEGRATION_PLAN.md
DESCRIPTION: usage-coach, discord-multiagent, folder-bot의 장점을 Vibe Coding 하네스에
             PostgreSQL·Windows 중심으로 통합하기 위한 단계별 도입 계획.

REVISION HISTORY:
- 2026-08-03 Codex: 외부 프로젝트 분석을 바탕으로 최초 통합 계획 작성
- 2026-08-03 Codex: 단일 Discord connector, 기본 3터미널, 다중 PC 버스 및
                    Telegram 즉시 제거 결정 반영
-->

# Discord Harness Integration Plan

## 1. 문서 목적

이 문서는 다음 공개 프로젝트와 데모 영상에서 확인한 기능을 Vibe Coding에 도입하기 위한
source of truth다.

- 영상: `https://www.youtube.com/watch?v=v40AFadpg4w`
- Usage Coach: `https://github.com/netwaif/usage-coach`
- Discord MultiAgent: `https://github.com/netwaif/discord-multiagent`
- Folder Bot: `https://github.com/netwaif/folder-bot`

목표는 외부 프로젝트를 그대로 설치하는 것이 아니다. 현재 Vibe Coding의 PostgreSQL 기반
ITCP, PTY 터미널, 프로젝트 관리, Telegram 브리지, Vibe View를 유지하면서 다음 경험을
하나의 하네스로 제공하는 것이다.

> 사용량을 보고 안전한 작업 크기를 판단하고, Discord에서 프로젝트별 AI 세션을 지시·감시하며,
> 컨텍스트가 차면 체크포인트를 남기고 새 세션으로 안전하게 이어서 작업한다.

이 문서는 구현 순서와 경계를 정의한다. 세부 API 계약은 구현 단계에서
`docs/API_SPEC.md`에 반영한다.

---

## 2. 최종 사용자 경험

```text
Discord
├─ 상태 대시보드
│  ├─ Claude/Codex/Antigravity 사용량과 리셋 시각
│  ├─ 권장 작업 크기와 판단 이유
│  ├─ 프로젝트별 활성 에이전트·모델·컨텍스트 사용률
│  └─ 상태가 악화될 때만 알림
├─ 프로젝트 채널
│  └─ 채널 하나 ↔ 프로젝트 하나 ↔ 선택된 터미널/세션
└─ 원격 제어
   ├─ 작업 요청과 결과 수신
   ├─ 승인 요청 처리
   ├─ 작업 상태 조회
   └─ 체크포인트 저장 후 세션 재시작
```

Vibe View, Telegram, Discord는 서로 다른 상태를 갖지 않는다. 모두 중앙 API와 PostgreSQL의
동일한 프로젝트, 태스크, 세션, 쿼터 정책을 사용한다.

---

## 3. 도입 결정

| 대상 | 결정 | 흡수할 부분 | 흡수하지 않을 부분 |
|------|------|-------------|---------------------|
| usage-coach | 적극 흡수 | 5시간·7일 페이스 비교, 작업 크기 권고, quota guard, 상태 악화 알림 | codexbar 필수 의존, 별도 상태 정본 |
| discord-multiagent | 선택 흡수 | worker 승인, brief/write scope, 검증 체크리스트, 재진입 규칙, 시스템 불변식 | 파일 기반 런타임 상태, Claude 단일 오케스트레이터 |
| folder-bot | 개념 흡수 | 폴더=채널=세션 매핑, 멱등 등록, doctor, 원격 컨텍스트 리사이클 | macOS LaunchAgent, tmux, 프로젝트별 독립 상태 저장 |
| Discord UI | 신규 구현 | 웹훅 대시보드, 양방향 봇, 승인 컴포넌트 | Discord를 시스템 정본으로 사용하는 구조 |

### 3.1 핵심 결정

1. PostgreSQL 18이 계속 유일한 런타임 정본이다.
2. Discord는 새로운 실행 엔진이 아니라 기존 하네스의 connector다.
3. 기존 `/api/agent-quota`와 Claude/Codex 수집기를 재사용한다.
4. Telegram과 Discord는 가능한 한 동일한 connector 계약을 사용한다.
5. Windows PTY와 기존 daemon 관리 흐름을 사용하며 tmux/LaunchAgent를 도입하지 않는다.
6. 외부 저장소의 MIT 코드가 필요하면 출처와 변경 내용을 보존하되, 우선 로직을 재구현한다.
7. 원격 입력은 로컬 UI보다 좁은 권한을 가지며 allowlist와 승인 게이트를 통과해야 한다.
8. Discord Gateway 연결은 하나만 운영하고 터미널별 채널/스레드로 정체성을 분리한다.
9. 터미널은 PC당 기본 3개로 노출하고 필요할 때 추가하며 3개로 제한하지 않는다.
10. Telegram은 지원 대상에서 즉시 제외한다. 브리지·UI·API·의존성은 Phase 0에서 제거하고
    기존 PostgreSQL 메시지 기록만 감사 이력으로 보존한다.

---

## 4. 현재 자산과 재사용 지점

| 기능 | 현재 자산 | 통합 방향 |
|------|-----------|-----------|
| Claude 쿼터 | `.ai_monitor/src/claude_quota.py` | 코칭 입력으로 사용 |
| Codex 쿼터 | `.ai_monitor/src/codex_quota.py` | 코칭 입력으로 사용 |
| 통합 쿼터 API | `.ai_monitor/api/hive_api.py`의 `/api/agent-quota` | policy 결과 확장 또는 전용 API 분리 |
| 컨텍스트 표시 | `/api/context-usage`, `TerminalSlot.tsx` | Discord 세션 상태에도 재사용 |
| 원격 메시징 | `scripts/telegram_bridge.py`, `telegram_agent_bot.py` | connector 공통 계층 추출의 기준 |
| 에이전트 통신 | ITCP `pg_messages` | Discord 요청·응답 전달 |
| 태스크 | PostgreSQL `hive_tasks` | 승인·worker·검증 상태 확장 |
| 세션 복구 | `active_session_context`, `scripts/checkpoint.py` | 컨텍스트 리사이클에 재사용 |
| 터미널 실행 | PTY 서버와 agent API | 프로젝트 채널의 실행 대상 |
| daemon UI | `DaemonsPanel.tsx` | Discord connector on/off와 상태 표시 |
| 설정 UI | Telegram 설정 API/Panel | Discord 설정 UX의 기준 |

---

## 5. 목표 아키텍처

```text
                       ┌──────────────────────┐
                       │  Quota Policy Engine │
                       │ coach + guard        │
                       └──────────┬───────────┘
                                  │
┌───────────┐    ┌────────────────▼────────────────┐    ┌─────────────┐
│ Vibe View │◀──▶│ Vibe Coding API / Agent Runtime │◀──▶│ PostgreSQL  │
└───────────┘    └────────────────┬────────────────┘    └─────────────┘
                                  │
                         ┌────────▼────────┐
                         │ Connector Core  │
                         └────────────┬────┘
                                      │
                                  Discord
                                      │
                          channel ↔ project/session
```

### 5.1 Connector 공통 계약

connector는 최소한 다음 내부 이벤트를 처리해야 한다.

- `InboundMessage`: 사용자, 채널, 텍스트, 첨부, reply 대상
- `OutboundMessage`: 텍스트, 진행 상태, 파일, 스트림 갱신
- `ApprovalRequest`: 작업 ID, 위험 수준, 승인/거절 선택지
- `StatusSnapshot`: 프로젝트, 터미널, 모델, 컨텍스트, 쿼터
- `SessionControl`: 상태 조회, 중단, 체크포인트, 재시작

플랫폼별 사용자 ID와 채널 ID는 내부 `actor_id`, `project_id`, `terminal_id`로 변환한 뒤에만
실행 계층에 전달한다.

### 5.2 터미널과 다중 PC 라우팅

- 터미널 주소는 `<node_id>:<terminal_id>` 형식을 사용한다. 예: `desktop-a:T1`.
- 기본 터미널은 T1~T3이며 T4 이상은 기존 슬롯 추가 흐름으로 동적으로 등록한다.
- Discord 채널/스레드는 특정 터미널 또는 group room에 binding할 수 있다.
- 그룹 메시지는 `@all`, node, terminal, agent type, reply 대상 중 하나로 라우팅한다.
- 멘션이 없으면 room의 지정 orchestrator에게 전달한다.
- `@all` 상태 조회는 허용하지만 실행 요청은 fan-out 비용을 보여주고 승인받는다.
- PC 간 메시지는 PostgreSQL ITCP/LAN bus가 정본이며 Discord는 관찰·입력 connector다.

### 5.3 데이터 모델 초안

정확한 DDL은 구현 단계에서 확정한다.

| 엔터티 | 핵심 필드 |
|--------|-----------|
| connector_bindings | platform, guild/chat_id, channel_id, project_id, terminal_id, enabled |
| connector_acl | platform, actor_id, binding_id, role, allowed_actions |
| connector_events | direction, platform, external_event_id, binding_id, status, metadata, created_at |
| agent_rooms | room_id, project_id, scope, enabled, created_at |
| agent_room_members | room_id, node_id, terminal_id, agent_type, role |
| quota_policy | provider, margin, floor, big_task_threshold, soon_minutes, mode |
| quota_decisions | provider, level, action, reason, snapshot, task_id, created_at |
| task_approvals | task_id, action, requested_by, decided_by, status, expires_at |
| session_checkpoints | project_id, terminal_id, task_id, summary, next_actions, created_at |

민감한 토큰과 웹훅 URL은 일반 설정·로그·metadata에 저장하지 않는다.

---

## 6. 단계별 구현 계획

## Phase 0 — 계약과 기준선 고정

### 목표

기존 기능을 깨뜨리지 않고 변경 전 기준과 내부 계약을 확정한다.

### 작업

- [x] Telegram 런타임·설정·UI·의존성 제거
- [x] 제거 전 수신→ITCP→agent→응답 경로에서 Discord connector가 재사용할 계약만 추출
- [ ] PTY 세션 생성·종료·재연결 경로 확인
- [ ] `active_session_context`와 checkpoint 복구 계약 확인
- [x] Claude/Codex 쿼터 응답을 공통 내부 타입으로 정규화
- [ ] connector 권한과 위험 작업 분류표 확정
- [ ] Discord 기능 플래그 기본값을 `off`로 결정
- [ ] 관련 기존 테스트의 기준선 실행 결과 기록

### 완료 기준

- PTY, quota, route, daemon 테스트가 통과한다.
- connector와 quota policy 입력/출력 타입이 문서화된다.
- 신규 기능을 꺼 둔 상태에서 동작 변화가 없다는 기준이 있다.

## Phase 1 — Usage Coach 내장

### 목표

사용량 수치를 행동 가능한 작업 권고로 변환한다.

### 작업

- [x] provider 독립적인 순수 `quota_policy` 모듈 작성
- [x] 5시간·7일 `left` 대 `timeLeft` 비교 구현
- [x] `normal`, `large_ok`, `wait_reset`, `small_only`, `weekly_risk` 상태 구현
- [x] 사용자용 `action`, `reason`, `retry_after/reset_at` 생성
- [x] 설정 가능한 `margin`, `floor`, `big_task_threshold`, `soon_minutes` 추가
- [x] 조회 실패와 부분 데이터 정책 구현
- [x] `/api/agent-quota` 확장 또는 `/api/quota/advice` 신규 API 확정
- [ ] Vibe View와 TUI에 권고 표시 (Vibe View 완료, TUI 남음)
- [ ] 모든 판단을 PostgreSQL에 중복 없이 기록

### Guard 수준

| 수준 | 동작 |
|------|------|
| off | 표시만 하고 실행에 영향 없음 |
| warn | 실행은 허용하고 경고 기록 |
| approve | 큰 작업은 사용자 승인 필요 |
| pause | 안전 임계치 아래에서는 새 자율 루프 시작 차단 |

기본값은 `warn`으로 한다. 데이터 조회 실패 시 기본 `fail-open`하되 실패 자체는 눈에 보이게
표시하고 기록한다. 배포·삭제 등 별도 위험 게이트는 쿼터 조회 실패와 무관하게 유지한다.

### 완료 기준

- 모든 5가지 권고 상태에 대한 단위 테스트가 통과한다.
- Claude/Codex 중 한 provider가 실패해도 다른 provider 결과가 유지된다.
- UI 숫자와 정책 판단이 동일한 snapshot을 사용한다.
- guard가 기존 수동 터미널 입력을 임의로 중단시키지 않는다.

## Phase 2 — Discord 읽기 전용 대시보드

### 목표

Discord 웹훅 메시지 하나에서 하이브 상태를 확인한다.

### 작업

- [x] Discord webhook 설정과 secret 저장 방식 구현 (환경변수 주입, 응답·로그 비노출)
- [x] provider별 사용량·권고 Components V2 렌더링
- [x] 활성 프로젝트·터미널·모델 표시 (컨텍스트 사용률은 후속)
- [x] 동일 메시지 upsert와 PostgreSQL message ID 복구 구현
- [ ] 기본 5분 주기와 수동 새로고침 구현 (5분 daemon 완료, 수동 갱신 후속)
- [ ] 상태가 노랑/빨강으로 악화될 때만 알림
- [x] daemon 시작/중지/상태 API와 UI 연결
- [x] Discord 장애 시 로컬 하네스에 영향이 없도록 별도 프로세스로 격리

### 완료 기준

- 새 메시지를 누적하지 않고 하나의 대시보드 메시지를 갱신한다.
- 재시작 후 기존 message ID를 복구하거나 안전하게 새 메시지를 만든다.
- webhook URL이 로그, API 응답, 오류 화면에 노출되지 않는다.
- 모바일과 데스크톱 Discord에서 텍스트가 읽을 수 있게 표시된다.

## Phase 3 — Discord 양방향 Connector

### 목표

허가된 Discord 채널에서 기존 에이전트 런타임으로 작업을 요청하고 결과를 받는다.

### 작업

- [x] Discord Gateway bot과 lifecycle daemon 구현
- [x] guild/channel/user allowlist 구현
- [x] 외부 event ID 기반 PostgreSQL 중복 실행 방지
- [x] channel_id → project_id/terminal_id 라우팅
- [x] Discord는 공통 chat bus에만 게시하고 서버의 백그라운드 소비자가 세션으로 전달
- [x] 소비자가 `reply_to_seq` 상관 응답을 bus에 게시하면 Discord가 최종 응답 전송
- [ ] 긴 응답 분할, rate limit, 재시도, backoff 구현
- [ ] reply/mention 기반 대상 에이전트 선택 (주소·node·agent mention 완료, Discord reply 후속)
- [ ] 첨부파일 검증과 격리 저장 구현
- [x] 플랫폼 중립 connector core 추출

### 완료 기준

- 등록되지 않은 서버·채널·사용자의 요청이 실행되지 않는다.
- 같은 Discord 이벤트가 재전달돼도 작업은 한 번만 생성된다.
- 채널에 연결된 프로젝트 루트 밖의 파일 작업이 차단된다.
- Discord 연결 종료 후 재접속해도 진행 중 작업 상태를 복구한다.

## Phase 4 — 프로젝트 채널과 Folder Bot 경험

### 목표

프로젝트 등록만으로 전용 Discord 채널 세션을 지속 운영한다.

### 작업

- [ ] project-channel binding CRUD API 구현
- [ ] 설정 UI에서 프로젝트·채널·기본 agent·terminal 선택
- [ ] “현재 프로젝트를 Discord에 연결” 설치 흐름 구현
- [ ] 등록·갱신·제거를 멱등 처리
- [ ] 등록된 프로젝트를 대시보드에 자동 표시
- [ ] 프로젝트별 실행 직렬화와 동시성 정책 구현
- [ ] doctor 진단: token, intent, ACL, binding, daemon, PTY, DB 확인
- [ ] 재부팅 후 connector와 binding 복원

### 완료 기준

- 채널 하나가 잘못된 프로젝트로 라우팅되지 않는다.
- 프로젝트 연결을 제거해도 기존 프로젝트 파일은 수정·삭제되지 않는다.
- 동일 설정을 반복 적용해도 봇·binding·daemon이 중복 생성되지 않는다.
- Windows 설치본에서 별도 tmux 없이 자동 시작과 복구가 동작한다.

## Phase 5 — 승인 게이트와 멀티 에이전트 계약

### 목표

Discord에서 안전하게 worker 호출과 위험 작업을 승인한다.

### 작업

- [ ] task metadata에 planned workers, write scope, evaluator 추가
- [ ] worker brief와 결과 검증 계약 추가
- [ ] 승인 요청/승인/거절/만료 상태 구현
- [ ] Discord 버튼과 Vibe View 승인 UI를 동일 API에 연결
- [ ] 승인자를 platform actor와 내부 사용자로 감사 기록
- [ ] generator와 evaluator가 동일 작업자가 되지 않도록 정책 검사
- [ ] quota `approve` 상태와 위험 작업 승인을 구분해 표시

### 위험도 기본안

| 작업 | 기본 정책 |
|------|-----------|
| 읽기, 분석, 상태 조회 | 자동 허용 |
| 테스트, lint, 격리된 worktree 수정 | 정책 범위 내 허용 |
| 프로젝트 루트 밖 쓰기 | 차단 |
| 삭제, 배포, 외부 메시지, 운영 설정 변경 | 명시적 승인 |
| 새로운 유료 worker 또는 큰 자율 루프 | 쿼터 상태에 따라 승인 |

### 완료 기준

- 승인되지 않은 위험 작업은 어떤 connector에서도 실행할 수 없다.
- 승인은 task와 구체적인 action에 묶이며 다른 작업에 재사용되지 않는다.
- 승인·거절·만료가 PostgreSQL 감사 로그에 남는다.
- UI와 Discord에서 동일한 승인 상태가 보인다.

## Phase 6 — 컨텍스트 체크포인트와 세션 리사이클

### 목표

Discord 명령으로 현재 세션을 정리하고 새 컨텍스트에서 안전하게 이어간다.

### Phase 6-0 — 컨텍스트 계측 실태 (2026-08-05 실측)

자동 트리거를 얹기 전에 계측 원천을 실측했다. **결과가 설계를 바꿨다.**

| CLI | 원천 | 상태 | 자동 트리거 |
|-----|------|------|-------------|
| claude | `~/.claude/projects/*/*.jsonl` (639개) | 정상 — `/api/context-usage` | 가능 |
| codex | `~/.codex/sessions/**/rollout-*.jsonl` (34개) | API 부재 → `src/codex_context.py` 신설 | 가능 |
| antigravity | `/api/antigravity-context-usage` | **죽은 계측** | **불가 — 제외** |

- codex는 `last_token_usage.input_tokens / model_context_window`가 정답이다.
  `total_token_usage`는 세션 누적이라 실측에서 11164%가 나온다(오용 금지).
- antigravity API는 폐기 경로 `~/.gemini/tmp/<folder>/chats/`를 읽는다. 실측 시
  그 경로엔 파일 1개(mtime 5/26)뿐이고, 실제 대화는
  `~/.gemini/antigravity-cli/conversations/*.db`(SQLite, 39개, mtime 8/4)에 있다.
  → `AUTO_TRIGGER_CLIS`에서 제외하고 수동 `!recycle`만 허용한다.
  agy용 파서를 만들면 이 표와 `session_recycle.AUTO_TRIGGER_CLIS`를 함께 갱신할 것.

### 작업

- [x] 재시작 가능 상태와 금지 상태 정의 (`plan_recycle` 순수 함수 — 금지 7종)
- [x] checkpoint에 목표·결정·다음 단계·변경 파일 저장 (`active_session_context` 재사용)
- [x] 진행 중 tool/process 정리와 timeout 처리 (DRAIN 20초, 자동은 타임아웃 시 후퇴)
- [x] PTY 세션 정상 종료 후 새 세션 생성 (`/api/pty/terminate` → `spawn`)
- [x] 새 세션에서 규칙·checkpoint 로드 (재정박 프롬프트, 규칙은 경로만·본문 금지)
- [x] 성공·실패 상태를 Discord에 표시 (`!recycle` 응답)
- [ ] Vibe View 패널 표시 — **미착수** (API `/api/session/recycle/status`는 준비됨)
- [x] 재시작 요청 중복과 재진입 경쟁 방지 (`recycle_state` + 멱등 토큰)
- [x] 실패 시 기존 checkpoint로 수동 복구 가능하게 유지 (`_local/reanchor-<T>.md` 폴백)

### 구현 산출물

| 파일 | 역할 |
|------|------|
| `src/session_recycle.py` | 상태머신(GUARD→SEAL→DRAIN→SWAP→REANCHOR) — 순수 로직 |
| `src/brief_limits.py` | 재정박·브리프 글자 상한 + 중간 절단 (규칙 9의 유일 강제 지점) |
| `src/codex_context.py` | codex 컨텍스트 파서 (Phase 6-0에서 신설) |
| `api/recycle_api.py` | HTTP 계층 + 실제 deps 주입 |
| `infra/daemons.py` | `run_recycle_watcher` — 60초 폴링 자동 발동 |
| `scripts/discord_gateway.py` | `!recycle` 명시 명령 |
| `tests/test_session_recycle.py` | GUARD 10종 + 불변식 회귀 31건 |

### 구현 중 발견한 결함 (재발 방지)

`seal()`이 부르는 `set_session_checkpoint`가 `updated_at = NOW()`를 찍는다.
그래서 SEAL 직후 `user_active()`의 "나이" 판정이 항상 0초 → 항상 True →
**DRAIN이 매번 20초를 꽉 채우고 실패, 자동 리사이클이 구조적으로 100% 불발**이었다.
가짜 deps를 쓰는 단위 테스트로는 잡히지 않는 통합 결함.
→ SEAL 성공 시각을 기준선으로 잡고 "기준선 이후의 새 쓰기"만 활동으로 판정하도록 수정.

### 완료 기준

- 재시작 전후 project_id와 task_id가 유지된다.
- 새 세션의 context 사용률이 초기화되고 checkpoint의 다음 작업을 인식한다.
- 저장 실패 시 기존 세션을 종료하지 않는다.
- 새 세션 기동 실패 시 복구 방법과 실패 원인이 남는다.

## Phase 7 — 통합 검증과 배포

### 작업

- [ ] quota policy 단위 테스트
- [ ] Discord payload/Components snapshot 테스트
- [ ] ACL과 project boundary 보안 테스트
- [ ] 중복 이벤트·rate limit·재연결 테스트
- [ ] 승인 게이트 우회 회귀 테스트
- [ ] 체크포인트/재시작 통합 테스트
- [ ] 내부 ITCP와 기존 로컬 채팅 회귀 테스트
- [ ] Windows 설치·업데이트·자동 시작 테스트
- [ ] secret redaction 검사
- [ ] `docs/API_SPEC.md`, `PROJECT_MAP.md`, 사용자 가이드 갱신
- [ ] feature flag로 제한 배포 후 관찰

### 최종 완료 기준

- Discord와 Vibe View가 동일 프로젝트·태스크 상태를 읽는다.
- Discord가 없어도 기존 Vibe Coding 기능이 정상 동작한다.
- 모든 원격 실행에 actor, project, action, result 감사 기록이 남는다.
- 쿼터 guard, 승인 게이트, 프로젝트 sandbox를 우회하는 알려진 경로가 없다.
- Windows 설치본 재부팅 후 connector와 프로젝트 binding이 복구된다.

## Phase 0-A — Telegram 제거

### 제거 대상

- [x] `scripts/telegram_bridge.py`, `telegram_agent_bot.py`, `telegram_helpers.py`
- [x] `api/telegram_api.py`와 Telegram route/handler
- [x] `TelegramPanel.tsx`와 navigation/setup UI
- [x] Telegram daemon 등록과 pid/log 처리
- [x] `python-telegram-bot` 의존성과 패키징 hidden import
- [x] Telegram 전용 source/channel 분기와 설정 doctor
- [x] Telegram 테스트를 Discord/connector 회귀 테스트로 교체
- [x] `.env`의 Telegram 설정은 자동 삭제하지 않고 migration 안내 후 사용자가 정리

### 완료 기준

- 활성 코드와 패키지 설정에 Telegram 런타임 참조가 없다.
- 기존 Telegram 메시지 기록은 삭제하지 않고 과거 감사 데이터로 조회 가능하다.
- 설치본과 개발 실행 모두 Telegram 패키지 없이 기동한다.
- Discord, Vibe View, 내부 ITCP 전체 회귀 테스트가 통과한다.

---

## 7. 보안 불변식

다음 항목은 편의 기능보다 우선하며 구현 중 완화하지 않는다.

1. Discord bot token과 webhook URL을 PostgreSQL 일반 컬럼, `.env` 응답, 로그에 평문 노출하지 않는다.
2. Windows에서는 Unix `chmod 0600`을 보안 보장으로 간주하지 않는다.
3. allowlist에 없는 actor, guild, channel의 메시지는 agent 입력으로 전달하지 않는다.
4. connector가 전달한 경로는 항상 등록된 project root 아래로 정규화한다.
5. 외부 event ID를 저장해 at-least-once 전달에 의한 중복 실행을 막는다.
6. Discord 메시지 내용만으로 삭제·배포·secret 조회를 자동 승인하지 않는다.
7. 첨부파일은 실행하지 않고 크기·확장자·저장 위치를 검증한다.
8. 사용자에게 전달하는 오류에서 토큰, 로컬 민감 경로, 원문 환경변수를 제거한다.
9. connector 장애, API rate limit, Discord 장애가 로컬 agent 프로세스를 종료시키지 않는다.
10. 세션 checkpoint 저장 실패 시 현재 세션을 파괴하지 않는다.

---

## 8. 비목표

- Discord를 PostgreSQL 대신 작업 상태 정본으로 사용하지 않는다.
- Discord 안에서 완전한 IDE나 Vibe View 전체를 복제하지 않는다.
- 외부 저장소의 macOS LaunchAgent/tmux 구성을 Windows에 억지로 이식하지 않는다.
- 프로젝트마다 별도 오케스트레이터와 별도 DB를 무조건 생성하지 않는다.
- 모든 자연어 메시지를 shell 명령으로 직접 실행하지 않는다.
- 쿼터 데이터만으로 진행 중인 사용자 작업을 강제 종료하지 않는다.
- 초기 버전에서 Discord 서버·채널 자동 생성 권한까지 요구하지 않는다.

---

## 9. 예상 변경 영역

정확한 파일은 각 Phase 착수 시 관련 코드를 다시 확인하고 확정한다.

```text
.ai_monitor/
├─ api/
│  ├─ quota_policy_api.py       # 후보
│  ├─ connectors_api.py         # 후보
│  └─ approvals_api.py          # 후보
├─ src/
│  ├─ quota_policy.py           # 후보
│  ├─ connector_core.py         # 후보
│  ├─ discord_connector.py      # 후보
│  └─ pg_*                      # binding/event/approval 저장
└─ vibe-view/src/
   └─ components/panels/        # Discord 설정·승인·상태 UI

scripts/
├─ discord_bridge.py            # 후보 daemon entrypoint
└─ checkpoint.py                # 기존 흐름 확장 가능성

tests/
├─ test_quota_policy.py
├─ test_discord_connector.py
├─ test_connector_acl.py
├─ test_task_approvals.py
└─ test_session_recycle.py
```

신규 코드 파일도 `RULES.md`의 1500줄 제한과 파일 헤더 규칙을 따른다. connector 플랫폼별
로직, PostgreSQL 저장, API handler를 한 파일에 집중시키지 않는다.

---

## 10. 구현 착수 순서

첫 구현 스프린트는 Phase 0과 Phase 1만 범위로 한다.

1. 현재 quota 응답 fixture 확보
2. quota policy 순수 함수와 단위 테스트 작성
3. 읽기 전용 advice API 연결
4. Vibe View/TUI 표시
5. `warn` guard 기록
6. 회귀 검증

Discord token이나 서버 설정이 없어도 이 스프린트는 완성할 수 있다. Discord 구현은 quota
policy가 안정된 뒤 Phase 2의 읽기 전용 webhook 대시보드부터 시작한다.

---

## 11. 보류 결정과 확인 필요 사항

다음 사항은 해당 Phase 직전에 사용자의 선택을 받는다.

- secret 저장소로 Windows Credential Manager/DPAPI/기존 별도 계층 중 무엇을 사용할지
- Discord 서버와 채널을 사용자가 수동 생성할지, 봇이 생성할 권한을 가질지
- quota guard 기본값을 `warn`에서 `approve`로 올릴지
- 프로젝트 채널의 기본 agent를 고정할지, 메시지마다 선택할지
- 외부 접속 시 파일 첨부 기능을 초기 범위에 포함할지

이 선택들은 Phase 1 구현을 막지 않는다.

---

## 12. 성공 지표

- 사용자가 쿼터 숫자를 직접 해석하지 않고 권장 작업 크기를 이해한다.
- Discord 대시보드 메시지가 누적되지 않고 최신 상태 하나를 유지한다.
- 프로젝트 채널에서 요청한 작업이 올바른 project/terminal에만 도착한다.
- 컨텍스트 재시작 후 수동 설명 없이 미완료 작업을 이어갈 수 있다.
- 원격 실행 보안 위반과 secret 노출이 테스트에서 0건이다.
- Discord 기능을 끈 상태의 기존 테스트와 사용자 흐름에 회귀가 없다.
