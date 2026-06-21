<!--
FILE: docs/PLATFORM_LAYERS.md
DESCRIPTION: Vibe Coding 플랫폼의 레이어 경계 정의.
             "Vibe Coding = 하네스/하이브/옵시디언 내장 멀티에이전트 IDE"라는
             아키텍처 원칙을 문서화한다.
             모든 프로젝트에 공통으로 주입되는 런타임과, 프로젝트별로 정의되는
             확장의 경계를 명시하여 향후 멀티 프로젝트 플랫폼화의 기준선을 제공한다.

REVISION HISTORY:
- 2026-04-19 Claude: 최초 작성 — Phase 1 경계 문서화
  - 3-Layer 모델(Host / Common Runtime / Project Extension) 정의
  - 현재 리포의 레이어 혼재 지점 자가 진단
  - Phase 2~4 마이그레이션 로드맵 제시
-->

# 🏛️ Vibe Coding — Platform Layers

> **"Vibe Coding은 하네스/하이브/옵시디언을 내장한 멀티에이전트 IDE다.
> 프로젝트를 여기서 열면 이 3개는 자동으로 붙는 기본 런타임이고,
> 그 위에 프로젝트별 스킬·에이전트가 얹힌다."**

이 문서는 Vibe Coding 플랫폼의 **레이어 경계**를 정의한다.
코드 수정 전 합의 기준선이며, 이후 모든 리팩터링·신규 기능은 이 문서를 기준으로 "어느 레이어 작업인가"를 명시해야 한다.

---

## 🎯 3-Layer 모델

```
┌────────────────────────────────────────────────────────────┐
│  Layer 2: Project Extensions                              │
│  ─ 프로젝트 루트의 .vibe/skills, .vibe/agents              │
│  ─ CLAUDE.md, GEMINI.md, CODEX_GUIDE.md                   │
│  ─ feature_list.json (프로젝트 고유)                       │
└────────────────────────────────────────────────────────────┘
                         ▲ 의존
                         │
┌────────────────────────────────────────────────────────────┐
│  Layer 1: Common Runtime (모든 프로젝트에 자동 주입)         │
│  ─ 하네스 엔지니어링 (harness_verify, sprint contracts)    │
│  ─ 하이브 마인드 + 제텔카스텐 (PostgreSQL hive_*, zettel_*) │
│  ─ 옵시디언 Vault 동기화                                   │
└────────────────────────────────────────────────────────────┘
                         ▲ 의존
                         │
┌────────────────────────────────────────────────────────────┐
│  Layer 0: Host Platform (Vibe Coding IDE 그 자체)          │
│  ─ .ai_monitor/ (React UI + Python 서버)                  │
│  ─ 터미널 PTY, Monaco 편집기, 멀티 프로젝트 탭             │
│  ─ PostgreSQL 18 내장, pyinstaller 패키징                 │
└────────────────────────────────────────────────────────────┘
```

---

## Layer 0 — Host Platform

**역할:** IDE/에디터 껍데기. 중립적 실행 환경.

**구성 요소:**
- `.ai_monitor/server.py` — HTTP/SSE/WebSocket 오케스트레이터
- `.ai_monitor/vibe-view/` — React UI (에디터 셸, 터미널, 파일 탐색기)
- `.ai_monitor/pty-server/` — Node.js PTY
- PostgreSQL 18 포터블 런타임
- pyinstaller 빌드 스펙, GitHub Actions 릴리즈 파이프라인

**원칙:**
- 프로젝트 내용을 **모른다**. 열려 있는 프로젝트 루트 경로와 `project_id`만 안다.
- Layer 1/2에 대해 중립. Layer 1 API를 호출하는 게 아니라, Layer 1이 Layer 0의 훅(파일 감시, 터미널 이벤트, UI 라우팅)에 **등록**된다.

---

## Layer 1 — Common Runtime (자동 주입)

**역할:** 모든 프로젝트에 공통으로 활성화되는 런타임 서비스. 이 리포의 "진짜 알맹이".

### 1-A. 하네스 엔지니어링

