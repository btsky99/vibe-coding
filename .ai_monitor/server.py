"""
FILE: .ai_monitor/server.py
DESCRIPTION: 하이브 마인드 중앙 통제 서버 — 에이전트 간 통신 중계, 상태 모니터링, 데이터 영속성 관리.

REVISION HISTORY:
- 2026-07-04 Claude: /api/agent-quota 디스패치 누락 수정 — hive_api 핸들러만 있고
                     allowlist 미갱신으로 쿼터 배지가 index.html을 받던 버그
- 2026-04-30 Claude: Platform Phase 2-3 — _current_project_root/_id 로직을
                     infra/project_context.py로 추출 (서버 외부에서도 재사용 가능)
- 2026-03-19 Claude: 표준 헤더 형식 적용 (RULES.md 섹션 2 준수)
"""
# 🕒 변경 이력 (History):
# [2026-04-15] - Claude (자동 문서 생성기 데몬 추가 — PROJECT_MAP/HIVEMIND stale 수정)
#   - run_doc_generators_daemon(): generate_project_map.py + generate_hivemind_doc.py를
#     30분 주기로 자동 실행 (시동 시 즉시 1회 + 이후 주기적)
#   - 데몬 등록 블록에 DocGeneratorsDaemon 스레드 추가
#   - 원인: 두 자동 생성기가 시동 시퀀스에서 빠져있어 PROJECT_MAP.md 17일/HIVEMIND.md 15일째
#     stale 상태. 이로 인해 사용자/AI 모두 옛날 정보 위에서 작업하던 문제
#   - 효과: PROJECT_MAP.md, HIVEMIND.md가 항상 최신 상태 유지
# [2026-04-15] - Claude (오케스트레이터 데몬 자동 시동 — 'all' 태스크 적체 근본 수정)
#   - run_orchestrator_daemon(): scripts/orchestrator.py를 --daemon 모드로 자동 실행
#   - 데몬 스레드 등록 블록에 OrchestratorDaemon 스레드 추가
#   - 원인: wiki_generator 등이 발행하는 assigned_to='all' 태스크를 재배정할
#     주체(orchestrator)가 시동 시퀀스에서 빠져있어 태스크가 영원히 pending 상태로 적체
#   - 효과: 60초마다 'all' pending 태스크를 살아있는 에이전트로 자동 재배정
# [2026-03-26] - Claude (원스톱 설치 + 언인스톨 + PTY 자동 빌드)
#   - --install: 바탕화면 바로가기 + PTY node-pty 네이티브 모듈 자동 npm install
#   - --uninstall: 바탕화면 바로가기 삭제 + pip uninstall 안내
#   - 첫 실행 시 바탕화면 바로가기 자동 생성 (바이브코딩.lnk 없으면)
#   - _ensure_pty_node_modules(): 서버 시작 시 node-pty 네이티브 바이너리 없으면 npm install 자동 실행
#   - 원인: pip install로 다른 PC에 설치하면 node-pty C++ 바이너리가 호환 안 되어 터미널 연결 실패
# [2026-03-25] - Claude (PTY 좀비 정리 시 다른 인스턴스 보호 — 설치버전↔개발버전 동시 실행 가능)
#   - _kill_orphan_pty_servers(): 기존 모든 pty-server.js 무차별 kill → 자기 인스턴스 소유만 정리
#   - 자기 PTY PID 비교 + 부모 프로세스 검증으로 다른 인스턴스의 PTY 서버 보호
#   - 원인: 설치버전 시작 시 개발용 PTY 서버까지 죽여서 터미널 전부 사망하던 버그
# [2026-03-19] - Claude (디스패치 히스토리 API 추가 — "최근 디스패치" 패널 빈 화면 수정)
#   - GET /api/dispatcher/history: hive_tasks에서 created_by='dispatcher' 레코드 조회
#   - DispatcherPanel.tsx의 DispatchResult 인터페이스 형식으로 변환하여 반환
#   - auto_dispatcher.py의 hive_tasks 기록 기능과 연동하여 대시보드 표시 완성
# [2026-03-16] - Claude (PostgreSQL 커넥션 풀 추가)
#   - 매 쿼리마다 psycopg2.connect() 호출하던 방식 → 모듈 레벨 커넥션 풀(최대 5개) 재사용
#   - _get_pg_conn() / _return_pg_conn(): 스레드 안전 풀 관리 (threading.Lock)
#   - 끊어진 연결(OperationalError) 자동 감지 후 폐기 → 다음 호출 시 새 커넥션 생성
#   - run_pg_sql, run_pg_sql_csv 양쪽 모두 풀 적용
# [2026-03-16] - Claude (포트 충돌 근본 수정 v3.7.78)
#   - HTTP/WS 포트: 슬롯 기반 고정값 → 바인딩 테스트 후 실패 시 _find_free_port 대체 탐색
#   - 원인: 서로 다른 프로젝트(dev/installer)가 각자 slot 0 → 둘 다 HTTP:9000 충돌
#   - 인스턴스 락 포트(_BASE_PORT)는 프로젝트 해시별 고유라 교차 방지 안 됨
# [2026-03-12] - Claude (지식 그래프 연결선 자동 생성)
#   - thought_to_pg(): parent_id 미지정 시 같은 에이전트 직전 thought를 자동 부모로 연결
#     → hive_bridge.py 새 프로세스 호출마다 체인이 끊기던 근본 원인 수정
#   - _backfill_thought_parent_ids(): 서버 기동 시 기존 고아 노드 소급 연결
# [2026-03-13] - Claude (B안 통합 — kanban_board.py 제거)
#   - /api/kanban/launch: kanban_board.py(PySide6 네이티브) → dashboard_window.py kanban 탭으로 변경
#   - frozen 모드: vibe-kanban.exe → vibe-dashboard.exe <port> kanban 으로 통일
#   - React TaskBoardPanel(?kanban=1)이 동일 API 사용 → 두 창 데이터 불일치 해소
# [2026-03-12] - Claude (배포 서브창 EXE 런처 수정 — A안)
#   - /api/dashboard/launch, /api/kanban/launch, /api/graph/launch:
#     frozen(배포) 모드에서 Python 스크립트 서브프로세스 대신
#     vibe-dashboard.exe / vibe-kanban.exe / vibe-graph.exe 직접 실행
#   - 개발(dev) 모드는 기존 Python 스크립트 방식 유지
# [2026-03-11] - Claude (지식 그래프 연결선 수정)
#   - thought_to_pg: parent_id 파라미터 추가 + RETURNING id로 신규 노드 id 반환
#   - /api/hive/thought/pg: parent_id 수신 + 응답에 id 포함
# [2026-03-11] - Claude (배포 버전 PostgreSQL 자동 시작/경로 수정)
#   - PG_BIN: frozen 모드에서 {exe 디렉터리}\pgsql\bin\psql.exe 로 수정
#   - ensure_postgres_running(): 배포 버전 최초 실행 시 initdb + pg_ctl start 자동 수행
#   - 서버 기동 시 ensure_postgres_running() 호출하여 PG 자동 초기화/시작
# [2026-03-11] - Claude (frozen EXE 무한 창 생성 버그 수정 v3.7.47)
#   - run_watchdog/run_telegram_bridge 등: sys.executable → _python_runner_cmds()[0]
#   - frozen 모드에서 sys.executable = EXE 자신이므로 subprocess 실행 시 EXE가 무한 재귀 생성되던 버그
#   - Python 인터프리터 미탐색 시 해당 데몬 스킵(경고 출력)
# [2026-03-08] - Claude (칸반 네이티브 창 실행 API 추가)
#   - POST /api/kanban/launch: PySide6 kanban_board.py를 서브프로세스로 실행
#     → window.open() 브라우저 창 대신 OS 네이티브 데스크톱 창으로 열림
# [2026-03-05] - Claude (모듈 분리 — 데드 코드 639줄 제거)
#   - /api/git/status, /api/git/log: git_api 위임 중복 직접 구현 제거
#   - /api/memory, /api/project-info: memory_api 위임 중복 구현 제거
#   - /api/context-usage, /api/antigravity-context-usage, /api/local-models: hive_api 중복 제거
#   - /api/hive/activity: 데드 코드 제거 + hive_api.py에 핸들러 추가 (실제 동작 버그 수정)
#   - /api/hive/logs, /api/hive/health, /api/skill-results: 중복 제거
#   - server.py 4396줄 → 3757줄 (-639줄)
# [2026-03-04] - Claude (PTY 터미널 자율 에이전트 자동 트리거)
#   - read_from_ws()에 입력 버퍼 + Enter 인터셉션 추가
#   - Antigravity 터미널: Enter 입력 시 cli_agent.py 자동 백그라운드 라우팅
#   - Claude 터미널: UserPromptSubmit 훅(hook_bridge.py) 중복 방지로 PTY 인터셉션 스킵
#   - _ws_init_done 플래그: 세션 시작 직후 자동 주입 명령(set TERMINAL_ID 등) 무시
# [2026-03-04] - Claude (CLI 오케스트레이터 자율 에이전트 통합)
#   - api.agent_api 임포트 추가
#   - /api/events/agent SSE 엔드포인트 추가 (cli_agent 출력 실시간 스트리밍)
#   - do_GET, do_POST에 /api/agent/* 라우팅 추가
# [2026-03-04] - Claude (SSE 중간 멈춤 버그 수정 v3 — 브로드캐스트 워커 중복 기동 제거)
#   - _agent_broadcast_worker를 두 곳에서 시작하던 중복 코드 제거
#     → 두 워커가 동일 cli_agent._output_queue를 경쟁 소비 → 이벤트가 분산되어 클라이언트 미전달
#   - 4094~4099 블록에서 한 번만 시작하도록 수정
# [2026-03-04] - Claude (SSE 중간 멈춤 버그 수정 v2 — 브로드캐스트 워커 활성화)
#   - _agent_broadcast_worker 스레드를 서버 시작 시 시작하도록 수정
#     → 이전에는 함수 정의만 있고 스레드가 시작 안 됨 → AGENT_CLIENTS에 아무것도 없어 이벤트 소실
#   - SSE 핸들러: per-client Queue 방식으로 완전 전환 (직접 큐 읽기 제거)
# [2026-03-04] - Claude (SSE 중간 멈춤 버그 수정 v1)
#   - /api/events/agent: settimeout(1.0) 제거 — Queue.get()과 소켓 타임아웃이
#     겹쳐 빠른 출력 시 socket.timeout이 except Exception에 걸려 연결 강제 종료됨
#   - queue.Empty와 소켓 오류를 별도 except로 분리하여 정확한 에러 처리
# [2026-03-01] - Claude (배포 버전 경로 버그 수정 — 스킬/MCP 인식 안 됨)
#   - _current_project_root() 헬퍼 추가: config.json last_path 우선 참조
#     → 배포 버전에서 PROJECT_ROOT가 exe 폴더/임시폴더로 잘못 설정되던 문제 해소
#   - /api/hive/health: PROJECT_ROOT → _current_project_root() 교체
#   - /api/superpowers/status: PROJECT_ROOT → _current_project_root() 교체
#   - /api/superpowers/install|uninstall: PROJECT_ROOT → _current_project_root() 교체
#   - /api/config/update: last_path 변경 시 projects.json 동기화 (다음 시작 시 정확한 PROJECT_ROOT)
# [2026-03-01] - Claude (콘솔 창 깜빡임 전면 수정)
#   - /api/copy-path: 클립보드 복사 시 PowerShell 콘솔 창 방지 (CREATE_NO_WINDOW + -WindowStyle Hidden)
#   - /api/hive/health/repair: watchdog --check subprocess 콘솔 창 방지
#   - /api/ollama/status: wmic(RAM), nvidia-smi(GPU) subprocess 콘솔 창 방지
#   - run_watchdog(): 워치독 데몬 Popen 콘솔 창 방지
# [2026-03-01] - Claude (Gemini 세션 감지 기능)
#   - pty_handler: Antigravity/Claude 세션 시작 시 session_logs에 즉시 기록 ("세션 시작 ───")
#   - pty_handler: 세션 종료 시 원인 구분 (PTY 프로세스 종료 vs WebSocket 연결 끊김)
#   - 강제 종료(SessionEnd 미실행) 시 "프로세스 종료 감지" 로그 자동 생성
# [2026-02-28] - Claude (배포 버전 경로 버그 수정)
#   - _load_task_logs_into_thoughts(): DATA_DIR 미정의 시점에 frozen 모드 APPDATA 경로 사용
#   - 기존 Path(__file__).parent/'data' → frozen 여부 판별 후 올바른 데이터 디렉토리 참조
# [2026-02-28] - Gemini-1 (서버 안정성 및 자가 치유 패치)
#   - 터미널 인코딩 오류(UnicodeEncodeError) 방지를 위해 stdout/stderr UTF-8 강제 설정.
#   - 좀비 스레드 누수 방지를 위한 전역 소켓 타임아웃(60s) 및 SSE 개별 타임아웃 적용.
#   - SSE /stream, /api/events/thoughts, /api/events/fs 루프의 연결 해제 감지 로직 강화.
# [2026-02-27] - Claude (새 기능)
#   - _parse_antigravity_session(): Antigravity 세션 JSON 파일 토큰 파서 추가
#   - /api/antigravity-context-usage 엔드포인트 추가
# [2026-02-26] - Claude (버그 수정)
...
# ... 기존 내용 유지 ...

import sys

# ─────────────────────────────────────────────────────────────────────────────
# 🎯 'hook' 서브커맨드 빠른 경로 — 무거운 서버 import 전에 분기
# ─────────────────────────────────────────────────────────────────────────────
# 설치 EXE 단독 PC에서도 외부 프로젝트가 `vibe-coding.exe hook`만 호출하면
# scripts/hive_hook.py main()이 stdin JSON을 받아 PreToolUse/PostToolUse/Stop/
# UserPromptSubmit 이벤트를 처리한다. 서버 부트(PostgreSQL, API 모듈 로드 등)
# 없이 즉시 디스패치하므로 매 훅 호출당 startup 비용이 수 초→수십 ms 수준으로 축소.
# (개발 모드/설치 EXE 양쪽 모두 동일하게 동작)
if len(sys.argv) > 1 and sys.argv[1] == 'hook':
    import os as _os_hook
    from pathlib import Path as _Path_hook
    if getattr(sys, 'frozen', False):
        _hook_base = _Path_hook(getattr(sys, '_MEIPASS', _os_hook.path.dirname(sys.executable)))
        _hook_scripts = _hook_base / 'scripts'
    else:
        _hook_base = _Path_hook(__file__).resolve().parent
        _hook_scripts = _hook_base.parent / 'scripts'
    # hive_hook이 `from src.xxx`/`from infra.xxx` import 가능하도록 base 추가
    for _p in (str(_hook_scripts), str(_hook_base)):
        if _p not in sys.path:
            sys.path.insert(0, _p)
    # windowed EXE(--noconsole)에서 stdout/stderr가 None이면 hive_hook의 print()가 터짐 → devnull 폴백
    # (부모 프로세스가 pipe로 연결한 경우엔 valid file이라 그대로 사용됨)
    if sys.stdout is None:
        sys.stdout = open(_os_hook.devnull, 'w', encoding='utf-8')
    if sys.stderr is None:
        sys.stderr = open(_os_hook.devnull, 'w', encoding='utf-8')
    try:
        from hive_hook import main as _hive_hook_main
        _hive_hook_main()
        sys.exit(0)
    except Exception as _hook_err:
        # 훅 자체가 사용자 작업을 차단하면 안 됨 — 조용히 종료
        try:
            sys.stderr.write(f"[hook dispatch error] {_hook_err}\n")
        except Exception:
            pass
        sys.exit(0)

import json
import time
import os
import mimetypes
import webbrowser
import shutil
import subprocess
import re
import threading
import asyncio
import api.git_api as git_api
import api.memory_api as memory_api
import api.agent_api as agent_api
import api.pty_api as pty_api
import api.vibe_api as vibe_api
import api.tasks_api as tasks_api
import api.files_api as files_api
import api.zettel_api as zettel_api
import api.vibe_skills_api as vibe_skills_api
# [2026-04-13] office_api 직접 호출 제거 — 오피스 서버로 프록시 전환
import api.office_api as office_api
import api.experience_api as experience_api
import api.codegraph_api as codegraph_api
import api.telegram_api as telegram_api
import api.update_api as update_api
import api.install_api as install_api
import api.events_api as events_api
import api.heal_api as heal_api
import api.locks_api as locks_api
import api.projects_api as projects_api
import api.message_api as message_api
import api.launch_api as launch_api
import api.commands_api as commands_api
import api.config_api as config_api
import string
import socket
from collections import deque
from pathlib import Path
from src.file_store import (
    delete_memory_entry,
    ensure_legacy_store,
    get_memory_entry,
    merge_memory_files,
    upsert_memory_entry,
)
from src.pg_store import (
    ensure_schema,
    get_memory,
    list_memory,
    list_tasks,
    query_rows,
    save_task,
    set_memory,
    update_task,
    delete_task,
    # Paperclip 스타일 오케스트레이션 함수
    add_task_comment,
    list_task_comments,
    atomic_checkout,
    release_checkout,
    list_agent_status,
    trigger_agent,
    record_heartbeat,
    insert_pg_log,
)

# ── PostgreSQL 18 연동 헬퍼 (Postgres-First 고도화) ─────────────────────────
# frozen(배포) 모드: exe 옆의 pgsql\ 폴더 (installer가 설치)
# 개발 모드: 소스 트리 내 .ai_monitor/bin/pgsql/
if getattr(sys, 'frozen', False):
    _PG_DIR = Path(sys.executable).resolve().parent / "pgsql"
else:
    _PG_DIR = Path(__file__).resolve().parent / "bin" / "pgsql"

PG_BIN     = _PG_DIR / "bin" / "psql.exe"
PG_CTL_BIN = _PG_DIR / "bin" / "pg_ctl.exe"
INITDB_BIN = _PG_DIR / "bin" / "initdb.exe"
PG_PORT = int(os.environ.get('VIBE_PG_PORT', '5433'))

# ── 프로젝트별 PostgreSQL 데이터베이스 이름 ──
# [2026-03-22] 프로젝트별 DB 분리: 하나의 PG 인스턴스에서 프로젝트마다 별도 DB를 사용.
# PROJECT_ID가 확정된 뒤 _init_project_db()에서 실제 DB를 생성하고 PG_PROJECT_DB를 갱신.
# 초기값은 'postgres' (DB 생성 전 ensure_postgres_running 등에서 사용).
PG_PROJECT_DB: str = "postgres"

# ── PostgreSQL 커넥션 풀은 src/pg_store.py로 이관 (단계 8a) ────────────────
# [2026-04-21] server.py L208~252의 다중 DB 풀 함수 4개를 pg_store에 흡수.
# lifecycle.cleanup_postgres가 `_pg_pool`/`_pg_pool_lock`을 인자로 받으므로
# 이름 alias로 재노출하여 호출부(L3980)의 시그니처를 유지한다.
from src import pg_store as _pg_store_mod
_pg_pool = _pg_store_mod._pool
_pg_pool_lock = _pg_store_mod._pool_lock


def _get_pg_conn(db: str = "postgres"):
    return _pg_store_mod.get_pool_conn(db)


def _return_pg_conn(conn, db: str = "postgres") -> None:
    _pg_store_mod.return_pool_conn(conn, db)

# DB 데이터: %APPDATA%\VibeCoding\pgdata (배포/개발 모두 동일)
# [2026-04-05 Claude] 개발 모드에서 소스 트리 내 data/ 사용 시 PG 버전 불일치 문제 발생
# → 배포/개발 모두 %APPDATA% 경로로 통일하여 바이너리 업그레이드 시 충돌 방지
_PG_DATA_DIR = Path(os.getenv('APPDATA', '')) / "VibeCoding" / "pgdata"


# ── PG 런타임은 infra/postgres_runtime.py로 이관 (단계 8b) ────────────────
# [2026-04-21] server.py L230~536 (ensure_postgres_running + _init_project_db)
# 블록 분리. PG_PORT/PG_PROJECT_DB 글로벌 mutation은 caller 래퍼가 담당.
from infra import postgres_runtime as _postgres_runtime


def ensure_postgres_running() -> None:
    """PG 기동 + 공용 스키마 초기화. PG_PORT 글로벌을 갱신한다."""
    global PG_PORT
    PG_PORT = _postgres_runtime.start_server(
        PG_CTL_BIN, INITDB_BIN, _PG_DATA_DIR, PG_PORT
    )
    os.environ['VIBE_PG_PORT'] = str(PG_PORT)
    if not PG_CTL_BIN.exists():
        return  # 개발/미설치 환경은 스키마 배치 스킵
    try:
        import time as _schema_time
        _schema_start = _schema_time.monotonic()
        run_pg_sql(_postgres_runtime.BOOTSTRAP_SCHEMA_SQL)
        _schema_ms = (_schema_time.monotonic() - _schema_start) * 1000
        print(f"[PG] 스키마 및 확장 초기화 완료 ({_schema_ms:.0f}ms)")
    except Exception as e:
        print(f"[PG] 스키마 초기화 오류: {e}")


def _init_project_db(project_id: str) -> None:
    """프로젝트 DB 생성 + pg_store 전파. PG_PROJECT_DB 글로벌을 갱신한다."""
    global PG_PROJECT_DB
    from src.pg_store import set_project_db as _set_project_db
    PG_PROJECT_DB = _postgres_runtime.create_project_db(
        project_id, run_pg_sql, _set_project_db
    )


