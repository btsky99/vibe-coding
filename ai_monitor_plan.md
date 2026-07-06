# 구현 계획 — server.py 디스패치 재구조화 Phase 2 (라우팅 인라인 + infra 안전분)

<!--
FILE: ai_monitor_plan.md
DESCRIPTION: server.py do_GET/do_POST 인라인 라우트를 도메인 그룹 모듈로 추출 + 복합조건 wrapper 테이블화
             + infra 안전분(PTY/세션파싱) + 소형헬퍼 흡수. 목표 3597→~1950줄. 1500은 Phase 3.

REVISION HISTORY:
- 2026-07-05 Claude: Phase 2 신규. brainstorm 승인(안전우선). Critic 반영(R11/R12 드롭, R14 Phase3).
-->

> 설계 승인: 2026-07-05 brainstorm(안전우선 범위). 메모리: `project_server_split_plan.md` Phase 2 섹션
> 목표: server.py 3597 → **~1950줄**. 동작 불변. **1500 최종 도달은 Phase 3**(R14 이중전역 통합 + main 조사).
> 안전: 하이브리드 폴백 유지 + 완전성 가드(매 라운드) + 라운드별 커밋.

## 🚨 매 라운드 공통 안전 절차 (모든 Task에 적용)
1. **착수 직전 재검증**: `grep -n "def <함수명>" .ai_monitor/server.py` + 실제 줄 수 확인 (R11/R12 드리프트 교훈 — 계획-착수 간 드리프트 실재)
2. **verbatim 포팅**: 함수 시그니처·동작 불변. 전역 참조는 **함수 바디 내 이름 참조**로 주입 (디폴트 인자 바인딩 금지 — late-binding 함정)
3. **동일 문자열 다중 블록**: Edit 도구 고유 컨텍스트 매칭 (near-miss 사고 860b657 — 스크립트 순차치환 금지)
4. **검증 3종**: `pytest tests/test_route_table.py` (완전성 가드) + `pytest tests/ --ignore=tests/office` (105 passed) + `python -c "import ast; ast.parse(open('.ai_monitor/server.py',encoding='utf-8').read())"` (구문/import 스모크)
5. **라운드별 별도 커밋** (git bisect 가능) + 단계 전환 시 `python scripts/checkpoint.py`

---

## 파트 A — 라우팅 인라인 → 도메인 그룹 모듈

### [ ] Task 1 (R1): fs_dialog_api.py 신규 — 파일시스템 다이얼로그
- 파일: `.ai_monitor/api/fs_dialog_api.py`🆕, `.ai_monitor/server.py`✏️
- 방법: GET `/api/browse-folder`(subprocess 폴더다이얼로그)·`/api/drives`(드라이브스캔)·`/api/dirs`(os.scandir) + POST `/api/select-folder`(tkinter)·`/api/open-external` 인라인 로직을 `handle_get(h, path)`/`handle_post(h, path)`로 이전. server.py는 GET_PREFIX 없는 exact라 GET_ROUTES/POST_ROUTES exact 테이블 + wrapper.
- 검증: 공통 3종. 폴더 다이얼로그 라우트는 subprocess라 스모크만.
- 의존성: 없음

### [ ] Task 2 (R2): install_api.py 확장 — 도구 설치
- 파일: `.ai_monitor/api/install_api.py`✏️, `.ai_monitor/server.py`✏️
- 방법: GET `/api/tool-status`·`/api/install-tool-status`·`/api/install-*-cli`(복합조건 in 3개: gemini/claude/codex)·`/api/register-codex-to-ai` + POST `/api/install-playwright-cli`(52줄)·`/api/run-script`(61줄) 이전. install-*-cli 복합조건은 R9에서 wrapper 처리 예정이므로 이번엔 핸들러 본문만 이전하고 라우트 조건은 legacy 유지.
- 검증: 공통 3종.
- 의존성: 없음

### [ ] Task 3 (R3): logs_api.py 신규 — 로그/스트림
- 파일: `.ai_monitor/api/logs_api.py`🆕, `.ai_monitor/server.py`✏️
- 방법: GET `/stream`(SSE psycopg2 LISTEN/NOTIFY 86줄)·`/api/server-logs`·`/api/messages` + POST `/api/messages/clear` 이전.
  ⚠️ **/stream late-binding**: `stream(h, pg_port, pg_project_db, run_pg_sql_csv)` 호출 시 server.py wrapper 바디에서 `logs_api.stream(self, PG_PORT, PG_PROJECT_DB, run_pg_sql_csv)`로 **매 호출 시 이름 재조회**. 디폴트 인자로 바인딩 금지.
