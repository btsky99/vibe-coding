<!--
FILE: docs/HARNESS_V2.md
DESCRIPTION: Vibe Coding 멀티에이전트 하네스 V2 명세서.
             Anthropic 엔지니어링 블로그의 최신 패턴을 기반으로 설계.
             Claude, Gemini, Codex 모든 에이전트가 공통으로 준수하는 하네스 계약.

REVISION HISTORY:
- 2026-03-30 Claude: 최초 작성 — Anthropic 블로그 기반 V2 설계
  - Generator-Evaluator 분리 패턴 도입
  - 세션 시작 프로토콜 표준화
  - Feature List JSON 기반 진행 추적
  - 스프린트 계약 패턴 명세
  - 컨텍스트 관리 전략 (리셋 vs 압축)
- 2026-04-19 Claude: Layer 3 다이어그램에서 auto_dispatcher.py 제거
  - 2026-04-18 커밋 37d8266 "멀티 LLM 디스패처 정리 — 실사용 0" 반영
  - 실제 작업 분배는 hive_tasks 원자적 체크아웃으로 대체됨
-->

# 🛡️ Vibe Coding Harness V2

> **"Every component in a harness encodes an assumption about what the model can't do on its own."**
> — Anthropic Engineering Blog, 2026

이 문서는 AI 에이전트(Claude, Gemini, Codex)가 장기 실행 작업을 효율적으로 수행하기 위한 **하네스(Harness) V2 명세서**입니다.