def run_pg_sql(sql: str, params: tuple = None, db: str = None):
    """PostgreSQL SQL 실행. psycopg2 우선, 미설치 시 psql.exe subprocess 폴백.

    params를 지정하면 parameterized query로 실행 (SQL 인젝션 방지).
    psycopg2: %s placeholder, psql 폴백: params가 있으면 psycopg2.sql.SQL로 렌더링 후 전달.
    db=None이면 PG_PROJECT_DB(프로젝트별 DB)를 사용.
    """
    if db is None:
        db = PG_PROJECT_DB
    # psycopg2 커넥션 풀 사용 (매번 connect 대신 재사용하여 오버헤드 제거)
    try:
        import psycopg2
        conn = _get_pg_conn(db)
        try:
            with conn.cursor() as cur:
                cur.execute(sql, params)
                try:
                    rows = cur.fetchall()
                    # psql 텍스트 출력과 호환되는 형식으로 반환 (RETURNING id 등)
                    result = '\n'.join(str(row[0]) for row in rows)
                    _return_pg_conn(conn, db)
                    return result
                except Exception as e:
                    _return_pg_conn(conn, db)
                    return ''  # 결과 없음 허용 (INSERT/UPDATE 등 반환값 없는 SQL)
        except (psycopg2.OperationalError, psycopg2.InterfaceError):
            # 커넥션 끊김 — 폐기하고 에러로 처리 (다음 호출 시 새 커넥션 생성됨)
            try:
                conn.close()
            except Exception:
                pass
            print(f"[Postgres psycopg2 ERROR] 커넥션 끊김, 폐기 후 재시도 필요")
            return None
        except Exception as e:
            # 쿼리 에러 — 커넥션 자체는 살아있을 수 있으므로 풀에 반환
            _return_pg_conn(conn, db)
            print(f"[Postgres psycopg2 ERROR] {e}")
            return None
    except ImportError:
        pass  # psycopg2 없으면 subprocess 폴백
    except Exception as e:
        print(f"[Postgres psycopg2 ERROR] {e}")
        return None
    # psql.exe subprocess 폴백 — params가 있으면 수동 이스케이프 (psql은 parameterized 미지원)
    if params:
        def _pg_escape(v):
            if v is None:
                return 'NULL'
            s = str(v).replace("'", "''")
            return f"'{s}'"
        sql = sql.replace('%s', '{}').format(*[_pg_escape(p) for p in params])
    if not PG_BIN.exists():
        return None
    try:
        _no_window = getattr(subprocess, 'CREATE_NO_WINDOW', 0x08000000)
        res = subprocess.run(
            [str(PG_BIN), "-p", str(PG_PORT), "-U", "postgres", "-d", db, "-c", sql],
            capture_output=True, text=True, encoding='utf-8', errors='replace',
            creationflags=_no_window
        )
        return res.stdout.strip()
    except Exception as e:
        print(f"[Postgres ERROR] {e}")
        return None

_pgmq_available: bool | None = None  # pgmq 확장 존재 여부 캐시 — 한 번 확인 후 재확인 안 함

def log_to_pg(agent: str, terminal_id: str, task: str, status: str = "success"):
    """pg_logs 테이블에 로그 기록 — parameterized query로 SQL 인젝션 방지"""
    run_pg_sql(
        "INSERT INTO pg_logs (agent, terminal_id, task, status, project_id) VALUES (%s, %s, %s, %s, %s);",
        (agent, terminal_id, task, status, PROJECT_ID)
    )
    # PGMQ 확장이 설치된 경우에만 큐 전송 — 없으면 무시 (무한 에러 방지)
    global _pgmq_available
    if _pgmq_available is False:
        return
    if _pgmq_available is None:
        # 최초 1회만 pgmq 스키마 존재 확인
        check = run_pg_sql("SELECT 1 FROM pg_namespace WHERE nspname = 'pgmq';")
        _pgmq_available = bool(check and check.strip())
        if not _pgmq_available:
            print("[log_to_pg] pgmq 확장 미설치 — PGMQ 큐 전송 비활성화")
            return
    mq_msg = json.dumps({"agent": agent, "tid": terminal_id, "task": task, "status": status}, ensure_ascii=False)
    run_pg_sql("SELECT pgmq.send('hive_queue', %s::jsonb);", (mq_msg,))

def thought_to_pg(agent: str, skill: str, thought: dict, parent_id: int = None, project_id: str = None) -> int:
    """[2026-03-22] 지식그래프 제거됨 — 호출부 호환을 위해 no-op 스텁 유지."""
    return 0

def run_pg_sql_csv(sql: str, params: tuple = None, db: str = None) -> list:
    """Postgres 쿼리 결과를 dict 리스트로 반환. psycopg2 우선, 없으면 psql --csv 폴백.

    params를 지정하면 parameterized query로 실행 (SQL 인젝션 방지).
    db=None이면 PG_PROJECT_DB(프로젝트별 DB)를 사용.
    """
    if db is None:
        db = PG_PROJECT_DB
    # psycopg2 커넥션 풀 사용 (RealDictCursor로 dict 반환)
    try:
        import psycopg2
        import psycopg2.extras
        conn = _get_pg_conn(db)
        try:
            with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
                cur.execute(sql, params)
                result = [dict(row) for row in cur.fetchall()]
                _return_pg_conn(conn, db)
                return result
        except (psycopg2.OperationalError, psycopg2.InterfaceError):
            # 커넥션 끊김 — 폐기 (다음 호출 시 새 커넥션 생성됨)
            try:
                conn.close()
            except Exception:
                pass
            print(f"[Postgres psycopg2 CSV ERROR] 커넥션 끊김, 폐기")
            return []
        except Exception as e:
            _return_pg_conn(conn, db)
            print(f"[Postgres psycopg2 CSV ERROR] {e}")
            return []
    except ImportError:
        pass
    except Exception as e:
        print(f"[Postgres psycopg2 CSV ERROR] {e}")
        return []
    # psql.exe --csv 폴백 — params가 있으면 수동 이스케이프
    if params:
        def _pg_escape(v):
            if v is None:
                return 'NULL'
            s = str(v).replace("'", "''")
            return f"'{s}'"
        sql = sql.replace('%s', '{}').format(*[_pg_escape(p) for p in params])
    if not PG_BIN.exists():
        return []
    try:
        _no_window = getattr(subprocess, 'CREATE_NO_WINDOW', 0x08000000)
        res = subprocess.run(
            [str(PG_BIN), "-p", str(PG_PORT), "-U", "postgres", "-d", db, "--csv", "-c", sql],
            capture_output=True, text=True, encoding='utf-8', errors='replace',
            creationflags=_no_window
        )
        import csv, io
        return list(csv.DictReader(io.StringIO(res.stdout.strip())))
    except Exception as e:
        print(f"[Postgres CSV ERROR] {e}")
        return []

# ─────────────────────────────────────────────────────────────────────────────

# [수정] 오케스트레이터 스킬 체인 모듈 전역 임포트 (scripts 폴더)
_SCRIPTS_DIR = str(Path(__file__).resolve().parent.parent / "scripts")
if _SCRIPTS_DIR not in sys.path:
    sys.path.insert(0, _SCRIPTS_DIR)
try:
    import skill_orchestrator
except ImportError:
    skill_orchestrator = None

# Windows 터미널(CP949 등)에서 이모지/한글 출력 시 UnicodeEncodeError 방지
if sys.stdout and sys.stdout.encoding and sys.stdout.encoding.lower() not in ("utf-8", "utf8"):
    try:
        import io
        sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8', errors='replace')
        sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding='utf-8', errors='replace')
    except Exception as e:
        pass  # stdout/stderr UTF-8 래핑 실패 — 원본 스트림 유지

# [수정] pythonw.exe로 실행 시(터미널 없음) 에러 로그를 파일로 기록하도록 개선
if sys.stdout is None or sys.stderr is None:
    try:
        # DATA_DIR 정의 전이므로 임시 경로 사용 후 아래에서 재지정 가능성 검토
        _log_p = Path(__file__).resolve().parent / "server.log"
        _f = open(_log_p, "a", encoding="utf-8")
        sys.stdout = _f
        sys.stderr = _f
        print(f"\n--- Server Started (Log Redirected) at {time.strftime('%Y-%m-%d %H:%M:%S')} ---")
    except Exception as e:
        pass  # stdout/stderr 리다이렉트 실패 — 터미널 없는 환경에서 로깅 불가

# 전역 소켓 타임아웃 제거 (SSE 등 장기 연결 방해 요소)
# socket.setdefaulttimeout(60)  <-- 제거됨

# BASE_DIR: 개발 모드 → server.py 위치, 배포(frozen) 모드 → sys._MEIPASS
# PROJECT_ROOT: 개발 모드 → git 루트, 배포 모드 → cwd/exe-parent에서 마커 탐색,
#               마커 부재 시 %APPDATA%\VibeCoding\{projects.json,config.json} fallback
def _find_project_root_marker(start: Path) -> Path | None:
    """start와 상위 디렉토리에서 .git/CLAUDE.md/GEMINI.md 마커 탐색.
    찾으면 마커가 있는 디렉토리, 없으면 None.
    """
    try:
        cur = start.resolve()
    except Exception:
        return None
    for _ in range(10):
        if any((cur / m).exists() for m in ('.git', 'CLAUDE.md', 'GEMINI.md')):
            return cur
        if cur.parent == cur:
            break
        cur = cur.parent
    return None


def _resolve_frozen_project_root(exe_parent: Path) -> Path:
    """[회귀 수정] 설치 EXE의 PROJECT_ROOT 결정.
    1) cwd 마커 탐색 → 사용자가 프로젝트 폴더에서 실행한 경우
    2) exe_parent 마커 탐색 → 설치 폴더에 마커가 있는 경우(거의 없음)
    3) %APPDATA%\\VibeCoding\\config.json.last_path
    4) %APPDATA%\\VibeCoding\\projects.json[0]
    5) 최종 폴백: exe_parent (잘못된 PROJECT_ID 발생 가능)
    """
    found = _find_project_root_marker(Path.cwd())
    if found is not None:
        return found
    found = _find_project_root_marker(exe_parent)
    if found is not None:
        return found
    if os.name == 'nt':
        _appdata = Path(os.getenv('APPDATA', '')) / 'VibeCoding'
    else:
        _appdata = Path.home() / '.vibe-coding'
    try:
        cfg_file = _appdata / 'config.json'
        if cfg_file.exists():
            cfg = json.loads(cfg_file.read_text(encoding='utf-8'))
            lp = cfg.get('last_path', '')
            if lp and Path(lp).is_dir():
                return Path(lp)
    except Exception:
        pass
    try:
        projs_file = _appdata / 'projects.json'
        if projs_file.exists():
            saved = json.loads(projs_file.read_text(encoding='utf-8'))
            if isinstance(saved, list) and saved:
                first = Path(str(saved[0]).replace('/', os.sep))
                if first.is_dir():
                    return first
    except Exception:
        pass
    return exe_parent


if getattr(sys, 'frozen', False):
    BASE_DIR = Path(sys._MEIPASS)
    PROJECT_ROOT = _resolve_frozen_project_root(Path(sys.executable).resolve().parent)
else:
    BASE_DIR = Path(__file__).resolve().parent
    _parent = BASE_DIR.parent
    if 'site-packages' in str(_parent):
        PROJECT_ROOT = Path.home()
    else:
        PROJECT_ROOT = _parent


# ── 런타임 보조 유틸 — infra/runtime.py로 분리 (2026-04-20) ──────────────────────
# 무상태 함수는 infra/runtime.py로 옮기고, BASE_DIR/PROJECT_ROOT 글로벌을 바인딩하는
# 얇은 래퍼만 server.py에 남김.
from infra import runtime as _runtime


def _soft_src_dir() -> Path:
    """경량 소스 업데이트 채널(boot.py A안)이 관리하는 앱 소스 체크아웃 루트.
    [불변식] PROJECT_ROOT(=사용자 작업 프로젝트)와 다르다. boot.py가 runpy로 실행하면
      이 파일(__file__)은 SRC/.ai_monitor/server.py 이므로 parent.parent = SRC(관리 체크아웃).
      soft_updater는 이 디렉토리에 git fetch/reset 한다.
    """
    return Path(__file__).resolve().parent.parent


def _python_runner_cmds() -> list[str]:
    return _runtime.python_runner_cmds(BASE_DIR, PROJECT_ROOT)


def _project_python_runner_cmds(project_root: Path | None = None) -> list[str]:
    return _runtime.project_python_runner_cmds(BASE_DIR, PROJECT_ROOT, project_root)


def _resolve_playwright_install_script() -> Path | None:
    return _runtime.resolve_playwright_install_script(BASE_DIR, PROJECT_ROOT)


def _open_folder_dialog_subprocess() -> str:
    # EXE 빌드에서 sys.executable은 vibe-coding.exe → 실제 Python을 인자로 전달
    return _runtime.open_folder_dialog_subprocess(_python_runner_cmds()[0])

# [제거됨 2026-03-22] websockets import → Node.js ws 라이브러리로 대체

# 전역 상태 관리
main_window = None  # pywebview 창 핸들 — main()에서 초기화, SSEHandler에서 참조
THOUGHT_LOGS = [] # AI 사고 과정 로그 (최근 50개 유지)
# THOUGHT_CLIENTS는 아래(라인 658 근처)에서 한 번만 선언 — 중복 선언 제거

def _load_task_logs_into_thoughts():
    """서버 시작 시 task_logs.jsonl의 최근 20개 항목을 THOUGHT_LOGS에 미리 로드합니다.
    이렇게 해야 클라이언트 접속 즉시 과거 작업 내역이 사고 패널에 표시됩니다.

    [경로 주의] DATA_DIR는 이 함수가 호출되는 시점(서버 코드 상단)에 아직 정의되지 않으므로,
    frozen(배포) 모드와 개발 모드를 직접 판별하여 올바른 데이터 디렉토리를 사용합니다.
    - frozen 모드: %APPDATA%\\VibeCoding (Windows) / ~/.vibe-coding (기타)
    - 개발 모드 : server.py 위치 기준 ./data/
    """
    _self = Path(__file__).resolve()
    _early_data_dir = _self.parent / 'data'
    log_path = _early_data_dir / 'task_logs.jsonl'
    if not log_path.exists():
        return
    try:
        lines = [l.strip() for l in log_path.read_text(encoding='utf-8').splitlines() if l.strip()]
        recent = lines[-20:] # 최근 20개만 로드
        for line in recent:
            try:
                obj = json.loads(line)
                THOUGHT_LOGS.append({
                    'agent':     obj.get('agent', 'System'),
                    'thought':   obj.get('task', ''),
                    'tool':      None,
                    'timestamp': obj.get('timestamp', ''),
                    'level':     'info',
                })
            except Exception as e:
                pass  # 개별 task_log 항목 파싱 실패 허용
        print(f"[*] ThoughtTrace: {len(recent)}개 task_logs 항목 사전 로드 완료")
    except Exception as e:
        print(f"[!] ThoughtTrace 사전 로드 실패: {e}")

# [v3.7.62 수정] 모듈 레벨 즉시 실행 → 서버 시작 후 백그라운드 스레드로 이동.
# 기존: server.py import 시 파일 IO가 즉시 발생 → 창 뜨기 전에 블로킹.
# 수정: HTTP 서버 시작 후 _schedule_thought_preload()로 호출됨.

# --- 파일 시스템 실시간 감시 (Watchdog) — 본체는 infra/fs_watcher.py ----------
FS_CLIENTS = set() # SSE 클라이언트 연결 세트
THOUGHT_CLIENTS = set() # 사고 과정 SSE 클라이언트 연결 세트
# 자율 에이전트 SSE: 클라이언트별 개별 Queue 세트 (브로드캐스트 방식)
# 단일 Queue 방식은 다중 연결 시 이벤트를 한 클라이언트만 소비하는 버그가 있어 교체
AGENT_CLIENTS: set = set()
# SSE 클라이언트 set 접근 시 thread safety 보장 — 다중 스레드에서 동시 add/discard 시
# RuntimeError: set changed size during iteration 방지
_SSE_LOCK = threading.Lock()


# ── FS 감시 + 에이전트 브로드캐스트 — infra/fs_watcher.py로 분리 (2026-04-20) ────
# Handler/Worker 본체는 infra/fs_watcher.py로 옮기고, SSE 글로벌 상태(FS_CLIENTS,
# AGENT_CLIENTS, _SSE_LOCK, DATA_DIR)를 바인딩하는 얇은 래퍼만 server.py에 남김.
from infra import fs_watcher as _fs_watcher
# Observer / FileSystemEventHandler — 다른 코드(데몬 등)에서 server 모듈 통해
# 참조할 수 있어 호환성 유지를 위해 재노출
Observer = _fs_watcher.Observer
FileSystemEventHandler = _fs_watcher.FileSystemEventHandler


def _agent_broadcast_worker():
    _fs_watcher.agent_broadcast_worker(AGENT_CLIENTS, _SSE_LOCK)


def start_fs_watcher(root_path):
    return _fs_watcher.start_fs_watcher(root_path, FS_CLIENTS, _SSE_LOCK, DATA_DIR)
# ----------------------------------------------

# [제거됨 2026-03-22] winpty/pywinpty → Node.js node-pty 마이크로서비스로 대체
# winpty DLL 로딩 코드 및 PtyProcess import 제거

from datetime import datetime
from pathlib import Path
from http.server import BaseHTTPRequestHandler, HTTPServer
from socketserver import ThreadingMixIn
from urllib.parse import urlparse, parse_qs, urlencode
import urllib.request
# 버전 로드: 파일 경로 기반으로 일원화.
# 과거 `from _version import __version__` 방식은 PyInstaller frozen 환경에서
# sys.modules/sys.path 상태에 따라 다른 '_version' 모듈과 충돌하거나
# ModuleNotFoundError가 발생할 수 있어 v3.7.207부터 파일 읽기만 사용.
__version__ = "0.0.0-unknown"
import re as _re_ver
_this_dir = os.path.dirname(os.path.abspath(__file__))
_version_candidates = [
    # frozen(PyInstaller): MEIPASS 루트 (spec의 ('.ai_monitor/_version.py', '.') 대상)
    os.path.join(getattr(sys, '_MEIPASS', ''), '_version.py'),
    # 개발 모드: server.py와 같은 디렉토리 (.ai_monitor/_version.py)
    os.path.join(_this_dir, '_version.py'),
    # 폴백: 상위 디렉토리 (일부 설치 레이아웃)
    os.path.join(_this_dir, '..', '_version.py'),
]
for _candidate in _version_candidates:
    try:
        if _candidate and os.path.isfile(_candidate):
            with open(_candidate, 'r', encoding='utf-8') as _vf:
                _m = _re_ver.search(r'__version__\s*=\s*["\']([^"\']+)["\']', _vf.read())
                if _m:
                    __version__ = _m.group(1)
                    break
    except Exception:
        continue
if __version__ == "0.0.0-unknown":
    # 진단: 모든 후보가 실패하면 stderr에 경로 덤프 (EXE 로그에서 확인)
    print(f"[version] WARN: _version.py 로딩 실패. frozen={getattr(sys, 'frozen', False)} "
          f"MEIPASS={getattr(sys, '_MEIPASS', '(none)')} __file__={__file__}",
          file=sys.stderr)

# 데이터 디렉토리: 배포 모드 → %APPDATA%\VibeCoding, 개발 모드 → .ai_monitor/data
if getattr(sys, 'frozen', False):
    if os.name == 'nt':
        DATA_DIR = Path(os.getenv('APPDATA', '')) / "VibeCoding"
    else:
        DATA_DIR = Path.home() / ".vibe-coding"
else:
    DATA_DIR = BASE_DIR / "data"
os.makedirs(DATA_DIR, exist_ok=True)

# [자가 치유 2.0 ④] 임베딩 모델 캐시를 DATA_DIR 하위로 고정
# [WHY] fastembed 기본 캐시는 %TEMP%\fastembed_cache — Temp 정리 시 ~100MB 모델이
# 증발해 매번 재다운로드. 이미 설정된 env(사용자 지정)는 존중한다.
os.environ.setdefault('VIBE_EMBED_CACHE', str(DATA_DIR / 'embed_cache'))

# 전역 Obsidian Vault — 모든 프로젝트가 공유하는 단일 vault
if os.name == 'nt':
    GLOBAL_VAULT_DIR = Path(os.getenv('APPDATA', str(Path.home()))) / 'VibeCoding' / 'vault'
else:
    GLOBAL_VAULT_DIR = Path.home() / '.vibe-coding' / 'vault'

# 스크립트 디렉토리 — 개발: PROJECT_ROOT/scripts, 배포(frozen): BASE_DIR/scripts
_scripts_candidate = PROJECT_ROOT / 'scripts'
if not _scripts_candidate.exists():
    _scripts_candidate = BASE_DIR / 'scripts'
SCRIPTS_DIR = _scripts_candidate if _scripts_candidate.exists() else None
# Claude Code 프로젝트 디렉터리 명명 규칙(: 제거, /·\ → --) 과 동일하게 인코딩
_proj_raw = str(PROJECT_ROOT).replace('\\', '/').replace(':', '').replace('/', '--')
PROJECT_ID: str = _proj_raw.lstrip('-') or 'default'   # e.g. "D--vibe-coding"

sys.path.append(str(BASE_DIR / 'src'))
# api 모듈 패키지 경로 등록
sys.path.insert(0, str(BASE_DIR))
try:
    from db import init_db
    from db_helper import insert_log, get_recent_logs, send_message, get_messages, clear_messages
except ImportError as e:
    print(f"Critical Import Error: {e}")
    # src 폴더가 없는 경우 대비하여 한 번 더 경로 확인
    sys.path.append(str(BASE_DIR))
    from src.db import init_db
    from src.db_helper import insert_log, get_recent_logs, send_message, get_messages, clear_messages

# 데이터 디렉토리 생성 보장 및 DB 초기화 (중복 제거 및 위치 조정)
init_db()

# 정적 파일 경로를 절대 경로로 고정 (404 방지 핵심!)
STATIC_DIR = (BASE_DIR / "vibe-view" / "dist").resolve()
SESSIONS_FILE = DATA_DIR / "sessions.jsonl"
LOCKS_FILE = DATA_DIR / "locks.json"
CONFIG_FILE = DATA_DIR / "config.json"
# 에이전트 간 메시지 채널 파일
MESSAGES_FILE = DATA_DIR / "messages.jsonl"
# 에이전트 간 공유 작업 큐 파일 (JSON 배열 — 업데이트/삭제 지원)
TASKS_FILE = DATA_DIR / "tasks.json"
# 프로젝트 목록 파일 (최근 사용 프로젝트 저장)
PROJECTS_FILE = DATA_DIR / "projects.json"

# 데이터 디렉토리 생성 보장
if not DATA_DIR.exists():
    os.makedirs(DATA_DIR, exist_ok=True)

# 프로젝트 목록 초기화 (없을 경우 현재 폴더의 상위 폴더를 기본으로 추가)
if not PROJECTS_FILE.exists():
    with open(PROJECTS_FILE, 'w', encoding='utf-8') as f:
        json.dump([str(Path(__file__).resolve().parent.parent).replace('\\', '/')], f)