- 검증: 공통 3종 + `/stream` SSE 연결 스모크(psycopg2 직접연결 유지 확인, 풀 전환 금지).
- 의존성: 없음

### [ ] Task 4 (R4): static_api.py 신규 — 정적파일 서빙
- 파일: `.ai_monitor/api/static_api.py`🆕, `.ai_monitor/server.py`✏️
- 방법: GET else 브랜치 정적서빙(46줄, Vite dist + SPA fallback + MIME)·`/api/image-file`(바이너리 이미지)·`/api/help`(docs md) 이전. else 브랜치는 do_GET 최후미 fallback이라 `handle_static(h, path)`가 마지막 폴백 호출로 남음.
- 검증: 공통 3종 + 앱 재시작 후 index.html·정적자원 로드 확인(Playwright).
- 의존성: 없음

### [ ] Task 5 (R5): dashboard_api.py 신규 — 대시보드/에이전트
- 파일: `.ai_monitor/api/dashboard_api.py`🆕, `.ai_monitor/server.py`✏️
- 방법: GET `/api/agents`(인메모리 AGENT_STATUS + DB 병합 23줄) + POST `/api/dashboard/launch`·`/api/kanban/launch`·`/api/agents/heartbeat`(42줄) 이전. AGENT_STATUS 등 공유 상태는 참조 주입.
- 검증: 공통 3종.
- 의존성: 없음

### [ ] Task 6 (R6): office_launch_api.py 신규 — 오피스 실행
- 파일: `.ai_monitor/api/office_launch_api.py`🆕, `.ai_monitor/server.py`✏️
- 방법: POST `/api/office/launch`·`/api/office/restart`·`/api/office/status`(exact 3개) + office 프록시(복합 `startswith('/api/office/') and path not in (...)`) 이전. 프록시는 `_proxy_to_office_server` 호출 유지. PROJECT_ROOT·_child_procs 등 주입.
- 검증: 공통 3종.
- 의존성: 없음

### [ ] Task 7 (R7): hive_ingest_api.py 신규 — 하이브 수집 ⚠️SSE
- 파일: `.ai_monitor/api/hive_ingest_api.py`🆕, `.ai_monitor/server.py`✏️
- 방법: POST `/api/hive/log/pg`(18)·`/api/hive/thought/pg`(19)·`/api/thoughts/add`(SSE 브로드캐스트+벡터DB 69줄) 이전.
  🔴 **THOUGHT_LOGS·THOUGHT_CLIENTS·_SSE_LOCK을 events_api.py와 동일 identity로 주입** (별도 생성 금지 — 아니면 SSE 팬아웃 조용히 끊김). exact 3개는 POST_ROUTES 테이블에 등록(exact-first라 뒤 hive prefix elif 도달 안 함) + **이전 완료 후 legacy if 블록(2327~2434) 삭제**.
- 검증: 공통 3종 + **수동 SSE 스모크**: 브라우저에서 thoughts SSE 구독 후 `/api/thoughts/add` POST → 실시간 수신 확인.
- 의존성: 없음 (events_api.py 공유객체 참조만)

### [ ] Task 8 (R8): 기존 모듈 확장 — 잔여 인라인
- 파일: `git_api.py`✏️·`screenshot_api.py`🆕·`memory_api.py`✏️·`config_api.py`✏️·`vibe_api.py`✏️, `server.py`✏️
- 방법: POST `/api/git/rollback`(29)·`/api/git/diff`(19)→git_api / POST `/api/screenshot/analyze`(23)→screenshot_api🆕 / GET `/api/memory/db-info`(19)→memory_api / GET `/api/config`(17)→config_api / GET `/api/vibe/sidebar·notifications·skills`→vibe_api / GET `/api/kanban/pg-activity`(27)→tasks_api or dashboard_api. 각 순수위임/인라인 이전.
- 검증: 공통 3종.
- 의존성: 없음

### [ ] Task 9 (R9): 복합조건 wrapper 테이블화
- 파일: `.ai_monitor/server.py`✏️
- 방법: 복합조건 라우트(hive prefix2+exact8 / tasks in4+startswith·endswith / office startswith·not-in / files in2 / memory in2 / install-cli in3)를 **server.py 내부에 wrapper 함수**(`_g_hive_composite` 등)로 조건 그대로 감싸 `GET_COND_ROUTES`/`POST_COND_ROUTES` 신규 리스트에 등록. do_GET/do_POST 폴백 순서: **exact→prefix→cond→legacy**. 조건을 dict키로 억지 매핑 금지. wrapper 내부에 `path in (...)` 조건 리터럴 잔류(가드 추출용).
- 검증: 공통 3종. 복합조건 라우트 각각 수동 curl/스모크(hive/tasks/office 대표 경로).
- 의존성: Task 1~8 (인라인 이전 완료 후 조건 wrapper화가 깔끔)

