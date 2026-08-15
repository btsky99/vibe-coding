---
title: PostgreSQL 저장 계층
type: 시스템
sources:
  - .ai_monitor/src/db_helper.py:1
  - .ai_monitor/src/pg_base.py:1
  - .ai_monitor/src/pg_base.py:102
  - .ai_monitor/src/pg_base.py:250
  - .ai_monitor/src/pg_base.py:451
  - .ai_monitor/src/pg_base.py:465
  - .ai_monitor/src/pg_base.py:489
  - .ai_monitor/src/pg_office.py:205
  - .ai_monitor/src/pg_office.py:252
  - .ai_monitor/src/pg_office.py:290
  - .ai_monitor/src/pg_schema.py:1
  - .ai_monitor/src/pg_schema.py:41
  - .ai_monitor/src/pg_schema.py:281
  - .ai_monitor/src/pg_schema.py:295
  - .ai_monitor/src/pg_schema.py:531
  - .ai_monitor/src/pg_schema.py:721
  - .ai_monitor/src/pg_store.py:1
  - session_memory  # ~/.claude/projects/<슬러그>/memory/ · 1장
related: []
confidence: high
updated: 2026-08-15
---

# PostgreSQL 저장 계층

## 한 줄

itcp는 scripts/ 에 있어 pip 설치 환경엔 없음 → ImportError 시 no-op 폴백.

> 자동 합성 (코드 주석 17건 · 파일 5개 · 세션 메모리 1장 · 추출 55d5cf1).
> 🔴 **여기를 고치기 전에** 원본(주석 또는 사고 장부)을 먼저 고칠 것 — 다음 빌드에 덮어써진다.

## 🧠 세션에서 굳은 것 (세션 메모리)

> 원본은 `~/.claude/projects/<슬러그>/memory/` 다. **여기가 아니라 원본을 고칠 것** — 다음 빌드에 덮어써진다.

### 🧠 project_code_intelligence

**MindVault 영감 — tree-sitter + PostgreSQL FTS + 코드 그래프 + LLM 위키. 3 Phase 단계적 구현.**

MindVault 영상 분석 후 코드 인텔리전스 시스템 구현 결정 (2026-04-14)

**Why:** 바이브 코딩 도구로서, 사용자 프로젝트가 커질 때 AI의 토큰 낭비(61,800개→0) 해결 필수
**How to apply:** 접근법 C (tree-sitter + PostgreSQL FTS + LLM 위키 하이브리드)

#### 3 Phase 구현 계획 (전체 완료)
- Phase 1: ✅ tree-sitter AST 파싱 + PostgreSQL FTS BM25 검색 + 코드 그래프 저장
- Phase 2: ✅ react-force-graph-2d 그래프 시각화 + 검색 UI
- Phase 3: ✅ LLM 위키 자동생성 (v3.7.204, 2026-04-15 완료)

#### 핵심 파일
- code_indexer.py, code_search.py, codegraph_api.py
- CodeGraphPanel.tsx, CodeSearchPanel.tsx, CodeWikiPanel.tsx
- pg_store.py에 4개 테이블 추가 (code_projects, code_nodes, code_edges, code_wiki)

#### 의존성
- tree-sitter + 개별 언어 파서 (Python, TS, Go, Rust, Java 등)
- react-force-graph-2d

출처: 세션 메모리 `project_code_intelligence.md` · type=project

## 코드에 박힌 지식

## `.ai_monitor/src/db_helper.py`

### 모듈 상단 `[제약]`

위임하는 얇은 래퍼. itcp 메시지 전송은 지연 import.
[2026-07-18] Claude — 헤더 누락 보강 (코드 품질 점검 규칙 5 준수)
- [제약] itcp는 scripts/ 에 있어 pip 설치 환경엔 없음 → ImportError 시 no-op 폴백.

출처: `.ai_monitor/src/db_helper.py:1`

## `.ai_monitor/src/pg_base.py`

### 모듈 상단 `[WHY]` `[불변식]`