# [2026-06-21] frozen(설치본) 프로젝트 컨텍스트 자동 고정 — 회귀 사고 방지.
# [과거사고] 설치 버전에서 하이브 마인드/제텔카스텐/태스크 패널이 통째로 비어 보이던 버그.
#   근본 원인: 설치본 config.json(%APPDATA%\VibeCoding)의 last_path가 활성 프로젝트를 안 가리키면
#   project_id가 install-dir 슬러그(phantom)로 잡혀, project_id로 필터되는 모든 데이터가 0건 조회됨.
#   (DB는 dev/설치 공유라 데이터는 D--vibe-coding로 멀쩡히 저장돼 있는데 네임스페이스만 어긋남)
# [대책] 시작 시 PROJECT_ROOT가 실제 프로젝트(.git/CLAUDE.md/GEMINI.md 마커 보유)로 해석됐으면
#   last_path를 거기에 자동 고정 + projects.json 동기화 → 프론트(FileExplorer가 /api/config last_path로
#   currentPath 설정)와 백엔드 기본 project_id가 항상 정렬됨. 마커 없는 install-dir 폴백이면
#   PROJECT_CONTEXT_UNRESOLVED 플래그를 세워 UI가 "프로젝트 선택"을 유도하도록 노출(빈 패널 미스터리 방지).
PROJECT_CONTEXT_UNRESOLVED = False

def _persist_active_project_context() -> None:
    """frozen 모드에서 해석된 PROJECT_ROOT를 last_path/projects.json에 고정한다."""
    global PROJECT_CONTEXT_UNRESOLVED
    if _find_project_root_marker(PROJECT_ROOT) is None:
        PROJECT_CONTEXT_UNRESOLVED = True
        print(
            f"[project_context] WARN: 활성 프로젝트 미해석 — PROJECT_ROOT={PROJECT_ROOT} (마커 없음). "
            "대시보드에서 프로젝트 폴더를 선택해야 하이브/제텔/태스크가 채워집니다.",
            file=sys.stderr,
        )
        return
    try:
        cfg = {}
        if CONFIG_FILE.exists():
            cfg = json.loads(CONFIG_FILE.read_text(encoding='utf-8'))
        lp = cfg.get('last_path', '')
        # last_path가 비었거나 더 이상 존재하지 않는 경로면 현재 실제 PROJECT_ROOT로 고정
        if not (lp and Path(lp).is_dir()):
            _norm = str(PROJECT_ROOT).replace('\\', '/')
            cfg['last_path'] = _norm
            CONFIG_FILE.write_text(json.dumps(cfg, ensure_ascii=False, indent=2), encoding='utf-8')
            _projs = []
            try:
                if PROJECTS_FILE.exists():
                    _projs = json.loads(PROJECTS_FILE.read_text(encoding='utf-8'))
            except Exception:
                _projs = []
            if _norm in _projs:
                _projs.remove(_norm)
            _projs.insert(0, _norm)
            PROJECTS_FILE.write_text(json.dumps(_projs[:20], ensure_ascii=False, indent=2), encoding='utf-8')
            print(f"[project_context] 활성 프로젝트 자동 고정: {_norm}", file=sys.stderr)
    except Exception as _e:
        print(f"[project_context] last_path 고정 실패: {_e}", file=sys.stderr)

if getattr(sys, 'frozen', False):
    _persist_active_project_context()

# 락 파일 초기화 (없을 경우)
if not LOCKS_FILE.exists():
    with open(LOCKS_FILE, 'w', encoding='utf-8') as f:
        json.dump({}, f)

# 메시지 채널 파일 초기화 (없을 경우)
if not MESSAGES_FILE.exists():
    MESSAGES_FILE.touch()

ensure_legacy_store(DATA_DIR)

# [2026-03-22] Postgres-backed state schema 초기화는 _init_project_db() 이후로 이동.
# 모듈 로드 시점에서는 프로젝트 DB가 아직 확정되지 않았으므로, __main__ 블록에서 호출.
# 개발 모드에서는 아래 _try_ensure_schema_dev()에서 처리.
# PG가 이미 떠있으면 바로 스키마 초기화
ensure_schema(DATA_DIR)

# [2026-04-13] 오피스 초기화는 office_server.py에서 수행 — 클래식 서버에서 제거

# [2026-03-22] 지식그래프 관련 _backfill_thought_parent_ids() 제거

# ── 메모리 워처 + 임베딩 헬퍼는 infra/memory_watcher.py로 이관 (Task 6.1) ──
# [2026-04-21] server.py L989~1378 블록 분리. 글로벌 상태(CONFIG_FILE/DATA_DIR/
# PROJECT_ID)는 얇은 래퍼로 모듈 함수에 주입한다.
from infra import memory_watcher as _memory_watcher

# Postgres 기반 메모리 스키마 초기화 (side-effect at import time)
_memory_watcher.init_memory_db(DATA_DIR)


def _legacy_memory_data_dir() -> Path:
    return _memory_watcher.legacy_memory_data_dir(CONFIG_FILE, DATA_DIR)


# MemoryWatcher 클래스는 동일 이름으로 재노출 — 기동 코드 호환성 유지
MemoryWatcher = _memory_watcher.MemoryWatcher



# ── 현재 활성 프로젝트 루트 동적 조회 ────────────────────────────────────────
# 실제 로직은 infra/project_context.py로 분리 (Phase 2-3, 2026-04-30).
# 여기엔 서버 전역 PROJECT_ROOT/CONFIG_FILE을 주입하는 얇은 래퍼만 둔다.
from infra.project_context import (
    current_project_root as _ctx_project_root,
    current_project_id as _ctx_project_id,
)


def _current_project_root() -> Path:
    """현재 활성 프로젝트 루트를 반환합니다.

    config.json의 last_path가 유효하면 우선, 없으면 시작 시 결정된 PROJECT_ROOT.
    """
    return _ctx_project_root(PROJECT_ROOT, CONFIG_FILE)


def _validate_file_path(raw_path: str) -> Path:
    """파일 경로 검증 — 경로 순회(../) 방지.

    resolve()로 심볼릭 링크/상대경로를 정규화한 후,
    현재 프로젝트 루트 또는 허용된 시스템 경로 하위인지 확인합니다.
    검증 실패 시 ValueError를 발생시킵니다.

    Returns:
        Path: 검증 완료된 절대 경로
    """
    if not raw_path:
        raise ValueError("Path is required")
    resolved = Path(raw_path).resolve()
    project_root = _current_project_root().resolve()
    # 프로젝트 루트 하위 또는 APPDATA(설정 파일) 경로 허용
    _allowed_roots = [project_root]
    _appdata = os.environ.get('APPDATA')
    if _appdata:
        _allowed_roots.append(Path(_appdata).resolve())
    if not any(str(resolved).startswith(str(r)) for r in _allowed_roots):
        raise ValueError(f"Access denied: path outside allowed directories: {resolved}")
    return resolved


# ── 요청 단위 project_id override (Phase 2-5.2) ────────────────────────────
# do_GET/POST/PUT/DELETE 진입부에서 ?project_id= 쿼리를 thread-local에 설정.
# 같은 스레드의 다음 요청 진입부에서 무조건 덮어쓰므로 finally 불필요.
_request_pid_ctx = threading.local()


def _set_request_pid(query_string: str) -> None:
    """요청 핸들러 진입부에서 호출 — 쿼리의 ?project_id=를 thread-local에 저장."""
    pid = ''
    if query_string:
        try:
            qs = parse_qs(query_string)
            pid = (qs.get('project_id', [''])[0] or '').strip()
        except Exception:
            pid = ''
    _request_pid_ctx.override = pid


def _current_project_id() -> str:
    """현재 활성 프로젝트의 PROJECT_ID 슬러그를 반환합니다.

    UI에서 폴더를 전환하면 즉시 반영됩니다 (_current_project_root 기반).
    형식: 경로의 드라이브/슬래시를 '--'로 치환 (예: D--vibe-coding)

    [Phase 2-5.2] 요청에 ?project_id= 쿼리가 있으면 우선 사용.
    멀티 윈도우/탭 전환 직후 race window 차단 목적.
    """
    explicit = (getattr(_request_pid_ctx, 'override', '') or '').strip()
    if explicit:
        return explicit
    return _ctx_project_id(PROJECT_ROOT, CONFIG_FILE)


def _codex_main_model() -> str:
    """config.json 또는 환경변수에서 Codex 직접 실행용 메인 모델명을 반환합니다."""
    env_value = os.environ.get('CODEX_MAIN_MODEL', '').strip()
    if env_value:
        return env_value

    try:
        if CONFIG_FILE.exists():
            cfg = json.loads(CONFIG_FILE.read_text(encoding='utf-8'))
            nested = cfg.get('codex_models', {})
            if isinstance(nested, dict):
                nested_main = nested.get('main', '')
                if isinstance(nested_main, str) and nested_main.strip():
                    return nested_main.strip()
            legacy = cfg.get('codex_main_model', '')
            if isinstance(legacy, str) and legacy.strip():
                return legacy.strip()
    except Exception as e:
        print(f"[FILE ERROR] _codex_main_model config 로드: {e}")

    return ''


# ── CLI 도구 설치 상태 + npm install 상태 머신은 infra/tool_install.py로 이관 ──
# [2026-04-21] server.py L1081~1335 블록 분리 (Task 7.1). 글로벌 상태 dict는
# 모듈 내부로 캡슐화되었다. server.py에는 /api 라우트가 실제로 호출하는 3개 함수
# (tool_status / get_npm_executable / get_tool_install_state)의 얇은 래퍼만 남긴다.
from infra import tool_install as _tool_install


def _tool_status(name: str) -> dict:
    return _tool_install.tool_status(name)


def _get_npm_executable() -> str:
    return _tool_install.get_npm_executable()


def _get_tool_install_state(name: str) -> dict:
    return _tool_install.get_tool_install_state(name)


def _parse_session_tail(path: Path):
    """Claude Code 세션 JSONL 파일 꼬리에서 마지막 토큰 usage 정보 추출.

    대형 파일(수천 줄)의 불필요한 전체 읽기를 피하기 위해 파일 끝 8KB만 읽어
    마지막 assistant 메시지의 usage 필드를 파싱합니다.
    발견 못하면 None 반환.
    """
    try:
        TAIL_BYTES = 8192  # 끝 8KB면 최근 메시지 수십 개 충분히 커버
        with open(path, 'rb') as f:
            f.seek(0, 2)                      # 파일 끝으로 이동
            size = f.tell()
            f.seek(max(0, size - TAIL_BYTES)) # 끝 8KB 위치로
            raw = f.read().decode('utf-8', errors='ignore')

        # 완전한 줄만 추출 (첫 줄은 잘릴 수 있으므로 제외)
        lines = [l.strip() for l in raw.splitlines() if l.strip()]

        session_id = slug = model = cwd = last_ts = ''
        input_tokens = output_tokens = cache_read = cache_write = 0

        # 역순으로 탐색 → 가장 최신 데이터 우선
        for line in reversed(lines):
            try:
                obj = json.loads(line)
            except Exception:
                continue  # JSONL 개별 행 파싱 실패 허용

            # 세션 메타 수집 (처음 발견 시만 기록)
            if not session_id and obj.get('sessionId'):
                session_id = obj['sessionId']
            if not slug and obj.get('slug'):
                slug = obj['slug']
            if not cwd and obj.get('cwd'):
                cwd = obj['cwd']
            if not last_ts and obj.get('timestamp'):
                last_ts = obj['timestamp']

            # assistant 메시지에서 usage 추출
            if obj.get('type') == 'assistant' and isinstance(obj.get('message'), dict):
                usage = obj['message'].get('usage', {})
                if usage.get('input_tokens'):
                    if not model:
                        model = obj['message'].get('model', '')
                    input_tokens = usage.get('input_tokens', 0)
                    output_tokens = usage.get('output_tokens', 0)
                    cache_read = usage.get('cache_read_input_tokens', 0)
                    cache_write = usage.get('cache_creation_input_tokens', 0)
                    if not last_ts:
                        last_ts = obj.get('timestamp', '')
                    break  # 가장 최신 usage 찾으면 즉시 종료

        if not session_id:
            return None  # 유효한 세션 파일 아님

        return {
            'session_id': session_id,
            'slug': slug or path.stem[:12],   # slug 없으면 파일명 앞 12자
            'model': model or 'unknown',
            'input_tokens': input_tokens,
            'output_tokens': output_tokens,
            'cache_read': cache_read,
            'cache_write': cache_write,
            'last_ts': last_ts,
            'cwd': str(cwd).replace('\\', '/'),
        }
    except Exception as e:
        print(f"[FILE ERROR] _parse_session_tail: {e}")
        return None


def _parse_antigravity_session(path: Path):
    """Antigravity CLI 세션 JSON 파일에서 최신 토큰 usage 정보 추출.

    ~/.gemini/tmp/{project}/chats/session-*.json 파일을 읽어
    가장 최근 antigravity 타입 메시지의 tokens 필드를 파싱합니다.
    tokens 구조: { input, output, cached, thoughts, tool, total }
    [2026-02-27] Claude: Antigravity 컨텍스트 사용량 표시 기능 추가
    """
    try:
        with open(path, 'r', encoding='utf-8') as f:
            data = json.load(f)

        session_id = data.get('sessionId', '')
        if not session_id:
            return None  # 유효한 세션 파일 아님

        last_updated = data.get('lastUpdated', '')
        messages = data.get('messages', [])

        input_tokens = output_tokens = cached_tokens = 0
        model = ''

        # 역순으로 antigravity 타입 메시지 탐색 → 가장 최신 usage 우선
        for msg in reversed(messages):
            if msg.get('type') == 'antigravity':
                tokens = msg.get('tokens', {})
                if tokens.get('input'):
                    input_tokens  = tokens.get('input', 0)
                    output_tokens = tokens.get('output', 0)
                    cached_tokens = tokens.get('cached', 0)
                    model = msg.get('model', 'antigravity')
                    break

        return {
            'session_id':   session_id,
            'slug':         session_id[:8],        # 앞 8자리로 슬러그 대체
            'model':        model or 'antigravity',
            'input_tokens': input_tokens,
            'output_tokens': output_tokens,
            'cache_read':   cached_tokens,
            'last_ts':      last_updated,
            'cwd':          '',
        }
    except Exception as e:
        print(f"[FILE ERROR] _parse_antigravity_session: {e}")
        return None


# ── .env 파일 읽기/쓰기 유틸 ─────────────────────────────────────────────────

# ─────────────────────────────────────────────────────────────────────────────

# 정적 파일 경로
STATIC_DIR = (BASE_DIR / "vibe-view" / "dist").resolve()

print(f"[*] Static files directory: {STATIC_DIR}")
if not STATIC_DIR.exists():
    print(f"[!] WARNING: Static directory NOT FOUND at {STATIC_DIR}")
    # 실행 중인 파일 주변에서 dist 폴더를 한 번 더 찾아봄 (휴리스틱)
    alt_dist = (Path(sys.executable).parent / "vibe-view" / "dist").resolve()
    if alt_dist.exists():
        STATIC_DIR = alt_dist
        print(f"[*] Found alternative static directory at {alt_dist}")


class ThreadedHTTPServer(ThreadingMixIn, HTTPServer):
    """멀티 스레드 지원 HTTP 서버 (SSE 등 지속적 연결 동시 처리용)"""
    daemon_threads = True
    # 서버 종료 후 포트 TIME_WAIT 상태 무시 — 재부팅 없이 즉시 재실행 가능
    allow_reuse_address = True

# ── 에이전트 실시간 상태 관리 (오케스트레이션 핵심 데이터) ──────────────────
# 구조: { "agent_name": { "status": "active|idle|error", "task": "task_id", "last_seen": timestamp } }
AGENT_STATUS = {}
AGENT_STATUS_LOCK = threading.Lock()


def _restore_agent_status_from_db():
    """서버 시작 시 PostgreSQL agent_heartbeats에서 에이전트 상태를 복구한다.

    재시작해도 이전 에이전트 상태를 유지하여 대시보드가 즉시 현황을 보여준다.
    5분 이상 heartbeat가 없으면 offline으로 표시한다.
    """
    try:
        rows = list_agent_status()
        if not rows:
            return
        now_ts = time.time()
        with AGENT_STATUS_LOCK:
            for row in rows:
                agent_id = row.get('agent_id', '')
                if not agent_id:
                    continue
                # last_beat ISO 문자열 → timestamp 변환
                last_beat_str = row.get('last_beat', '')
                try:
                    from datetime import datetime
                    dt = datetime.fromisoformat(last_beat_str)
                    last_seen_ts = dt.timestamp()
                except Exception:
                    last_seen_ts = now_ts - 600  # 파싱 실패 시 10분 전으로 설정
                # 5분 이상 지났으면 offline
                age_sec = now_ts - last_seen_ts
                if age_sec > 300:
                    status = 'offline'
                else:
                    status = row.get('status', 'idle')
                AGENT_STATUS[agent_id] = {
                    'status': status,
                    'task': row.get('current_task'),
                    'last_seen': last_seen_ts,
                    'beat_count': row.get('beat_count', 0),
                }
        print(f"[*] 에이전트 상태 복구 완료: {len(rows)}개 에이전트 (DB → 메모리)")
    except Exception as e:
        print(f"[!] 에이전트 상태 복구 실패 (무시): {e}")


# 에이전트 상태 복구는 main()에서 ensure_schema 이후에 호출
# (모듈 로드 시점에는 PostgreSQL이 아직 기동 중일 수 있음)


# [2026-06-21] Claude: vibe_mux(Named Pipe 터미널 멀티플렉서) 전면 제거.
# 프론트/백엔드 어디서도 /api/mux/* 를 소비하지 않는 미사용 계층이었음.
# 에이전트 간 메시징은 itcp(pg_messages) 단일 경로로 통일.


def _send_json_response(handler, data, status=200):
    """JSON 응답을 전송하는 헬퍼."""
    body = json.dumps(data, ensure_ascii=False).encode('utf-8')
    handler.send_response(status)
    handler.send_header('Content-Type', 'application/json; charset=utf-8')
    handler.send_header('Access-Control-Allow-Origin', handler._cors_origin() if hasattr(handler, '_cors_origin') else '*')
    handler.send_header('Content-Length', str(len(body)))
    handler.end_headers()
    handler.wfile.write(body)

# ─────────────────────────────────────────────────────────────────────────────
# 라우트 디스패치 테이블 (Phase 1: 순수 prefix 위임만)
# [WHY] do_GET의 if/elif 사슬을 테이블 조회로 점진 전환(brainstorm 승인 C). 복합조건 라우트
#   (hive: prefix+8exact 혼합 / tasks: endswith)는 회귀 위험이라 아직 legacy elif에 잔류 —
#   테이블 miss 시 _do_GET 하위 elif로 폴백(하이브리드). 완전성 가드(tests/test_route_table.py)가
#   재구조화 중 라우트 누락을 방어한다.
# [불변식] wrapper는 전역(git_api/DATA_DIR/_proxy_to_office_server 등)을 **호출 시점**에 해석 —
#   모듈에서 나중에 정의되는 심볼(_proxy_to_office_server 등)도 안전(함수 본문 이름 해석은 런타임).
# [안전] 이 8개 prefix는 서로 비중첩 + 어떤 GET exact 라우트도 이들로 시작하지 않음(검증됨) →
#   do_GET 최상단에서 prefix-first 조회해도 exact를 가리지 않는다. POST는 exact-prefix 충돌 있어 별도.
def _g_git(h, pp):        git_api.handle_get(h, pp.path, parse_qs(pp.query), BASE_DIR=BASE_DIR)
def _g_agent(h, pp):      agent_api.handle_get(h, pp.path)
def _g_pty(h, pp):        pty_api.handle_get(h, pp.path, parse_qs(pp.query))
def _g_experience(h, pp): experience_api.handle_get(h, pp.path, parse_qs(pp.query))
def _g_zettel(h, pp):     zettel_api.handle_get(h, pp.path, parse_qs(pp.query), DATA_DIR=DATA_DIR, PROJECT_ID=PROJECT_ID)
def _g_codegraph(h, pp):  codegraph_api.handle_get(h, pp.path, parse_qs(pp.query), DATA_DIR=DATA_DIR, PROJECT_ID=PROJECT_ID)
def _g_office(h, pp):     _proxy_to_office_server(h, method='GET')
def _g_tools(h, pp):
    from api import tools_api
    tools_api.handle_get(h, pp.path, parse_qs(pp.query))

GET_PREFIX_ROUTES = [
    ('/api/git/', _g_git),
    ('/api/agent/', _g_agent),
    ('/api/pty/', _g_pty),
    ('/api/experience', _g_experience),
    ('/api/zettel/', _g_zettel),
    ('/api/codegraph/', _g_codegraph),
    ('/api/office/', _g_office),
    ('/api/tools/', _g_tools),
]
# ─────────────────────────────────────────────────────────────────────────────
# POST 라우트 디스패치 테이블 (Phase 1 Task 3: 순수 위임만)
# [WHY] do_POST의 if/elif 사슬 중 "인라인 로직 없는 순수 위임" 라우트만 테이블로 이전
#   (do_GET Task 2 동형). 인라인 핸들러(dashboard/launch, screenshot/analyze, heartbeat 등)와
#   복합조건 라우트는 legacy 잔류 → 테이블 miss 시 do_POST 하위 if/elif로 폴백(하이브리드).
# [불변식/안전] GET과 달리 POST는 exact-prefix 충돌이 있어 이전 대상을 엄격히 제한한다:
#   - /api/git/rollback·/api/git/diff(인라인) ⊂ /api/git/  → git 계열 전부 legacy 잔류(이전 금지)
#   - /api/hive/log/pg·/api/hive/thought/pg(인라인) ⊂ /api/hive/ → hive/orchestrator/superpowers 잔류
#   - /api/office/*(복합조건 프록시), /api/tasks/*(endswith), /api/agents/*/trigger(endswith) 잔류
#   따라서 이전한 prefix(tools/agent/pty/zettel/codegraph/memory)는 어떤 인라인 exact와도 비충돌(검증됨).
#   [디스패치 순서] exact 먼저 → prefix 나중 → legacy 폴백. exact-first라서 prefix가 exact를 가리지 않음.
# [불변식] wrapper는 전역(update_api/_soft_src_dir/_get_node_pty_sessions 등)을 **호출 시점** 해석 —
#   모듈 뒤쪽에서 정의되는 심볼(_NODE_PTY_REST_URL 등)도 런타임 해석이라 안전(GET 테이블과 동일 규칙).
def _p_body(h):
    _cl = int(h.headers.get('Content-Length', 0))
    return json.loads(h.rfile.read(_cl).decode('utf-8')) if _cl else {}

