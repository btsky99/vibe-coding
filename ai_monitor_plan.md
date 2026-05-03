# 바이브 코딩 — Next Phase 계획서

> 2026-04-16 브레인스토밍 결과. 5단계 개선 계획 완료 후 다음 방향.

---

## 설계 철학 (오늘 토론에서 합의)

1. **멀티-LLM 유지** — Claude/Gemini/Codex 각자 강점 활용, 직접 협업보다 **메모리 공유** 중심
2. **로컬 DB = 속도**, **옵시디언+GDrive = 공유** — 역할 분리
3. **점진적 구현** — 한번에 다 안 만들고 단계별로

---

## Phase A: 멀티 프로젝트 탭

> 하나의 EXE에서 여러 프로젝트를 탭으로 전환, 각 프로젝트마다 T1~T8 독립 실행

### Step A-1: 프로젝트 스위칭 (MVP)
- 상단 메뉴바에 프로젝트 드롭다운 추가
- config.json `projects`에서 목록 로드
- 전환 시 `current_project_id` 변경 + PTY 세션 리셋
- DB는 project_id로 이미 격리됨 — 추가 작업 최소

### Step A-2: 프로젝트 탭 UI
- 드롭다운 → 상단 탭 바로 업그레이드
- 탭 간 전환 시 PTY 세션 상태 보존 (숨김 처리)
- 각 탭에 프로젝트명 + 활성 에이전트 수 배지

### Step A-3: 완전 독립 멀티탭
- 프로젝트별 PTY 세션 풀 분리 (project_id:T1~T8)
- 동시에 여러 프로젝트 에이전트 실행
- 탭 간 메모리 공유 (hive_memory 크로스 project)

---

## Phase B: 멀티-LLM 메모리 공유 모델

> 직접 협업 → 간접 협업. 각 LLM이 자기 일 하면서 배운 것을 공유 메모리에 남기는 구조.

### 현재 상태
- `hive_memory` 테이블 존재, `scripts/memory.py`로 읽기/쓰기 가능
- 에이전트별 프로필과 디스패처 코드는 유지 (실험적 라벨)
- Claude만 실제 활성, Gemini/Codex는 사용자가 수동 실행 시 참여

### 강화할 것
- [ ] 세션 시작 시 **자동 브리핑** — "지난번에 Gemini가 이거 조사했어" 자동 주입
- [ ] 메모리 **작성자 태그** 강화 — 누가 남긴 메모인지 명확히
- [ ] 메모리 UI — HivePanel에 "최근 공유 메모리" 카드 추가
- [ ] 디스패처는 "실험적" 유지 — 필요 시 수동으로 활성화 가능

### 원칙
- 에이전트끼리 직접 통신 안 함 (ITCP는 레거시 유지)
- DB에 남기고, 다음 에이전트가 읽는 비동기 패턴
- 오버헤드 최소: 메모리 읽기/쓰기만

---

## Phase C: 하이브-제텔카스텐 통합 (DB 1차, 옵시디언은 거울)

> **재정리 (2026-04-17)** — 기존 설계는 옵시디언 중심이었지만, 팩트체크 결과
> `zettel_notes` 테이블이 DB에 이미 234건 쌓여 있고 제텔 구조(note_type,
> links, access_count, archived) 모두 갖춤. 진짜 문제는 에이전트가
> `hive_memory`(48건)만 조회하고 `zettel_notes`는 못 본다는 것.
> 옵시디언은 크로스-PC **미러**에 불과, DB가 1차 지식 소스.

### 현재 DB 팩트 (2026-04-17)
| 테이블 | 건수 | 현 역할 | 문제 |
|--------|------|---------|------|
| `hive_memory` | 48 | 실시간 메모, 채팅, 잡다 | 에이전트가 이것만 봄 |
| `zettel_notes` | 234 | 커밋 훅 자동 캡처, 제텔 구조 | 조회 경로 단절 → 사장됨 |
| `zettel_links` | N | 노트 간 연결 | 옵시디언 동기화용 |

### 역할 분리 (수정)
| 계층 | 역할 | 속도 | 범위 |
|------|------|------|------|
| `hive_memory` (DB) | 실시간 작업 흔적, 채팅, 진행 메모 | ms | PC 1대 |
| `zettel_notes` (DB) | **정제된 지식** — 에이전트 1차 참조 | ms | PC 1대 |
| 옵시디언+GDrive | zettel_notes의 거울 | 초~분 | 모든 PC |

### Phase C 실행 순서 (1→2→3)

#### C.1 통합 검색 API (쉬움, 즉효)
- [ ] `/api/memory?include_zettel=true` — hive_memory + zettel_notes 동시 검색
- [ ] `list_memory()` 시그니처 확장: `include_zettel: bool = False`
- [ ] 검색 결과에 `source: 'hive' | 'zettel'` 필드 추가
- [ ] UI: MemoryPanel에 "지식 포함" 토글 + HivePanel 카드가 zettel도 표시
- **효용**: 즉시 234건 지식이 에이전트 조회 범위에 들어옴

#### C.2 에이전트 브리핑 소스 확장
- [ ] 세션 시작 자동 브리핑에 `zettel_notes.access_count` 상위 N개 + 최근
      permanent 노트 주입 (현재는 hive_memory만)
- [ ] "지난번 너가/다른 에이전트가 배운 것" 섹션으로 분리 표시
- [ ] B.2 작성자 태그와 맞물려 "Gemini가 쓴 지식 1건, Claude가 쓴 지식 2건" 식
- **효용**: 에이전트가 누적 지식을 세션 첫 턴부터 활용

#### C.3 hive_memory → zettel_notes 승격 파이프라인
- [ ] 자동 분류기 — tag에 `learning`/`insight` 또는 note_type 지정 시 승격
- [x] fleeting → permanent 자동 승격 규칙 — C.4, B안 (7일+access≥2 OR degree≥3 OR 태그 permanent/영구), `memory.py promote-auto [--dry-run]`
- [ ] 승격 시 `source_ref`에 원본 hive_memory key 보존
- [ ] 옵시디언 동기화 선별 (permanent만, fleeting 제외)
- **효용**: 잡다한 `hive_memory`가 지식으로 정제되어 쌓임