(pg_store.py 분할 1/6 — 모든 pg_* 도메인 모듈이 의존하는 최하층)
[2026-06-10] Claude — pg_store.py(2492줄) 분할로 신설 (1500줄 규칙 준수)
- [불변식] 이 모듈은 src.pg_* 를 모듈 레벨에서 import 하지 않는다 (순환 방지).
query_rows/execute의 ensure_schema 호출만 함수 내부 지연 import.
- [WHY] PG_DB는 set_project_db()가 런타임에 재바인딩하는 가변 전역 —
다른 모듈에서 `from src.pg_base import PG_DB`로 값 복사 금지(스테일 값 위험).
반드시 query_rows/execute 등 함수를 통해 간접 접근한다.

출처: `.ai_monitor/src/pg_base.py:1`

### set_pg_port `[WHY]` `[불변식]` `[제약]`

server.py ensure_postgres_running()에서 호출 — 동적 폴백으로 확정된 실제 PG 포트를
pg_base 전역에 전파한다. set_project_db(DB)와 대칭인 포트 push 함수.
[WHY] PG_PORT(위 line 40)는 import 시점 env 1회 평가라, 이미 import된 server 프로세스
내부에는 동적 포트 폴백(기본 5433 점유 → 5434 이동)이 반영되지 않는다
(os.environ['VIBE_PG_PORT'] write-back은 이후 spawn되는 자식 프로세스의 fresh import에만
효과). 그 탓에 psycopg2 단일/풀 커넥션(_get_pg_conn·get_pool_conn)과 psql.exe 폴백
(_run_psql)이 전부 stale 5433을 사용 → 폴백 발동 환경에서만 터지는 잠복 연결 버그.
이 push 함수로 pg_base.PG_PORT를 단일 진실소스로 만들어 세 소비처를 한 번에 동기화한다.
[불변식] 포트가 실제로 바뀔 때만 기존 커넥션을 폐기한다 — 단일 _pg_conn + 풀 _pool 전량.
옛 포트로 맺어둔 커넥션을 재사용하면 엉뚱한 인스턴스에 접속(set_project_db 폐기와 동형).
[제약] 호출 시점은 부팅 초기 ensure_postgres_running(단일 스레드) 전제라 _pg_conn은 lock
없이 접근(set_project_db와 동일). _pool은 API 스레드 접근 가능성 대비 _pool_lock 보호.

출처: `.ai_monitor/src/pg_base.py:102`

### 모듈 상단 `[불변식]`

── 범용 SQL 실행 (텍스트/CSV) ──────────────────────────────────────────────
[이관 R14] server.py에서 pg_base로 이동 — DB I/O는 데이터 계층에 집중(architecture.md
"DB 쓰기 함수는 pg_store에 집중"). psql 폴백 포트가 이제 set_pg_port로 동기화된
pg_base.PG_PORT(단일 진실소스)를 써서, 흡수 전 잠복하던 stale-포트 회귀가 해소됨.
[불변식] db=None → PG_DB(set_project_db로 런타임 동기화되는 현재 프로젝트 DB).
psycopg2 풀 경로는 get_pool_conn/return_pool_conn(동일 모듈) 직접 사용.

출처: `.ai_monitor/src/pg_base.py:250`

### query_rows `[WHY]` `[제약]`

[제약] params는 반드시 2번째 위치 인자다 — 순서를 바꾸지 말 것.
[🔴 과거사고 2026-08-09] 이 함수에 params가 없던 시절 recycle_api가
`query_rows(sql, (a, b))`로 불렀고, 튜플이 timeout에 바인딩돼 %s가 그대로
서버로 나갔다. psycopg2는 파라미터가 없으면 보간을 아예 건너뛰므로
"syntax error at or near %"만 남고 호출부는 빈 리스트를 정상 응답으로 받았다.
결과: 리사이클의 GUARD 3종(flap_guard/user_active/already_running)이
전부 판정 불가 → 사용자가 타이핑 중이어도 세션이 교체됐다.
params를 뒤로 옮기면 그 사고가 그대로 재현된다.
[WHY] global 선언 — 분할 전 코드는 선언 없이 except에서 _pg_conn = None을
대입해 로컬 변수만 만들었고(리셋 무효), 죽은 커넥션이 _get_pg_conn의
SELECT 1 프로브로만 회복되고 있었다. 분할하며 근본 수정.

출처: `.ai_monitor/src/pg_base.py:451`

### query_rows `[WHY]`

[WHY] 지연 import — pg_schema가 pg_base를 모듈 레벨에서 import 하므로
역방향은 함수 내부에서만 (순환 import 방지)