# exact 위임
def _p_telegram_config(h, pp): h._handle_telegram_config_post()
def _p_telegram_test(h, pp):   h._handle_telegram_test()
def _p_apply_update(h, pp):    update_api.apply_update(h, DATA_DIR)
def _p_soft_update(h, pp):     update_api.soft_update_apply(h, DATA_DIR, _soft_src_dir())
def _p_trigger_update(h, pp):  update_api.trigger_update_check(h, DATA_DIR)
def _p_projects(h, pp):        projects_api.handle_post(h, PROJECTS_FILE)
def _p_experience(h, pp):      experience_api.handle_post(h, pp.path)
def _p_config_update(h, pp):   config_api.handle_update(h, CONFIG_FILE, PROJECTS_FILE)
def _p_launch(h, pp):          launch_api.handle_launch(h, _codex_main_model)
def _p_send_command(h, pp):    commands_api.handle_send_command(h, _NODE_PTY_REST_URL, _get_node_pty_sessions)
def _p_locks(h, pp):           locks_api.handle_lock(h, LOCKS_FILE)
def _p_message(h, pp):         message_api.handle_send(h, WS_PORT, BASE_DIR, send_message)
def _p_vibe_notify(h, pp):       vibe_api.handle_notify(h)
def _p_vibe_progress(h, pp):     vibe_api.handle_progress(h, method='POST')
def _p_vibe_progress_clr(h, pp): vibe_api.handle_progress(h, method='DELETE')
def _p_vibe_status(h, pp):       vibe_api.handle_status(h, method='POST')
def _p_vibe_status_clr(h, pp):   vibe_api.handle_status(h, method='DELETE')
def _p_vibe_log(h, pp):          vibe_api.handle_log(h, method='POST')
def _p_vibe_log_clr(h, pp):      vibe_api.handle_log(h, method='DELETE')
def _p_files(h, pp):
    files_api.handle_post(h, pp.path, _p_body(h), validate_file_path=_validate_file_path)

# prefix 위임 (일부는 body 선읽기)
def _p_tools(h, pp):
    from api import tools_api
    tools_api.handle_post(h, pp.path, _p_body(h))
def _p_agent(h, pp): agent_api.handle_post(h, pp.path)
def _p_pty(h, pp):   pty_api.handle_post(h, pp.path)
def _p_zettel(h, pp):
    zettel_api.handle_post(h, pp.path, _p_body(h), DATA_DIR=DATA_DIR, PROJECT_ID=PROJECT_ID)
def _p_codegraph(h, pp):
    codegraph_api.handle_post(h, pp.path, _p_body(h), DATA_DIR=DATA_DIR, PROJECT_ID=PROJECT_ID)
def _p_memory(h, pp):
    from api import memory_api
    memory_api.handle_post(h, pp.path, _p_body(h), DATA_DIR=DATA_DIR, PROJECT_ID=PROJECT_ID)

POST_ROUTES = {
    '/api/config/telegram': _p_telegram_config,
    '/api/telegram/test': _p_telegram_test,
    '/api/apply-update': _p_apply_update,
    '/api/soft-update/apply': _p_soft_update,
    '/api/trigger-update-check': _p_trigger_update,
    '/api/projects': _p_projects,
    '/api/experience': _p_experience,
    '/api/config/update': _p_config_update,
    '/api/launch': _p_launch,
    '/api/send-command': _p_send_command,
    '/api/locks': _p_locks,
    '/api/message': _p_message,
    '/api/vibe/notify': _p_vibe_notify,
    '/api/vibe/progress': _p_vibe_progress,
    '/api/vibe/progress/clear': _p_vibe_progress_clr,
    '/api/vibe/status': _p_vibe_status,
    '/api/vibe/status/clear': _p_vibe_status_clr,
    '/api/vibe/log': _p_vibe_log,
    '/api/vibe/log/clear': _p_vibe_log_clr,
    '/api/save-file': _p_files,
    '/api/file-rename': _p_files,
    '/api/files/create': _p_files,
    '/api/files/delete': _p_files,
}

POST_PREFIX_ROUTES = [
    ('/api/tools/', _p_tools),
    ('/api/agent/', _p_agent),
    ('/api/pty/', _p_pty),
    ('/api/zettel/', _p_zettel),
    ('/api/codegraph/', _p_codegraph),
    ('/api/memory/', _p_memory),
]
# ─────────────────────────────────────────────────────────────────────────────

