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

### 2-3 project_id Resolver 유틸
- [ ] 현재 활성 프로젝트 조회 헬퍼 (서버·UI 양쪽 일관)
- [ ] 컨텍스트 미지정 쿼리 탐지 (개발 모드에서 경고)

### 2-4 API 레이어 일관화
- [ ] 모든 `.ai_monitor/api/*.py`의 쓰기 경로에 `project_id` 인자 필수화
- [ ] 읽기 경로에 `project_id` 필터 옵션 추가

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
> 이 계획서는 2026-04-16 브레인스토밍 결과입니다.
> Phase A-1부터 순서대로 진행하며, 각 단계 끝마다 검증 + 사용자 OK 후 다음으로.