### 원칙
- DB가 1차. 옵시디언은 읽기 좋은 거울일 뿐.
- `zettel_notes`가 "진짜 지식 저장소", `hive_memory`는 "작업 흔적".
- 승격은 자동 + 수동(에이전트가 명시 태그) 둘 다 가능하게.

---

## 우선순위 & 실행 순서 (2026-04-17 갱신)

| 순서 | Phase | 난이도 | 예상 | 의존성 | 상태 |
|------|-------|--------|------|--------|------|
| 1 | A-1 프로젝트 스위칭 | 🟢 쉬움 | 반나절 | 없음 | ✅ |
| 2 | B.1 자동 브리핑 | 🟢 쉬움 | 반나절 | 없음 | ✅ |
| 3 | B.2 작성자 태그 강화 | 🟢 쉬움 | 반나절 | B.1 | ✅ (fb2612e) |
| 4 | B.3 HivePanel 메모리 카드 | 🟢 쉬움 | 반나절 | B.2 | ✅ (e6615b2) |
| 5 | C.1 통합 검색 API | 🟢 쉬움 | 반나절 | B.2 | ✅ (5f64eac) |
| 6 | C.2 브리핑 소스 확장 | 🟡 중간 | 반나절 | C.1, B.1 | ✅ (1bb9414) |
| 7 | C.3 승격 파이프라인 | 🟡 중간 | 1일 | C.1 | ✅ (0489122) |
| 8 | C.4 fleeting→permanent 자동 규칙 | 🟡 중간 | 반나절 | C.3 | ✅ (8ec7e74, c685f4a) |
| 9 | A-2/A-3 → **Platform Phase 2~5로 통합** (`docs/PLATFORM_LAYERS.md`) | — | — | — | 🎯 진행 중 |

> **2026-04-19 재정렬:** A-2/A-3(멀티 프로젝트 탭)는 단순 UI 작업이 아니라
> "Vibe Coding = 하네스/하이브/옵시디언 내장 IDE" 아키텍처 정의의 일부.
> 상위 로드맵은 [docs/PLATFORM_LAYERS.md](docs/PLATFORM_LAYERS.md)로 승격,
> 이 계획서는 그 하위 마이크로태스크만 추적.

---

## Platform Phase 2 — project_id 스코프 강제 (상세)

> 상위 문서: [docs/PLATFORM_LAYERS.md](docs/PLATFORM_LAYERS.md)
> 목표: Layer 1의 모든 DB 쓰기가 `project_id`로 격리되어, 여러 프로젝트가
> 서로 오염 없이 공존 가능하게 한다.

### 2-1 DB 스키마 감사 (읽기 전용) ✅ 2026-04-30
- [x] Layer 1 테이블 목록 확정 — 16개 테이블
- [x] 각 테이블에 `project_id` 컬럼 존재 여부 측정 — 16/16 보유
- [x] 기존 데이터의 `project_id` 분포 측정 — 빈 값 332건 (5개 테이블)
- [x] 감사 결과: 인덱스 누락 1건(hive_sessions), NOT NULL 미적용 2건(hive_sessions, pg_logs)

### 2-2 project_id 컬럼 추가 마이그레이션 (있어야 할 곳) ✅ 2026-04-30
- [x] 빈 값 데이터 332건 'D--vibe-coding'으로 backfill (migrate_project_id_backfill.py 확장 — hive_tasks, pg_logs 추가)
- [x] hive_sessions에 project_id 인덱스 추가
- [x] hive_sessions, pg_logs project_id NOT NULL 강제
- [x] pg_store.py 동기화 — 신규 환경에서도 동일 보장

### 2-3 project_id Resolver 유틸 ✅ 2026-04-30
- [x] 활성 project_id 헬퍼 분리 — `infra/project_context.py` 신설
      (`current_project_root`, `current_project_id`, `slugify`)
- [x] 서버: `_current_project_root`/`_id`가 새 모듈 위임
- [x] 컨텍스트 미지정 경고 — `assert_project_id(pid, op)` + VIBE_DEV_MODE 가드
- [ ] UI 측 통합 헬퍼 (Phase 2-4/2-5에서 라우팅 일관화 시 같이 처리)

### 2-4 데이터 계층 일관화 (pg_store.py 중심) ✅ 2026-05-02

> 2026-04-30 브레인스토밍 결과 — 타겟을 **API 모듈 → 데이터 계층**으로 이동.
> API 직접 INSERT는 2개뿐(office/vibe), 실제 쓰기 진입점은 `pg_store.py` 32곳에 집약.
> 호출자 9~18개 모듈은 pg_store 한 군데 잡으면 자동 혜택.
> 위험도 🟢 — Phase 2-2의 NOT NULL이 마지막 수문장. 가드는 dev 모드 전용, prod 무동작.
>
> **결과 (2026-05-02):** pg_store 11곳 + zettelkasten 1곳 가드 적용. 패턴 C 5개를 A로 변환. `save_state`/`record_heartbeat`는 본질적으로 전역(state_key/agent_id PK)이라 N/A 재분류. `api/office_api.py` 직접 INSERT 2건은 다음 라운드 별도 처리.

#### 패턴 정의
- **A. 호출자 인자**: `def f(..., project_id='')` — 호출자가 명시
- **B. 내부 자동해결**: 함수 내부에서 `current_project_id()` 호출
- **C. 누락**: 빈 값 들어갈 수 있음 → A 또는 B로 변환 대상

#### 마이크로태스크

- [x] **Task 2-4.0 감사** — pg_store.py 쓰기 함수 27개 분류 완료. 패턴 A 5, B 0, C 7(→ 2개는 N/A 재분류, 5개 보완), N/A 13.
- [x] **Task 2-4.1 가드 삽입 — 패턴 A** — pg_store 5곳 + zettelkasten 1곳에 `assert_project_id` 적용.
- [x] **Task 2-4.2 누락 보완 — 패턴 C** — 5개 함수 시그니처에 `project_id: str = ''` 추가 + 가드 + INSERT/UPDATE 컬럼 반영. `bulk_update_tasks`는 WHERE 절 필터 추가(프로젝트 누수 차단). `save_state`/`record_heartbeat`는 PK 전역이라 N/A 유지.
- [x] **Task 2-4.3 검증** — VIBE_DEV_MODE=1 정상 7건 WARN 0 / 누락 케이스 의도 WARN / prod 무동작 ✅
- [x] **Task 2-4.4 문서** — `.claude/rules/architecture.md` 데이터 계층 항목 + `infra/project_context.py` 헤더 사용 예시 추가.
- [x] **Task 2-4.5 메모리 + 계획서** — `feedback_project_id_pattern.md` 신규 + `MEMORY.md` 인덱스 + `project_next_phase_plan.md` 갱신.