class SSEHandler(BaseHTTPRequestHandler):
    # ── Telegram 설정 API 핸들러 — api/telegram_api.py로 분리 (2026-04-20) ──────
    # 본체는 api/telegram_api.py에 모듈 함수로 이전. SSEHandler 메서드는
    # PROJECT_ROOT/_child_procs를 바인딩하는 얇은 위임만 유지.

    def _handle_telegram_config_get(self):
        telegram_api.telegram_config_get(self, PROJECT_ROOT, _child_procs)

    def _handle_telegram_config_post(self):
        telegram_api.telegram_config_post(self, PROJECT_ROOT)

    def _handle_telegram_test(self):
        telegram_api.telegram_test(self, PROJECT_ROOT)

    def _cors_origin(self) -> str:
        """CORS Origin을 localhost/127.0.0.1만 허용하도록 반환합니다.

        [보안 수정] 2026-03-17 Claude
        - 기존: Access-Control-Allow-Origin: * (모든 도메인 허용)
        - 수정: 요청의 Origin 헤더가 localhost/127.0.0.1일 때만 해당 Origin 반환
        - 악성 웹페이지에서 localhost API로 fetch하는 CSRF 공격 차단
        """
        origin = self.headers.get('Origin', '')
        if origin and any(origin.startswith(p) for p in (
            'http://localhost', 'http://127.0.0.1',
            'https://localhost', 'https://127.0.0.1',
        )):
            return origin
        return f'http://localhost:{HTTP_PORT}'

    def do_GET(self):
        parsed_path = urlparse(self.path)
        path = parsed_path.path
        _set_request_pid(parsed_path.query)  # Phase 2-5.2: ?project_id= override

        # ── 라우트 테이블 우선 조회(Phase 1: 순수 prefix) → miss 시 아래 elif 폴백 ──
        for _pfx, _fn in GET_PREFIX_ROUTES:
            if path.startswith(_pfx):
                _fn(self, parsed_path)
                return

        # ─── SSE 실시간 스트리밍 3종 — api/events_api.py로 분리 (공유 집합/락 참조 주입) ───
        if path == '/api/events/thoughts':
            events_api.stream_thoughts(self, THOUGHT_LOGS, THOUGHT_CLIENTS, _SSE_LOCK)
            return
        if path == '/api/events/agent':
            events_api.stream_agent(self, AGENT_CLIENTS, _SSE_LOCK)
            return
        if path == '/api/events/fs':
            events_api.stream_fs(self, FS_CLIENTS, _SSE_LOCK)
            return

        if parsed_path.path == '/stream':
            self.send_response(200)
            self.send_header('Content-Type', 'text/event-stream')
            self.send_header('Access-Control-Allow-Origin', self._cors_origin())
            self.send_header('Cache-Control', 'no-cache')
            self.send_header('Connection', 'keep-alive')
            self.end_headers()
            
            import psycopg2
            import select
            
            # 1. 초기 데이터 전송 (최근 50개 - PostgreSQL pg_logs 테이블에서 조회)
            try:
                rows = run_pg_sql_csv(
                    "SELECT agent, metadata->>'level' as level, task as trigger, metadata->>'session_id' as session_id, "
                    "terminal_id as terminal_id, project_id as project, "
                    "status as status, to_char(ts, 'YYYY-MM-DD HH24:MI:SS') as timestamp "
                    "FROM pg_logs ORDER BY id DESC LIMIT 50"
                )
                if rows:
                    for row in reversed(rows):
                        if not row.get('level'):
                            row['level'] = 'info'
                        self.wfile.write(f"data: {json.dumps(row, ensure_ascii=False)}\n\n".encode('utf-8'))
                        self.wfile.flush()
            except Exception as e:
                print(f"[SSE-PG] Initial Read Error: {e}")

            # 2. 실시간 LISTEN 루프
            try:
                pg_conn = psycopg2.connect(host="localhost", port=PG_PORT, user="postgres", database=PG_PROJECT_DB)
                pg_conn.set_isolation_level(psycopg2.extensions.ISOLATION_LEVEL_AUTOCOMMIT)
                cursor = pg_conn.cursor()
                cursor.execute("LISTEN hive_log_channel;")
                
                self.connection.settimeout(60.0) # SSE 연결 타임아웃
                
                while True:
                    if select.select([pg_conn], [], [], 5) == ([], [], []):
                        # 하트비트 전송
                        self.wfile.write(b": heartbeat\n\n")
                        self.wfile.flush()
                        continue
                    
                    pg_conn.poll()
                    while pg_conn.notifies:
                        notify = pg_conn.notifies.pop(0)
                        payload = json.loads(notify.payload)
                        
                        table_name = payload.get('table')
                        if table_name in ('hive_logs', 'pg_logs'):
                            data = payload.get('data', {})
                            meta = data.get('metadata', {})
                            if isinstance(meta, str):
                                try: meta = json.loads(meta)
                                except: meta = {}
                            
                            agent = data.get('agent')
                            level = meta.get('level', 'info') if meta else 'info'
                            trigger = data.get('task') if table_name == 'pg_logs' else data.get('message')
                            session_id = meta.get('session_id') or meta.get('task_id') if meta else None
                            terminal_id = data.get('terminal_id') if table_name == 'pg_logs' else (meta.get('terminal_id') if meta else '')
                            project = data.get('project_id') if table_name == 'pg_logs' else (meta.get('project') if meta else '')
                            status = data.get('status') if table_name == 'pg_logs' else (meta.get('raw_status') if meta else '')
                            timestamp = data.get('ts') or data.get('created_at') if table_name == 'pg_logs' else data.get('timestamp')
                            
                            out_row = {
                                "agent": agent,
                                "level": level,
                                "trigger": trigger,
                                "session_id": session_id,
                                "terminal_id": terminal_id,
                                "project": project,
                                "status": status,
                                "timestamp": timestamp
                            }
                            
                            self.wfile.write(f"data: {json.dumps(out_row, ensure_ascii=False)}\n\n".encode('utf-8'))
                            self.wfile.flush()
            except (BrokenPipeError, ConnectionResetError, socket.timeout):
                pass
            except Exception as e:
                print(f"[SSE-PG] Stream Error: {e}")
            finally:
                try: pg_conn.close()
                except: pass
        elif parsed_path.path == '/api/heartbeat':
            # 하트비트 수신 — 자동 종료 로직 제거됨 (밤새 실행 지원)
            self.send_response(200)
            self.send_header('Content-Type', 'application/json;charset=utf-8')
            self.send_header('Access-Control-Allow-Origin', self._cors_origin())
            self.end_headers()
            self.wfile.write(json.dumps({"status": "ok", "ts": datetime.now().isoformat()}).encode('utf-8'))
        elif parsed_path.path == '/api/projects':
            projects_api.handle_get(self, PROJECTS_FILE)
        elif parsed_path.path == '/api/agents':
            # 실시간 에이전트 상태 목록 반환 (오케스트레이터용)
            # 인메모리 + PostgreSQL DB 데이터 병합하여 반환
            self.send_response(200)
            self.send_header('Content-Type', 'application/json;charset=utf-8')
            self.send_header('Access-Control-Allow-Origin', self._cors_origin())
            self.end_headers()
            with AGENT_STATUS_LOCK:
                result = dict(AGENT_STATUS)
            # DB에만 있는 에이전트도 포함 (다른 프로세스가 기록한 경우)
            try:
                for row in list_agent_status():
                    aid = row.get('agent_id', '')
                    if aid and aid not in result:
                        result[aid] = {
                            'status': row.get('status', 'offline'),
                            'task': row.get('current_task'),
                            'last_beat': row.get('last_beat'),
                            'beat_count': row.get('beat_count', 0),
                        }
            except Exception:
                pass
            self.wfile.write(json.dumps(result, ensure_ascii=False).encode('utf-8'))
        elif parsed_path.path == '/api/browse-folder':
            self.send_response(200)
            self.send_header('Content-Type', 'application/json;charset=utf-8')
            self.send_header('Access-Control-Allow-Origin', self._cors_origin())
            self.end_headers()
            try:
                selected_path = _open_folder_dialog_subprocess()
                self.wfile.write(json.dumps({"path": selected_path}).encode('utf-8'))
            except Exception as e:
                self.wfile.write(json.dumps({"error": str(e)}).encode('utf-8'))
        elif parsed_path.path == '/api/config':
            self.send_response(200)
            self.send_header('Content-Type', 'application/json;charset=utf-8')
            self.send_header('Access-Control-Allow-Origin', self._cors_origin())
            self.end_headers()
            config = {}
            if CONFIG_FILE.exists():
                try:
                    with open(CONFIG_FILE, 'r', encoding='utf-8') as f:
                        config = json.load(f)
                except: pass
            config.setdefault('vault_dir', str(GLOBAL_VAULT_DIR))
            # [2026-06-21] 설치본 빈-패널 사고 대응 — 활성 프로젝트 컨텍스트를 프론트에 노출.
            # project_unresolved=True면 UI가 "프로젝트 폴더를 선택하세요"를 유도(빈 하이브/제텔 패널 방지).
            config['project_unresolved'] = PROJECT_CONTEXT_UNRESOLVED
            config['active_project_id'] = _current_project_id()
            self.wfile.write(json.dumps(config).encode('utf-8'))
        elif parsed_path.path == '/api/tool-status':
            self.send_response(200)
            self.send_header('Content-Type', 'application/json;charset=utf-8')
            self.send_header('Access-Control-Allow-Origin', self._cors_origin())
            self.end_headers()
            query = parse_qs(parsed_path.query)
            tool_name = (query.get('name') or [''])[0].strip().lower()
            self.wfile.write(json.dumps(_tool_status(tool_name), ensure_ascii=False).encode('utf-8'))
        elif parsed_path.path == '/api/install-tool-status':
            self.send_response(200)
            self.send_header('Content-Type', 'application/json;charset=utf-8')
            self.send_header('Access-Control-Allow-Origin', self._cors_origin())
            self.end_headers()
            query = parse_qs(parsed_path.query)
            tool_name = (query.get('name') or [''])[0].strip().lower()
            self.wfile.write(json.dumps(_get_tool_install_state(tool_name), ensure_ascii=False).encode('utf-8'))
        elif parsed_path.path == '/api/drives':
            self.send_response(200)
            self.send_header('Content-Type', 'application/json;charset=utf-8')
            self.send_header('Access-Control-Allow-Origin', self._cors_origin())
            self.end_headers()
            drives = []
            if os.name == 'nt':
                for letter in string.ascii_uppercase:
                    drive = f"{letter}:/"  # 경로 일관성: 항상 포워드 슬래시 사용 (2026-02-27)
                    if os.path.exists(drive):
                        drives.append(drive)
            else:
                drives = ['/']
            self.wfile.write(json.dumps(drives).encode('utf-8'))
        elif parsed_path.path in ('/api/install-gemini-cli', '/api/install-claude-code', '/api/install-codex-cli'):
            # 터미널 창을 띄워서 npm install -g 실행 — 사용자가 진행 상황을 직접 확인
            _install_map = {
                '/api/install-gemini-cli': ('gemini', '@google/gemini-cli', 'Gemini CLI'),
                '/api/install-claude-code': ('claude', '@anthropic-ai/claude-code', 'Claude Code'),
                '/api/install-codex-cli': ('codex', '@openai/codex', 'Codex CLI'),
            }
            _tool_key, _pkg, _display = _install_map[parsed_path.path]
            try:
                _npm = _get_npm_executable()
                if not _npm:
                    raise FileNotFoundError('npm 실행 파일을 찾을 수 없습니다. Node.js가 설치되어 있는지 확인하세요.')
                _title = f"[{_display} 설치]"
                _cmd = (
                    f'start "{_title}" cmd.exe /k "'
                    f'title {_title} && '
                    f'echo ========================================= && '
                    f'echo   {_display} 설치를 시작합니다... && '
                    f'echo ========================================= && '
                    f'echo. && '
                    f'"{_npm}" install -g {_pkg} && '
                    f'echo. && echo ✅ {_display} 설치가 완료되었습니다! || '
                    f'echo. && echo ❌ {_display} 설치에 실패했습니다."'
                )
                subprocess.Popen(_cmd, shell=True)
                result = {'status': 'success', 'message': f'{_display} 설치 터미널이 열렸습니다.'}
            except Exception as exc:
                result = {'status': 'error', 'message': str(exc)}
            self.send_response(200)
            self.send_header('Content-Type', 'application/json;charset=utf-8')
            self.send_header('Access-Control-Allow-Origin', self._cors_origin())
            self.end_headers()
            self.wfile.write(json.dumps(result, ensure_ascii=False).encode('utf-8'))
        elif parsed_path.path == '/api/register-codex-to-ai':
            self.send_response(200)
            self.send_header('Content-Type', 'application/json;charset=utf-8')
            self.send_header('Access-Control-Allow-Origin', self._cors_origin())
            self.end_headers()
            try:
                python_cmds = _python_runner_cmds()
                wrapper_script = str(BASE_DIR / 'bin' / 'codex_wrapper.py')
                last_error = ''
                for python_cmd in python_cmds:
                    proc = subprocess.run(
                        [python_cmd, wrapper_script, '--install'],
                        input='all\n',
                        capture_output=True,
                        text=True,
                        timeout=30,
                        cwd=str(PROJECT_ROOT),
                    )
                    output = proc.stdout.strip() or proc.stderr.strip()
                    if proc.returncode == 0:
                        result = {"status": "success", "message": f"Antigravity CLI & Claude Desktop에 vibe-coding MCP 등록 완료!\n{output}"}
                        break
                    last_error = output or f"등록 실패 (exit code {proc.returncode})"
                else:
                    result = {"status": "error", "message": last_error or "사용 가능한 Python 실행기를 찾지 못했습니다."}
            except subprocess.TimeoutExpired:
                result = {"status": "error", "message": "등록 시간 초과 (30초)"}
            except Exception as e:
                result = {"status": "error", "message": str(e)}
            self.wfile.write(json.dumps(result, ensure_ascii=False).encode('utf-8'))
        elif parsed_path.path == '/api/shutdown':
            # 안전한 셧다운: 서버와 자식 프로세스를 정리한 뒤 종료
            # [설계 의도] 프론트엔드 TopMenuBar에서 호출. 확인 다이얼로그를 거친 후에만 도달.
            # 좀비 프로세스 방지를 위해 PTY 세션 정리 후 os._exit() 호출.
            self.send_response(200)
            self.send_header('Content-Type', 'application/json;charset=utf-8')
            self.send_header('Access-Control-Allow-Origin', self._cors_origin())
            self.end_headers()
            self.wfile.write(json.dumps({"status": "ok", "message": "서버 종료 중..."}).encode('utf-8'))
            # 비동기로 0.5초 후 종료 (응답 전송 완료 대기)
            import threading
            def _delayed_shutdown():
                time.sleep(0.5)
                # 자식 프로세스(PTY 서버, 워치독 등) 먼저 종료 — os._exit()는 atexit 핸들러를 실행하지 않으므로
                # 여기서 명시적으로 호출해야 node.exe 등이 _MEI 임시 폴더를 해제하여 정리 가능
                _cleanup_child_procs()
                time.sleep(1)  # 자식 프로세스 종료 대기 — 파일 핸들 해제 시간 확보
                # PyInstaller 임시 디렉터리(_MEI*) 잔여물 정리
                _cleanup_pyinstaller_temp()
                os._exit(0)
            threading.Thread(target=_delayed_shutdown, daemon=True).start()
        # [2026-03-22] /api/files → files_api.py로 위임됨 (상단 모듈 위임 섹션)
        elif parsed_path.path == '/api/install-skills':
            install_api.install_skills(self, BASE_DIR, SCRIPTS_DIR, ensure_schema)

        # ── [모듈 위임] hive_api — /api/hive/*, /api/orchestrator/*, /api/superpowers/status,
        #    /api/skill-results, /api/context-usage, /api/antigravity-context-usage, /api/local-models ──
        elif (parsed_path.path.startswith('/api/hive/') or
              parsed_path.path.startswith('/api/orchestrator/') or
              # [과거사고 2026-07-04] agent-quota 누락 — hive_api.py에 핸들러만 추가하고
              # 이 allowlist를 안 갱신해 SPA 폴백(index.html)이 응답 → 쿼터 배지 미표시.
              # hive_api에 단건 라우트 추가 시 반드시 이 튜플도 동기 갱신.
              parsed_path.path in ('/api/superpowers/status', '/api/skill-results',
                                   '/api/skill-ab-test', '/api/skill/predict',
                                   '/api/context-usage', '/api/antigravity-context-usage',
                                   '/api/agent-quota', '/api/local-models')):
            _params = parse_qs(parsed_path.query)
            from api import hive_api
            hive_api.handle_get(
                self, parsed_path.path, _params,
                DATA_DIR=DATA_DIR, SCRIPTS_DIR=SCRIPTS_DIR, BASE_DIR=BASE_DIR,
                PROJECT_ROOT=PROJECT_ROOT, PROJECT_ID=PROJECT_ID,
                TASKS_FILE=TASKS_FILE, AGENT_STATUS=AGENT_STATUS,
                AGENT_STATUS_LOCK=AGENT_STATUS_LOCK,
                pty_sessions=_get_node_pty_sessions(),
                _current_project_root=_current_project_root,
                _parse_session_tail=_parse_session_tail,
                _parse_antigravity_session=_parse_antigravity_session,
                run_pg_sql_csv=run_pg_sql_csv
            )

        elif parsed_path.path.startswith('/api/git/'):
            _params = parse_qs(parsed_path.query)
            git_api.handle_get(self, parsed_path.path, _params, BASE_DIR=BASE_DIR)

        # ── [모듈 위임] vibe_api — /api/vibe/* (cmux 호환 CLI API) ────────
        elif parsed_path.path == '/api/vibe/sidebar':
            vibe_api.handle_sidebar_state(self)
        elif parsed_path.path == '/api/vibe/notifications':
            vibe_api.handle_notifications(self)

        # ── [모듈 위임] agent_api — /api/agent/* ─────────────────────────
        elif parsed_path.path.startswith('/api/agent/'):
            agent_api.handle_get(self, parsed_path.path)
        elif parsed_path.path.startswith('/api/pty/'):
            pty_api.handle_get(self, parsed_path.path, parse_qs(parsed_path.query))

        # ── Telegram 설정 API ──────────────────────────────────────────
        elif parsed_path.path == '/api/config/telegram':
            self._handle_telegram_config_get()

        # ── [모듈 위임] memory_api — /api/memory, /api/project-info ──────
        elif parsed_path.path in ('/api/memory', '/api/project-info'):
            _params = parse_qs(parsed_path.query)
            memory_api.handle_get(
                self, parsed_path.path, _params,
                DATA_DIR=DATA_DIR, PROJECT_ID=PROJECT_ID, PROJECT_ROOT=PROJECT_ROOT,
                __version__=__version__,
            )

        # ── [모듈 위임] experience_api — /api/experience/* ────────────
        elif parsed_path.path.startswith('/api/experience'):
            _params = parse_qs(parsed_path.query)
            experience_api.handle_get(self, parsed_path.path, _params)

        # ── [모듈 위임] vibe_skills_api — /api/vibe/skills (Phase 3-2) ───
        elif parsed_path.path == '/api/vibe/skills':
            _params = parse_qs(parsed_path.query)
            vibe_skills_api.handle_get(self, parsed_path.path, _params, PROJECT_ROOT)

        # ── [모듈 위임] zettel_api — /api/zettel/* ────────────────────
        elif parsed_path.path.startswith('/api/zettel/'):
            _params = parse_qs(parsed_path.query)
            zettel_api.handle_get(
                self, parsed_path.path, _params,
                DATA_DIR=DATA_DIR, PROJECT_ID=PROJECT_ID,
            )

        # ── [모듈 위임] codegraph_api — /api/codegraph/* ─────────────
        elif parsed_path.path.startswith('/api/codegraph/'):
            _params = parse_qs(parsed_path.query)
            codegraph_api.handle_get(
                self, parsed_path.path, _params,
                DATA_DIR=DATA_DIR, PROJECT_ID=PROJECT_ID,
            )

        # ── 오피스 API → 오피스 서버 프록시 (중복 코드 제거 — 2026-04-13) ──
        elif parsed_path.path.startswith('/api/office/'):
            _proxy_to_office_server(self, method='GET')

        # ── [모듈 위임] tasks_api — /api/tasks, /api/task-logs ─────────
        elif (parsed_path.path in ('/api/tasks', '/api/tasks/kanban', '/api/task-logs',
                                    '/api/agents/status')
              or parsed_path.path.startswith('/api/tasks/') and parsed_path.path.endswith('/comments')):
            _params = parse_qs(parsed_path.query)
            tasks_api.handle_get(
                self, parsed_path.path, _params,
                DATA_DIR=DATA_DIR,
                list_tasks=list_tasks,
                current_project_id=_current_project_id(),
                list_task_comments=list_task_comments,
                list_agent_status=list_agent_status,
            )

        # ── [모듈 위임] tools_api — /api/tools/* (도구 설치 상태) ──────
        elif parsed_path.path.startswith('/api/tools/'):
            from api import tools_api
            _params = parse_qs(parsed_path.query)
            tools_api.handle_get(self, parsed_path.path, _params)

        # ── [모듈 위임] files_api — /api/files, /api/read-file ────────
        elif parsed_path.path in ('/api/files', '/api/read-file'):
            _params = parse_qs(parsed_path.query)
            files_api.handle_get(
                self, parsed_path.path, _params,
                PROJECT_ROOT=_current_project_root(),
                validate_file_path=_validate_file_path,
            )

        elif parsed_path.path == '/api/dirs':
            self.send_response(200)
            self.send_header('Content-Type', 'application/json;charset=utf-8')
            self.send_header('Access-Control-Allow-Origin', self._cors_origin())
            self.end_headers()
            query = parse_qs(parsed_path.query)
            target_path = query.get('path', [''])[0]
            dirs = []
            if target_path and os.path.exists(target_path) and os.path.isdir(target_path):
                try:
                    for entry in os.scandir(target_path):
                        # .으로 시작하는 숨김 폴더 중 주요 설정 폴더는 허용
                        if entry.is_dir() and (not entry.name.startswith('.') or entry.name in ('.claude', '.ai_monitor', '.gemini', '.github')):
                            dirs.append({"name": entry.name, "path": entry.path.replace('\\', '/')})
                except Exception as e:
                    print(f"[FILE ERROR] /api/dirs scandir: {e}")
            dirs.sort(key=lambda x: x['name'].lower())
            try:
                self.wfile.write(json.dumps(dirs).encode('utf-8'))
                self.wfile.flush()
            except Exception as _e:
                print(f'[/api/dirs write ERROR] {_e}', flush=True)
        elif parsed_path.path == '/api/help':
            self.send_response(200)
            self.send_header('Content-Type', 'application/json;charset=utf-8')
            self.send_header('Access-Control-Allow-Origin', self._cors_origin())
            self.end_headers()
            query = parse_qs(parsed_path.query)
            topic = query.get('topic', [''])[0]
            docs_dir = Path(__file__).parent / 'docs'
            help_file = docs_dir / f'help-{topic}.md'
            if help_file.exists():
                content = help_file.read_text(encoding='utf-8')
                self.wfile.write(json.dumps({"content": content}).encode('utf-8'))
            else:
                self.wfile.write(json.dumps({"error": "Help topic not found"}).encode('utf-8'))
            return

        elif parsed_path.path == '/api/image-file':
            query = parse_qs(parsed_path.query)
            raw_path = query.get('path', [''])[0]
            try:
                target_path = _validate_file_path(raw_path)
            except ValueError:
                self.send_response(403)
                self.send_header('Access-Control-Allow-Origin', self._cors_origin())
                self.end_headers()
                return
            IMAGE_MIME = {
                'png': 'image/png', 'jpg': 'image/jpeg', 'jpeg': 'image/jpeg',
                'gif': 'image/gif', 'webp': 'image/webp', 'svg': 'image/svg+xml',
                'bmp': 'image/bmp', 'ico': 'image/x-icon',
            }
            ext = str(target_path).rsplit('.', 1)[-1].lower() if '.' in str(target_path) else ''
            mime = IMAGE_MIME.get(ext, 'application/octet-stream')
            if not target_path.exists() or not target_path.is_file():
                self.send_response(404)
                self.end_headers()
                return
            self.send_response(200)
            self.send_header('Content-Type', mime)
            self.send_header('Access-Control-Allow-Origin', self._cors_origin())
            self.end_headers()
            with open(target_path, 'rb') as f:
                self.wfile.write(f.read())

        # [2026-03-22] /api/read-file → files_api.py로 위임됨 (상단 모듈 위임 섹션)

        # [2026-03-22 추가] 서버 로그 뷰어 API — server_error.log + pgsql.log 내용 반환
        # 환경설정(보기 메뉴)에서 로그를 실시간으로 확인하고 클립보드 복사 가능
        elif parsed_path.path == '/api/server-logs':
            self.send_response(200)
            self.send_header('Content-Type', 'application/json;charset=utf-8')
            self.send_header('Access-Control-Allow-Origin', self._cors_origin())
            self.end_headers()
            query = parse_qs(parsed_path.query)
            # tail 줄 수 (기본 200줄)
            tail_n = int(query.get('lines', ['200'])[0])
            log_type = query.get('type', ['server'])[0]  # server | pgsql | task
            logs_data: dict = {"type": log_type, "lines": [], "path": ""}
            try:
                if log_type == 'pgsql':
                    log_path = DATA_DIR.parent / "pgsql.log"
                    if not log_path.exists():
                        log_path = DATA_DIR / "pgsql.log"
                elif log_type == 'task':
                    log_path = DATA_DIR / "task_logs.jsonl"
                else:
                    log_path = DATA_DIR / "server_error.log"
                logs_data["path"] = str(log_path)
                if log_path.exists():
                    all_lines = log_path.read_text(encoding='utf-8', errors='replace').splitlines()
                    logs_data["lines"] = all_lines[-tail_n:]
                else:
                    logs_data["lines"] = [f"(로그 파일 없음: {log_path})"]
            except Exception as e:
                logs_data["lines"] = [f"(로그 읽기 오류: {e})"]
            body = json.dumps(logs_data, ensure_ascii=False).encode('utf-8')
            self.wfile.write(body)

        elif parsed_path.path == '/api/check-update-ready':
            update_api.check_update_ready(self, DATA_DIR, __version__)

        elif parsed_path.path == '/api/trigger-update-check':
            update_api.trigger_update_check(self, DATA_DIR)

        elif parsed_path.path == '/api/soft-update/check':
            update_api.soft_update_check(self, DATA_DIR, _soft_src_dir())

        elif parsed_path.path == '/api/heal/metrics':
            # [설계] 전체(global) 집계 — CLI heal_report와 일치. project_id 슬러그 불일치로
            #   숫자가 0으로 오도되는 것 방지(설치/dev 슬러그 분기 [[project_installed_empty_panels]]).
            heal_api.handle_get(self, '')

        elif parsed_path.path == '/api/copy-path':
            self.send_response(200)
            self.send_header('Content-Type', 'application/json;charset=utf-8')
            self.send_header('Access-Control-Allow-Origin', self._cors_origin())
            self.end_headers()
            query = parse_qs(parsed_path.query)
            target_path = query.get('path', [''])[0]
            try:
                # Windows 클립보드에 경로 복사
                # CREATE_NO_WINDOW: PowerShell 콘솔 창이 순간 깜빡이는 문제 방지
                if os.name == 'nt':
                    _no_window = getattr(subprocess, 'CREATE_NO_WINDOW', 0x08000000)
                    subprocess.run(
                        ['powershell', '-WindowStyle', 'Hidden', '-Command', f'Set-Clipboard -Value "{target_path}"'],
                        check=True, encoding='utf-8', creationflags=_no_window
                    )
                self.wfile.write(json.dumps({"status": "success", "message": "Path copied to clipboard"}).encode('utf-8'))
            except Exception as e:
                self.wfile.write(json.dumps({"status": "error", "message": str(e)}).encode('utf-8'))

        elif parsed_path.path == '/api/messages':
            # 에이전트 간 메시지 채널 목록 반환 (최신 100개, SQLite 연동)
            self.send_response(200)
            self.send_header('Content-Type', 'application/json;charset=utf-8')
            self.send_header('Access-Control-Allow-Origin', self._cors_origin())
            self.end_headers()
            try:
                msgs = get_messages(100)
                self.wfile.write(json.dumps(msgs, ensure_ascii=False).encode('utf-8'))
            except Exception as e:
                self.wfile.write(json.dumps({'error': str(e)}).encode('utf-8'))
        # [2026-03-22] /api/tasks, /api/tasks/kanban, /api/task-logs → tasks_api.py로 위임됨

        elif parsed_path.path == '/api/kanban/pg-activity':
            # Postgres-First 칸반 데이터: pg_logs에서 최근 8시간 터미널별 활동 조회
            # 응답: { "T1": [{agent, task, status, ts}, ...], "T2": [...], ... }
            self.send_response(200)
            self.send_header('Content-Type', 'application/json;charset=utf-8')
            self.send_header('Access-Control-Allow-Origin', self._cors_origin())
            self.end_headers()
            try:
                rows = run_pg_sql_csv(
                    "SELECT terminal_id, agent, task, status, "
                    "to_char(ts, 'HH24:MI:SS') AS ts "
                    "FROM pg_logs "
                    "WHERE ts > NOW() - INTERVAL '8 hours' AND (project_id=%s OR project_id='') "
                    "ORDER BY ts DESC LIMIT 300",
                    (_current_project_id(),)
                )
                # 터미널별 그룹화 (최대 15개/터미널)
                by_terminal: dict = {}
                for row in rows:
                    tid = row.get('terminal_id') or 'T0'
                    if tid not in by_terminal:
                        by_terminal[tid] = []
                    if len(by_terminal[tid]) < 15:
                        by_terminal[tid].append(row)
                self.wfile.write(json.dumps(by_terminal, ensure_ascii=False).encode('utf-8'))
            except Exception as e:
                self.wfile.write(json.dumps({"error": str(e)}).encode('utf-8'))

        elif parsed_path.path == '/api/memory/db-info':
            # 현재 사용 중인 공유 메모리 DB 경로 및 항목 수 반환
            # 배포 버전에서 어떤 DB를 바라보고 있는지 UI에서 확인할 수 있게 함
            self.send_response(200)
            self.send_header('Content-Type', 'application/json;charset=utf-8')
            self.send_header('Access-Control-Allow-Origin', self._cors_origin())
            self.end_headers()
            try:
                ensure_schema(DATA_DIR)
                rows = query_rows("SELECT COUNT(*) AS count FROM hive_memory;")
                count = int(rows[0].get('count', 0)) if rows else 0
                self.wfile.write(json.dumps({
                    'db_path': f'postgres://localhost:{PG_PORT}/{PG_PROJECT_DB}',
                    'is_local': False,
                    'backend': 'postgres',
                    'count': count,
                }, ensure_ascii=False).encode('utf-8'))
            except Exception as e:
                self.wfile.write(json.dumps({'error': str(e), 'count': 0}).encode('utf-8'))

        else:
            # 정적 파일 서비스 로직 (Vite 빌드 결과물)
            # 요청 경로를 정리
            path = self.path
            if path == '/':
                path = '/index.html'

            # /monitor → 에이전트 상황판 독립 페이지
            if path.rstrip('/') == '/monitor':
                path = '/monitor.html'
            
            # 쿼리스트링 제거
            path = path.split('?')[0]
            
            filepath = STATIC_DIR / path.lstrip('/')
            
            # 파일이 없으면 index.html로 Fallback (SPA 특성)
            if not filepath.exists() or not filepath.is_file():
                filepath = STATIC_DIR / 'index.html'
                
            if filepath.exists() and filepath.is_file():
                try:
                    with open(filepath, 'rb') as f:
                        content = f.read()
                    self.send_response(200)
                    mimetype, _ = mimetypes.guess_type(str(filepath))
                    if filepath.suffix == '.js':
                        mimetype = 'application/javascript'
                    elif filepath.suffix == '.css':
                        mimetype = 'text/css'
                    elif filepath.suffix == '.svg':
                        mimetype = 'image/svg+xml'
                    self.send_header('Content-Type', mimetype or 'application/octet-stream')
                    self.send_header('Cache-Control', 'no-cache, no-store, must-revalidate')
                    self.send_header('Pragma', 'no-cache')
                    self.send_header('Expires', '0')
                    self.end_headers()
                    self.wfile.write(content)
                except Exception as e:
                    self.send_response(500)
                    self.end_headers()
                    self.wfile.write(str(e).encode('utf-8'))
            else:
                self.send_response(404)
                self.end_headers()
                self.wfile.write(b"Not Found")

    def do_OPTIONS(self):
        self.send_response(200)
        self.send_header('Access-Control-Allow-Origin', self._cors_origin())
        self.send_header('Access-Control-Allow-Methods', 'GET, POST, PUT, DELETE, OPTIONS')
        self.send_header('Access-Control-Allow-Headers', 'Content-Type, Authorization')
        self.end_headers()

    def do_PUT(self):
        """PUT 메소드 — 오피스 API는 오피스 서버로 프록시."""
        parsed_path = urlparse(self.path)
        path = parsed_path.path
        _set_request_pid(parsed_path.query)  # Phase 2-5.2: ?project_id= override
        if path.startswith('/api/office/'):
            length = int(self.headers.get('Content-Length', '0') or 0)
            body = self.rfile.read(length) if length > 0 else None
            _proxy_to_office_server(self, method='PUT', body=body)
            return
        self.send_response(404)
        self.send_header('Content-Type', 'application/json;charset=utf-8')
        self.send_header('Access-Control-Allow-Origin', self._cors_origin())
        self.end_headers()
        self.wfile.write(b'{"error":"not found"}')

    def do_DELETE(self):
        """DELETE 메소드 — 오피스 API는 오피스 서버로 프록시, PTY는 Node로 프록시."""
        parsed_path = urlparse(self.path)
        path = parsed_path.path
        _set_request_pid(parsed_path.query)  # Phase 2-5.2: ?project_id= override
        if path.startswith('/api/office/'):
            length = int(self.headers.get('Content-Length', '0') or 0)
            body = self.rfile.read(length) if length > 0 else None
            _proxy_to_office_server(self, method='DELETE', body=body)
            return
        if path.startswith('/api/pty/'):
            pty_api.handle_delete(self, path)
            return
        self.send_response(404)
        self.send_header('Content-Type', 'application/json;charset=utf-8')
        self.send_header('Access-Control-Allow-Origin', self._cors_origin())
        self.end_headers()
        self.wfile.write(b'{"error":"not found"}')

    def do_POST(self):
        parsed_path = urlparse(self.path)
        path = parsed_path.path
        _set_request_pid(parsed_path.query)  # Phase 2-5.2: ?project_id= override

        # ── 라우트 테이블 우선 조회(Phase 1 Task 3) → miss 시 아래 if/elif 폴백 ──
        # [불변식] exact 먼저 → prefix 나중. POST는 exact-prefix 충돌이 있어 순서 필수
        #   (예: /api/git/rollback은 인라인 잔류이고 /api/git/는 애초에 테이블 미이전).
        _exact = POST_ROUTES.get(path)
        if _exact is not None:
            _exact(self, parsed_path)
            return
        for _pfx, _fn in POST_PREFIX_ROUTES:
            if path.startswith(_pfx):
                _fn(self, parsed_path)
                return

        # ── 오피스 API POST → 오피스 서버 프록시 (launch/restart/status 제외) ──
        if path.startswith('/api/office/') and path not in (
            '/api/office/launch', '/api/office/restart', '/api/office/status',
        ):
            _cl = int(self.headers.get('Content-Length', '0') or 0)
            _raw = self.rfile.read(_cl) if _cl > 0 else None
            _proxy_to_office_server(self, method='POST', body=_raw)
            return

        # ─── 칸반 보드 네이티브 창 실행 ──────────────────────────────────────
        # window.open() 대신 PySide6 네이티브 프로세스를 직접 실행하여
        # 인터넷 브라우저 창이 아닌 OS 네이티브 데스크톱 창으로 띄웁니다.
        if path == '/api/dashboard/launch':
            self.send_response(200)
            self.send_header('Content-Type', 'application/json;charset=utf-8')
            self.send_header('Access-Control-Allow-Origin', self._cors_origin())
            self.end_headers()
            try:
                tab = 'agent'
                content_length = int(self.headers.get('Content-Length', 0))
                if content_length > 0:
                    body = self.rfile.read(content_length).decode('utf-8')
                    payload = json.loads(body or '{}')
                    if isinstance(payload, dict):
                        tab = str(payload.get('tab', 'agent')).strip().lower() or 'agent'

                _no_window = getattr(subprocess, 'CREATE_NO_WINDOW', 0x08000000)
                # Python 스크립트로 대시보드 창 실행
                dashboard_script = BASE_DIR / 'dashboard_window.py'
                python_cmds = _python_runner_cmds()
                if not python_cmds:
                    raise RuntimeError('Python interpreter not found for dashboard launch')
                subprocess.Popen(
                    [python_cmds[0], str(dashboard_script), str(HTTP_PORT), tab],
                    creationflags=_no_window,
                    close_fds=True,
                )
                self.wfile.write(json.dumps({"status": "launched", "tab": tab}).encode('utf-8'))
            except Exception as e:
                self.wfile.write(json.dumps({"status": "error", "message": str(e)}).encode('utf-8'))
            return

        if path == '/api/open-external':
            self.send_response(200)
            self.send_header('Content-Type', 'application/json;charset=utf-8')
            self.send_header('Access-Control-Allow-Origin', self._cors_origin())
            self.end_headers()
            try:
                content_length = int(self.headers.get('Content-Length', 0))
                payload = {}
                if content_length > 0:
                    body = self.rfile.read(content_length).decode('utf-8')
                    payload = json.loads(body or '{}')

                url = str(payload.get('url', '')).strip()
                parsed_url = urlparse(url)
                if not url or parsed_url.scheme not in ('http', 'https'):
                    raise ValueError('Only http/https URLs can be opened externally')

                opened = webbrowser.open(url)
                self.wfile.write(json.dumps({
                    "status": "ok",
                    "opened": bool(opened),
                    "url": url,
                }).encode('utf-8'))
            except Exception as e:
                self.wfile.write(json.dumps({
                    "status": "error",
                    "message": str(e),
                }).encode('utf-8'))
            return

        if path == '/api/install-playwright-cli':
            self.send_response(200)
            self.send_header('Content-Type', 'application/json;charset=utf-8')
            self.send_header('Access-Control-Allow-Origin', self._cors_origin())
            self.end_headers()
            try:
                content_length = int(self.headers.get('Content-Length', 0))
                payload = {}
                if content_length > 0:
                    payload = json.loads(self.rfile.read(content_length).decode('utf-8') or '{}')

                project_root = _current_project_root()
                requested_root = str(payload.get('project_path', '')).strip()
                if requested_root:
                    requested_path = Path(requested_root).expanduser()
                    if requested_path.is_dir():
                        project_root = requested_path.resolve()

                script_path = _resolve_playwright_install_script()
                if not script_path:
                    raise RuntimeError('install_playwright_cli.py not found')

                python_cmd = _project_python_runner_cmds(project_root)[0]
                install_cmd = subprocess.list2cmdline([python_cmd, str(script_path)])
                cmdline = (
                    'title Vibe Coding - Playwright Installer && '
                    'echo Working directory: %CD% && '
                    'echo. && '
                    'echo Installing Playwright CLI and Chromium browser... && '
                    f'{install_cmd} && '
                    'echo. && echo Playwright installation completed. You can close this window. || '
                    'echo. && echo Playwright installation failed. Review the log above before closing this window.'
                )
                create_new_console = getattr(subprocess, 'CREATE_NEW_CONSOLE', 0x00000010)
                subprocess.Popen(
                    ['cmd.exe', '/k', cmdline],
                    cwd=str(project_root),
                    close_fds=True,
                    creationflags=create_new_console,
                )
                self.wfile.write(json.dumps({
                    "status": "success",
                    "message": f"Playwright installation started for {project_root}. A console window was opened so you can inspect the result.",
                    "project_path": str(project_root),
                    "python": python_cmd,
                }, ensure_ascii=False).encode('utf-8'))
            except Exception as e:
                self.wfile.write(json.dumps({
                    "status": "error",
                    "message": str(e),
                }, ensure_ascii=False).encode('utf-8'))
            return

        # [2026-03-30 Claude] 하네스 V2 스크립트 실행 API
        # AI 도구 메뉴에서 harness_verify.py, session_init.py 등을 실행
        if path == '/api/run-script':
            self.send_response(200)
            self.send_header('Content-Type', 'application/json;charset=utf-8')
            self.send_header('Access-Control-Allow-Origin', self._cors_origin())
            self.end_headers()
            try:
                content_length = int(self.headers.get('Content-Length', 0))
                payload = json.loads(self.rfile.read(content_length).decode('utf-8') or '{}') if content_length > 0 else {}
                script_name = payload.get('script', '')
                # 허용된 스크립트 목록 및 Claude Code 프롬프트 매핑
                _ALLOWED_SCRIPTS = {
                    'harness_verify': {
                        'script': 'scripts/harness_verify.py',
                        'args': ['--json'],
                        'prompt': '해당 프로젝트 폴더에서 Claude Code를 실행한 뒤 다음을 입력하세요:\n\npython scripts/harness_verify.py --json',
                    },
                    'session_init': {
                        'script': 'scripts/session_init.py',
                        'args': ['--agent', 'claude'],
                        'prompt': '해당 프로젝트 폴더에서 Claude Code를 실행한 뒤 다음을 입력하세요:\n\npython scripts/session_init.py --agent claude',
                    },
                    'harness_init': {
                        'script': None,
                        'prompt': '해당 프로젝트 폴더에서 Claude Code를 실행한 뒤 /vibe-harness-init 명령을 입력하세요.',
                    },
                }
                if script_name not in _ALLOWED_SCRIPTS:
                    raise ValueError(f'허용되지 않은 스크립트: {script_name}')
                info = _ALLOWED_SCRIPTS[script_name]
                script_rel = info['script']
                # EXE(설치) 모드: 스크립트 실행 대신 Claude Code 프롬프트 안내
                if getattr(sys, 'frozen', False) or script_rel is None:
                    self.wfile.write(json.dumps({
                        "status": "prompt",
                        "output": info['prompt'],
                    }, ensure_ascii=False).encode('utf-8'))
                else:
                    # 개발 모드: 직접 스크립트 실행
                    project_root = _current_project_root()
                    script_path = project_root / script_rel
                    if not script_path.exists():
                        raise FileNotFoundError(f'{script_rel} not found')
                    no_win = getattr(subprocess, 'CREATE_NO_WINDOW', 0x08000000)
                    result = subprocess.run(
                        [sys.executable, str(script_path)] + info.get('args', []),
                        capture_output=True, text=True,
                        encoding='utf-8', errors='replace',
                        timeout=15, cwd=str(project_root),
                        creationflags=no_win,
                    )
                    self.wfile.write(json.dumps({
                        "status": "ok" if result.returncode == 0 else "fail",
                        "output": result.stdout[:2000],
                        "error": result.stderr[:500] if result.returncode != 0 else "",
                    }, ensure_ascii=False).encode('utf-8'))
            except Exception as e:
                self.wfile.write(json.dumps({
                    "status": "error",
                    "message": str(e),
                }, ensure_ascii=False).encode('utf-8'))
            return

        if path == '/api/kanban/launch':
            # B안 통합: kanban_board.py(PySide6 네이티브) 제거 →
            # dashboard_window.py + React TaskBoardPanel(?kanban=1)으로 일원화.
            # 동일한 API(/api/orchestrator/skill-chain 등)를 통해 데이터 일관성 확보.
            self.send_response(200)
            self.send_header('Content-Type', 'application/json;charset=utf-8')
            self.send_header('Access-Control-Allow-Origin', self._cors_origin())
            self.end_headers()
            try:
                _no_window = getattr(subprocess, 'CREATE_NO_WINDOW', 0x08000000)
                # dashboard_window.py kanban 탭으로 실행
                dashboard_script = BASE_DIR / 'dashboard_window.py'
                python_cmds = _python_runner_cmds()
                if not python_cmds:
                    raise RuntimeError('Python interpreter not found for kanban launch')
                subprocess.Popen(
                    [python_cmds[0], str(dashboard_script), str(HTTP_PORT), 'kanban'],
                    creationflags=_no_window,
                    close_fds=True,
                )
                self.wfile.write(json.dumps({"status": "launched"}).encode('utf-8'))
            except Exception as e:
                self.wfile.write(json.dumps({"status": "error", "message": str(e)}).encode('utf-8'))
            return

        # ── 오피스 독립 서버 + 창 실행 ──
        # office_server.py를 별도 프로세스로 시작 → 포트 확인 → dashboard_window.py 실행
        if path == '/api/office/launch':
            self.send_response(200)
            self.send_header('Content-Type', 'application/json;charset=utf-8')
            self.send_header('Access-Control-Allow-Origin', self._cors_origin())
            self.end_headers()
            try:
                # 이미 오피스 서버가 실행 중이면 재사용
                if _office_state.alive and _office_state.port:
                    office_port = _office_state.port
                else:
                    office_port = _launch_office_server()
                # 오피스 대시보드 창 실행 (오피스 서버 포트 전달)
                _no_window = getattr(subprocess, 'CREATE_NO_WINDOW', 0x08000000)
                dashboard_script = BASE_DIR / 'dashboard_window.py'
                python_cmds = _python_runner_cmds()
                if not python_cmds:
                    raise RuntimeError('Python interpreter not found for office launch')
                subprocess.Popen(
                    [python_cmds[0], str(dashboard_script), str(office_port), 'office'],
                    creationflags=_no_window,
                    close_fds=True,
                )
                self.wfile.write(json.dumps({
                    "status": "launched",
                    "office_port": office_port,
                }).encode('utf-8'))
            except Exception as e:
                self.wfile.write(json.dumps({"status": "error", "message": str(e)}).encode('utf-8'))
            return

        # ── 오피스 서버 재시작 ──
        if path == '/api/office/restart':
            self.send_response(200)
            self.send_header('Content-Type', 'application/json;charset=utf-8')
            self.send_header('Access-Control-Allow-Origin', self._cors_origin())
            self.end_headers()
            try:
                new_port = _restart_office_server()
                self.wfile.write(json.dumps({
                    "status": "restarted", "office_port": new_port,
                }).encode('utf-8'))
            except Exception as e:
                self.wfile.write(json.dumps({"status": "error", "message": str(e)}).encode('utf-8'))
            return

        # ── 오피스 서버 상태 조회 ──
        if path == '/api/office/status':
            self.send_response(200)
            self.send_header('Content-Type', 'application/json;charset=utf-8')
            self.send_header('Access-Control-Allow-Origin', self._cors_origin())
            self.end_headers()
            alive = _office_state.alive
            self.wfile.write(json.dumps({
                "running": alive,
                "port": _office_state.port if alive else None,
                "pid": _office_state.proc.pid if alive and _office_state.proc else None,
            }).encode('utf-8'))
            return

        # [2026-03-22] /api/graph/launch 제거 (지식그래프 삭제)
        # [2026-04-18] /api/eval-review/launch 제거 (디스패처 정리)

        # ─── 신규: 사고 과정 로그 추가 (v5.0) ───
        # ─── 신규: PostgreSQL 통합 로깅 API (v5.0) ───
        if path == '/api/hive/log/pg':
            self.send_response(200)
            self.send_header('Content-Type', 'application/json;charset=utf-8')
            self.send_header('Access-Control-Allow-Origin', self._cors_origin())
            self.end_headers()
            try:
                content_length = int(self.headers['Content-Length'])
                data = json.loads(self.rfile.read(content_length).decode('utf-8'))
                log_to_pg(
                    agent=data.get('agent', 'unknown'),
                    terminal_id=data.get('terminal_id', 'T0'),
                    task=data.get('task', ''),
                    status=data.get('status', 'success')
                )
                self.wfile.write(json.dumps({"status": "success"}).encode('utf-8'))
            except Exception as e:
                self.wfile.write(json.dumps({"status": "error", "message": str(e)}).encode('utf-8'))
            return

        if path == '/api/hive/thought/pg':
            self.send_response(200)
            self.send_header('Content-Type', 'application/json;charset=utf-8')
            self.send_header('Access-Control-Allow-Origin', self._cors_origin())
            self.end_headers()
            try:
                content_length = int(self.headers['Content-Length'])
                data = json.loads(self.rfile.read(content_length).decode('utf-8'))
                # parent_id를 받아 지식 그래프 연결선 생성 지원
                new_id = thought_to_pg(
                    agent=data.get('agent', 'unknown'),
                    skill=data.get('skill', 'general'),
                    thought=data.get('thought', {}),
                    parent_id=data.get('parent_id')
                )
                self.wfile.write(json.dumps({"status": "success", "id": new_id}).encode('utf-8'))
            except Exception as e:
                self.wfile.write(json.dumps({"status": "error", "message": str(e)}).encode('utf-8'))
            return

        if path == '/api/thoughts/add':
            self.send_response(200)
            self.send_header('Content-Type', 'application/json;charset=utf-8')
            self.send_header('Access-Control-Allow-Origin', self._cors_origin())
            self.end_headers()
            try:
                content_length = int(self.headers['Content-Length'])
                data = json.loads(self.rfile.read(content_length).decode('utf-8'))

                # 데이터 유효성 검사 및 타임스탬프 추가
                data['timestamp'] = datetime.now().isoformat()
                THOUGHT_LOGS.append(data)
                if len(THOUGHT_LOGS) > 100:
                    THOUGHT_LOGS.pop(0)

                # ── 실시간 SSE 브로드캐스트 ──────────────────────────────
                msg = f"data: {json.dumps(data, ensure_ascii=False)}\n\n"
                disconnected = []
                with _SSE_LOCK:
                    clients_snapshot = list(THOUGHT_CLIENTS)
                for client in clients_snapshot:
                    try:
                        client.wfile.write(msg.encode('utf-8'))
                        client.wfile.flush()
                    except Exception:
                        disconnected.append(client)
                if disconnected:
                    with _SSE_LOCK:
                        for client in disconnected:
                            THOUGHT_CLIENTS.discard(client)

                # ── 벡터 DB에 영구 저장 ──────────────────────────────────
                try:
                    agent   = data.get('agent', 'unknown')
                    thought = data.get('thought', '')
                    level   = data.get('level', 'info')
                    tool    = data.get('tool', '')
                    step    = data.get('step', '')
                    ts_ms   = str(int(time.time() * 1000))

                    key     = f"thought:{agent}:{ts_ms}"
                    title   = f"[{level}] {thought[:80]}"
                    content = thought
                    if tool:  content += f"\n🔧 tool: {tool}"
                    if step:  content += f"\n📍 step: {step}"

                    tags = ['thought', level, agent]
                    set_memory(
                        key=key,
                        title=title,
                        content=content,
                        tags=tags,
                        author=agent,
                        project_id=PROJECT_ID,
                        created_at=data['timestamp'],
                        updated_at=data['timestamp'],
                    )

                    print(f"🧠 [Thought→DB] {key}")
                except Exception as db_err:
                    print(f"[Thought→DB] 저장 실패 (무시): {db_err}")
                # ─────────────────────────────────────────────────────────

                print(f"🧠 [Thought Trace] New thought captured: {data.get('thought', '')[:50]}...")
                self.wfile.write(json.dumps({"status": "success"}).encode('utf-8'))
            except Exception as e:
                print(f"[Error] /api/thoughts/add failed: {e}")
                self.wfile.write(json.dumps({"status": "error", "message": str(e)}).encode('utf-8'))
            return

        # [Phase 1 Task 3] tools/files/apply-update/soft-update/trigger-update/projects/experience/
        #   config-update/launch/send-command/locks/message/vibe·zettel·codegraph·memory·agent·pty는
        #   상단 POST_ROUTES/POST_PREFIX_ROUTES로 이전 — 아래는 인라인 로직 + 복합조건 라우트만 잔류.
        if parsed_path.path == '/api/agents/heartbeat':
            # 에이전트 실시간 상태 보고 수신
            self.send_response(200)
            self.send_header('Content-Type', 'application/json;charset=utf-8')
            self.send_header('Access-Control-Allow-Origin', self._cors_origin())
            self.end_headers()
            try:
                content_length = int(self.headers['Content-Length'])
                data = json.loads(self.rfile.read(content_length).decode('utf-8'))
                agent_name = data.get('agent')
                if not agent_name:
                    self.wfile.write(json.dumps({"status": "error", "message": "Agent name is required"}).encode('utf-8'))
                    return
                
                agent_status = data.get("status", "active")
                agent_task = data.get("task")
                now_ts = time.time()
                with AGENT_STATUS_LOCK:
                    AGENT_STATUS[agent_name] = {
                        "status": agent_status,
                        "task": agent_task,
                        "last_seen": now_ts,
                    }
                # PostgreSQL에도 영구 기록 (재시작 시 복구용)
                try:
                    # heartbeat UPSERT는 항상 실행 (상태 갱신)
                    record_heartbeat(agent_name, status=agent_status,
                                     current_task=agent_task)
                    # pg_logs는 상태 변경 시에만 기록 (무제한 증가 방지)
                    prev = AGENT_STATUS.get(agent_name, {})
                    prev_status = prev.get('status')
                    if prev_status != agent_status:
                        insert_pg_log(
                            agent=agent_name, task=agent_task or '',
                            status=agent_status,
                            metadata={'source': 'heartbeat', 'prev': prev_status},
                        )
                except Exception:
                    pass  # DB 실패해도 인메모리는 유지
                self.wfile.write(json.dumps({"status": "success"}).encode('utf-8'))
            except Exception as e:
                self.wfile.write(json.dumps({"status": "error", "message": str(e)}).encode('utf-8'))
        elif parsed_path.path == '/api/git/rollback':
            # 특정 파일 변경사항 원상복구 (git checkout -- 파일)
            self.send_response(200)
            self.send_header('Content-Type', 'application/json;charset=utf-8')
            self.send_header('Access-Control-Allow-Origin', self._cors_origin())
            self.end_headers()
            try:
                content_length = int(self.headers['Content-Length'])
                data = json.loads(self.rfile.read(content_length).decode('utf-8'))
                file_path = data.get('file')
                git_dir = data.get('path', str(BASE_DIR.parent))
                
                if not file_path:
                    self.wfile.write(json.dumps({"status": "error", "message": "File path required"}).encode('utf-8'))
                    return
                
                # git checkout -- "파일명" 실행
                result = subprocess.run(
                    ['git', 'checkout', '--', file_path],
                    cwd=git_dir, capture_output=True, text=True, timeout=10, encoding='utf-8',
                    creationflags=0x08000000
                )
                
                if result.returncode == 0:
                    self.wfile.write(json.dumps({"status": "success"}).encode('utf-8'))
                else:
                    self.wfile.write(json.dumps({"status": "error", "message": result.stderr.strip()}).encode('utf-8'))
            except Exception as e:
                self.wfile.write(json.dumps({"status": "error", "message": str(e)}).encode('utf-8'))
        elif parsed_path.path == '/api/git/diff':
            self.send_response(200)
            self.send_header('Content-Type', 'application/json;charset=utf-8')
            self.send_header('Access-Control-Allow-Origin', self._cors_origin())
            self.end_headers()
            query = parse_qs(parsed_path.query)
            target_file = query.get('path', [''])[0]
            git_dir = query.get('git_path', [str(BASE_DIR.parent)])[0]
            
            try:
                # git diff "파일명" 실행
                result = subprocess.run(
                    ['git', 'diff', '--', target_file],
                    cwd=git_dir, capture_output=True, text=True, timeout=5, encoding='utf-8',
                    creationflags=0x08000000
                )
                self.wfile.write(json.dumps({"diff": result.stdout}).encode('utf-8'))
            except Exception as e:
                self.wfile.write(json.dumps({"error": str(e)}).encode('utf-8'))

        # ── [모듈 위임 - POST] hive_api ──────────────────────────────────
        # /api/hive/approve-skill, /api/orchestrator/skill-chain/update,
        # /api/orchestrator/run, /api/superpowers/install|uninstall
        elif (parsed_path.path.startswith('/api/hive/') or
              parsed_path.path.startswith('/api/orchestrator/') or
              parsed_path.path.startswith('/api/superpowers/')):
            from api import hive_api
            content_length = int(self.headers.get('Content-Length', 0))
            _body = json.loads(self.rfile.read(content_length).decode('utf-8')) if content_length else {}
            hive_api.handle_post(
                self, parsed_path.path, _body,
                DATA_DIR=DATA_DIR, SCRIPTS_DIR=SCRIPTS_DIR, BASE_DIR=BASE_DIR,
                PROJECT_ROOT=PROJECT_ROOT,
                _current_project_root=_current_project_root,
            )

        # ── [모듈 위임 - POST] git_api ────────────────────────────────────
        # /api/git/rollback, /api/git/diff (쿼리스트링 방식)
        elif parsed_path.path.startswith('/api/git/'):
            from api import git_api
            from urllib.parse import parse_qs as _parse_qs
            # /api/git/diff는 query string 방식이므로 query dict를 data로 전달
            _qs = _parse_qs(parsed_path.query)
            if parsed_path.path == '/api/git/diff':
                git_api.handle_post(self, parsed_path.path, _qs, BASE_DIR=BASE_DIR)
            else:
                content_length = int(self.headers.get('Content-Length', 0))
                _body = json.loads(self.rfile.read(content_length).decode('utf-8')) if content_length else {}
                git_api.handle_post(self, parsed_path.path, _body, BASE_DIR=BASE_DIR)

        elif parsed_path.path == '/api/select-folder':
            # 폴더 선택 다이얼로그 — tkinter 별도 프로세스 방식
            # pywebview의 create_file_dialog()는 GUI 스레드 제한으로 HTTP 핸들러에서 호출 불가
            # 독립 Python 프로세스로 tkinter를 실행하여 안정적으로 동작
            self.send_response(200)
            self.send_header('Content-Type', 'application/json;charset=utf-8')
            self.send_header('Access-Control-Allow-Origin', self._cors_origin())
            self.end_headers()
            try:
                path = _open_folder_dialog_subprocess()
                if path:
                    # 선택된 경로를 설정에도 즉시 저장
                    config = {}
                    if CONFIG_FILE.exists():
                        try:
                            with open(CONFIG_FILE, 'r', encoding='utf-8') as f:
                                config = json.load(f)
                        except: pass
                    config['last_path'] = path
                    with open(CONFIG_FILE, 'w', encoding='utf-8') as f:
                        json.dump(config, f, ensure_ascii=False, indent=2)
                    self.wfile.write(json.dumps({"status": "success", "path": path}).encode('utf-8'))
                else:
                    self.wfile.write(json.dumps({"status": "cancelled"}).encode('utf-8'))
            except Exception as e:
                self.wfile.write(json.dumps({"status": "error", "message": str(e)}).encode('utf-8'))

        elif parsed_path.path == '/api/messages/clear':
            # 메시지 채널 전체 삭제 (대시보드 UI 초기화용)
            self.send_response(200)
            self.send_header('Content-Type', 'application/json;charset=utf-8')
            self.send_header('Access-Control-Allow-Origin', self._cors_origin())
            self.end_headers()
            ok = clear_messages()
            self.wfile.write(json.dumps({'status': 'ok' if ok else 'error'}).encode('utf-8'))
        # ── [모듈 위임 - POST] tasks_api — /api/tasks, update, delete, claim, comments, checkout, trigger ─
        elif (parsed_path.path in ('/api/tasks', '/api/tasks/update', '/api/tasks/delete', '/api/tasks/claim')
              or (parsed_path.path.startswith('/api/tasks/') and
                  (parsed_path.path.endswith('/comments') or parsed_path.path.endswith('/checkout')))
              or (parsed_path.path.startswith('/api/agents/') and parsed_path.path.endswith('/trigger'))):
            content_length = int(self.headers.get('Content-Length', 0))
            _body = json.loads(self.rfile.read(content_length).decode('utf-8')) if content_length else {}
            tasks_api.handle_post(
                self, parsed_path.path, _body,
                SESSIONS_FILE=SESSIONS_FILE,
                save_task=save_task, update_task=update_task, delete_task=delete_task,
                current_project_id=_current_project_id(),
                PROJECT_ID=PROJECT_ID,
                add_task_comment=add_task_comment,
                atomic_checkout=atomic_checkout,
                release_checkout=release_checkout,
                trigger_agent=trigger_agent,
            )

        elif parsed_path.path == '/api/screenshot/analyze':
            # 멀티모달 버그 감지 — 스크린샷을 Antigravity Vision API로 분석
            self.send_response(200)
            self.send_header('Content-Type', 'application/json;charset=utf-8')
            self.send_header('Access-Control-Allow-Origin', self._cors_origin())
            self.end_headers()
            try:
                content_length = int(self.headers['Content-Length'])
                data = json.loads(self.rfile.read(content_length).decode('utf-8'))
                image_b64 = data.get('image', '')
                if not image_b64:
                    self.wfile.write(json.dumps({'error': 'image (base64) is required'}).encode('utf-8'))
                elif not SCRIPTS_DIR:
                    self.wfile.write(json.dumps({'error': '설치 버전에서는 스크린샷 분석 기능을 사용할 수 없습니다'}).encode('utf-8'))
                else:
                    scripts_dir = str(SCRIPTS_DIR)
                    if scripts_dir not in sys.path:
                        sys.path.insert(0, scripts_dir)
                    from screenshot_analyzer import analyze_and_create_tasks
                    result = analyze_and_create_tasks(image_b64, project_id=PROJECT_ID)
                    self.wfile.write(json.dumps(result, ensure_ascii=False).encode('utf-8'))
            except Exception as e:
                self.wfile.write(json.dumps({'error': str(e)}).encode('utf-8'))

        else:
            self.send_response(404)
            self.end_headers()

    def log_message(self, format, *args):
        # 불필요한 콘솔 로그 제거하여 터미널 깔끔하게 유지
        pass