**참고 자료:**
- [Effective Harnesses for Long-Running Agents](https://www.anthropic.com/engineering/effective-harnesses-for-long-running-agents)
- [Harness Design for Long-Running Apps](https://www.anthropic.com/engineering/harness-design-long-running-apps)

---

## 🎯 핵심 원칙 (V2 Principles)

| # | 원칙 | 설명 |
|---|------|------|
| 1 | **지도를 주고 매뉴얼을 주지 마라** | `PROJECT_MAP.md`를 최우선 참고. 코드를 읽기 전에 지도를 먼저 본다. |
| 2 | **불변식을 기계로 강제하라** | `harness_verify.py`가 정의하는 제약 조건을 모든 에이전트가 준수. |
| 3 | **자기평가를 믿지 마라** | Generator ≠ Evaluator. 만든 에이전트와 평가하는 에이전트를 분리. |
| 4 | **세션은 리셋이다** | 새 세션 = 새 사람. 세션 시작 프로토콜을 반드시 실행. |
| 5 | **완료를 조기 선언하지 마라** | `feature_list.json`의 모든 항목이 `passes: true`가 아니면 미완성. |
| 6 | **격리된 작업 (Git Worktrees)** | 메인 브랜치 오염 방지를 위해 워크트리에서 작업. |

---

## 🏗️ 하네스 3계층 구조

```
┌─────────────────────────────────────────────────────────┐
│  Layer 1: 컨텍스트 하네스 (Context Harness)               │
│  ─ 에이전트가 현재 상황을 파악하는 데 필요한 모든 것         │
│  ─ AGENTS.md, PROJECT_MAP.md, RULES.md                   │
│  ─ feature_list.json, HIVEMIND.md(자동)                  │
│  ─ 세션 시작 프로토콜                                     │
├─────────────────────────────────────────────────────────┤
│  Layer 2: 검증 하네스 (Verification Harness)              │
│  ─ 에이전트의 작업 결과를 독립적으로 평가                    │
│  ─ Generator-Evaluator 파이프라인                         │
│  ─ harness_verify.py (기계적 검증)                        │
│  ─ 스프린트 계약 (Sprint Contract)                        │
├─────────────────────────────────────────────────────────┤
│  Layer 3: 실행 하네스 (Execution Harness)                 │
│  ─ 에이전트 간 작업 분배와 통신                             │
│  ─ itcp.py (PostgreSQL 기반 메시징)                       │
│  ─ hive_tasks (PostgreSQL 원자적 체크아웃 기반 분배)       │
│  ─ Plan → Work → Review 사이클                           │
└─────────────────────────────────────────────────────────┘
```

---

## 📋 Layer 1: 컨텍스트 하네스

### 1.1 세션 시작 프로토콜 (Session Init Protocol)

**모든 에이전트는 새 세션 시작 시 아래 순서를 반드시 실행한다.**

```
Step 1: 현재 위치 확인
  → pwd (또는 작업 디렉토리 확인)

Step 2: 하이브 컨텍스트 로드
  → python scripts/memory.py list        (하이브 공유 메모리)
  → python scripts/analyze_hive.py       (에이전트 활동 분석)

Step 3: 진행 상황 파악
  → cat feature_list.json                (기능 목록 + 완료 상태)
  → git log --oneline -10                (최근 커밋)

Step 4: 환경 검증
  → python scripts/harness_verify.py     (하네스 상태 확인)

Step 5: 다음 작업 선택
  → feature_list.json에서 passes=false인 첫 번째 항목 선택
  → 또는 ai_monitor_plan.md에서 현재 단계 확인
```

**에이전트별 추가 프로토콜:**

| 에이전트 | 추가 단계 |
|---------|----------|
| Claude  | `check_new_messages` (그룹챗 확인) |
| Gemini  | `.gemini/skills/` 스킬 목록 로드 |
| Codex   | `itcp receive` (ITCP 메시지 확인) |

### 1.2 Feature List (기능 목록)

프로젝트의 모든 기능을 구조화된 JSON으로 관리한다.
이 파일은 **에이전트가 수정할 수 없는 테스트 기준** 역할을 한다.

**파일 위치:** `feature_list.json` (프로젝트 루트)

**스키마:**
```json
{
  "version": "2.0",
  "last_updated": "2026-03-30",
  "last_updated_by": "human",
  "features": [
    {
      "id": "F001",
      "category": "functional | visual | performance | security",
      "priority": "P0 | P1 | P2",
      "description": "기능 설명 (한글)",
      "acceptance_criteria": [
        "검증 가능한 구체적 기준 1",
        "검증 가능한 구체적 기준 2"
      ],
      "assigned_to": "claude | gemini | codex | null",
      "evaluated_by": "claude | gemini | codex | null",
      "passes": false,
      "notes": ""
    }
  ]
}
```

**불변 규칙:**
- `features` 배열의 항목을 **삭제하는 것은 금지** (사람만 삭제 가능)
- `passes`를 `true`로 변경하려면 **다른 에이전트의 평가**가 필요
- `last_updated_by`가 `"human"`인 경우 구조 변경 금지

### 1.3 진행 상황 추적 (progress.md 은퇴 — 2026-06-21)

**[변경]** 과거에는 루트 `progress.md` 파일에 진행 상황을 수기로 기록했으나,
**HIVEMIND.md(자동 생성) + PostgreSQL(pg_logs/hive_tasks/agent_heartbeats)** 가
같은 역할을 더 정확히(실시간, 다중 에이전트) 수행하므로 progress.md는 폐기했다.

- "어제 뭐 했지" 류 조회 → **DB 우선** (`scripts/analyze_hive.py`, `pg_logs`)
- 세션 연속성/다음 세션 브리핑 → `active_session_context` + `scripts/checkpoint.py`
- 진행 상황 스냅샷 문서 → `HIVEMIND.md` (자동 갱신)

harness_verify의 `progress-stale` 검사와 itcp 부트스트랩의 progress 주입도 함께 제거됨.

---

## 🔍 Layer 2: 검증 하네스

### 2.1 Generator-Evaluator 파이프라인

**핵심 원칙: 만든 에이전트 ≠ 평가하는 에이전트**

Anthropic 블로그의 핵심 발견: "에이전트가 자신의 작업을 평가할 때 과도하게 긍정적으로 평가한다."
이를 해결하기 위해 Generator(생성기)와 Evaluator(평가기)를 분리한다.

```
┌──────────────┐     구현     ┌──────────────┐
│  Generator   │ ──────────▶ │   코드/기능    │
│  (구현 에이전트) │             │   산출물      │
└──────────────┘             └──────┬───────┘
                                    │
                                    ▼
                             ┌──────────────┐
                             │  Evaluator   │
                             │  (평가 에이전트) │
                             └──────┬───────┘
                                    │
                          ┌─────────┴─────────┐
                          │                   │
                        PASS               FAIL
                          │                   │
                    passes=true          피드백 전달
                                              │
                                              ▼
                                      Generator 재작업
```

**역할 매칭 매트릭스:**

| Generator | 최적 Evaluator | 이유 |
|-----------|---------------|------|
| Claude (프론트엔드) | Gemini | 아키텍처 관점 평가 |
| Claude (로직) | Codex | 샌드박스 실행으로 실제 검증 |
| Gemini (설계) | Claude | 정밀 로직 검증 |
| Gemini (데이터) | Codex | 실행 결과 검증 |
| Codex (스크립트) | Claude | 코드 리뷰 + 보안 검증 |
| Codex (테스트) | Gemini | 테스트 커버리지 분석 |

**단일 에이전트 모드 (Solo Mode):**
에이전트가 1개만 활성화된 경우, `harness_verify.py`를 Evaluator로 대체한다.
기계적 검증만 수행하되, **자기평가는 최소화**한다.

### 2.2 스프린트 계약 (Sprint Contract)

작업 시작 전, Generator와 Evaluator가 **"완료의 정의"를 사전 합의**한다.

**계약 프로세스:**

```
1. Generator → 스프린트 계약 초안 작성
   "F003 그룹 채팅 UI를 구현하겠습니다. 완료 기준:"
   - [ ] 메시지 전송/수신 동작
   - [ ] 실시간 업데이트 (WebSocket)
   - [ ] 에이전트별 아이콘 표시
   - [ ] 모바일 반응형 레이아웃

2. Evaluator → 계약 검토 및 보완
   "추가 기준 요청:"
   - [ ] 메시지 100개 이상 스크롤 성능
   - [ ] 오프라인 시 재연결 처리

3. 합의 → 구현 시작

4. 구현 완료 → Evaluator가 계약 기준으로 검증
```

**계약 파일 위치:** `sprint_contracts/` 디렉토리
**파일명 규칙:** `sprint_FXXX_YYYYMMDD.md`

**계약 템플릿:**
```markdown
# Sprint Contract: F003 그룹 채팅 UI

- Generator: Claude
- Evaluator: Gemini
- 시작일: 2026-03-30
- 예상 세션: 2회

## 완료 기준 (Acceptance Criteria)
- [ ] 메시지 전송/수신 동작
- [ ] 실시간 업데이트
- [ ] 에이전트별 아이콘
- [ ] 모바일 반응형

## Evaluator 추가 기준
- [ ] 스크롤 성능 (100+ 메시지)
- [ ] 오프라인 재연결

## 검증 방법
- Evaluator가 실제 UI를 조작하여 각 기준 검증
- harness_verify.py 통과 필수
```

### 2.3 기계적 검증 (harness_verify.py)

`harness_verify.py`는 사람의 개입 없이 자동으로 실행되는 검증 스크립트이다.

**V2 검사 항목:**

| 검사 ID | 설명 | 실패 시 |
|---------|------|---------|
| `required-doc` | 필수 문서 존재 확인 | 문서 생성 |
| `agents-too-long` | AGENTS.md 120줄 제한 | 내용 분리 |
| `agents-link-missing` | 필수 참조 링크 | 링크 추가 |
| `hot-file-large` | 핵심 파일 크기 초과 | 모듈 분리 |
| `runtime-path-missing` | 핵심 스크립트 누락 | 파일 복구 |
| `feature-list-missing` | feature_list.json 부재 | 파일 생성 |
| `feature-list-schema` | feature_list.json 스키마 위반 | 스키마 수정 |
| `self-eval-detected` | Generator=Evaluator 동일 | 평가자 변경 |
| `contract-missing` | 활성 작업에 스프린트 계약 없음 | 계약 작성 |

---

## ⚡ Layer 3: 실행 하네스

### 3.1 Plan → Work → Review 사이클

모든 기능 구현은 3단계 사이클을 따른다.

```
┌─────────┐     ┌─────────┐     ┌─────────┐
│  PLAN   │ ──▶ │  WORK   │ ──▶ │ REVIEW  │
│ 계획 수립 │     │ 코드 구현 │     │ 독립 평가 │
└─────────┘     └─────────┘     └────┬────┘
     ▲                                │
     │          FAIL                  │
     └────────────────────────────────┘
```

**각 단계별 책임:**

| 단계 | 수행자 | 산출물 |
|------|--------|--------|
| PLAN | Gemini (또는 사람) | ai_monitor_plan.md + sprint_contract |
| WORK | Claude / Codex | 코드 + git commit + DB 로그(pg_logs/checkpoint) |
| REVIEW | 다른 에이전트 또는 harness_verify.py | feature_list.json 업데이트 |

### 3.2 에이전트 간 통신 (ITCP)

에이전트 간 모든 통신은 **PostgreSQL pg_messages** 테이블을 통해 이루어진다.

**채널 구조:**

| 채널 | 용도 | 예시 |
|------|------|------|
| `general` | 일반 정보 공유 | "F003 작업 시작합니다" |
| `task` | 작업 요청/위임 | "F005 Codex에게 위임" |
| `review` | 평가 요청/결과 | "F003 평가 완료: PASS" |
| `contract` | 스프린트 계약 협상 | "추가 기준 제안" |
| `broadcast` | 전체 공지 | "하네스 V2 적용 완료" |

**Generator-Evaluator 통신 패턴:**

```
Generator (Claude)
  → [review 채널] "F003 구현 완료. 평가 요청."
  → 첨부: sprint_contracts/sprint_F003_20260330.md

Evaluator (Gemini)
  → [review 채널] "F003 평가 결과: 3/5 기준 통과. 피드백:"
  → "- 스크롤 성능 미달: 100개 메시지 시 1.2초 지연"
  → "- 오프라인 재연결 미구현"

Generator (Claude)
  → [review 채널] "피드백 반영 완료. 재평가 요청."
```

### 3.3 컨텍스트 관리 전략

**Opus 4.6 기준:**
- 자동 압축(auto-compaction)이 대부분의 경우 충분
- 컨텍스트 리셋은 **2시간 이상 연속 작업** 시에만 고려

**세션 전환 시 핸드오프:**
1. `scripts/checkpoint.py`로 현재 상태/의도/다음 단계 기록 (DB)
2. `feature_list.json` 갱신
3. git commit으로 체크포인트 생성
4. 다음 세션은 세션 시작 프로토콜로 시작 (HIVEMIND.md + DB 브리핑)

**컨텍스트 리셋이 필요한 신호:**
- 같은 버그를 3회 이상 반복 시도
- 에이전트가 이전에 삭제한 코드를 다시 생성
- 응답 품질이 눈에 띄게 저하

---

## 🚫 금지 사항

1. `server.py`의 5000줄 초과 수정 금지 (분리 권장)
2. `RULES.md`에 명시되지 않은 에이전트 행동 지침 임의 수정 금지
3. `feature_list.json`에서 항목 삭제 금지 (사람만 가능)
4. Generator가 자신의 `passes` 필드를 `true`로 변경 금지
5. 스프린트 계약 없이 P0/P1 기능 구현 시작 금지

---

## 📊 하네스 성숙도 체크리스트

프로젝트의 하네스 성숙도를 자가 진단하는 체크리스트:

- [ ] `feature_list.json`이 존재하고 최신 상태인가?
- [ ] 모든 P0 기능에 스프린트 계약이 있는가?
- [ ] Generator ≠ Evaluator가 보장되는가?
- [ ] `harness_verify.py`가 CI에서 실행되는가?
- [ ] 세션 시작 프로토콜이 모든 에이전트에서 작동하는가?
- [ ] ITCP를 통한 에이전트 간 통신이 정상인가?

---

## 🔄 V1 → V2 마이그레이션

| V1 | V2 | 변경 사항 |
|----|-----|----------|
| HARNESS_V1.md | HARNESS_V2.md | 이 문서로 대체 |
| harness_verify.py (5개 검사) | harness_verify.py (10개 검사) | V2 검사 항목 추가 |
| HARNESS_CHECKS.md | HARNESS_CHECKS.md | V2 기준으로 업데이트 |
| 없음 | feature_list.json | 신규 |
| 없음 | sprint_contracts/ | 신규 |

**하위 호환성:** V1의 모든 검사 항목은 V2에 포함. V1 문서는 V2 참조로 리다이렉트.

---

**작성일:** 2026-03-30
**상태:** 하네스 V2 — Anthropic 엔지니어링 블로그 기반 설계 완료