#### 의존성
- 2-4.1은 2-4.0 완료 후
- 2-4.2는 2-4.0 완료 후 (패턴 C 0이면 스킵)
- 2-4.3은 2-4.1, (2-4.2) 완료 후
- 2-4.4는 2-4.3 완료 후 (검증 통과 후 문서화)
- 2-4.5는 마지막

#### 비범위 (Out of Scope)
- 읽기 경로 `project_id` 필터 — Phase 2-5 또는 별도 작업
- 시그니처를 `project_id: str` (필수 인자)로 강제 — 6개월 dev 운영 후 검토 (Q2=A 결정)
- CI에서 VIBE_DEV_MODE=1 자동 실행 — 메모리에만 보존, 별도 작업

### 2-5 UI 프로젝트 탭 (기존 A-2 흡수)
- [ ] 상단 탭 바 컴포넌트
- [ ] 탭 전환 시 SWR/폴링 키에 project_id 자동 첨부
- [ ] 탭별 PTY 세션 상태 보존

---

## Platform Phase 3 — `.vibe/` 컨벤션 스캐너

> 상위 문서: [docs/PLATFORM_LAYERS.md](docs/PLATFORM_LAYERS.md)
> 목표: 프로젝트 루트의 `.vibe/skills/`를 자동 스캔해 Claude/Gemini/Codex
> 공통으로 사용 가능한 슬래시 커맨드로 노출. Layer 2 확장의 첫 걸음.

**2026-04-19 설계 결정:**
- 깊이: 얕은 스캐너 (UI 팝업 병합, 런타임 주입 X)
- 포맷: Claude Code skills 스키마 (`.vibe/skills/<name>/SKILL.md` + YAML frontmatter)
- 병합: `.claude/` + `.vibe/` 둘 다 스캔, 중복 시 `.vibe/` 우선

### 3-1 규약 문서 (`docs/VIBE_CONVENTIONS.md`) ✅ 2026-04-19
- [x] `.vibe/` 디렉토리 구조 정의
- [x] SKILL.md frontmatter 스키마 (Claude Code 호환)
- [x] `.claude/` vs `.vibe/` 병합 규칙 명시
- [x] 제한·금지 사항

### 3-2 서버 스캐너 (`.ai_monitor/api/vibe_skills_api.py`) ✅ 2026-04-19
- [x] `list_vibe_skills(project_root)` — `.vibe/skills/*/SKILL.md` 파싱
- [x] `list_claude_skills(project_root)` — 기존 `.claude/skills/*/SKILL.md` 파싱 (재사용)
- [x] `merge_skills()` — 이름 충돌 시 `.vibe/` 우선, origin 필드 부여
- [x] GET `/api/vibe/skills` 라우팅 (server.py:1672)

### 3-3 UI 병합
- [ ] 오피스 채팅 `/` 팝업의 스킬 소스를 `/api/vibe/skills`로 전환 (현재 `/api/office/skills`)
- [ ] `origin` 배지(claude/vibe) 표시
- [ ] 클래식 모드 슬래시 팝업(있다면)도 동일 전환

### 3-4 자기 드레싱 — 이 리포의 `.vibe/skills/` 샘플 ✅
- [x] `.vibe/skills/platform-check/SKILL.md` 존재

### 3-5 하네스 검증 ✅ 2026-04-19
- [x] `scripts/harness_verify.py`에 `.vibe/` 포맷 검증 추가 (`_check_vibe_skills`)
- [x] SKILL.md frontmatter 필수 필드 (`name`, `description`) 누락 시 WARN
- [ ] `tests/test_harness_verify.py` 케이스 추가

---

## 완료된 작업 (2026-04-15~16)

- [x] Phase 1: 정확한 그림 만들기
- [x] Phase 2: 시스템 정직성 확보 — gemini/codex 라벨링
- [x] Phase 3: 자동 분배 시스템 점검 — alive 체크 + 게이팅
- [x] Phase 4: 가시성 UI — 오케스트레이터 카드, 유령 배지, 백프레셔
- [x] Phase 5: 최적화 — hive_hook 다이어트, SkillChainPanel 리네임

---

## server.py 분할 (2026-04-20 승인 — B안 도메인 모듈화) ✅ 2026-04-30 완료

> 상위 메모: `~/.claude/projects/D--vibe-coding/memory/project_server_split_plan.md`
> 목표: 6363 → 4963줄 (5000 미만 안전 마진). 마지막 hot-file WARN 해소 + Platform Phase 5(빌드 분리) 선행.
> 원칙: 단계별 별도 커밋, 함수 시그니처 유지, 매 단계 후 `pytest tests/` + 서버 부팅 smoke.
> **결과: 4914줄 달성 (5000 미만). infra/ 6모듈(lifecycle/runtime/fs_watcher/memory_watcher/tool_install/postgres_runtime) 분리 완료. 단계 8b 커밋 8507db6.**

### 사전 작업

- [x] **Task 0: infra/ 패키지 디렉토리 생성** ✅
  - 파일: `.ai_monitor/infra/__init__.py`
  - 방법: 빈 `__init__.py` 생성. 패키지화만 목적.
  - 검증: `python -c "from ai_monitor import infra"` 성공

### 단계 1 — infra/lifecycle.py (190줄, 🟢) ✅

- [ ] **Task 1.1: 정리/시그널 함수 추출**
  - 파일: `.ai_monitor/infra/lifecycle.py` 신설
  - 방법: server.py L4998~5191의 `_graceful_shutdown_pty_server`, `_cleanup_child_procs`, `_cleanup_pyinstaller_temp`, `_cleanup_postgres`, `_signal_exit_handler` 5개 함수 이동. 글로벌 의존성(`_child_procs`, `_BASE_PORT` 등) 인자/import로 명시화.
  - 검증: `from ai_monitor.infra.lifecycle import _signal_exit_handler` 성공