# [제거됨 2026-03-22] pty_sessions, pty_output_buffers, pty_output_seq 글로벌 → Node PTY 서버로 이전
# Python 서버에서 PTY 세션 정보가 필요한 경우 Node PTY 서버의 REST API를 호출합니다.
# URL: http://127.0.0.1:{WS_PORT}/api/pty/sessions
_NODE_PTY_REST_URL = None  # __main__에서 설정됨

def _get_node_pty_sessions() -> dict:
    """Node PTY 서버에서 세션 정보를 REST로 조회합니다."""
    if not _NODE_PTY_REST_URL:
        return {}
    try:
        import urllib.request
        req = urllib.request.Request(f"{_NODE_PTY_REST_URL}/api/pty/sessions")
        with urllib.request.urlopen(req, timeout=2) as resp:
            return json.loads(resp.read().decode('utf-8'))
    except Exception:
        return {}


# [제거됨 2026-03-22] _append_pty_output, getter 주입 → Node PTY 서버로 이전
# agent_api와 pty_api는 이제 Node PTY 서버의 REST API를 직접 호출합니다.

# [제거됨 2026-03-22] pty_handler 함수 전체 → Node.js pty-server.js로 이전
# 아래의 기존 코드는 모두 제거되었습니다:
# - pty_handler(): WebSocket PTY 핸들러 (~340줄)
# - _cleanup_all_pty_sessions(): PTY 세션 정리
# 대신 Node PTY 서버가 이 역할을 수행합니다.
# Python 서버는 Node PTY 서버를 subprocess로 관리하고,
# _child_procs를 통해 종료 시 자동 kill됩니다.
_REMOVED_PTY_HANDLER = True  # 마커 — 참조 점검용

