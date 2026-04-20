<!--
FILE: progress.md
DESCRIPTION: 프로젝트 진행 상황 추적 파일. 모든 에이전트가 세션 시작 시 읽고, 작업 완료 시 갱신한다.

REVISION HISTORY:
- 2026-03-30 Claude: 최초 생성 — HARNESS_V2 세션 프로토콜의 핵심 구성 요소
- 2026-04-19 Claude: Platform Phase 2 완료 + 잔여 이슈 현실 반영
- 2026-04-19 Claude (저녁): Phase 3 전체 완료 + 설치본 버전 표시 수정 +
  TerminalSlot 분할 + 내일 할 일 정리
- 2026-04-20 Claude: server.py 분할 8단계 중 5단계 완료 (-556줄, 6363→5807)
-->

# Progress

## 최종 업데이트: 2026-04-20 by Claude

### 완료된 작업 (대시보드 대청소 ~ Platform Phase 2)
- [F001] 터미널 실시간 모니터링 — v3.5 Claude
- [F002] 에이전트 상태 패널 — v3.6 Claude
- [F004] 하네스 검증 시스템 V2 — harness_verify.py 10개 검사
- [F007] EXE 빌드 파이프라인 — v3.6 Claude
- [F008] 하이브 마인드 통합 — v3.7 Claude (hive_tasks 기반으로 재정의)
- HARNESS V2 설계 + 구현 + 자동화(CI + Claude 훅) — 2026-03-30
- 메타버스 오피스 모드 구현 — v3.7.180+
- 하이브 5단계 개선 계획(A/B/C) — 2026-04-15~17 (C.4 포함 전부 완료)
- 제텔카스텐 파이프라인 가동 — 242건 누적
- **UI 대청소** (2026-04-18): MessagesPanel/MessageComposer, CODEWIKI, CodeSearch/CodeGraph, DispatcherPanel, AgentPanel 제거. 실사용 0 기반 정리
- **Platform Phase 1** (2026-04-19): docs/PLATFORM_LAYERS.md — 3-Layer 모델(Host / Common Runtime / Project Extension) 정의 + 경계 불변식 5개
- **Platform Phase 2** (2026-04-19): Layer 1 16개 테이블 project_id 스코프 통일
  - 단계 1: 값 정규화 1,825건 UPDATE
  - 단계 2: 3개 테이블 컬럼 RENAME (project → project_id), 깊은 코드 관통 15개 파일
  - 단계 3: 11개 테이블 컬럼 신설 + 2,358건 backfill
- 하네스 꼬리 정리 — 폐기된 auto_dispatcher/AgentPanel 등록 해제
- **Platform Phase 3** (2026-04-19 저녁): `.vibe/` 컨벤션 스캐너 전체 (3-1~3-5)
  - 3-1 `docs/VIBE_CONVENTIONS.md` 규약 문서
  - 3-2 서버 스캐너 `.ai_monitor/api/vibe_skills_api.py` + `/api/vibe/skills` 라우트
  - 3-3 UI 병합 — 오피스 채팅 `/` 팝업에 `.vibe/` 스킬 + emerald "vibe" 배지
  - 3-4 자기 드레싱 — `.vibe/skills/platform-check/SKILL.md` 첫 Layer 2 샘플
  - 3-5 하네스 검증 `_check_vibe_skills()` — frontmatter / name / 디렉토리명 일치
- **설치본 버전 표시 회귀 수정** (2026-04-19 저녁): `_version.py` 로딩을
  파일 경로 기반으로 일원화. frozen 환경 sys.modules 충돌 리스크 제거 +
  실패 시 stderr 진단 덤프. v3.7.207 이후 EXE에서 v-배지 정상 표시 예정
- **TerminalSlot 분할** (2026-04-19 저녁): 1243 → 1188줄. ShortcutEditModal,
  SlashCommandMenu를 `components/terminal/`로 추출. 하네스 WARN 해소
- **server.py 분할 5단계 완료** (2026-04-20): B안 도메인 모듈화. 6363 → 5807줄
  (-556, 41% 진척). branch: `claude/zen-jennings-713b94`. 5 commits.
  - 단계 1: `infra/lifecycle.py` — _cleanup_*, _signal_exit_handler (-135)
  - 단계 2: `infra/runtime.py` — _python_runner_cmds, playwright (-71)
  - 단계 3: `infra/fs_watcher.py` — FSChangeHandler, agent broadcast (-67)
  - 단계 4: `api/office_proxy_api.py` — OfficeServerState 캡슐화 (-149)
  - 단계 5: `api/telegram_api.py` — handler 위임 패턴 첫 도입 (-134)
  - 매 단계 별도 커밋, pytest 51 passed 일관 유지
  - 8단계 계획 ai_monitor_plan.md 기록 (남은 단계 6/7/8a)

### 진행 중
- [F003] LLM 그룹 채팅 — 기본 구현 완료, 컨텍스트 메뉴 검증 대기. sprint_contracts/sprint_F003_20260419.md
- [F005] Generator-Evaluator 파이프라인 — 솔로 모드에서 harness_verify.py로 기계적 대체 동작 중. sprint_contracts/sprint_F005_20260419.md
- [F006] 세션 시작 프로토콜 — Claude 자동(훅), Gemini/Codex 수동. sprint_contracts/sprint_F006_20260419.md

### 남은 작업 (Platform Phase 3 이후)
- **Phase 3**: `.vibe/` 컨벤션 스캐너 — 프로젝트 루트의 `.vibe/skills`, `.vibe/agents` 자동 로드
- **Phase 4**: Obsidian Vault 연동 — `zettel_notes` ↔ Markdown 양방향
- **Phase 5**: 플랫폼 빌드 분리 — 리포 개발 코드와 배포 IDE 런타임 분리