- [ ] **Task 1.2: server.py 호출부 import 전환 + 원본 삭제**
  - 파일: `.ai_monitor/server.py`
  - 방법: 상단 import 추가, `atexit.register`/`signal.signal` 호출 위치 그대로 유지. 원본 def 5개 삭제.
  - 검증: `pytest tests/` + `python .ai_monitor/server.py --version` 무에러
- [ ] **Task 1.3: 단계 1 커밋 (`refactor(server): infra/lifecycle.py 분리`)**

### 단계 2 — infra/runtime.py (100줄, 🟢) ✅

- [ ] **Task 2.1: 런타임 유틸 추출**
  - 파일: `.ai_monitor/infra/runtime.py` 신설
  - 방법: server.py L770~870의 `_open_folder_dialog_subprocess`, `_python_runner_cmds`, `_project_python_runner_cmds`, `_resolve_playwright_install_script` 이동.
  - 검증: import 성공
- [ ] **Task 2.2: server.py + watchdog 호출부 import 전환**
  - 파일: `.ai_monitor/server.py`
  - 방법: 모든 호출부(`_python_runner_cmds()` 등) `runtime.` 접두 적용 또는 from-import.
  - 검증: 서버 부팅 smoke + `pytest tests/`
- [ ] **Task 2.3: 단계 2 커밋**

### 단계 3 — infra/fs_watcher.py (95줄, 🟢) ✅

- [ ] **Task 3.1: FS Watcher + broadcast 워커 추출**
  - 파일: `.ai_monitor/infra/fs_watcher.py` 신설
  - 방법: server.py L907~1000의 `_agent_broadcast_worker`, `FSChangeHandler`, `start_fs_watcher` 이동. `AGENT_CLIENTS` 등 글로벌 큐 의존성은 인자로 주입.
  - 검증: import + 클래스 인스턴스화 성공
- [ ] **Task 3.2: 시동 시퀀스 import 전환**
  - 파일: `.ai_monitor/server.py` (`main()` 부근)
  - 방법: `start_fs_watcher(PROJECT_ROOT)` 호출 유지, import만 수정.
  - 검증: 서버 부팅 시 watchdog 로그 정상 출력
- [ ] **Task 3.3: 단계 3 커밋**

### 단계 4 — api/office_proxy_api.py (210줄, 🟢) ✅

- [ ] **Task 4.1: Office 프록시 함수 추출**
  - 파일: `.ai_monitor/api/office_proxy_api.py` 신설
  - 방법: server.py L4823~4998의 `_proxy_to_office_server`, `_launch_office_server`, `_restart_office_server`, `_start_office_monitor` 이동. `_child_procs` 등은 인자/모듈 주입.
  - 검증: import 성공
- [ ] **Task 4.2: SSEHandler 호출부 + 시동 시퀀스 import 전환**
  - 파일: `.ai_monitor/server.py`
  - 방법: `/api/office/*` 라우트 핸들러의 `_proxy_to_office_server` 호출 유지, 모듈 import만 수정.
  - 검증: 서버 부팅 시 office_server 자동 기동 확인
- [ ] **Task 4.3: 단계 4 커밋**

### 단계 5 — api/telegram_api.py (155줄, 🟡) ✅

- [ ] **Task 5.1: Telegram 핸들러 함수 변환**
  - 파일: `.ai_monitor/api/telegram_api.py` 신설
  - 방법: SSEHandler 메서드 3개(`_handle_telegram_config_get/post`, `_handle_telegram_test`)를 모듈 함수 `def telegram_config_get(handler: SSEHandler) -> None:` 형태로 추출. `self.send_response` 등은 `handler.send_response`로 변환.
  - 검증: import 성공 + 시그니처 SSEHandler 인자 패턴 통일
- [ ] **Task 5.2: SSEHandler 라우팅에서 위임 호출**
  - 파일: `.ai_monitor/server.py` (L2847, L3427, L3430)
  - 방법: `self._handle_telegram_*` → `telegram_api.telegram_*(self)`. 클래스 메서드 def 3개 삭제.
  - 검증: `/api/config/telegram` GET/POST 수동 호출 200 응답
- [ ] **Task 5.3: 단계 5 커밋**

### 단계 6 — infra/memory_watcher.py (370줄, 🟡) ✅

- [ ] **Task 6.1: 메모리 임베딩 + Watcher 추출**
  - 파일: `.ai_monitor/infra/memory_watcher.py` 신설
  - 방법: server.py L1127~1500의 `_legacy_memory_data_dir`, `_memory_conn`, `_init_memory_db`, `_get_embedder`, `_embed`, `_cosine_sim`, `MemoryWatcher` 이동. embedder lazy init 글로벌(`_EMBEDDER`)은 모듈 내로 캡슐화.
  - 검증: `from ai_monitor.infra.memory_watcher import MemoryWatcher` + 인스턴스화 성공
- [ ] **Task 6.2: 시동 시퀀스 + memory_api 호출부 전환**
  - 파일: `.ai_monitor/server.py`, 필요 시 `.ai_monitor/api/memory_api.py`
  - 방법: import만 수정. `_embed`/`_cosine_sim` 사용처 grep 후 일괄 변경.
  - 검증: 서버 부팅 시 MemoryWatcher 스레드 정상 시작 + memory 검색 API smoke
- [ ] **Task 6.3: 단계 6 커밋**

### 단계 7 — infra/tool_install.py (200줄, 🟡) ✅

- [ ] **Task 7.1: 도구 설치 상태 머신 추출**
  - 파일: `.ai_monitor/infra/tool_install.py` 신설
  - 방법: server.py L1594~1850의 `_tool_status`, `_tool_install_now`, `_default_tool_install_state`, `_get_npm_executable`, `_get_tool_install_state`, `_set_tool_install_state`, `_watch_tool_install`, `_start_tool_install` 이동. 글로벌 상태 dict는 모듈 변수로 캡슐화.
  - 검증: import 성공 + `_tool_status('codex')` 응답 동일
- [ ] **Task 7.2: SSEHandler 라우팅 import 전환**
  - 파일: `.ai_monitor/server.py`
  - 방법: `/api/tools/*` 핸들러의 함수 호출만 import 수정.
  - 검증: 서버 부팅 + `/api/tools/status` 응답 비교