# 워치독/Telegram/힐데몬 등 서버가 직접 spawn한 서브프로세스 참조 목록
# — X 버튼 종료 시 이 목록을 순회하여 모두 taskkill로 강제 종료
_child_procs: list = []

# ── 오피스 서버 프로세스 관리 — api/office_proxy_api.py로 분리 (2026-04-20) ──────
# OfficeServerState 객체 1개에 proc/port/monitor 상태를 캡슐화.
# SSEHandler 라우팅은 _office_state.proc / _office_state.port / _office_state.alive
# 를 직접 읽는다.
from api import office_proxy_api as _office_proxy
_office_proxy.setup(office_api)
_office_state = _office_proxy.OfficeServerState(
    base_dir=BASE_DIR,
    data_dir=DATA_DIR,
    http_port_getter=lambda: HTTP_PORT,
    child_procs=_child_procs,
    python_cmd_getter=_python_runner_cmds,
)


def _proxy_to_office_server(handler, method: str = 'GET', body: bytes | None = None):
    _office_proxy.proxy_to_office_server(_office_state, handler, method, body)


def _launch_office_server() -> int:
    return _office_proxy.launch_office_server(_office_state)


def _restart_office_server() -> int:
    return _office_proxy.restart_office_server(_office_state)


def _start_office_monitor():
    _office_proxy.start_office_monitor(_office_state)


# ── 라이프사이클 정리 함수 — infra/lifecycle.py로 분리 (2026-04-20) ──────────────
# 무상태 함수는 infra/lifecycle.py로, 모듈 글로벌(_child_procs/WS_PORT/PG_*)을
# 바인딩하는 얇은 래퍼만 server.py에 남김.
from infra import lifecycle as _lifecycle


def _graceful_shutdown_pty_server():
    _lifecycle.graceful_shutdown_pty_server(WS_PORT)


def _cleanup_child_procs():
    _lifecycle.cleanup_child_procs(_child_procs, WS_PORT)


def _cleanup_pyinstaller_temp():
    _lifecycle.cleanup_pyinstaller_temp()


def _cleanup_postgres():
    _lifecycle.cleanup_postgres(PG_CTL_BIN, _PG_DATA_DIR, PG_PORT, _pg_pool, _pg_pool_lock)


# ── atexit 등록 — 정상 종료(sys.exit, return from __main__)에도 PTY + 자식 프로세스 정리 보장 ──
import atexit, signal as _signal
# [제거됨] PTY 세션 정리는 Node PTY 서버가 자체 처리 + _child_procs로 프로세스 kill
atexit.register(_cleanup_child_procs)
# [주의] _cleanup_postgres는 main() 내에서만 등록 — 모듈 레벨에서 등록하면
# server.py를 import하는 모든 프로세스 종료 시 PG를 죽여버리는 치명적 버그 발생

def _signal_exit_handler(sig, frame):
    """SIGTERM / SIGBREAK(Ctrl+Break) 수신 시 PTY + 자식 프로세스 + PG 정리 후 즉시 종료."""
    print(f"[*] 시그널 {sig} 수신 — PTY 및 자식 프로세스 정리 후 종료합니다.")
    _cleanup_child_procs()  # Node PTY 서버도 _child_procs에 포함되어 자동 종료됨
    _cleanup_postgres()  # [2026-04-06] 내장 PG도 종료
    time.sleep(1)  # 자식 프로세스 파일 핸들 해제 대기
    _cleanup_pyinstaller_temp()
    os._exit(0)

_signal.signal(_signal.SIGTERM, _signal_exit_handler)
try:
    # Windows 전용 Ctrl+Break 시그널 처리 (SIGBREAK = 21)
    _signal.signal(_signal.SIGBREAK, _signal_exit_handler)
except (AttributeError, OSError):
    pass  # 비-Windows 환경에서는 SIGBREAK 없음


# 포트 설정: 9000(HTTP) / 9001(WS) — 충돌 시 빈 포트 자동 탐색 (최대 20개)
# 9000은 개발/모니터링 도구 관례 포트 (사용자 지정)
from src.server_utils import find_free_port as _find_free_port

# [수정 2026-03-15 v3.7.68] HTTP/WS 포트는 __main__ 인스턴스 락 획득 후 슬롯 기반으로 확정
# 모듈 임포트 시점에는 기본값만 설정. 실제 포트는 아래 __main__ 블록에서 덮어씀.
HTTP_PORT = 9000  # 실제 값은 __main__에서 슬롯 기반으로 재설정됨
WS_PORT   = 9001  # 실제 값은 __main__에서 슬롯 기반으로 재설정됨

# [제거됨 2026-03-22] Python WebSocket PTY 서버 → Node.js pty-server로 대체
# run_ws_server(), start_ws_server() 함수 제거
# PTY 서버는 이제 .ai_monitor/pty-server/pty-server.js에서 실행됩니다.

def open_app_window(url):
    """GUI 실행 실패 시 기본 브라우저로 대시보드를 엽니다."""
    import webbrowser
    print(f"[*] GUI 창을 띄울 수 없어 브라우저로 연결합니다: {url}")
    webbrowser.open(url)