| 컴포넌트 | 현재 위치 | 책임 |
|---------|----------|------|
| `harness_verify.py` | `scripts/` | 필수 문서·런타임 파일·핫 파일 크기·feature_list 스키마·계약 검증 |
| Feature List | `feature_list.json` | 프로젝트별 기능 목록 + passes 상태 |
| Sprint Contracts | `sprint_contracts/` | Generator-Evaluator 합의 계약 |
| Progress Log | `HIVEMIND.md`(자동) + DB(pg_logs/checkpoint) | 세션 간 핸드오프 (progress.md 폐기 2026-06-21) |
| HARNESS_V2.md | `docs/` | 계약 명세 |

### 1-B. 하이브 마인드 + 제텔카스텐

| 컴포넌트 | PostgreSQL 테이블 | 책임 |
|---------|------------------|------|
| 태스크 큐 | `hive_tasks` | 원자적 체크아웃 기반 작업 분배 |
| 공유 메모리 | `hive_memory` | 에이전트 간 지식 교환 |
| 세션 컨텍스트 | `hive_sessions`, `active_session_context` | 세션 복구 / 브리핑 |
| 활동 추적 | `pg_logs`, `agent_heartbeats`, `agent_experience` | DB 우선 조회 원칙의 근거 |
| 에이전트 통신 | `pg_messages`, `task_comments` | ITCP 프로토콜 |
| 제텔카스텐 노트 | `zettel_notes`, `zettel_links` | fleeting → permanent 자동 승격 |

### 1-C. 옵시디언 Vault 동기화 (현재 미구현 — Phase 4)

- `zettel_notes`(permanent) ↔ Obsidian Markdown 양방향 동기화
- `zettel_links` ↔ `[[wiki-links]]` 변환
- 프로젝트별 Vault 분리 (`vaults/<project_id>/`)

**원칙:**
- Layer 1은 **프로젝트 비의존**. `project_id`를 인자로만 받는다.
- Layer 1은 PostgreSQL을 단일 진실 소스로 삼는다 (`.jsonl`/SQLite 폴백 금지).
- Layer 1은 Layer 2를 **스캔**하되 강제하지 않는다.

---

## Layer 2 — Project Extensions

**역할:** 프로젝트 루트에 정의되어 **자동 로드**되는 확장.

**컨벤션 (제안 — Phase 3에서 확정):**

```
<project-root>/
├── CLAUDE.md               # 에이전트 가이드 (필수)
├── GEMINI.md
├── CODEX_GUIDE.md
├── feature_list.json       # 프로젝트 고유 기능 목록 (Layer 1 스키마 준수)
├── sprint_contracts/       # Layer 1 스키마 준수
└── .vibe/
    ├── skills/             # 프로젝트 특화 슬래시 커맨드
    │   └── <skill-name>/
    │       └── SKILL.md
    ├── agents/             # 프로젝트 특화 에이전트 역할
    │   └── <agent-name>.md
    └── rules/              # 프로젝트 규칙 (RULES.md 보완)
```

**원칙:**
- Layer 2는 **Layer 1 API만 호출**. Layer 0 내부에 직접 접근 금지.
- Layer 2가 없어도 Layer 1은 동작. 기본값/폴백 제공.
- `.vibe/`는 `.claude/`와 **별개**. `.claude/`는 Claude CLI 전용, `.vibe/`는 플랫폼 공통.

---

## 🚨 경계 불변식 (Invariants)

| # | 불변식 | 위반 시 |
|---|-------|---------|
| 1 | Layer 0은 Layer 1/2의 내용을 몰라도 동작해야 한다 | 플랫폼화 불가 |
| 2 | Layer 1은 어떤 프로젝트에서도 동일 동작 (`project_id` 스코프만 분리) | 프로젝트 간 오염 |
| 3 | Layer 2는 Layer 1 API만 호출 (Layer 0 직접 접근 금지) | 호스트 변경 시 프로젝트 깨짐 |
| 4 | DB의 모든 Layer 1 테이블은 `project_id` 컬럼 필수 | 멀티 프로젝트 미지원 |
| 5 | 프로젝트 간 상태 공유 시 `hive_memory.scope='global'` 명시 | 암묵적 공유로 추적 불가 |