- [ ] **Task 7.3: 단계 7 커밋**

### 단계 8a — src/pg_store.py 흡수: 커넥션 풀 (80줄, 🟡) ✅

### 단계 8b — infra/postgres_runtime.py 분리 ✅ 2026-04-30 (커밋 8507db6)

- [ ] **Task 8a.1: 커넥션 풀 함수 이관**
  - 파일: `.ai_monitor/src/pg_store.py` (기존 파일 확장)
  - 방법: server.py L216~261의 `_get_pg_conn`, `_return_pg_conn` 두 함수를 `pg_store.py`로 이동. 풀 잠금/딕셔너리도 함께. 시그니처 유지.
  - 검증: `from ai_monitor.src.pg_store import _get_pg_conn` 성공
- [ ] **Task 8a.2: server.py + 모든 호출부 import 전환**
  - 파일: `.ai_monitor/server.py`, `.ai_monitor/api/*.py` (호출하는 곳 전부)
  - 방법: `grep -rn "_get_pg_conn\|_return_pg_conn" .ai_monitor/`로 전수조사 후 import 수정.
  - 검증: `pytest tests/` 통과 + 서버 부팅 + `/api/hive/health` 200
- [ ] **Task 8a.3: 단계 8a 커밋**

### 최종 검증

- [ ] **Task 9: 줄 수 + 하네스 검증**
  - 방법: `wc -l .ai_monitor/server.py` (목표: <5000줄). `python scripts/harness_verify.py` (목표: hot-file WARN 0건).
  - 검증: 줄 수 표기 + 하네스 출력 caller에 보고
- [ ] **Task 10: progress.md 업데이트**
  - 파일: `progress.md`
  - 방법: 완료 섹션에 단계 8개 + 줄 수 결과 기록. 다음 진입점 갱신 (Phase 4 Obsidian Vault 또는 8b ensure_postgres 이관).

### 의존성 그래프

- Task 0 → 모든 단계의 선행 조건
- 단계 1~4: 서로 독립 (병렬 가능하지만 커밋 분리 위해 순차)
- 단계 5: 단계 1~4 완료 후 (안정성 확인)
- 단계 6: Task 0 완료 후 가능, 5 완료 권장
- 단계 7: 6 완료 후
- 단계 8a: 7 완료 후 (가장 위험, 마지막에)
- Task 9~10: 8a 완료 후

---

## Phase 2-5.3a — 탭별 PTY 세션 풀 분리 (1차 PR, 2026-05-02 brainstorm 승인)

> 상위 메모: `~/.claude/projects/D--vibe-coding/memory/project_pty_pool_isolation.md`
> 목표: 평탄 PTY 풀에 `project_id` 차원 추가. 탭 전환 시 프로젝트별 세션 격리.
> 후속(분리 PR): 2-5.3b TTL 정리 워커, 2-5.3c UI 탭별 활성 에이전트 수 배지.
> 위험도 🟡 중간 — PTY 동작 변경, 단독 PR 권장. 매 단계 후 서버 부팅 smoke + Playwright 검증.

### 사전 조사 결과 (2026-05-02 스캔)
- 프론트 `slot[0-9]` 직접 참조 0건 ✅ (안전)
- 현재 sessionId 구조: WebSocket 슬롯 번호 +1 ("1"~"8" 일반, "101+N" 오피스 채팅, "O1+" 오피스 spawn)
- 오피스 spawn(`O*`)은 같은 ptySessions Map에 prefix로 구분 — 본 정책 미적용 대상
- WebSocket 핸들러 2곳: L325(일반), L627(오피스 채팅)

### 마이크로태스크

- [x] **Task A.1: Node 키 헬퍼 함수 추가**
  - 파일: `.ai_monitor/pty-server/pty-server.js` (상단 ~L40 부근)
  - 방법: `sessionKey(pid, slotId)`, `parseSessionKey(key)`, `_resolvePidFromQuery(url, cwd)` 3개 헬퍼 추가. pid 빈 값이면 `'_default'` 폴백. `slugifyProjectPath` 동일 규칙(백엔드 infra/project_context.py).
  - 검증: 단위 호출로 키 생성/파싱 round-trip 확인

- [x] **Task A.2: WebSocket 핸들러 #1 sessionId 생성 변경**
  - 파일: `.ai_monitor/pty-server/pty-server.js` L325~497 (일반 PTY 핸들러)
  - 방법: L344~345의 sessionId 생성을 `sessionKey(pid, slotMatch[1]+1)` 형태로 교체. URL searchParams에서 `project_id` 추출, 누락 시 cwd로 폴백 후 `_default`. 모든 ptySessions/ptyOutputBuffers/ptyOutputSeq 호출은 sessionId 변수 사용 → 자동 전환.
  - 검증: `node -e "require('./pty-server.js')"` syntax check + 서버 부팅 smoke

- [x] **Task A.3: WebSocket 핸들러 #2 sessionId 생성 변경**
  - 파일: `.ai_monitor/pty-server/pty-server.js` L627~810 (오피스 채팅 핸들러)
  - 방법: L644~645도 동일하게 sessionKey 적용. existingSession 재부착 로직(L647)도 새 키 사용.
  - 검증: 서버 부팅 smoke

- [x] **Task A.4: GET /api/pty/sessions 라우트 — project_id 필터**
  - 파일: `.ai_monitor/pty-server/pty-server.js` L884~905
  - 방법: `?project_id=` 쿼리 받음. 있으면 해당 prefix만 필터, 없으면 전체. 응답 sessionInfo에 `projectId` 필드 추가. 슬롯 표기는 `T{1-8}` 유지(키에서 slot 번호 parse).
  - 검증: `curl http://127.0.0.1:9001/api/pty/sessions?project_id=D--vibe-coding` 응답 확인

- [x] **Task A.5: 단건 조작 엔드포인트 (write/interrupt/terminate/output)**
  - 파일: `.ai_monitor/pty-server/pty-server.js` L952, L971, L992, L1014
  - 방법: 각 핸들러에서 `req.query.project_id` 받아 `sessionKey(pid, target)`로 조회. 누락 시 `_default` 폴백. 4개 핸들러 동일 패턴.
  - 검증: `curl -X POST .../api/pty/interrupt/3?project_id=...` 정상 응답

