---
title: API 계층 · 그 밖
type: 시스템
sources:
  - .ai_monitor/api/_common.py:1
  - .ai_monitor/api/_common.py:23
  - .ai_monitor/api/_common.py:48
  - .ai_monitor/api/daemons_api.py:36
  - .ai_monitor/api/dashboard_api.py:35
  - .ai_monitor/api/dashboard_api.py:59
  - .ai_monitor/api/dashboard_api.py:88
  - .ai_monitor/api/experience_api.py:165
  - .ai_monitor/api/fs_dialog_api.py:1
  - .ai_monitor/api/fs_dialog_api.py:40
  - .ai_monitor/api/git_api.py:1
  - .ai_monitor/api/git_api.py:129
  - .ai_monitor/api/git_api.py:163
  - .ai_monitor/api/heal_api.py:15
  - .ai_monitor/api/hive_ingest_api.py:1
  - .ai_monitor/api/hive_ingest_api.py:71
  - .ai_monitor/api/locks_api.py:17
  - .ai_monitor/api/logs_api.py:1
  - .ai_monitor/api/logs_api.py:25
  - .ai_monitor/api/message_api.py:23
  # …외 12건 (본문 각 항목에 경로 표기)
related: []
confidence: high
updated: 2026-08-15
---

# API 계층 · 그 밖

## 한 줄