---

## 🔍 현재 리포의 레이어 혼재 자가 진단

> **"이 리포는 Layer 0 + Layer 1 + 이 리포 자체의 Layer 2가 뒤섞여 있다."**

| 위치 | 원래 레이어 | 혼재 문제 |
|------|-----------|---------|
| `scripts/harness_verify.py` | Layer 1 | 이 리포 루트를 `PROJECT_ROOT`로 하드코딩. 타 프로젝트 주입 불가 |
| `.ai_monitor/api/vibe_api.py` | Layer 0 | `feature_list.json` 직접 조작 — Layer 1 로직이 Layer 0에 섞임 |
| `.ai_monitor/api/memory_api.py` | Layer 1 로직 | 위치는 Layer 0 안쪽 — 주입 시 분리 필요 |
| `.claude/skills/`, `.claude/commands/` | Layer 2 (이 리포 자체의) | Claude CLI 전용 — 플랫폼 공통 `.vibe/` 규약 별도 필요 |
| `HARNESS_V2.md`, `RULES.md` | Layer 1 명세 | 위치는 프로젝트 루트 — 플랫폼 템플릿으로 승격 필요 |
| `feature_list.json` | 이 리포의 Layer 2 데이터 | 플랫폼의 "템플릿"과 구분 필요 |

---

## 🛣️ 마이그레이션 로드맵

### Phase 1 (현재) — 경계 문서화 ✅
이 문서 작성 + 레이어 원칙 합의.

### Phase 2 — project_id 스코프 강제
- 모든 Layer 1 테이블 스키마 점검: `project_id` 컬럼 필수화
- 기존 빈/default project_id 마이그레이션
- UI에 **프로젝트 탭** 추가 — 탭 전환 시 모든 쿼리에 `project_id` 자동 적용
- `project_next_phase_plan.md`의 "멀티 프로젝트 탭" 흡수

### Phase 3 — `.vibe/` 컨벤션 스캐너
- `.vibe/skills`, `.vibe/agents`, `.vibe/rules` 로더 구현
- 프로젝트 열기 시 자동 스캔 → UI에 동적 등록
- `harness_verify.py`를 `PROJECT_ROOT` 인자 기반으로 범용화

### Phase 4 — Obsidian Vault 연동
- `vaults/<project_id>/` 구조
- `zettel_notes` ↔ Markdown 양방향 동기화
- `zettel_links` ↔ `[[wiki-links]]` 변환
- 프로젝트 설정에서 Vault 경로 지정

### Phase 5 — 플랫폼 빌드 분리
- "이 리포 개발용" 코드와 "배포 IDE 런타임"을 빌드 시 분리
- Layer 1 템플릿을 EXE에 내장 → 새 프로젝트 열 때 자동 스캐폴딩

---

## ❓ 자주 하는 질문

**Q. 어제 삭제한 `auto_dispatcher.py`는 Layer 1이었나?**
이론상 Layer 1 (에이전트 간 분배). 하지만 이 리포 실사용 0이었고, 현재는 `hive_tasks` 원자적 체크아웃이 같은 역할을 충분히 수행. 플랫폼화 진행 중 다시 필요해지면 재도입. 지금은 제거 유지.

**Q. `CLAUDE.md`는 Layer 1인가 Layer 2인가?**
**Layer 2 데이터**. 스키마/규약은 Layer 1, 실제 내용은 프로젝트별.

**Q. `.claude/`와 `.vibe/`는 중복 아닌가?**
아니다. `.claude/`는 Claude CLI 전용 훅/스킬 (Anthropic 규약), `.vibe/`는 플랫폼 공통 (멀티 에이전트 — Claude·Gemini·Codex 공용). Phase 3에서 `.claude/` 내용 중 공통 부분을 `.vibe/`로 마이그레이션.

---

**작성일:** 2026-04-19
**상태:** Phase 1 — 초안. 사용자 리뷰 대기.