- [x] **Task A.6: 오피스 spawn 핸들러 키 적용**
  - 파일: `.ai_monitor/pty-server/pty-server.js` L1041~1138
  - 방법: L1049 `O${officeId}` → `sessionKey(pid, 'O' + officeId)`. 본 정책(TTL/배지)에서는 prefix `*:O*` 검사로 자연 제외 보장 (2-5.3b에서 활용).
  - 검증: `/api/pty/office/spawn` 호출 후 `/api/pty/office/sessions` 응답에 새 키 형식 노출

- [x] **Task A.7: DELETE /api/pty/sessions 핸들러 신설**
  - 파일: `.ai_monitor/pty-server/pty-server.js` (L1041 바로 위 적당한 위치)
  - 방법: `app.delete('/api/pty/sessions', ...)` 추가. `?project_id={pid}` 필수. 해당 prefix 모든 세션 `killSessionPty(key, 'project_removed')` 호출. `O*` 오피스는 제외(별도 라이프사이클). 응답: `{cleaned: N, project_id}`.
  - 검증: spawn → DELETE → sessions 비어있음 확인

- [x] **Task A.8: pty_api.py 패스스루 검증**
  - 파일: `.ai_monitor/api/pty_api.py`
  - 방법: 196줄 패스스루 코드 검토. query string 자동 전달되는지 확인 (L136 `urlencode(flat, doseq=True)`). 별도 수정 없으면 무변경, 필요 시 레거시 변환 경로(`/api/pty/output` L113~131)에 project_id 명시 전달.
  - 검증: `curl localhost:9000/api/pty/sessions?project_id=...` Node와 동일 응답

- [x] **Task A.9: 프론트 TerminalSlot.tsx WebSocket URL**
  - 파일: `.ai_monitor/vibe-view/src/components/TerminalSlot.tsx` L297
  - 방법: `wsParams.append('project_id', slugifyProjectPath(currentPath))` 한 줄 추가. `withProjectId`는 URL에 ?를 붙이는 헬퍼라 wsParams.append가 더 자연스러움. import에 `slugifyProjectPath` 추가.
  - 검증: 빌드 후 DevTools Network에 ws URL `?project_id=D--vibe-coding` 포함 확인

- [x] **Task A.10: useVibeData.ts /api/pty/sessions 폴링 적용**
  - 파일: `.ai_monitor/vibe-view/src/hooks/useVibeData.ts`
  - 방법: pty/sessions 폴링 fetch에 `withProjectId(URL, currentPath)` 적용. 이미 `/api/memory`에 적용된 패턴 동일.
  - 검증: DevTools Network에 폴링 요청 `?project_id=` 포함 + 다른 프로젝트 탭 전환 시 세션 분리 동작

- [x] **Task A.11: 빌드 + 서버 부팅 smoke**
  - 방법: `cd .ai_monitor/vibe-view && npm run build` → `python .ai_monitor/server.py`. 콘솔에 PTY 서버 정상 기동 + `[PTY] 세션 시작: T...` 로그 정상 형식 확인.
  - 검증: 부팅 무에러, 기존 단일 프로젝트 시나리오 회귀 없음

- [ ] **Task A.12: Playwright 격리 검증** ⏳ EXE 재시작 후 사용자 검증 대기
  - 방법: 프로젝트 2개 추가(config.json `projects`) → 탭 A에서 T1 spawn(`echo TAB_A`) → 탭 B 전환 → T1 spawn(`echo TAB_B`) → 탭 A 복귀 → T1 출력에 `TAB_A`만 있는지 확인.
  - 검증: 탭 간 출력 섞임 없음, 탭 복귀 시 detach 재부착 정상

- [x] **Task A.13: 메모리/계획서/HIVEMIND 갱신**
  - 파일: `~/.claude/projects/D--vibe-coding/memory/project_pty_pool_isolation.md` (구현 완료 표시), `MEMORY.md` (Next Phase 항목 업데이트), `HIVEMIND.md` (Phase 2-5.3a 완료)
  - 방법: 실제 변경 줄 수, 검증 결과, 후속(2-5.3b/c) 진입점 기록

- [ ] **Task A.14: 커밋** ⏳ A.12 검증 통과 후
  - 방법: `feat(pty): Phase 2-5.3a — 탭별 PTY 세션 풀 분리 ({pid}:slot{N} 복합 키)`. 본문에 변경 파일/이유/영향 명시(commit-rules 준수).
  - 검증: `git log --oneline -1` + `git status` 클린

### 의존성
- A.1 → A.2, A.3 (헬퍼 먼저)
- A.2, A.3 → A.4~A.7 (핸들러 변경 후 라우트 적응)
- A.4~A.7 → A.8 (백엔드 안정 후 패스스루 검증)
- A.8 → A.9, A.10 (백엔드 OK 확인 후 프론트)
- A.9, A.10 → A.11 → A.12 (검증)
- A.12 → A.13 → A.14 (마무리)

### 비범위 (2-5.3b/c로 분리)
- TTL 60분 자동 정리 워커, lastInputAt/lastOutputAt 필드 추가 → 2-5.3b
- UI 탭별 활성 에이전트 수 배지 → 2-5.3c
- 프로젝트 rename 지원 → 미지원 명시(헤더 주석에 기재)

---

## Phase 2-5.3b — TTL 정리 워커 (2차 PR, 2026-05-02 계획)

> 상위 메모: `~/.claude/projects/D--vibe-coding/memory/project_pty_pool_isolation.md`
> 목표: 탭 detach 후 60분 + idle 조건 만족 시 PTY 자동 정리. 풀 무한 누적 방지.
> 의존성: 2-5.3a 커밋 완료 후. lastInputAt/lastOutputAt 필드 도입이 핵심.
> 위험도 🟡 중간 — 자동 종료 로직 오류 시 사용자 작업 유실. yolo=true 면제 + idle 판정 보수적으로.
>
> **정책 합의 (2026-05-02 brainstorm):**
> - TTL: 60분
> - 스윕 주기: 5분 (setInterval)
> - idle 판정: `agent_status == 'idle'` **AND** `now - lastOutputAt > 10분` **AND** `now - lastInputAt > 10분`
> - **yolo=true 세션 면제** — 사용자가 명시한 장기 실행 의도 존중
> - **오피스 O* 슬롯 면제** — 별도 라이프사이클(spawn/사용자 close)
> - **attached 세션 면제** — WebSocket 살아있는 동안 정리 금지
> - DETACH_GRACE_MS(현재 30분)와 별도 — DETACH_GRACE는 socket 끊긴 후 PTY 즉시 종료, TTL은 idle 누적