출처: `.ai_monitor/src/pg_base.py:465`

### query_rows `[제약]`

psycopg2 미설치 시 psql.exe 폴백
[제약] psql은 %s 바인딩을 모른다. 여기서 문자열로 끼워 넣으면 인젝션 경로가
열리므로 대신 명시적으로 포기한다 — 조용히 %s를 흘려보낸 것이 바로 위
과거사고의 발단이었다. 파라미터 쿼리는 psycopg2 경로 전용이다.

출처: `.ai_monitor/src/pg_base.py:489`

## `.ai_monitor/src/pg_office.py`

### upsert_active_session `[불변식]`

기존 active 레코드가 있으면 업데이트, 없으면 새로 생성
[불변식] 매칭 키 = terminal_id + project_id — 다른 프로젝트의 같은 터미널(T0)과 절대 병합 금지

출처: `.ai_monitor/src/pg_office.py:205`

### set_session_checkpoint `[WHY]`

의도 단위 체크포인트 — active 세션에 '왜/결정/다음'을 기록 (자가 치유 2.0 ②).
[WHY] 크래시 복구 브리핑이 '수정 파일 목록'만 보여주면 다음 세션이
의도를 재추론(=재설명 요구)해야 한다. 의도/결정/다음 단계를 남기면
설명 없이 즉시 이어받는다.
- decision은 decisions JSONB 배열에 누적 append — 세션 내 결정 흐름 보존.
- active 세션이 없으면 새로 생성 (CLI 단독 사용 대비).

출처: `.ai_monitor/src/pg_office.py:252`

### complete_active_session `[주의]`

활성 세션을 완료 처리한다. Stop 이벤트에서 호출.
[주의] project_id 없이 부르면 같은 터미널 번호의 다른 프로젝트 세션까지
닫아버림 — 훅 경유 호출은 반드시 project_id를 전달할 것.

출처: `.ai_monitor/src/pg_office.py:290`

## `.ai_monitor/src/pg_schema.py`

### 모듈 상단 `[WHY]` `[불변식]`

(pg_store.py 분할 2/6)
[2026-06-10] Claude — pg_store.py 분할로 신설 (1500줄 규칙 준수)
- [불변식] _SCHEMA_READY 플래그는 이 모듈 내부 상태 — 외부에서 직접 대입 금지.
프로젝트 DB 전환 후 재초기화는 reset_schema_cache() 사용 (server.py 기동 2단계).
- [WHY] _migrate_* 가 도메인 함수(set_memory/save_task 등)를 지연 import —
pg_memory/pg_tasks가 pg_base→(지연)ensure_schema 경로로 이 모듈을 쓰므로
모듈 레벨 상호 import 시 순환 발생. 마이그레이션은 최초 1회만 실행되어
함수 내부 import 비용은 무시 가능.

출처: `.ai_monitor/src/pg_schema.py:1`

### reset_schema_cache `[WHY]`

스키마 준비 플래그를 리셋한다 — set_project_db()로 DB가 바뀐 직후 호출.
[WHY] server.py 기동 2단계에서 프로젝트 DB 전환 후 새 DB에 스키마를 다시
배치해야 하는데, 분할 전에는 `pg_store._SCHEMA_READY = False` 직접 대입으로
처리했다. 분할 후 플래그가 이 모듈 내부 상태가 되어 함수로 캡슐화.

출처: `.ai_monitor/src/pg_schema.py:41`