### 남은 하네스 WARN
- `hot-file-large:.ai_monitor/server.py:5807>5000` — **807줄 초과** (어제 1,363
  → 오늘 807로 -556 감소). 단계 6~8a 끝나면 5000 미만 도달 예정.
  worktree `claude/zen-jennings-713b94`에서 진행 중, 아직 main 머지 안 함.

### 🌅 내일 시작 시 진입점 (우선순위 순)

1. **server.py 분할 단계 6 — `infra/memory_watcher.py` 추출** (🟡 위험도)
   - 위치: `claude/zen-jennings-713b94` 워크트리에서 계속
   - 추출 대상: server.py L1127~1500의 `_legacy_memory_data_dir`, `_memory_conn`,
     `_init_memory_db`, `_get_embedder`, `_embed`, `_cosine_sim`, `MemoryWatcher`
   - 예상 절감: ~370줄 (5807 → 약 5437)
   - 주의: embedder lazy init 글로벌(`_EMBEDDER`) 캡슐화, memory_api 호출부도 grep
   - 시작 명령:
     `git -C D:/vibe-coding worktree list  # 워크트리 위치 확인`
     `cd D:/vibe-coding/.claude/worktrees/zen-jennings-713b94`
     `cat ai_monitor_plan.md | tail -100  # 단계 6 상세 확인`

2. **server.py 분할 단계 7 — `infra/tool_install.py`** (🟡, ~200줄, 단계 6 완료 후)
   - server.py L1594~1850. 도구 설치 상태 머신 + 글로벌 dict 캡슐화

3. **server.py 분할 단계 8a — `src/pg_store.py` 흡수** (🟡, ~80줄, 단계 7 완료 후)
   - L216~261의 `_get_pg_conn`/`_return_pg_conn` 이관. 모든 호출부 grep 후 import 변경

4. **5000 미만 도달 시 머지** — 하네스 WARN 0건 확인 후
   - `git -C D:/vibe-coding fetch && git rebase origin/main` (worktree에서)
   - main으로 머지 → push → GitHub Actions가 자동 빌드. **설치본 버전 표시 실측은
     머지 후 새 EXE에서**

5. **새 EXE 설치본 버전 표시 실측** — 머지/빌드 완료 후 (어제 진입점에서 이월)
   - 우상단 보라 배지에 실제 버전이 뜨는지 확인
   - 실패 시 EXE 실행 로그의 `[version] WARN: ...` stderr 줄 참조

6. **Platform Phase 4 — Obsidian Vault 연동** (server.py 작업 마무리 후)
   - brainstorm 필요 — 규모 큼

### 작업 위치/상태
- **현재 브랜치**: `claude/zen-jennings-713b94` (워크트리)
- **워크트리 경로**: `D:/vibe-coding/.claude/worktrees/zen-jennings-713b94`
- **마지막 커밋**: `8c7900b refactor(server): api/telegram_api.py 분리 — 단계 5`
- **메인과 차이**: ahead 5 commits (단계 1~5), 미머지
- **신규 파일**: `.ai_monitor/infra/{lifecycle,runtime,fs_watcher}.py`,
  `.ai_monitor/api/{office_proxy_api,telegram_api}.py`
- **계획 위치**: `ai_monitor_plan.md` 마지막 섹션 "server.py 분할" 참조

### 운영 메모 (2026-04-19에 학습)
- **머지 루틴**: 매 push마다 GitHub Actions가 auto-bump 커밋을 origin/main에
  추가하므로 main push 시 **rebase 필요**. `pull --rebase`를 흐름에 포함
- **worktree 머지**: 메인 리포에 unstaged(`config.json`, `dist`, `HIVEMIND.md`,
  `PROJECT_MAP.md` 등 자동 생성물 + 사용자 파일)가 상시 있음.
  `git stash push → rebase → stash pop` 루틴으로 안전 보호
- **하네스 훅 에러 "column project does not exist"**: main 리포 스크립트를 훅이
  호출하는 구조. DB는 공유되므로 스키마 변경 시 **worktree 커밋 → main 머지**
  전까지는 구 훅이 신 DB에 충돌. 머지하면 자동 해결

### 다음 세션 시작 시 참고사항
- 하네스 V2 가동 중. `status=ok` (40 passes, 1 warning — server.py만, 5807줄).
- Platform Layer 경계 준수: 모든 DB 쓰기는 `project_id` 스코프 강제됨.
- `.vibe/skills/` 스캐너 가동 중: `/api/vibe/skills` GET + 오피스 채팅 `/` 팝업.
- **server.py 분할 패턴 (4가지)** — 단계 6~8a에서 동일 적용:
  1. **인자 명시화**: 모듈 글로벌(BASE_DIR/PROJECT_ROOT 등)을 함수 인자로 받기
  2. **얇은 래퍼**: server.py에는 글로벌 바인딩만 하는 1~3줄짜리 래퍼만 유지
  3. **State 객체**: 변하는 상태는 클래스로 캡슐화 (OfficeServerState 사례)
  4. **핸들러 위임**: SSEHandler 메서드는 `module_fn(self, ...)` 위임으로 1줄화
- 상위 로드맵: [docs/PLATFORM_LAYERS.md](docs/PLATFORM_LAYERS.md).
- 세부 실행 계획: [ai_monitor_plan.md](ai_monitor_plan.md).
- `.vibe/` 규약: [docs/VIBE_CONVENTIONS.md](docs/VIBE_CONVENTIONS.md).