### 마이크로태스크

- [x] **Task B.1: lastInputAt / lastOutputAt 필드 추가** ✅ (2026-05-03)
  - 파일: `.ai_monitor/pty-server/pty-server.js`
  - 방법: `ptySessions.set(sessionId, {...})` 6곳(legacy spawn, persistent spawn, office spawn 등)에 `lastInputAt: Date.now(), lastOutputAt: Date.now()` 추가. `ptyProcess.onData` 핸들러(L581, L909, L1370)에서 `session.lastOutputAt = Date.now()` 갱신. WebSocket `ws.on('message')` 핸들러(L292, L645)에서 PTY write 직후 `session.lastInputAt = Date.now()` 갱신.
  - 검증: spawn → write 1회 → output 수신 → `/api/pty/sessions?project_id=...` 응답에 두 timestamp 포함 (Task B.4의 응답 필드 확장 후 확인)

- [x] **Task B.2: idle 판정 헬퍼 추가** ✅ (2026-05-03)
  - 파일: `.ai_monitor/pty-server/pty-server.js` (L70 부근, 기존 키 헬퍼 아래)
  - 방법: `function isSessionIdleForCleanup(session, now)` 추가. 반환 조건: `!session.attached` AND `!session.yolo` AND `!String(session.slotId).startsWith('O')` AND `(now - (session.detachedAt timestamp || session.started)) > TTL_MS` AND `(now - session.lastOutputAt) > IDLE_THRESHOLD_MS` AND `(now - session.lastInputAt) > IDLE_THRESHOLD_MS`. agent_status는 hive_tasks 조회가 어려우므로 위 조건으로 근사. 상수: `TTL_MS = 60*60*1000`, `IDLE_THRESHOLD_MS = 10*60*1000` 환경변수 오버라이드 가능 (`PTY_TTL_MS`, `PTY_IDLE_THRESHOLD_MS`).
  - 검증: 단위 호출 — yolo=true 케이스, attached 케이스, O* 케이스, idle 60분 초과 케이스 4개 round-trip

- [x] **Task B.3: 5분 스윕 워커 setInterval 추가** ✅ (2026-05-03)
  - 파일: `.ai_monitor/pty-server/pty-server.js` (L161 heartbeat setInterval 아래)
  - 방법: `setInterval(() => { const now = Date.now(); for (const [key, info] of ptySessions.entries()) { if (isSessionIdleForCleanup(info, now)) { console.log('[PTY] TTL cleanup:', key, 'idle=', ...); killSessionPty(key, 'ttl_cleanup'); } } }, 5*60*1000)`. 환경변수 `PTY_TTL_SWEEP_MS` 오버라이드 가능.
  - 검증: 환경변수 짧게 설정(`PTY_IDLE_THRESHOLD_MS=5000 PTY_TTL_MS=10000 PTY_TTL_SWEEP_MS=3000`) 후 spawn → detach → 15초 대기 → 세션 자동 사라짐 확인

- [x] **Task B.4: GET /api/pty/sessions 응답 필드 확장** ✅ (2026-05-03)
  - 파일: `.ai_monitor/pty-server/pty-server.js` L1043~1095
  - 방법: terminals[label] 객체에 `last_input_at`, `last_output_at`, `idle_seconds` 필드 추가. `idle_seconds = Math.floor((now - Math.max(lastInputAt, lastOutputAt)) / 1000)`. 디버깅 + 2-5.3c UI 표시 양쪽 활용.
  - 검증: `curl /api/pty/sessions?project_id=...` 응답에 새 필드 3개 포함

- [x] **Task B.5: shutdown/exit 시 TTL 워커 정리** ✅ (2026-05-03)
  - 파일: `.ai_monitor/pty-server/pty-server.js`
  - 방법: TTL 워커 timer를 모듈 변수로 보관 → SIGTERM/SIGINT/exit 핸들러(L1494~1496)에서 `clearInterval(ttlSweepTimer)` 호출. cleanupAllSessions와 충돌 회피.
  - 검증: Ctrl+C 종료 시 워커 정상 정리, 좀비 timer 없음

- [x] **Task B.6: 빌드 + 서버 부팅 + 단기 시나리오 검증** ✅ (2026-05-03 — 단위 8/8 + 부팅 OK + 응답 필드 OK)
  - 방법: `npm run build` (TS 빌드, pty-server.js는 빌드 영향 없음) → 환경변수 짧게 설정해서 서버 부팅 → spawn 후 detach → idle 도달 → console에 `[PTY] TTL cleanup` 로그 + sessions에서 사라짐 확인.
  - 검증: yolo=true 세션이 같은 idle 시간에도 살아있음 / 오피스 O* 살아있음 / attached 살아있음

- [x] **Task B.7: 메모리 + 계획서 갱신** ✅ (2026-05-03)
  - 파일: `~/.claude/projects/D--vibe-coding/memory/project_pty_pool_isolation.md`, `ai_monitor_plan.md`
  - 방법: 2-5.3b 완료 표시, 측정값(검증 로그 발췌), 환경변수 기본값 명시

- [ ] **Task B.8: 커밋**
  - 방법: `feat(pty): Phase 2-5.3b — TTL 60분 idle 세션 자동 정리 워커`. 본문에 정책(yolo/오피스 면제), 환경변수 4개, lastInputAt/lastOutputAt 필드 추가 명시.
  - 검증: `git log --oneline -1` + `git status` 클린

### 의존성
- B.1 → B.2 (헬퍼가 새 필드 사용)
- B.2 → B.3 (워커가 헬퍼 호출)
- B.1, B.3 → B.4 (응답 필드는 B.1 필드 + B.3 idle 계산 의존)
- B.3 → B.5 (정리 대상 timer 존재)
- B.1~B.5 → B.6 → B.7 → B.8