def main():
    """메인 엔트리포인트 — pip install 시 `vibe-coding` 명령으로 호출됨.
    기존 `python server.py` 직접 실행도 동일하게 동작.
    """
    # ── CLI 인자 처리: --install / --uninstall / --create-shortcut ──
    if len(sys.argv) > 1:
        cmd = sys.argv[1]

        # --install: 바탕화면 바로가기 생성 + PTY 네이티브 모듈 빌드 (원스톱 설치)
        if cmd in ('--install', '--create-shortcut'):
            # PTY 서버 네이티브 모듈 빌드 (node-pty — 터미널 기능 핵심)
            # node -e "require('node-pty')"로 실제 로드 가능 여부 검증 후 필요시만 빌드
            if cmd == '--install':
                import shutil as _shutil
                pty_dir = Path(__file__).resolve().parent / 'pty-server'
                _need_build = True
                _no_win = getattr(subprocess, 'CREATE_NO_WINDOW', 0x08000000)
                if (pty_dir / 'package.json').exists() and _shutil.which('node'):
                    try:
                        chk = subprocess.run(['node', '-e', "require('node-pty')"],
                                             cwd=str(pty_dir), capture_output=True, timeout=10,
                                             creationflags=_no_win)
                        if chk.returncode == 0:
                            _need_build = False
                            print("[*] 터미널 네이티브 모듈 정상 확인!")
                    except Exception:
                        pass

                if _need_build and (pty_dir / 'package.json').exists() and _shutil.which('npm'):
                    print("[*] 터미널 네이티브 모듈 빌드 중... (1~2분 소요)")
                    # shell=True: Windows에서 npm은 npm.cmd이므로 shell 경유 필요
                    r = subprocess.run('npm install', cwd=str(pty_dir), shell=True,
                                       capture_output=True, text=True, encoding='utf-8',
                                       errors='replace', timeout=300, creationflags=_no_win)
                    if r.returncode == 0:
                        print("[*] 터미널 네이티브 모듈 빌드 완료!")
                    else:
                        print(f"[!] npm install 실패: {r.stderr[:300]}")
                elif _need_build and not _shutil.which('npm'):
                    print("[!] Node.js가 설치되지 않았습니다. 터미널 기능에 필요합니다.")
            try:
                from .create_shortcut import create_shortcut
            except ImportError:
                from create_shortcut import create_shortcut
            create_shortcut()
            if cmd == '--install':
                print("\n✅ Vibe Coding 설치가 완료되었습니다!")
                print("   실행: vibe-coding")
                print("   제거: vibe-coding --uninstall")
            return

        # --uninstall: 바탕화면 바로가기 삭제 + pip uninstall 안내
        if cmd == '--uninstall':
            try:
                from .create_shortcut import remove_shortcut
            except ImportError:
                from create_shortcut import remove_shortcut
            remove_shortcut()
            print("\n🗑️  바로가기를 삭제했습니다.")
            print("   패키지 완전 제거: pip uninstall vibe-coding -y")
            return

    print(f"Vibe Coding {__version__}")

    # ── 첫 실행 시 바탕화면 바로가기 자동 생성 ──
    try:
        try:
            from .create_shortcut import create_shortcut, shortcut_exists
        except ImportError:
            from create_shortcut import create_shortcut, shortcut_exists
        if not shortcut_exists():
            print("첫 실행 감지 — 바탕화면 바로가기를 자동 생성합니다...")
            create_shortcut()
    except Exception:
        pass  # 바로가기 생성 실패해도 서버 시작에는 지장 없음

    # ── 단일 인스턴스 락 (최우선 — ensure_postgres_running 이전) ───────────────
    # [v3.7.179] 단일 인스턴스 전면 전환 — _MAX_INSTANCES 4→1.
    # 더블클릭으로 2개 창이 뜨고, 하나를 닫으면 터미널이 죽는 치명적 UX 버그 해결.
    # 이미 실행 중이면 기존 창을 Win32 API로 포커스하고 새 인스턴스는 즉시 종료.
    import hashlib as _hl
    # 같은 PROJECT_ROOT라도 개발 모드/설치 EXE/smoke test가 동시에 떠야 하므로
    # 락 시드를 실행 환경별로 분리한다 (v3.7.225)
    _lock_seed = str(PROJECT_ROOT)
    if getattr(sys, 'frozen', False):
        _lock_seed = f"{_lock_seed}::frozen"
    if os.environ.get('VIBE_SMOKE_TEST', '').strip() in ('1', 'true', 'on'):
        _lock_seed = f"{_lock_seed}::smoke"
    _proj_hash    = int(_hl.md5(_lock_seed.encode()).hexdigest()[:4], 16)
    _LOCK_PORT    = 19001 + (_proj_hash % 480)
    _proj_id      = f"{_proj_hash:04x}"

    _lock_sock = None
    try:
        _sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        _sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 0)
        _sock.bind(('127.0.0.1', _LOCK_PORT))
        _lock_sock = _sock
    except OSError:
        # 이미 실행 중 — 기존 창을 포커스하고 종료
        print(f"[*] 이미 실행 중인 인스턴스 감지 (락 포트 {_LOCK_PORT})")
        if os.name == 'nt':
            try:
                import ctypes
                _win_title = f"바이브 코딩 [{PROJECT_ROOT.name}]"
                _hwnd = ctypes.windll.user32.FindWindowW(None, _win_title)
                if _hwnd:
                    ctypes.windll.user32.ShowWindow(_hwnd, 9)        # SW_RESTORE
                    ctypes.windll.user32.SetForegroundWindow(_hwnd)
                    print(f"[*] 기존 창 포커스 완료: {_win_title}")
                else:
                    print(f"[*] 기존 창을 찾을 수 없습니다 (아직 로딩 중일 수 있음)")
            except Exception as e:
                print(f"[!] 창 포커스 실패: {e}")
        os._exit(0)

    # 좀비 소켓 대비: 락 획득 실패 후 프로세스가 실제로 없으면 강제 회수
    # (위에서 이미 성공했으므로 여기는 도달하지 않음 — 안전장치)

    print(f"[*] 인스턴스 락 확보 (포트 {_LOCK_PORT})")

    # ── 포트 확정: HTTP 9000, WS 9001 고정 + 충돌 시 대체 탐색 ─────────────────
    # VIBE_PORT_BASE 환경변수가 있으면 해당 포트부터 시작 (smoke test 격리용)
    # 단일 인스턴스이므로 슬롯 기반 분배 불필요. 고정 포트 우선 시도.
    _preferred_http = int(os.environ.get('VIBE_PORT_BASE', '9000'))
    _http_ok = False
    try:
        _test_sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        _test_sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 0)
        _test_sock.bind(('127.0.0.1', _preferred_http))
        _test_sock.close()
        _http_ok = True
    except OSError:
        _http_ok = False

    if _http_ok:
        HTTP_PORT = _preferred_http  # noqa: F811
    else:
        HTTP_PORT = _find_free_port(9010, max_tries=40)  # noqa: F811
        print(f"[!] 포트 {_preferred_http} 사용 중 → 대체 포트 {HTTP_PORT} 사용")

    _preferred_ws = HTTP_PORT + 1
    _ws_ok = False
    try:
        _test_sock2 = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        _test_sock2.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 0)
        _test_sock2.bind(('127.0.0.1', _preferred_ws))
        _test_sock2.close()
        _ws_ok = True
    except OSError:
        _ws_ok = False

    if _ws_ok:
        WS_PORT = _preferred_ws  # noqa: F811
    else:
        WS_PORT = _find_free_port(_preferred_ws + 1, max_tries=40)  # noqa: F811
        print(f"[!] WS 포트 {_preferred_ws} 사용 중 → 대체 포트 {WS_PORT} 사용")

    print(f"[*] 서버 포트 확정 — HTTP:{HTTP_PORT}, WS:{WS_PORT}")

    # ── AppUserModelID 설정 (WebView 생성 전에 필요) ──────────────────────
    if os.name == 'nt':
        try:
            import ctypes
            import ctypes.wintypes
            myappid = f'com.vibe.coding.{__version__}'
            ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID(myappid)
        except: pass

    # ── PID 파일 기록 ─────────────────────────────────────────────────────
    try:
        _pid_file = DATA_DIR / '.dev_server.pid'
        _pid_file.parent.mkdir(parents=True, exist_ok=True)
        _pid_file.write_text(str(os.getpid()), encoding='utf-8')
    except Exception:
        pass

    # 서버 시작 시 상황판 창 플래그 초기화
    try:
        _win_flag = DATA_DIR / '.monitor_opened'
        if _win_flag.exists():
            _win_flag.unlink()
    except Exception:
        pass

    # ── [v3.7.179] 스플래시 선행 표시 + 백그라운드 초기화 ──────────────────
    # WebView 창을 PG/PTY/HTTP 초기화 **전에** 먼저 생성하여 사용자에게 즉시 피드백.
    # 모든 무거운 초기화는 _init_and_load_app() 콜백에서 수행.
    # 기존: PG(2~5초)+PTY(1~2초)+HTTP 전부 끝난 후 창 생성 → 5~10초 무반응
    # 수정: 락+포트 확인(~0.1초) → 창 즉시 표시 → 백그라운드에서 초기화 → 완료 후 앱 전환

    # --- Auto-update check (non-blocking) ---
    try:
        try:
            from updater import check_and_update
        except ImportError:
            from .updater import check_and_update

        def _update_loop():
            while True:
                try:
                    ready_file = DATA_DIR / "update_ready.json"
                    already_ready = False
                    if ready_file.exists():
                        try:
                            info = json.loads(ready_file.read_text(encoding="utf-8"))
                            already_ready = info.get("ready", False)
                        except Exception:
                            pass
                    if not already_ready:
                        check_and_update(DATA_DIR)
                except Exception as e:
                    print(f"[!] Update check error: {e}")
                time.sleep(600)

        threading.Thread(target=_update_loop, daemon=True).start()
    except ImportError:
        print("[!] Updater module not found, skipping update check.")

    # --- 경량 소스 업데이트 채널 폴링 (boot.py A안, non-blocking) ---
    # [WHY] EXE 풀빌드 채널과 별개로 main 커밋 SHA를 주기 폴링 — 순수 .py push를 빠르게 감지.
    #   [과거사고 2026-07-03] "dev는 체크아웃 아니라 무해" 가정이 틀렸음 — dev 트리도 체크아웃이라
    #   ready=true 배너→apply가 dev 트리를 reset --hard(미푸시 커밋 4개 고아화). 지금은
    #   soft_updater._channel_block_reason이 비frozen 실행을 채널에서 차단(VIBE_SRC_DIR opt-in 제외).
    try:
        from soft_updater import check_soft_update as _check_soft

        def _soft_update_loop():
            while True:
                try:
                    _check_soft(DATA_DIR, _soft_src_dir())
                except Exception as e:
                    print(f"[soft-update] poll error: {e}")
                time.sleep(300)

        threading.Thread(target=_soft_update_loop, daemon=True).start()
    except Exception as e:
        print(f"[soft-update] 폴링 스레드 시작 실패: {e}")

    # 1. Node.js PTY 서버 시작 + 자동 복구 워치독 (node-pty 기반 — pywinpty 대체)
    # node-pty가 VS Code에서 사용하는 Microsoft 공식 PTY 라이브러리로,
    # ConPTY 기반 Windows 터미널 안정성이 pywinpty보다 우수합니다.
    # 개발 모드: node pty-server.js / 배포 모드: pty-server.exe 자동 감지
    # [2026-03-22] Claude: 헬스체크 워치독 추가 — PTY 서버 행/크래시 시 자동 재시작
    _pty_server_state = {'proc': None}  # 현재 PTY 서버 프로세스 핸들 (워치독이 참조, 리스트/딕셔너리로 클로저 우회)

    def _kill_orphan_pty_servers():
        """시작 전 **자기 포트의** 좀비 PTY 서버 프로세스만 정리합니다.
        [수정 2026-03-25 v3.7.122] 기존: 모든 pty-server.js를 무차별 kill → 다른 인스턴스
        (개발용/설치버전)의 PTY 서버까지 죽여서 터미널 전부 사망하는 버그.
        수정: WMIC CommandLine에서 PTY_PORT 환경변수를 확인하여 자기 WS 포트와
        동일한 PTY 서버만 정리. 다른 인스턴스의 PTY 서버는 건드리지 않음."""
        _no_window = getattr(subprocess, 'CREATE_NO_WINDOW', 0x08000000)
        try:
            # CommandLine + ProcessId를 함께 조회하여 포트 기반 필터링
            result = subprocess.run(
                ['wmic', 'process', 'where',
                 "CommandLine like '%pty-server.js%' and Name='node.exe'",
                 'get', 'ProcessId,CommandLine', '/FORMAT:LIST'],
                capture_output=True, text=True, encoding='utf-8',
                errors='replace', creationflags=_no_window, timeout=5
            )
            # /FORMAT:LIST 출력: CommandLine=... \n ProcessId=... 쌍으로 파싱
            _current_pid = None
            _current_cmdline = ""
            for line in result.stdout.splitlines():
                line = line.strip()
                if line.startswith("CommandLine="):
                    _current_cmdline = line[len("CommandLine="):]
                elif line.startswith("ProcessId="):
                    _current_pid = line[len("ProcessId="):].strip()
                    # 쌍이 완성됨 — 자기 포트인지 확인 후 kill
                    if _current_pid and _current_pid.isdigit():
                        # PTY_PORT=<WS_PORT> 환경변수가 커맨드라인에 직접 나타나지 않으므로
                        # 자기 인스턴스의 PTY 서버 PID와 비교하여 남의 것은 보호
                        _my_pty_pid = (_pty_server_state.get('proc').pid
                                       if _pty_server_state.get('proc') and
                                       _pty_server_state['proc'].poll() is None
                                       else None)
                        target_pid = int(_current_pid)
                        if _my_pty_pid and target_pid == _my_pty_pid:
                            # 자기 PTY 서버 — kill 대상
                            pass
                        elif _my_pty_pid and target_pid != _my_pty_pid:
                            # 다른 인스턴스의 PTY — 보호
                            print(f"[PTY Cleanup] PID {target_pid}는 다른 인스턴스 소유 → 보호 (자기 PID: {_my_pty_pid})")
                            _current_pid = None
                            _current_cmdline = ""
                            continue
                        # _my_pty_pid가 None인 경우(최초 시작): 부모 프로세스 확인
                        elif _my_pty_pid is None:
                            # 부모 PID를 확인하여 자기 자식인지 판별
                            try:
                                ppid_res = subprocess.run(
                                    ['wmic', 'process', 'where',
                                     f'ProcessId={target_pid}',
                                     'get', 'ParentProcessId', '/FORMAT:LIST'],
                                    capture_output=True, text=True, encoding='utf-8',
                                    errors='replace', creationflags=_no_window, timeout=3
                                )
                                for ppid_line in ppid_res.stdout.splitlines():
                                    ppid_line = ppid_line.strip()
                                    if ppid_line.startswith("ParentProcessId="):
                                        parent_pid = int(ppid_line.split("=")[1].strip())
                                        if parent_pid != os.getpid():
                                            # 부모가 다른 프로세스 → 다른 인스턴스 소유
                                            print(f"[PTY Cleanup] PID {target_pid}(부모: {parent_pid})는 "
                                                  f"다른 인스턴스 소유 → 보호 (자기 PID: {os.getpid()})")
                                            target_pid = None
                                            break
                            except Exception:
                                # 부모 확인 실패 시 안전하게 건너뜀 (다른 인스턴스 보호 우선)
                                print(f"[PTY Cleanup] PID {_current_pid} 부모 확인 실패 → 보호 (안전 우선)")
                                target_pid = None

                        if target_pid is not None:
                            try:
                                subprocess.run(
                                    ['taskkill', '/F', '/T', '/PID', str(target_pid)],
                                    capture_output=True, creationflags=_no_window, timeout=5
                                )
                                print(f"[PTY Cleanup] 좀비 PTY 서버(PID {target_pid}) 정리 완료")
                            except Exception:
                                pass
                    _current_pid = None
                    _current_cmdline = ""
        except Exception as e:
            print(f"[PTY Cleanup] 좀비 정리 실패 (무시): {e}")

    def _ensure_pty_node_modules():
        """PTY 서버의 node_modules가 현재 PC에서 유효한지 확인하고, 필요하면 npm rebuild를 실행합니다.
        node-pty는 C++ 네이티브 모듈이라 빌드한 PC의 Node ABI 버전에 종속됩니다.
        pip install로 다른 PC에 설치하면 pty.node 파일이 존재하더라도 Node 버전이 달라
        로드 실패하므로, 실제로 require('node-pty')가 성공하는지 검증해야 합니다.
        """
        pty_server_dir = BASE_DIR / 'pty-server'
        if not (pty_server_dir / 'package.json').exists():
            return  # pty-server 자체가 없으면 스킵

        # npm / node가 설치되어 있는지 확인
        import shutil as _shutil
        if not _shutil.which('node') or not _shutil.which('npm'):
            print("[!] Node.js가 설치되지 않았습니다. 터미널 기능을 위해 Node.js를 설치하세요.")
            return

        # node-pty 네이티브 모듈이 현재 Node.js에서 실제로 로드 가능한지 검증
        # 파일 존재만 확인하면 안 됨: pip install로 복사된 바이너리는 빌드 PC의 Node ABI라 호환 안 됨
        _no_window = getattr(subprocess, 'CREATE_NO_WINDOW', 0x08000000)
        try:
            check = subprocess.run(
                ['node', '-e', "require('node-pty')"],
                cwd=str(pty_server_dir),
                capture_output=True, text=True, timeout=10,
                creationflags=_no_window,
            )
            if check.returncode == 0:
                return  # 네이티브 모듈이 현재 Node에서 정상 로드됨
        except Exception:
            pass  # 검증 실패 → 재빌드 필요

        print("[*] PTY 서버 네이티브 모듈 빌드 중... (최초 1회, 1~2분 소요)")
        _no_window = getattr(subprocess, 'CREATE_NO_WINDOW', 0x08000000)
        try:
            # shell=True: Windows에서 npm은 npm.cmd이므로 shell 경유 필요
            result = subprocess.run(
                'npm install',
                cwd=str(pty_server_dir), shell=True,
                capture_output=True, text=True, encoding='utf-8', errors='replace',
                timeout=300,  # 5분 타임아웃
                creationflags=_no_window,
            )
            if result.returncode == 0:
                print("[*] PTY 서버 네이티브 모듈 빌드 완료!")
            else:
                print(f"[!] npm install 실패 (코드 {result.returncode}): {result.stderr[:500]}")
        except subprocess.TimeoutExpired:
            print("[!] npm install 타임아웃 (5분 초과)")
        except Exception as e:
            print(f"[!] npm install 실행 오류: {e}")

    def _start_node_pty_server():
        """PTY 서버를 시작하고 프로세스 핸들을 반환합니다."""
        _ensure_pty_node_modules()  # 네이티브 모듈 빌드 확인/실행
        pty_server_dir = BASE_DIR / 'pty-server'
        pty_server_exe = pty_server_dir / 'pty-server.exe'
        pty_server_js = pty_server_dir / 'pty-server.js'

        pty_env = os.environ.copy()
        pty_env['PTY_PORT'] = str(WS_PORT)
        pty_env['HTTP_PORT'] = str(HTTP_PORT)
        pty_env['PROJECT_ROOT'] = str(PROJECT_ROOT)

        # 번들된 node.exe 경로 — CI에서 같은 Node 버전으로 빌드된 런타임 (ABI 호환 보장)
        bundled_node = pty_server_dir / 'node.exe'

        if pty_server_exe.exists():
            # 배포 모드: pkg로 빌드된 단독 실행 파일
            cmd = [str(pty_server_exe)]
        elif pty_server_js.exists() and bundled_node.exists():
            # 배포 모드: 번들된 Node.js 런타임으로 실행 (네이티브 모듈 ABI 호환)
            cmd = [str(bundled_node), str(pty_server_js)]
        elif pty_server_js.exists():
            # 개발 모드: 시스템 Node.js로 직접 실행
            cmd = ['node', str(pty_server_js)]
        else:
            print("[!] PTY 서버 파일을 찾을 수 없습니다. 터미널 기능이 비활성화됩니다.")
            return None

        try:
            proc = subprocess.Popen(
                cmd,
                env=pty_env,
                cwd=str(pty_server_dir),
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                text=True,
                encoding='utf-8',
                errors='replace',
                creationflags=getattr(subprocess, 'CREATE_NO_WINDOW', 0x08000000),
            )
            _child_procs.append(proc)
            _pty_server_state['proc'] = proc
            print(f"[*] Node PTY Server started (PID {proc.pid}) on port {WS_PORT}")

            # PTY 서버 stdout을 백그라운드로 읽어서 로그 출력
            def _read_pty_stdout():
                try:
                    for line in proc.stdout:
                        line = line.strip()
                        if line:
                            print(f"[node-pty] {line}")
                except Exception:
                    pass
            threading.Thread(target=_read_pty_stdout, daemon=True).start()
            return proc

        except FileNotFoundError:
            print("[!] Node.js가 설치되지 않았습니다. 터미널 기능이 비활성화됩니다.")
            return None
        except Exception as e:
            print(f"[!] Node PTY Server 시작 실패: {e}")
            return None

    def _pty_health_check() -> bool:
        """PTY 서버 /health 엔드포인트에 GET 요청 — 2초 내 응답하면 True."""
        try:
            req = urllib.request.Request(f"http://127.0.0.1:{WS_PORT}/health")
            with urllib.request.urlopen(req, timeout=2.0) as resp:
                data = json.loads(resp.read().decode('utf-8'))
                return data.get('status') == 'ok'
        except Exception:
            return False

    def _kill_pty_proc(proc):
        """행 상태 PTY 프로세스를 강제 종료합니다 (taskkill /T 로 프로세스 트리 전체)."""
        if proc is None:
            return
        try:
            pid = proc.pid
            # Windows: 프로세스 트리 전체 강제 종료
            _no_window = getattr(subprocess, 'CREATE_NO_WINDOW', 0x08000000)
            subprocess.run(
                ['taskkill', '/F', '/T', '/PID', str(pid)],
                capture_output=True, creationflags=_no_window
            )
            print(f"[PTY Watchdog] 행 상태 PTY 서버(PID {pid}) 강제 종료 완료")
        except Exception as e:
            print(f"[PTY Watchdog] PTY 프로세스 종료 실패: {e}")
        # _child_procs 목록에서 제거 (중복 kill 방지)
        try:
            _child_procs.remove(proc)
        except ValueError:
            pass

    def _pty_watchdog_loop():
        """30초 간격으로 PTY 서버 헬스체크 — 3회 연속 실패 시 자동 재시작.

        전략:
        - 30초마다 /health 호출
        - 3회 연속 실패(90초 무응답) → 프로세스 강제 종료 + 재시작
        - 재시작 후 10초 대기 (기동 시간 확보)
        - 재시작 5회 연속 실패 시 간격을 60초로 늘려 리소스 낭비 방지
        """
        consecutive_fails = 0
        restart_fails = 0
        MAX_FAIL_BEFORE_RESTART = 3
        MAX_RESTART_FAILS = 5

        # 최초 기동 대기 — PTY 서버가 포트 바인딩할 시간 확보
        time.sleep(5)

        while True:
            interval = 60 if restart_fails >= MAX_RESTART_FAILS else 30

            # 1) 프로세스 자체가 죽었는지 확인
            proc_dead = (_pty_server_state['proc'] is not None and
                         _pty_server_state['proc'].poll() is not None)

            # 2) 헬스체크
            if proc_dead:
                healthy = False
            else:
                healthy = _pty_health_check()

            if healthy:
                consecutive_fails = 0
                restart_fails = 0  # 정상 응답 → 재시작 실패 카운터 리셋
            else:
                consecutive_fails += 1
                reason = "프로세스 종료됨" if proc_dead else "헬스체크 타임아웃"
                print(f"[PTY Watchdog] {reason} ({consecutive_fails}/{MAX_FAIL_BEFORE_RESTART})")

                if consecutive_fails >= MAX_FAIL_BEFORE_RESTART:
                    print(f"[PTY Watchdog] {MAX_FAIL_BEFORE_RESTART}회 연속 실패 → PTY 서버 자동 재시작")
                    _kill_pty_proc(_pty_server_state['proc'])
                    _kill_orphan_pty_servers()  # 좀비 PTY도 정리하여 포트 충돌 방지
                    new_proc = _start_node_pty_server()
                    if new_proc:
                        consecutive_fails = 0
                        restart_fails = 0
                        time.sleep(10)  # 기동 대기
                        continue
                    else:
                        restart_fails += 1
                        print(f"[PTY Watchdog] 재시작 실패 ({restart_fails}/{MAX_RESTART_FAILS})")

            time.sleep(interval)

    # ── [v3.7.179] GUI 창 선행 표시 → 백그라운드 초기화 → 앱 로드 ────────────
    # 모든 무거운 초기화(PG, PTY, 데몬, HTTP)를 WebView 콜백에서 실행.
    # 사용자는 스플래시를 즉시 보고, 초기화 진행 상황을 텍스트로 확인.
    _http_server_ref = [None]  # HTTP 서버 참조 (콜백 → 정리 코드 공유)
    
    # ── 데몬 함수 정의 (실행은 _init_and_load_app 콜백에서) ──────────────────

    # ── 데몬 본문은 infra/daemons.py로 분리 (2026-06-10 단계 9) ──────────────
    # [WHY] env는 매 호출 시 생성 — HTTP_PORT가 main() 후반(포트 슬롯 결정)에
    # 재바인딩되므로 함수 정의 시점에 값을 고정하면 안 된다.
    from infra import daemons as _daemons

    def _daemon_env() -> "_daemons.DaemonEnv":
        return _daemons.DaemonEnv(
            base_dir=BASE_DIR,
            project_root=PROJECT_ROOT,
            scripts_dir=SCRIPTS_DIR,
            data_dir=DATA_DIR,
            global_vault_dir=GLOBAL_VAULT_DIR,
            config_file=CONFIG_FILE,
            http_port=HTTP_PORT,
            child_procs=_child_procs,
            current_project_root=_current_project_root,
            current_project_id=_current_project_id,
        )

    def run_watchdog():
        _daemons.run_watchdog(_daemon_env())

    def run_telegram_bridge():
        _daemons.run_telegram_bridge(_daemon_env())

    def run_codex_pg_watcher():
        _daemons.run_codex_pg_watcher(_daemon_env())

    def run_orchestrator_daemon():
        _daemons.run_orchestrator_daemon(_daemon_env())

    def run_doc_generators_daemon():
        _daemons.run_doc_generators_daemon(_daemon_env())

    def _agent_sync_daemon():
        _daemons.agent_sync_daemon(AGENT_STATUS, AGENT_STATUS_LOCK)

    def run_zettel_sync():
        _daemons.run_zettel_sync(_daemon_env())

    def run_zettel_refine():
        _daemons.run_zettel_refine(_daemon_env())

    def run_commit_watcher():
        _daemons.run_commit_watcher(_daemon_env())

    def run_embedding_backfill():
        _daemons.run_embedding_backfill(_daemon_env())
    # ── GUI 창 먼저 표시 → 콜백에서 전체 초기화 수행 ──────────────────────────
    try:
        import webview
        official_icon = os.path.join(os.path.dirname(__file__), "bin", "vibe_final.ico")
        if not os.path.exists(official_icon):
            official_icon = os.path.join(os.path.dirname(__file__), "bin", "app_icon.ico")

        def force_win32_icon():
            if os.name == 'nt' and os.path.exists(official_icon):
                try:
                    import ctypes
                    from ctypes import wintypes
                    time.sleep(2)
                    hwnd = ctypes.windll.user32.FindWindowW(None, f"바이브 코딩 [{PROJECT_ROOT.name}]")
                    if hwnd:
                        hicon = ctypes.windll.user32.LoadImageW(
                            None, official_icon, 1, 0, 0, 0x00000010 | 0x00000040
                        )
                        if hicon:
                            ctypes.windll.user32.SendMessageW(hwnd, 0x80, 1, hicon)
                            ctypes.windll.user32.SendMessageW(hwnd, 0x80, 0, hicon)
                            print(f"[*] Win32 Taskbar Icon Forced: {official_icon}")
                except Exception as e:
                    print(f"[!] Win32 Icon Fix Error: {e}")

        # ── 스플래시 HTML — 진행 상황 텍스트 실시간 업데이트 지원 ──────────────
        _SPLASH_HTML = f"""<!DOCTYPE html>
<html><head><meta charset="utf-8"><style>
*{{margin:0;padding:0;box-sizing:border-box}}
body{{background:#0f0f1a;display:flex;align-items:center;justify-content:center;
height:100vh;font-family:-apple-system,'Segoe UI',sans-serif;color:white}}
.box{{text-align:center}}
.logo{{font-size:52px;margin-bottom:12px}}
.title{{font-size:22px;font-weight:600;margin-bottom:6px}}
.sub{{font-size:13px;color:#888;margin-bottom:28px;transition:opacity .3s}}
.proj{{font-size:12px;color:#7c3aed;margin-bottom:28px;
background:#1a0a3a;padding:4px 12px;border-radius:20px;display:inline-block}}
.ring{{width:36px;height:36px;border:3px solid #222;border-top-color:#7c3aed;
border-radius:50%;animation:spin 0.9s linear infinite;margin:0 auto}}
@keyframes spin{{to{{transform:rotate(360deg)}}}}
</style></head><body>
<div class="box">
  <div class="logo">🚀</div>
  <div class="title">바이브 코딩</div>
  <div class="proj">{PROJECT_ROOT.name}</div>
  <div class="sub" id="status">초기화 준비 중...</div>
  <div class="ring"></div>
</div></body></html>"""

        def _init_and_load_app(window):
            """[v3.7.179] 스플래시 표시 상태에서 PG/PTY/HTTP 전체 초기화 수행 후 앱 로드.
            이전: PG+PTY+HTTP 모두 끝난 후 창 생성 → 5~10초 무반응.
            수정: 창 즉시 표시 → 초기화 진행 → 완료 후 앱 전환."""
            import urllib.request as _ureq

            def _update_splash(msg):
                try:
                    window.evaluate_js(
                        f"document.getElementById('status').textContent='{msg}'"
                    )
                except Exception:
                    pass

            # ── 1단계: PostgreSQL + PTY 병렬 시작 ──
            _update_splash('데이터베이스 시작 중...')
            _pty_prep_done = threading.Event()
            def _prepare_pty():
                try:
                    _kill_orphan_pty_servers()
                    _ensure_pty_node_modules()
                except Exception as e:
                    print(f"[!] PTY 병렬 준비 오류: {e}")
                _pty_prep_done.set()
            threading.Thread(target=_prepare_pty, daemon=True).start()

            ensure_postgres_running()
            atexit.register(_cleanup_postgres)

            # ── 2단계: 프로젝트 DB + 스키마 ──
            _update_splash('프로젝트 데이터베이스 초기화 중...')
            _init_project_db(PROJECT_ID)
            try:
                import src.pg_store as _pg_mod
                # [WHY] pg_store 분할(2026-06-10) 후 _SCHEMA_READY는 pg_schema 내부
                # 상태 — 모듈 속성 직접 대입은 무효라 reset_schema_cache()로 캡슐화
                _pg_mod.reset_schema_cache()
                _pg_mod.ensure_schema(DATA_DIR)
            except Exception as e:
                print(f"[PG] 프로젝트 DB 스키마 초기화 실패: {e}")

            # ── 3단계: PTY 서버 시작 ──
            _update_splash('터미널 서버 시작 중...')
            _pty_prep_done.wait(timeout=30)
            _start_node_pty_server()
            threading.Thread(target=_pty_watchdog_loop, daemon=True,
                             name='PTY-Watchdog').start()

            _NODE_PTY_REST_URL = f"http://127.0.0.1:{WS_PORT}"
            pty_api.set_pty_rest_url(_NODE_PTY_REST_URL)
            agent_api.set_pty_rest_url(_NODE_PTY_REST_URL)

            # ── 4단계: 데몬 스레드 일괄 시작 ──
            _update_splash('서비스 시작 중...')
            threading.Thread(target=_agent_broadcast_worker, daemon=True,
                             name='AgentBroadcast').start()
            start_fs_watcher(PROJECT_ROOT)
            MemoryWatcher(PROJECT_ID).start()
            threading.Thread(target=run_watchdog, daemon=True).start()
            threading.Thread(target=run_telegram_bridge, daemon=True).start()
            threading.Thread(target=run_codex_pg_watcher, daemon=True,
                             name='CodexPGWatcher').start()
            threading.Thread(target=run_orchestrator_daemon, daemon=True,
                             name='OrchestratorDaemon').start()
            threading.Thread(target=run_doc_generators_daemon, daemon=True,
                             name='DocGeneratorsDaemon').start()
            threading.Thread(target=_agent_sync_daemon, daemon=True,
                             name='AgentSyncDaemon').start()
            threading.Thread(target=run_zettel_sync, daemon=True,
                             name='ZettelSync').start()
            threading.Thread(target=run_zettel_refine, daemon=True,
                             name='ZettelRefine').start()
            threading.Thread(target=run_commit_watcher, daemon=True,
                             name='CommitWatcher').start()
            # [회상 v2 즉시 활성] 기동 시 embed 모델을 백그라운드 워밍 — 백필 데몬의 90초
            #   대기나 첫 recall miss 전에도 벡터 회상이 되도록. 논블로킹(0.001s 반환).
            #   [WHY] recall-smart는 미로드면 fallback → 모델이 recall 경로로 안 올라오는
            #   닭-달걀. 데몬만으론 90초 창(+데몬 사망 시 영구) 비활성 → 여기서 선제 워밍.
            try:
                from infra.embed_service import warm_async as _warm_embed
                _warm_embed()
            except Exception:
                pass
            # [자가 치유 2.0 ④] 회상 v2 — embedding IS NULL 행 사후 채움
            threading.Thread(target=run_embedding_backfill, daemon=True,
                             name='EmbedBackfill').start()

            _restore_agent_status_from_db()

            # ── 5단계: HTTP 서버 시작 ──
            _update_splash('웹 서버 시작 중...')
            _actual_port = HTTP_PORT
            try:
                _srv = ThreadedHTTPServer(('127.0.0.1', _actual_port), SSEHandler)
                print(f"[*] Server running on http://localhost:{_actual_port}")
                threading.Thread(target=_srv.serve_forever, daemon=True).start()
                threading.Thread(target=_load_task_logs_into_thoughts, daemon=True,
                                 name='ThoughtPreload').start()
                _http_server_ref[0] = _srv
            except OSError as e:
                if 'already in use' in str(e).lower() or '10048' in str(e):
                    print(f"[!] 포트 {_actual_port} 충돌 → 대체 포트 탐색")
                    try:
                        _actual_port = _find_free_port(_actual_port + 10, max_tries=50)
                        _srv = ThreadedHTTPServer(('127.0.0.1', _actual_port), SSEHandler)
                        print(f"[*] 대안 포트로 서버 시작: http://localhost:{_actual_port}")
                        threading.Thread(target=_srv.serve_forever, daemon=True).start()
                        threading.Thread(target=_load_task_logs_into_thoughts, daemon=True,
                                         name='ThoughtPreload').start()
                        _http_server_ref[0] = _srv
                    except Exception as e2:
                        print(f"[!] 대안 포트에서도 실패: {e2}")
                        return
                else:
                    print(f"[!] Server Start Error: {e}")
                    return

            # ── 6단계: 서버 응답 확인 후 앱 로드 ──
            _update_splash('앱 로딩 중...')
            for _ in range(50):  # 최대 5초
                try:
                    _ureq.urlopen(f'http://127.0.0.1:{_actual_port}/', timeout=0.1)
                    break
                except Exception:
                    time.sleep(0.1)
            window.load_url(f'http://localhost:{_actual_port}')
            print(f"[*] 앱 로드 완료 — http://localhost:{_actual_port}")

        print(f"[*] Launching Desktop Window with Splash...")
        global main_window
        main_window = webview.create_window(f'바이브 코딩 [{PROJECT_ROOT.name}]',
                              html=_SPLASH_HTML, width=1400, height=900)

        threading.Thread(target=force_win32_icon, daemon=True).start()

        # ── WebView2 영구 저장소 경로 ──
        # 기본 private_mode=True 는 종료 시 localStorage 전체 삭제 → 프로필/설정 유실
        # %APPDATA%/vibe-coding/<dev|exe>/<프로젝트명>/webview_data 에 영구 저장
        # 개발/EXE 분리: 스키마 차이로 인한 데이터 손상 방지
        _appdata = os.environ.get('APPDATA') or str(Path.home() / 'AppData' / 'Roaming')
        _mode = 'exe' if getattr(sys, 'frozen', False) else 'dev'
        _webview_storage = Path(_appdata) / 'vibe-coding' / _mode / PROJECT_ROOT.name / 'webview_data'
        _webview_storage.mkdir(parents=True, exist_ok=True)
        print(f"[*] WebView2 storage: {_webview_storage}")

        # webview.start() 블로킹 — _init_and_load_app이 별도 스레드에서 전체 초기화 수행
        webview.start(
            _init_and_load_app,
            args=[main_window],
            private_mode=False,
            storage_path=str(_webview_storage),
        )

        # ── 창 닫힘 → 정리 ──
        print("[*] GUI 창이 닫혔습니다. 모든 자식 프로세스 정리 중...")
        _cleanup_child_procs()
        _cleanup_postgres()
        try:
            if _http_server_ref[0]:
                _http_server_ref[0].shutdown()
                _http_server_ref[0].server_close()
        except Exception:
            pass
        try:
            if _lock_sock:
                _lock_sock.close()
        except Exception:
            pass
        print("[*] 정리 완료 — 프로세스를 종료합니다.")
        os._exit(0)
    except Exception as e:
        print(f"[!] GUI Error: {e}")
        open_app_window(f"http://localhost:{HTTP_PORT}")
        try:
            while True:
                time.sleep(1)
        except KeyboardInterrupt:
            print("[*] Ctrl+C 감지 — 정리 후 종료합니다.")
            _cleanup_child_procs()
            try:
                if _http_server_ref[0]:
                    _http_server_ref[0].shutdown()
                    _http_server_ref[0].server_close()
            except Exception:
                pass
            os._exit(0)


if __name__ == '__main__':
    main()