### [ ] Task 10 (R9.5): 완전성 가드 보강
- 파일: `tests/test_route_table.py`✏️
- 방법: `_extract()`에 `path in ('/a', '/b', ...)` 튜플 파싱 추가(install-*-cli 3개·hive 8 exact 사각지대 해소). `*_COND_ROUTES` shadowing 검증(cond 라우트가 기존 prefix 테이블과 중복 커버 안 하는지) 추가. GOLDEN 세트에 신규 감지 라우트 반영.
- 검증: `pytest tests/test_route_table.py` — 보강 후에도 green. 임의 install-cli 조건 삭제 시 실패 확인.
- 의존성: Task 9

---

## 파트 B — infra 추출 (안전분만)

### [x] Task 11 (R10): infra/pty_process.py 신규 — PTY 프로세스 🔴클로저 ✅ 1d5e631
- 파일: `.ai_monitor/infra/pty_process.py`🆕, `.ai_monitor/server.py`✏️
- 방법: **착수 전 캡처변수 전수조사** — `_kill_orphan_pty_servers`·`_ensure_pty_node_modules`·`_start_node_pty_server`·`_pty_watchdog_loop`·`_get_node_pty_sessions`는 main() 내부 nested 클로저(현재 `_pty_server_state` dict로 우회 중). 각 함수가 캡처하는 외부 변수(WS_PORT, BASE_DIR, _pty_server_state 등) 전부 목록화 → top-level 함수로 승격하며 명시적 파라미터/상태객체로 전환. server.py는 `infra/pty_process.py` import 후 main()에서 상태객체 넘겨 호출.
- 검증: 공통 3종 + **PTY 서버 기동 스모크**(터미널 슬롯 열기 → Node PTY 연결 확인).
- 의존성: 없음 (파트 A와 독립)

### [x] Task 12 (R13): infra/session_parse.py 신규 — 세션 파싱 ✅
- 파일: `.ai_monitor/infra/session_parse.py`🆕, `.ai_monitor/server.py`✏️
- 방법: `_parse_session_tail`(70)·`_parse_antigravity_session`(64) top-level 함수를 이전(안전 — 클로저 아님). server.py는 import 후 재노출 or 호출부 경로 변경.
- 검증: 공통 3종.
- 의존성: 없음

---

## 파트 C — 소형 헬퍼 흡수

### [x] Task 13 (R15): 소형 헬퍼 infra 흡수 ✅
- 파일: `.ai_monitor/infra/*`✏️, `.ai_monitor/server.py`✏️
- 방법: `_persist_active_project_context`(67)·`_load_task_logs_into_thoughts`(57)·`_restore_agent_status_from_db`(49)·`_resolve_frozen_project_root`(57) 등 소형 헬퍼를 성격에 맞는 infra 모듈로 이전(project_context/session/lifecycle 등). 착수 전 각 함수 호출부 grep으로 의존성 확인.
- 검증: 공통 3종.
- 의존성: 없음

### [x] Task 14: Phase 2 마무리 — 문서/메모리/줄수 확인 ✅ (목표 미달 명시)
- 파일: `project_server_split_plan.md`(메모리)✏️, `PROJECT_MAP.md`(자동생성)
- 방법: `wc -l .ai_monitor/server.py` 최종 확인(~1950 목표). 메모리에 Phase 2 완료 + 실측 줄수 + Phase 3(R14 이중전역/main 조사) 명시. PROJECT_MAP 자동 재생성.
- 검증: server.py < 2000줄 확인. pytest 105 최종 통과.
- **실측(2026-07-06): server.py 3597 → 2383줄 (−1214, −33.8%). ⚠️ 목표 ~1950/게이트 <2000 미달(+433).**
  단일블록·인라인·헬퍼 추출은 완전 소진 — 남은 부피(legacy elif+main+SSEHandler)는 아키텍처 재구조화라 Phase 3.
  pytest 105 통과, PROJECT_MAP 재생성 완료. 상세: 메모리 `project_server_split_plan.md` "Phase 2 종결" 섹션.
- 의존성: Task 1~13

---

## 범위 고정
- **이번 Phase 2 제외(→ Phase 3)**: R14(run_pg_sql/csv → pg_store, 이중전역 PG_PORT/PG_DB 통합 선행 블로커), main()/SSEHandler 추가 조사, 1500 최종 도달.
- **드롭(이미 완료)**: R11(embedding→infra/daemons)·R12(fs_watcher→infra/fs_watcher). 착수 전 grep으로 재확인만.
- 하이브리드 폴백 유지(롤백 안전). 매 라운드 완전성 가드 필수.