### 비범위
- agent_status DB 조회 통합 — 현재는 lastInput/Output으로 근사. 추후 hive_tasks 연동 시 별도 작업.
- UI에서 idle 시간 표시 — 2-5.3c 배지 작업의 일부로 통합 가능.

---

## Phase 2-5.3c — 탭별 활성 에이전트 수 배지 (3차 PR, 2026-05-02 계획)

> 상위 메모: `~/.claude/projects/D--vibe-coding/memory/project_pty_pool_isolation.md`
> 목표: TopMenuBar.tsx 프로젝트 탭에 "에이전트 N개 실행 중" 배지 추가. 사용자가 어느 탭에서 무엇이 돌고 있는지 즉시 파악.
> 의존성: 2-5.3a 커밋 완료 + (선택) 2-5.3b idle_seconds 필드 활용 시 2-5.3b 선행.
> 위험도 🟢 낮음 — UI 표시 추가, 데이터 흐름 변경 없음.
>
> **설계 합의 (2026-05-02 brainstorm):**
> - 표시 위치: TopMenuBar.tsx L502~509 프로젝트 탭 버튼 우측 상단 모서리
> - 카운트: 해당 project_id의 ptySessions 중 `running && agent && !slot.startsWith('O')` 개수
> - 데이터 소스: `/api/pty/sessions` (현재 단일 프로젝트만 노출) → 신규 `/api/pty/sessions/summary` 추가
> - 0개 탭은 배지 미표시(노이즈 방지)
> - 폴링 주기: 10초 (활성도 체감 vs 백엔드 부하 균형)

### 마이크로태스크

- [x] **Task C.1: GET /api/pty/sessions/summary 엔드포인트** ✅ (2026-05-03)
  - 파일: `.ai_monitor/pty-server/pty-server.js` (L1096 라우트 다음)
  - 방법: 모든 project_id별 활성 에이전트 수 집계. 응답: `{ "D--vibe-coding": { agent_count: 2, total: 3 }, "_default": {...} }`. 오피스 O* 슬롯은 `total`엔 포함, `agent_count`엔 제외.
  - 검증: `curl /api/pty/sessions/summary` 응답이 `Object.keys(projects)` 전체 커버

- [x] **Task C.2: pty_api.py 패스스루** ✅ (2026-05-03 — handle_get L156-166 자동 패스스루로 추가 매핑 불필요)
  - 파일: `.ai_monitor/api/pty_api.py`
  - 방법: 현재 패스스루 라우팅이 자동 처리되는지 확인. 별도 매핑 필요하면 `/api/pty/sessions/summary` 추가. 196줄 패스스루 코드 검토.
  - 검증: `curl localhost:9000/api/pty/sessions/summary` Node와 동일 응답

- [x] **Task C.3: useVibeData.ts 폴링 추가** ✅ (2026-05-03)
  - 파일: `.ai_monitor/vibe-view/src/hooks/useVibeData.ts`
  - 방법: `ptySessionsSummary` state(`Record<string, {agent_count: number; total: number}>`) 추가. `useEffect`에 10초 폴링. fetch는 프로젝트 무관(전체 집계)이므로 `withProjectId` 미적용. VibeData interface에 노출.
  - 검증: DevTools Network에 10초마다 요청 + state 갱신

- [x] **Task C.4: TopMenuBar.tsx 배지 렌더링** ✅ (2026-05-03 — slugifyProjectPath로 path → project_id 매핑, 우상단 absolute 배지)
  - 파일: `.ai_monitor/vibe-view/src/components/TopMenuBar.tsx` L502~509
  - 방법: props에 `ptySessionsSummary` 추가. 탭 버튼 내부에 `{summary[path]?.agent_count > 0 && <span className="agent-badge">{n}</span>}` 추가. CSS는 inline style 또는 globals.css에 `.agent-badge` 정의(원형, 12px, 우상단 absolute).
  - 검증: 탭 A에서 claude spawn → 탭 A 버튼에 "1" 배지 → 탭 B 전환 후 gemini spawn → 탭 B에 "1", 탭 A에 "1" 동시 표시

- [x] **Task C.5: App.tsx props 전달** ✅ (2026-05-03)
  - 파일: `.ai_monitor/vibe-view/src/App.tsx`
  - 방법: useVibeData에서 `ptySessionsSummary` 받아 TopMenuBar에 전달. 1줄 변경.
  - 검증: TS 타입 체크 통과 + 빌드

- [x] **Task C.6: 빌드 + Playwright 검증** ✅ (2026-05-03 — tsc 0 errors + vite build 38s, 신규 번들 index-DQ7XHOFl.js. PyWebView 재시작 검증은 사용자 확인 대기)
  - 방법: `npm run build` → EXE 재시작 → 프로젝트 2개 탭 → 각각에 spawn → 배지 숫자 정상 + 0개 탭 배지 미표시
  - 검증: 5초 이내 배지 갱신, 종료 시 0으로 소멸

- [x] **Task C.7: 메모리 + 계획서 갱신** ✅ (2026-05-03)
  - 파일: `~/.claude/projects/D--vibe-coding/memory/project_pty_pool_isolation.md`, `ai_monitor_plan.md`
  - 방법: 2-5.3c 완료 표시, 스크린샷 첨부 시 옵시디언 자산 폴더 사용

- [ ] **Task C.8: 커밋**
  - 방법: `feat(ui): Phase 2-5.3c — 프로젝트 탭별 활성 에이전트 수 배지`. 본문에 신규 엔드포인트, 폴링 주기, 표시 규칙 명시.
  - 검증: `git log --oneline -1`

### 의존성
- C.1 → C.2 → C.3 → C.4, C.5 → C.6 → C.7 → C.8 (순차)
- C.4와 C.5는 병렬 가능

### 비범위
- 탭별 idle 시간/마지막 활동 표시 — 2-5.3b의 idle_seconds 활용 시 추후 확장
- 배지 클릭 시 해당 탭 자동 전환 — 현재 탭 클릭으로 충분

---
> 이 계획서는 2026-04-16 브레인스토밍 결과입니다.
> Phase A-1부터 순서대로 진행하며, 각 단계 끝마다 검증 + 사용자 OK 후 다음으로.
