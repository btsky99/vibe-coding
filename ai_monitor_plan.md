# Antigravity CLI 마이그레이션 — 잔여 Phase 1~4

<!--
FILE: ai_monitor_plan.md
DESCRIPTION: Gemini CLI → Antigravity CLI(agy) 전면 교체 잔여분 실행 계획.
             2026-05-24 brainstorm 승인(옵션 B: 식별자 일괄 변경 + DB UPDATE). 데드라인 6/18.

REVISION HISTORY:
- 2026-06-11 Claude: 잔여분 계획 작성 (이전 계획 '자가 치유 2.0'은 전 태스크 완료로 교체)
-->

> 승인: 2026-05-24 (옵션 B). 메모리: `project_antigravity_migration.md`
> 현황: Phase 0 PoC ✅ / Phase 1 부분(서버 실행 분기 + UI 라벨) ✅ / agy 1.0.6 설치 확인(2026-06-11)
> 규모: 코드 97파일 815회 발생, DB 9테이블 식별자 컬럼

## 불변식 (모든 태스크 공통)
- `GEMINI_API_KEY`/`GOOGLE_API_KEY` 등 **외부 서비스 환경변수 교체 금지** (hive_watchdog.py:331, screenshot_analyzer.py:58)
- 파일 rename/삭제 시 **vibe-coding.spec datas ↔ CI --add-data 동시 갱신** (과거사고 v3.7.215~218)
- API/실행 경계에서 레거시 식별자 `'gemini'` alias 수용 유지 (server.py:3228 패턴) — 내부 표준은 `'antigravity'`
- Phase 단위 별도 커밋 (git bisect 가능), 파일당 1500줄, 표준 헤더
- DB UPDATE 전 pg_dump 백업 의무

---

## Phase 1 잔여 — 어댑터 + 문서 기반

### [x] Task 1: agy 런타임 실측 — 설정/세션 디렉토리 + 훅 지원 여부
- **파일**: (조사 태스크 — 결과를 본 파일 하단 "실측 결과"에 기록)
- **방법**: `agy -p "1+1?"` 실행 전후 홈/프로젝트 디렉토리 변화 관찰. `agy help` 서브커맨드 조사. 프로젝트 `.gemini/`(commands/rules/settings.json/skills)를 agy가 읽는지 확인
- **검증**: ①agy 설정 디렉토리 경로 ②세션/대화 저장 경로 ③.gemini 인식 여부 3가지 기록
- **의존성**: 없음

### [x] Task 2: scripts/antigravity_adapter.py 신설 — 호출 격리 레이어 (021600f 커밋 완료, 검증 통과 2026-06-11)
- **파일**: `scripts/antigravity_adapter.py` (신규 ~120줄)
- **방법**: closed-source 인터페이스 변경 대비 단일 격리점. `find_agy()` (PATH 탐색), `build_print_cmd(prompt, model=None, yolo=False)` (-p/--model/--dangerously-skip-permissions 매핑), `session_dir()` (Task 1 실측 경로). cli_agent.py `_GEMINI_CMD`/`_select_gemini_model` 호출 경로와 server.py:3233 인라인 옵션 매핑을 어댑터 경유로 교체
- **검증**: `python -c "from antigravity_adapter import build_print_cmd; print(build_print_cmd('hi'))"` + 기존 호출부 grep 0건
- **의존성**: Task 1

### [x] Task 3: GEMINI.md 내용 Antigravity 기준 갱신 (rename 취소 — 실측 반영)
- **파일**: `GEMINI.md` (파일명 유지 — agy가 읽는 컨텍스트 파일), `docs/help-gemini-cli.md`→`help-antigravity-cli.md`(우리 문서라 rename 가능, tools_api 참조 갱신)
- **방법**: GEMINI.md 본문의 "Gemini CLI" 서술을 Antigravity CLI(agy) 기준으로 갱신. 파일명 유지 사유를 헤더 주석에 명기 (재발 방지)
- **검증**: GEMINI.md 내 구식 서술 0건, help 문서 참조 경로 유효
- **의존성**: Task 1 ✅

## Phase 2 — 코드 식별자 일괄 변경 (도메인별 커밋)

### [x] Task 4: scripts/ gemini_* 파일 5종 rename + 참조 갱신
- **파일**: `gemini_hook.py`→`antigravity_hook.py`, `gemini_output_filter.py`→`antigravity_output_filter.py`, `gemini_session_repair.py`→`antigravity_session_repair.py`, `run_gemini_clean.py`→`run_antigravity_clean.py`, 루트 `gemini_statusline.py`(역할 확인 후 rename 또는 삭제)
- **방법**: git mv + import/subprocess 호출부 갱신 (`git grep -n "gemini_hook\|gemini_output_filter\|gemini_session_repair\|run_gemini_clean"`). `.gemini/settings.json` 훅 command 경로 + **`~/.gemini/trusted_hooks.json` 동시 갱신** (불일치 시 agy가 훅 차단). spec/CI datas 동기
- **검증**: `python -m py_compile` 전체 + 구파일명 grep 0건
- **의존성**: Task 1, 2

### [x] Task 5: scripts/ 식별자 교체 ('gemini'→'antigravity')
- **파일**: scripts/ 내 gemini 포함 ~30파일 (cli_agent, agent_shell, orchestrator, itcp, hive_*, telegram_bridge 등)
- **방법**: 에이전트 이름 문자열/키워드/주석 교체. config 키 `gemini_enabled`→`antigravity_enabled` (읽기 시 레거시 키 폴백 1줄). GEMINI_API_KEY/GOOGLE_API_KEY 라인은 제외 목록으로 보호
- **검증**: py_compile + `pytest tests/ -q --ignore=tests/office` 기준선(4 실패) 유지
- **의존성**: Task 4