### ensure_schema `[WHY]`

)
LAN 브리지 Phase 2: 기기간 채팅 이력 — office_chat과 별도 테이블(혼용 금지).
[WHY project_id] 브리지는 project_id 무지(이식성)라 저장을 server.py(lan_api)가 담당,
현재 프로젝트 컨텍스트로 기록한다. 대부분 단일 프로젝트 사용이라 수용된 트레이드오프.
execute_raw("""

출처: `.ai_monitor/src/pg_schema.py:281`

### ensure_schema `[WHY]`

)
execute_raw("CREATE INDEX IF NOT EXISTS idx_lan_messages ON lan_messages (project_id, from_peer, to_peer, id);")
LAN 브리지 Phase 3: 원격 실행 감사로그 — 누가/무엇을/승인여부/결과를 남긴다.
[WHY 감사 필수] exec_trust=auto(자동승인)여도 이 로그는 항상 기록해 "무엇이 언제
돌았는지" 추적 가능하게. direction: 'out'=내가 요청, 'in'=내가 실행 대상.
execute_raw("""

출처: `.ai_monitor/src/pg_schema.py:295`

### ensure_schema `[WHY]` `[불변식]`

)
execute_raw("CREATE INDEX IF NOT EXISTS idx_active_session_status ON active_session_context (status, terminal_id);")
[2026-06-10 자가 치유 2.0 ②] 의도 단위 체크포인트 — 복구 브리핑을
"파일 목록"에서 "왜/어디까지 결정/다음 뭐" 수준으로 격상하는 3컬럼
execute_raw("ALTER TABLE active_session_context ADD COLUMN IF NOT EXISTS intent TEXT NOT NULL DEFAULT '';")
execute_raw("ALTER TABLE active_session_context ADD COLUMN IF NOT EXISTS decisions JSONB NOT NULL DEFAULT '[]'::jsonb;")
execute_raw("ALTER TABLE active_session_context ADD COLUMN IF NOT EXISTS next_step TEXT NOT NULL DEFAULT '';")
[2026-08-05 Phase 6 리사이클] 컨텍스트 교체 진행 상태.
[WHY] 계획 초안의 별도 session_checkpoints 테이블을 만들지 않았다 —
active_session_context가 이미 intent/decisions/next_step으로 체크포인트
정본이고 checkpoint.py가 여기에 쓴다. 새 테이블은 이중 정본이 된다.
[불변식] recycle_state가 비어 있지 않으면 리사이클 진행 중 —
plan_recycle이 이 값 하나로 동시 실행을 막으므로 실패 경로에서도
반드시 ''로 되돌려야 한다(안 그러면 해당 터미널이 영구 잠긴다).
execute_raw("ALTER TABLE active_session_context ADD COLUMN IF NOT EXISTS recycle_state TEXT NOT NULL DEFAULT '';")
execute_raw("ALTER TABLE active_session_context ADD COLUMN IF NOT EXISTS recycle_token TEXT NOT NULL DEFAULT '';")
execute_raw("ALTER TABLE active_session_context ADD COLUMN IF NOT EXISTS recycled_at TIMESTAMPTZ;")
execute_raw("ALTER TABLE active_session_context ADD COLUMN IF NOT EXISTS predecessor_id BIGINT;")
execute_raw("""

출처: `.ai_monitor/src/pg_schema.py:531`

### ensure_schema `[제약]`

)
execute_raw("CREATE INDEX IF NOT EXISTS idx_incident_sig ON incident_ledger (error_signature);")
execute_raw("CREATE INDEX IF NOT EXISTS idx_incident_project ON incident_ledger (project_id, last_seen_at DESC);")
_SCHEMA_READY = True
── [2026-06-10] 자가 치유 2.0 ④ — pgvector 회상 스키마 (선택적) ──
[제약] 반드시 _SCHEMA_READY=True 이후 — pg_vector_search가 query_rows를
쓰므로 그 전에 부르면 ensure_schema 재진입(_SCHEMA_LOCK 데드락).
확장 미설치 DB에서는 내부적으로 무음 비활성 (ILIKE 회상 폴백 유지).
try:
from src.pg_vector_search import ensure_vector_schema
ensure_vector_schema()
except Exception as _ve:
print(f"[pg_schema] vector 스키마 스킵: {_ve}")
if not _MIGRATION_DONE:
DB에 마이그레이션 완료 플래그 확인 — 프로세스 재시작 시 재실행 방지
_mig_check = query_rows(
"SELECT payload FROM hive_state WHERE state_key = 'migration_done' LIMIT 1;"
)
if not _mig_check:
migrate_legacy_data(data_dir or DATA_DIR)
execute("INSERT INTO hive_state (state_key, payload, updated_at) "
f"VALUES ('migration_done', '{{\"v\":1}}'::jsonb, {_sql_text(_now_iso())}) "
"ON CONFLICT (state_key) DO NOTHING;")
_MIGRATION_DONE = True
return True
def migrate_legacy_data(data_dir: Path | None = None) -> None:
data_dir = data_dir or DATA_DIR
ensure_legacy_store(data_dir)
_migrate_memory(data_dir)
_migrate_sessions(data_dir)
_migrate_tasks(data_dir / 'tasks.json')
_migrate_state_file(data_dir / 'hive_health.json', 'health')
_migrate_state_file(data_dir / 'skill_analysis.json', 'skill_analysis')
_migrate_skill_chains(data_dir)
def _migrate_memory(data_dir: Path) -> None:
from src.pg_memory import set_memory  # 순환 import 방지 지연 import (헤더 참고)
rows = load_memory_entries(data_dir)
for row in rows:
set_memory(
key=row.get('key', ''),
content=row.get('content', ''),
title=row.get('title', '') or row.get('key', ''),
tags=_parse_json_text(row.get('tags'), []),
author=row.get('author', 'unknown'),
project_id=row.get('project', ''),
created_at=row.get('created_at') or row.get('updated_at') or '',
updated_at=row.get('updated_at') or row.get('created_at') or '',
)
def _migrate_sessions(data_dir: Path) -> None:
from src.pg_memory import upsert_session_log  # 순환 import 방지 지연 import
rows = list(reversed(load_session_logs(data_dir)))
for row in rows:
upsert_session_log(
session_id=row.get('session_id', ''),
terminal_id=row.get('terminal_id', ''),
project_id=row.get('project', ''),
agent=row.get('agent', ''),
trigger_msg=row.get('trigger_msg', ''),
status=row.get('status', ''),
commit_hash=row.get('commit_hash', ''),
files_changed=_parse_json_text(row.get('files_changed'), []),
ts_start=row.get('ts_start', ''),
ts_end=row.get('ts_end', ''),
legacy_source='session_logs.jsonl',
legacy_id=row.get('id'),
)
def _migrate_tasks(path: Path) -> None:
if not path.exists():
return
try:
tasks = json.loads(path.read_text(encoding='utf-8'))
except Exception:
return
if not isinstance(tasks, list):
return
from src.pg_tasks import save_task  # 순환 import 방지 지연 import
for task in tasks:
if isinstance(task, dict):
save_task(task)
def _migrate_state_file(path: Path, state_key: str) -> None:
if not path.exists():
return
try:
payload = json.loads(path.read_text(encoding='utf-8'))
except Exception:
return
from src.pg_tasks import save_state  # 순환 import 방지 지연 import
save_state(state_key, payload)
def _migrate_skill_chains(data_dir: Path) -> None:
from src.pg_tasks import upsert_skill_chain_row  # 순환 import 방지 지연 import
rows = load_skill_chain_rows(data_dir)
for row in rows:
upsert_skill_chain_row(row, legacy_id=row.get('id'))

출처: `.ai_monitor/src/pg_schema.py:721`

## `.ai_monitor/src/pg_store.py`

### 모듈 상단 `[함정]`

(실제 구현: pg_base / pg_schema / pg_memory / pg_tasks / pg_experience / pg_office)
[2026-06-10] Claude — 2492줄 단일 파일을 도메인 6모듈로 분할 (1500줄 규칙 준수)
- [호환성] 기존 60여 곳의 `from src.pg_store import X` 호출부를 깨지 않기 위해
모든 공개 함수 + 외부에서 쓰이는 내부 헬퍼(_sql_text, _get_pg_conn, _pool 등)를
여기서 재노출한다. 신규 코드는 도메인 모듈을 직접 import 해도 된다.
- [함정] PG_DB는 set_project_db()가 pg_base 안에서 재바인딩하는 가변 전역 —
이 파사드의 PG_DB 사본은 import 시점 값으로 고정된다(스테일 가능).
값이 필요하면 src.pg_base를 모듈로 import 해 pg_base.PG_DB로 읽을 것.
- [함정] 구버전의 `pg_store._SCHEMA_READY = False` 직접 대입은 분할 후 무효 —
reset_schema_cache()를 사용한다 (server.py 기동 2단계가 유일한 호출부였음).
[2026-04-15 이전 이력] 분할 전 이력은 git log -- .ai_monitor/src/pg_store.py 참고

출처: `.ai_monitor/src/pg_store.py:1`

## 확인법

```bash
python scripts/wiki_lint.py        # 이 페이지의 출처가 아직 살아 있는지
python scripts/wiki_build.py       # 원본 주석 변경분 재합성
```

<!-- tags: WHY, 불변식, 제약, 주의, 함정 -->