사본이 미묘하게 달라(experience/vibe/zettel/codegraph만 default=str,

> 자동 합성 (코드 주석 32건 · 파일 18개 · 추출 909e7e6).
> 🔴 **여기를 고치기 전에** 원본(주석 또는 사고 장부)을 먼저 고칠 것 — 다음 빌드에 덮어써진다.

## 코드에 박힌 지식

## `.ai_monitor/api/_common.py`

### 모듈 상단 `[WHY]` `[불변식]`

_read_body(4중복)를 단일 출처로 통합한다. 각 모듈은
`from api._common import json_response as _json_response` 로 재노출해
기존 호출부(_json_response/_read_body)를 그대로 유지한다.
[2026-07-18] Claude: 중복 헬퍼 통합 신설.
- [WHY] 사본이 미묘하게 달라(experience/vibe/zettel/codegraph만 default=str,
tools_api만 Content-Length) 유지보수 시 한쪽만 고치는 사고 위험. 상위집합으로 통합.
- [호환성] default=str은 원래 TypeError로 죽던 datetime 등 입력에만 관여 →
정상 호출은 결과 동일. Content-Length 명시도 HTTP 정확성 개선이라 회귀 없음.
- [불변식] handler는 _cors_origin()을 제공하는 BaseHTTPRequestHandler 파생 전제.

출처: `.ai_monitor/api/_common.py:1`

### json_response `[WHY]`

JSON 응답 공통 헬퍼 — ensure_ascii=False(한글 보존) + default=str(datetime 등 방어).
[WHY] Content-Length를 명시해 HTTP keep-alive에서 응답 경계가 모호해지지 않게 한다.

출처: `.ai_monitor/api/_common.py:23`

### read_body `[WHY]`

POST/DELETE 요청 본문(JSON)을 파싱해 dict 반환. 실패 시 {}.
[WHY] pty_api 사본만 malformed JSON에서 예외를 던져 미처리 시 500 위험 →
방어형(예외 삼키고 {})으로 통일. 정상 본문은 결과 동일.

출처: `.ai_monitor/api/_common.py:48`

## `.ai_monitor/api/daemons_api.py`

### handle_update `[WHY]` `[불변식]`

POST /api/daemons — {"key": bool, ...} 부분 병합.
[불변식] 레지스트리에 없는 키는 저장하지 않는다 — 오타 키가 config에 쌓이면
start_all_daemons가 매 부팅 "알 수 없는 데몬 키" 경고를 뱉고, 사용자는 껐다고
믿는 항목이 계속 뜨는 것을 보게 된다.
[WHY True도 명시 저장] 키를 지우는 대신 true로 남긴다 — 사용자가 의도적으로 켠 것과
한 번도 건드리지 않은 것을 config만 봐도 구분할 수 있다(기본값 변경 시 안전).

출처: `.ai_monitor/api/daemons_api.py:36`

## `.ai_monitor/api/dashboard_api.py`

### list_agents `[불변식]`

GET /api/agents — 인메모리 AGENT_STATUS + PostgreSQL 병합 반환(오케스트레이터용).
[불변식] agent_status/agent_status_lock은 server.py 전역과 동일 객체여야
heartbeat가 쓴 최신 상태가 여기서 읽힌다(별도 사본이면 빈 dict).

출처: `.ai_monitor/api/dashboard_api.py:35`

### dashboard_launch `[WHY]` `[주의]`

POST /api/dashboard/launch — dashboard_window.py 네이티브 창 실행(기본 agent 탭).
[WHY] window.open()이 아닌 PySide6 네이티브 프로세스로 띄워 브라우저 창이 아닌 OS 창을 연다.
[주의] body 선읽기 금지 위임 규칙 무관 — 이 핸들러가 Content-Length 만큼 직접 소비.

출처: `.ai_monitor/api/dashboard_api.py:59`

### heartbeat `[불변식]` `[주의]`

POST /api/agents/heartbeat — 에이전트 실시간 상태 보고 수신 → 인메모리 + PG.
[불변식] agent_status/agent_status_lock은 server.py 전역과 동일 객체 —
/api/agents(list_agents)가 같은 dict를 읽어야 하트비트가 반영된다.
[원본보존] prev 조회가 agent_status[name] 갱신 뒤에 오므로 prev_status는 방금 쓴 값과
같아져 pg_logs 변경-감지 분기가 사실상 무력. 원본 동작 그대로 — 여기서 고치지 말 것.
[주의] 지역 상태 문자열은 agent_status_val로 명명 — 주입된 dict 파라미터(agent_status)와
이름 충돌 회피(원본 로컬명 agent_status를 리네임한 것뿐, 동작 동일).

출처: `.ai_monitor/api/dashboard_api.py:88`

## `.ai_monitor/api/experience_api.py`

### seed_from_git_log `[WHY]`

[WHY] POST /api/experience 시드 시 git 자식이 콘솔 없이 돌게 — proc.run이 숨김 주입.

출처: `.ai_monitor/api/experience_api.py:165`

## `.ai_monitor/api/fs_dialog_api.py`

### 모듈 상단 `[WHY]` `[불변식]` `[제약]`

폴더 선택 다이얼로그(tkinter 서브프로세스), 드라이브 스캔, 디렉터리 목록,
외부 앱(브라우저) 열기. 모두 OS 레벨 부수효과가 있어 한 도메인으로 묶음.
[WHY] server.py 1500줄 감축을 위한 도메인 단위 분리. 동작 완전 불변(verbatim 이전).
[제약] 서버 전역 헬퍼(_open_folder_dialog_subprocess)와 CONFIG_FILE 경로는 server.py 소유라
호출 인자로 주입받는다(late-binding). 모듈이 server 전역을 직접 import하면 순환 의존 위험.
[불변식] h(SSEHandler)의 _cors_origin()/send_response()/wfile은 핸들러 메서드로 그대로 사용.
- 2026-07-05 Claude: 신규 — server.py에서 browse-folder/drives/dirs/select-folder/open-external 5종 추출.

출처: `.ai_monitor/api/fs_dialog_api.py:1`

### handle_get `[WHY]`

[WHY] LAN 파일전송은 파일 1개 경로가 필요 — 폴더 다이얼로그와 별도.
open_file_dialog 미주입(구버전 호출) 시 500 대신 빈 경로로 안전 폴백.

출처: `.ai_monitor/api/fs_dialog_api.py:40`

## `.ai_monitor/api/git_api.py`

### 모듈 상단 `[주의]`

Git 저장소 상태 조회, 커밋 로그 조회, diff 확인,
파일 롤백(git checkout) 기능을 제공합니다.
server.py에서 분리하여 Git 관련 로직을 단일 파일로 관리합니다.
- 2026-03-01 Claude: server.py에서 분리 — git API 핸들러 담당
- 2026-07-06 Claude: do_POST exact 인라인 rollback/diff를 rollback()/diff()로 verbatim 분리(R8).
[주의] 아래 handle_post()의 rollback/diff 분기와 동작이 다르다(rollback 성공 message 없음,
git_dir 키가 'path' vs 'repo'; diff는 body 미사용·쿼리스트링만). 원본 do_POST의 exact 인라인이
prefix 위임(handle_post)보다 먼저 걸렸으므로 그 동작을 보존한다 — 두 경로 수렴은 R9 대상.

출처: `.ai_monitor/api/git_api.py:1`

### rollback `[주의]`

POST /api/git/rollback — 특정 파일 변경 원상복구(git checkout -- 파일).
[R8 verbatim] server.py do_POST exact 인라인 이전. body를 직접 소비(Content-Length 만큼).
[주의] handle_post()의 rollback 분기와 다름 — git_dir는 'path' 키, 성공 응답에 message 없음.
원본 exact 동작 보존(수렴은 R9). body 읽기는 try 내부(원본 위치 그대로).

출처: `.ai_monitor/api/git_api.py:129`

### diff `[주의]`

POST /api/git/diff — 파일 diff(쿼리스트링 기반, POST body 미사용).
[R8 verbatim] server.py do_POST exact 인라인 이전. params=parse_qs(query).
[주의] handle_post()의 diff 분기와 파라미터 추출 위치만 다름(헤더 전송 후 추출). 원본 exact 보존.

출처: `.ai_monitor/api/git_api.py:163`

## `.ai_monitor/api/heal_api.py`

### handle_get `[제약]`

GET /api/heal/metrics — 자가치유 4장치 계측 JSON.
[제약] 계산은 heal_metrics 단일 소스 위임. 오류 시 500 + error 필드(무음 실패 방지).

출처: `.ai_monitor/api/heal_api.py:15`

## `.ai_monitor/api/hive_ingest_api.py`

### 모듈 상단 `[불변식]`

사고과정 추가(SSE 브로드캐스트 + 벡터DB 영구 저장). server.py do_POST에서 분리.
[불변식 — 절대 준수] thoughts_add는 사고 SSE 팬아웃의 writer 측이다.
THOUGHT_LOGS / THOUGHT_CLIENTS / _SSE_LOCK 3개는 반드시 server.py 전역과
'동일 객체 identity'를 참조 주입받아야 한다. events_api.stream_thoughts(broadcaster)가
똑같은 3개 전역을 구독자 등록에 쓰기 때문 — 새로 만들거나 사본을 넘기면 구독자는
붙어있는데 새 thought가 절대 도달하지 않는다(에러도 안 남, 런타임에만 드러나는 치명 버그).
그래서 이 함수들은 상태를 모듈 내부에 두지 않고 전부 파라미터로 주입받는다.
- 2026-07-06 Claude: server.py do_POST 하이브 수집 3라우트 분리(Phase 2 R7).
로직 원본 verbatim 이전. 공유 전역(집합/락/로그리스트)·PG 헬퍼·벡터DB 헬퍼는 참조 주입.

출처: `.ai_monitor/api/hive_ingest_api.py:1`

### thoughts_add `[불변식]`

POST /api/thoughts/add — 사고과정 추가 + 실시간 SSE 브로드캐스트 + 벡터DB 영구 저장.
[불변식] thought_logs/thought_clients/sse_lock은 server.py 전역과 동일 객체여야 함
(events_api.stream_thoughts가 등록한 구독자 집합과 같아야 팬아웃이 닿음).
set_memory/project_id도 참조 주입(server.py의 pg_store.set_memory / 전역 PROJECT_ID)."""

출처: `.ai_monitor/api/hive_ingest_api.py:71`

## `.ai_monitor/api/locks_api.py`

### handle_lock `[불변식]`

POST /api/locks — {file, agent, action='lock'|'unlock'}. lock 충돌 시 conflict 반환.
[불변식] 다른 에이전트가 소유한 파일 lock 요청은 conflict(덮어쓰기 금지).

출처: `.ai_monitor/api/locks_api.py:17`

## `.ai_monitor/api/logs_api.py`

### 모듈 상단 `[불변식]`

GET /api/messages, POST /api/messages/clear. server.py do_GET/do_POST 인라인 블록을
verbatim 이전(Phase 2 R3). 동작 완전 불변.
[불변식/핵심 함정] stream()의 psycopg2 직접연결은 풀을 거치지 않는다. server.py의
살아있는 전역 PG_PORT / PG_PROJECT_DB(동적 포트 폴백 시 global로 갱신됨)와
run_pg_sql_csv를 인자로 주입받아야 한다 — server.py wrapper는 함수 바디 안에서
전역 이름을 참조해 매 호출 시 최신값을 재조회한다(디폴트 인자 late-binding 금지).
[구조 유지] psycopg2 직접연결→풀 전환은 별도 작업. 여기서는 원본 그대로 옮기기만 한다.
- 2026-07-06 Claude: server.py do_GET/do_POST 로그·스트림 4블록 분리(Phase 2 R3).
전역(PG_PORT/PG_PROJECT_DB/DATA_DIR/run_pg_sql_csv/get_messages/clear_messages)은 참조 주입.

출처: `.ai_monitor/api/logs_api.py:1`

### stream `[불변식]`

GET /stream — pg_logs 실시간 SSE(psycopg2 LISTEN/NOTIFY 무한루프).
[불변식] pg_port/pg_project_db는 server.py 전역의 최신값이어야 함(동적 포트 폴백 대응).
풀 미경유 직접연결 — 클라이언트별 전용 커넥션에서 LISTEN 도는 구조라 그대로 유지.

출처: `.ai_monitor/api/logs_api.py:25`

## `.ai_monitor/api/message_api.py`

### _load_slot_names `[제약]`

config.json의 slot_names{터미널ID: 이름}. 실패하면 빈 dict.
[제약] 예외를 삼킨다 — 이름 조회 실패로 메시지 배달 자체가 죽으면 안 된다.
빈 dict면 호출부가 pty 값으로 폴백하므로 동작은 이전과 같아진다.

출처: `.ai_monitor/api/message_api.py:23`

### handle_send `[제약]`

POST /api/message — {from,to,type,content} 저장 + 대상 PTY 주입 + 로그.
[제약] to가 ceo/all/broadcast/''가 아니면 Node PTY REST(/api/pty/sessions→write)로 주입.
CEO(사람)는 PTY 없어 스킵. WS_PORT는 호출 시점 값(런타임 슬롯 기반 재설정).

출처: `.ai_monitor/api/message_api.py:38`

## `.ai_monitor/api/nodes_api.py`

### 모듈 상단 `[제약]`

GET  /api/nodes/consoles      — 화면에 떠 있는 콘솔 창 목록 + 소속 판정
POST /api/nodes/console/kill  — 콘솔 창 안전 종료(3중 재검증)
[제약] consoles는 CIM 스냅샷(~700ms)이라 무겁다 — 상태판은 5초 주기로만 부른다.
더 잦게 부르면 스캔이 겹쳐 서버 응답 전체가 늘어진다.
- 2026-08-02 Claude: 최초 작성 — 정체불명 콘솔 창 식별 + 원격 노드 상태판.
- 2026-08-14 Claude: 아픽스 계층 철거 — remote/check-cli 제거. 원격 노드 조회(node_status)가
사라져 이 파일은 로컬 콘솔 창 전용이 됐다. 원격 상태가 다시 필요하면 아픽스 리포에 둘 것.

출처: `.ai_monitor/api/nodes_api.py:1`

### consoles `[WHY]`

GET /api/nodes/consoles — 화면에 떠 있는 콘솔 창 목록.
[WHY server_pid를 여기서 넘기는가] console_scan은 '이 서버의 자손'을 owned로 본다.
멀티 인스턴스(개발본 + 설치본 동시 실행)에서 os.getpid()는 각자 자기 자신이라
인스턴스마다 owned 판정이 올바르게 갈린다.

출처: `.ai_monitor/api/nodes_api.py:48`

## `.ai_monitor/api/office_launch_api.py`

### launch `[불변식]` `[주의]`

POST /api/office/launch — office_server.py를 별도 프로세스로 시작 → 포트 확인 →
dashboard_window.py 오피스 창 실행(오피스 서버 포트 전달).
[불변식] office_state는 server.py 전역(_office_state)과 동일 객체여야 프록시 라우트가
같은 생존/포트 상태를 읽는다(별도 사본이면 프록시가 죽은 포트로 중계).
[주의] 이미 살아있으면 서버 재사용 — office_state.alive and office_state.port 검사.

출처: `.ai_monitor/api/office_launch_api.py:32`

### status `[불변식]`

POST /api/office/status — 오피스 서버 생존/포트/PID 조회.
[불변식] office_state는 프록시 라우트와 동일 객체여야 일관된 생존 판정.

출처: `.ai_monitor/api/office_launch_api.py:75`

## `.ai_monitor/api/screenshot_api.py`

### analyze `[제약]`

POST /api/screenshot/analyze — 멀티모달 버그 감지.
[제약] SCRIPTS_DIR는 개발 실행 시에만 존재(설치본은 None) — None이면 기능 불가 응답.
screenshot_analyzer는 scripts/에만 있으므로 sys.path에 넣고 동적 import 한다.
[원본보존] 모든 실패는 200 + {'error': ...}로 반환(프론트가 에러 문자열을 표시).

출처: `.ai_monitor/api/screenshot_api.py:19`

## `.ai_monitor/api/setup_api.py`

### 모듈 상단 `[WHY]`

[WHY 상한] 쿨다운은 **프로세스 메모리**에만 있어 앱을 껐다 켜면 0으로 돌아간다. 그래서
도구 하나가 끝내 안 잡히는 PC(예: agy 미설치를 사용자가 원함)에서는 실행할 때마다
설치가 다시 돌았다 — 예전엔 그때마다 cmd 창까지 떴다. 시도 횟수를 디스크에 남겨
'설치는 됐는데 계속 다시 뜬다'를 끊는다. 사용자가 배너 버튼을 누르는 수동 경로는
이 상한을 받지 않는다(사람이 원해서 누른 것).

출처: `.ai_monitor/api/setup_api.py:32`

## `.ai_monitor/api/static_api.py`

### 모듈 상단 `[불변식]`

그리고 do_GET 최후미 else 폴백(Vite dist SPA 서빙). server.py 인라인 블록을
verbatim 이전(Phase 2 R4). 동작 완전 불변.
[불변식/핵심] serve()는 do_GET의 "최후미 폴백"이다 — exact/prefix/legacy 어디에도 안 걸린
모든 GET 요청이 여기로 온다. 절대 라우트 테이블(exact)에 등록하면 안 됨 — 등록하면 미매칭
GET이 404가 되어 SPA 라우팅이 깨진다. server.py do_GET 맨 끝 else 자리에서만 호출한다.
[경로 주입] static_dir(STATIC_DIR)·docs_dir·validate_file_path는 server.py 전역/함수라
인자로 주입받는다. 특히 STATIC_DIR은 server.py에서 동적 폴백(alt_dist)으로 갱신될 수
있으므로 wrapper가 호출 시점 최신값을 넘겨야 한다(late-binding).
[help_doc docs 경로] 원본은 server.py의 Path(__file__).parent/'docs' = .ai_monitor/docs 를
참조했다. 이 모듈의 __file__은 api/ 하위라 경로가 달라지므로 docs_dir를 반드시 주입받는다.
- 2026-07-06 Claude: server.py do_GET 정적서빙 else + /api/help + /api/image-file 3블록 분리(Phase 2 R4).
전역(STATIC_DIR/docs_dir/_validate_file_path)은 참조 주입. serve는 do_GET 최후미 폴백 유지.

출처: `.ai_monitor/api/static_api.py:1`

### serve `[불변식]`

do_GET 최후미 폴백 — Vite 빌드 결과물(SPA) 정적 서빙.
[불변식] 테이블 등록 금지. 미매칭 GET 전부 여기로 폴백 → 없으면 index.html SPA fallback.
[경로] path는 parsed_path.path(쿼리 제거 완료)를 받는다. 원본은 self.path(쿼리 포함)를
받아 split('?')로 잘랐으나, parsed_path.path는 이미 쿼리가 없어 split이 무해(동작 동일).
정적 파일 서비스 로직 (Vite 빌드 결과물)
요청 경로를 정리

출처: `.ai_monitor/api/static_api.py:74`

## `.ai_monitor/api/vibe_api.py`

### _run_sql `[설계]`

server.py의 run_pg_sql을 호출합니다.
[설계 의도] vibe_api는 server.py 모듈의 run_pg_sql / run_pg_sql_csv를
직접 임포트할 수 없으므로 (순환 의존), handler 객체를 통해
server 모듈의 전역 함수를 간접 호출합니다.
server.py에서 run_pg_sql을 모듈 레벨에서 임포트

출처: `.ai_monitor/api/vibe_api.py:40`

## `.ai_monitor/api/wiki_api.py`

### 모듈 상단 `[제약]`

wiki_build 는 scripts/ 에 있어 패키지 import 가 안 된다 — 경로로 로드한다.
[제약] frozen(EXE) 에서는 프로젝트 체크아웃의 scripts/ 를 봐야 한다. tools_api 가
같은 문제를 _find_install_script 로 풀고 있으니 규칙이 바뀌면 양쪽을 같이 고칠 것.

출처: `.ai_monitor/api/wiki_api.py:18`

### handle_post `[WHY]`

[WHY 명시 확인을 요구하나] 위키 페이지를 통째로 지운다. 사람이 옵시디언에서 손으로
덧붙인 문단도 함께 사라진다(원료에 없는 내용은 복원되지 않는다). 실수로 눌린
요청 하나에 그게 날아가면 안 된다.

출처: `.ai_monitor/api/wiki_api.py:88`

## 확인법

```bash
python scripts/wiki_lint.py        # 이 페이지의 출처가 아직 살아 있는지
python scripts/wiki_build.py       # 원본 주석 변경분 재합성
```

<!-- tags: WHY, 불변식, 설계, 제약, 주의 -->