### [x] Task 6: .ai_monitor/ 백엔드 식별자 교체
- **파일**: server.py, api/ 11파일, src/ 5파일, infra/ 2파일, bin/ 3파일, mission_control*
- **방법**: Task 5와 동일 규칙. `~/.gemini/tmp` 외부 세션 감지부(agent_api.py:404~)는 Task 1 실측 경로로 교체 (agy 미지원 기능이면 주석으로 비활성 사유 기록)
- **검증**: py_compile + 서버 부팅 smoke (`python .ai_monitor/server.py` 기동 로그 정상)
- **의존성**: Task 5

### [x] Task 7: 프론트엔드 교체 + 빌드
- **파일**: vibe-view/src 26파일 (constants.tsx, types.ts, TerminalSlot, ChatSlot, office/* 등)
- **방법**: 라벨/타입/아이콘 'gemini'→'antigravity' (Phase 1에서 일부 완료 — 잔존분). API 발신 식별자도 'antigravity'로 통일 (서버는 alias 수용이라 무중단)
- **검증**: `tsc --noEmit` 0 errors + `vite build` 성공
- **의존성**: Task 6

### [x] Task 8: tests/ 갱신
- **파일**: tests/ 내 gemini 참조 파일 (test_itcp_fallback 등 ~10파일)
- **방법**: 식별자/모킹 교체. 기존 실패 4건(test_agent_api 1 + 오염 3)은 본 작업 비범위 — 악화만 방지
- **검증**: 단독 실행 기준 전부 통과 (기존 실패 제외)
- **의존성**: Task 5, 6

## Phase 3 — DB 마이그레이션

### [x] Task 9: 백업 + 식별자 UPDATE
- **파일**: `scripts/migrate_antigravity_db.py` (신규 ~80줄, 일회성 — 4차 정리 규칙대로 완료 후 삭제 대상 표기)
- **방법**: ①pg_dump → `backups/pre_antigravity_migration_20260611.sql.gz` ②트랜잭션으로 9테이블 UPDATE: hive_memory.author, hive_sessions.agent, hive_skill_chains.agent, hive_tasks.assigned_to, pg_logs.agent, pg_messages.from_agent/to_agent, task_comments.author, zettel_notes.author — `WHERE col='gemini'` → `'antigravity'` ③건수 리포트
- **검증**: UPDATE 전후 `SELECT count(*) WHERE col='gemini'` → 0, 'antigravity' 증가분 일치
- **의존성**: Task 6 (백엔드가 신식별자 읽는 상태에서 실행)

## Phase 4 — 검증 + 문서

### [x] Task 10: 종합 검증
- **방법**: ①`git grep -in "gemini"` 전수 — 잔존은 보존 목록(GEMINI_API_KEY/GOOGLE_API_KEY, 이력 주석, docs 아카이브)만인지 확인 ②pytest 전체 ③서버 부팅 + Playwright로 UI 라벨 확인 (스크린샷 요청 금지 규칙) ④spec↔CI 동기 재확인
- **의존성**: Task 7, 8, 9

### [x] Task 11: 문서 + 메모리 갱신
- **파일**: CHANGELOG.md, PROJECT_MAP.md(재생성), HIVEMIND.md(자동), CLAUDE.md/RULES.md 내 gemini 언급, `.claude/rules/hive-sync.md`(에이전트 역할), 메모리 `project_antigravity_migration.md`
- **방법**: 사용자 안내 명기: **첫 agy 실행 시 OAuth 재로그인 필요**
- **검증**: 규칙 8 리포트 출력
- **의존성**: Task 10

---

## 의존성 요약
- Task 1 → 2 → 4 → 5 → 6 → {7, 8, 9} → 10 → 11
- Task 3 독립 (병렬 가능)

## 실측 결과 (Task 1 — 2026-06-11)
- **agy 1.0.7**. 데이터 루트 = `~/.gemini/antigravity-cli/` (conversations/*.db, history.jsonl, cli.log, cache/)
- **`~/.gemini/`·프로젝트 `.gemini/`를 agy가 그대로 사용** — oauth_creds.json, settings.json(hooks), trusted_hooks.json(우리 gemini_hook.py 신뢰 등록 확인). → **`.gemini/` rename 취소** (GEMINI_API_KEY와 동급의 외부 도구 인터페이스). GEMINI.md도 동일 사유로 **파일명 유지 + 내용만 Antigravity 기준 갱신**
- **`-p` print 모드는 stdout 파이프/리다이렉트 시 응답 미출력** (exit 0 + 빈 출력. cli.log상 모델 생성은 성공 — 콘솔 TUI 버퍼 전용 렌더). `models`도 동일, `changelog`는 정상. PowerShell 리다이렉트에선 행(>10분). winpty/node-pty는 본 헤드리스 환경 제약으로 미검증 — **앱 런타임의 pty-server(ConPTY) 경유가 비대화형 캡처의 유일한 신뢰 경로**
- 외부 세션 감지: 구 `~/.gemini/tmp/*/chats` → `~/.gemini/antigravity-cli/conversations/` mtime 스캔으로 교체 (Task 6)
- 훅 rename 시 **`~/.gemini/trusted_hooks.json` 동시 갱신 필수** — 경로 문자열 불일치 시 agy가 훅을 untrusted로 차단 (Task 4)
