<!--
FILE: progress.md
DESCRIPTION: 프로젝트 진행 상황 추적 파일. 모든 에이전트가 세션 시작 시 읽고, 작업 완료 시 갱신한다.

REVISION HISTORY:
- 2026-03-30 Claude: 최초 생성 — HARNESS_V2 세션 프로토콜의 핵심 구성 요소
- 2026-04-19 Claude: Platform Phase 2 완료 + 잔여 이슈 현실 반영
- 2026-04-19 Claude (저녁): Phase 3 전체 완료 + 설치본 버전 표시 수정 +
  TerminalSlot 분할 + 내일 할 일 정리
-->

# Progress

## 최종 업데이트: 2026-04-19 by Claude (저녁)

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

### 진행 중
- [F003] LLM 그룹 채팅 — 기본 구현 완료, 컨텍스트 메뉴 검증 대기. sprint_contracts/sprint_F003_20260419.md
- [F005] Generator-Evaluator 파이프라인 — 솔로 모드에서 harness_verify.py로 기계적 대체 동작 중. sprint_contracts/sprint_F005_20260419.md
- [F006] 세션 시작 프로토콜 — Claude 자동(훅), Gemini/Codex 수동. sprint_contracts/sprint_F006_20260419.md

### 남은 작업 (Platform Phase 3 이후)
- **Phase 3**: `.vibe/` 컨벤션 스캐너 — 프로젝트 루트의 `.vibe/skills`, `.vibe/agents` 자동 로드
- **Phase 4**: Obsidian Vault 연동 — `zettel_notes` ↔ Markdown 양방향
- **Phase 5**: 플랫폼 빌드 분리 — 리포 개발 코드와 배포 IDE 런타임 분리

### 남은 하네스 WARN
- `hot-file-large:.ai_monitor/server.py:6363>5000` — **1,363줄 초과**. 큰 스프린트
  필요. ensure_schema/라우팅/핸들러 분리 후보 다수. Platform Phase 5(빌드 분리)와
  같은 선상에서 설계 필요

### 🌅 내일 시작 시 진입점 (우선순위 순)

1. **새 EXE 설치본 버전 표시 실측** — 사용자 대기 중 작업.
   - GitHub Actions가 v3.7.209 전후로 새 EXE 자동 빌드
   - 설치 후 우상단 보라 배지에 실제 버전이 뜨는지 확인
   - 실패 시 EXE 실행 로그의 `[version] WARN: ...` stderr 줄 참조
     (frozen/MEIPASS/__file__ 경로가 찍혀 근본 원인 즉시 파악 가능)

2. **server.py 5000줄 이하 분할** — 하네스 남은 WARN 1건.
   - 6363 → 5000 이하. 1,363줄 절감 필요.
   - 후보: ensure_schema 이식(이미 pg_store로 일부 이관), 긴 핸들러들
     (/api/agent/*, /api/orchestrator/*, 세션 복구)을 별도 api/*.py 모듈로 추출
   - brainstorm 선행 필수 — 큰 리팩터링

3. **Platform Phase 4 — Obsidian Vault 연동** — `docs/PLATFORM_LAYERS.md` §Phase 4.
   - `zettel_notes`(permanent) ↔ `vaults/<project_id>/` Markdown 양방향 동기화
   - `zettel_links` ↔ `[[wiki-links]]` 변환
   - 프로젝트별 Vault 분리
   - brainstorm 필요 — 규모 큼

4. **Platform Phase 5 — 플랫폼 빌드 분리** — 리포 개발 코드와 배포 IDE 런타임 분리.
   - `.vibe/` 템플릿을 EXE에 내장 → 새 프로젝트 오픈 시 자동 스캐폴딩
   - Phase 3-5에서 준비된 규약 기반

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
- 하네스 V2 가동 중. `status=ok` (40 passes, 1 warning — server.py만).
- Platform Layer 경계 준수: 모든 DB 쓰기는 `project_id` 스코프 강제됨.
- `.vibe/skills/` 스캐너 가동 중: `/api/vibe/skills` GET + 오피스 채팅 `/` 팝업.
- 상위 로드맵: [docs/PLATFORM_LAYERS.md](docs/PLATFORM_LAYERS.md).
- 세부 실행 계획: [ai_monitor_plan.md](ai_monitor_plan.md).
- `.vibe/` 규약: [docs/VIBE_CONVENTIONS.md](docs/VIBE_CONVENTIONS.md).
