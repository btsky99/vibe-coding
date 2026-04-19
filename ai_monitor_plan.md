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

### 2-1 DB 스키마 감사 (읽기 전용)
- [ ] Layer 1 테이블 목록 확정 (hive_*, zettel_*, pg_logs, pg_messages,
      agent_*, active_session_context, task_comments, office_*)
- [ ] 각 테이블에 `project_id` 컬럼 존재 여부 + 기본값 + NOT NULL 여부 확인
- [ ] 기존 데이터의 `project_id` 분포 (empty/NULL 비율) 측정
- [ ] 감사 결과 표로 정리 + 마이그레이션 대상 후보 도출

### 2-2 project_id 컬럼 추가 마이그레이션 (있어야 할 곳)
- [ ] 2-1에서 도출된 테이블에 `project_id TEXT NOT NULL DEFAULT ''` 추가
- [ ] 빈 값 데이터에 현재 활성 프로젝트 id 일괄 backfill
- [ ] 인덱스 추가 (`(project_id, status)` 등 조회 패턴별)

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

### 3-2 서버 스캐너 (`.ai_monitor/api/vibe_skills_api.py`)
- [ ] `list_vibe_skills(project_root)` — `.vibe/skills/*/SKILL.md` 파싱
- [ ] `list_claude_skills(project_root)` — 기존 `.claude/skills/*/SKILL.md` 파싱 (재사용)
- [ ] `merge_skills()` — 이름 충돌 시 `.vibe/` 우선, origin 필드 부여
- [ ] GET `/api/vibe/skills` 라우팅 (server.py)

### 3-3 UI 병합
- [ ] 오피스 채팅 `/` 팝업의 스킬 소스를 `/api/vibe/skills`로 전환
- [ ] `origin` 배지(claude/vibe) 표시
- [ ] 클래식 모드 슬래시 팝업(있다면)도 동일 전환

### 3-4 자기 드레싱 — 이 리포의 `.vibe/skills/` 샘플
- [ ] `.vibe/skills/platform-check/SKILL.md` — PLATFORM_LAYERS.md 요약 + 레이어 진단
- [ ] 또는 `.vibe/skills/phase-plan/SKILL.md` — 현재 Phase 상태 보고

### 3-5 하네스 검증
- [ ] `scripts/harness_verify.py`에 `.vibe/` 포맷 검증 추가
- [ ] SKILL.md frontmatter 필수 필드 (`name`, `description`) 누락 시 WARN
- [ ] `tests/test_harness_verify.py` 케이스 추가

---

## 완료된 작업 (2026-04-15~16)

- [x] Phase 1: 정확한 그림 만들기
- [x] Phase 2: 시스템 정직성 확보 — gemini/codex 라벨링
- [x] Phase 3: 자동 분배 시스템 점검 — alive 체크 + 게이팅
- [x] Phase 4: 가시성 UI — 오케스트레이터 카드, 유령 배지, 백프레셔
- [x] Phase 5: 최적화 — hive_hook 다이어트, SkillChainPanel 리네임

---
> 이 계획서는 2026-04-16 브레인스토밍 결과입니다.
> Phase A-1부터 순서대로 진행하며, 각 단계 끝마다 검증 + 사용자 OK 후 다음으로.
