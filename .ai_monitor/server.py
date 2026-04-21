"""
FILE: .ai_monitor/server.py
DESCRIPTION: 하이브 마인드 중앙 통제 서버 — 에이전트 간 통신 중계, 상태 모니터링, 데이터 영속성 관리.

REVISION HISTORY:
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
#   - run_watchdog/run_telegram_bridge/run_heal_daemon: sys.executable → _python_runner_cmds()[0]
#   - frozen 모드에서 sys.executable = EXE 자신이므로 subprocess 실행 시 EXE가 무한 재귀 생성되던 버그
#   - Python 인터프리터 미탐색 시 해당 데몬 스킵(경고 출력)
# [2026-03-08] - Claude (칸반 네이티브 창 실행 API 추가)
#   - POST /api/kanban/launch: PySide6 kanban_board.py를 서브프로세스로 실행
#     → window.open() 브라우저 창 대신 OS 네이티브 데스크톱 창으로 열림
# [2026-03-05] - Claude (모듈 분리 — 데드 코드 639줄 제거)
#   - /api/git/status, /api/git/log: git_api 위임 중복 직접 구현 제거
#   - /api/memory, /api/project-info: memory_api 위임 중복 구현 제거
#   - /api/context-usage, /api/gemini-context-usage, /api/local-models: hive_api 중복 제거
#   - /api/hive/activity: 데드 코드 제거 + hive_api.py에 핸들러 추가 (실제 동작 버그 수정)
#   - /api/hive/logs, /api/hive/health, /api/skill-results: 중복 제거
#   - server.py 4396줄 → 3757줄 (-639줄)
# [2026-03-04] - Claude (PTY 터미널 자율 에이전트 자동 트리거)
#   - read_from_ws()에 입력 버퍼 + Enter 인터셉션 추가
#   - Gemini 터미널: Enter 입력 시 cli_agent.py 자동 백그라운드 라우팅
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
#   - pty_handler: Gemini/Claude 세션 시작 시 session_logs에 즉시 기록 ("세션 시작 ───")
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
#   - _parse_gemini_session(): Gemini 세션 JSON 파일 토큰 파서 추가
#   - /api/gemini-context-usage 엔드포인트 추가
# [2026-02-26] - Claude (버그 수정)
...
# ... 기존 내용 유지 ...

import json
import time
import os
import mimetypes
import webbrowser
import shutil
import subprocess
import re
import threading
import sys
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
import string
import socket
from collections import deque
from pathlib import Path
from src.file_store import (
    delete_memory_entry,
    ensure_legacy_store,
    get_agent_last_seen_from_sessions,
    get_memory_entry,
    merge_memory_files,
    upsert_memory_entry,
)
from src.pg_store import (
    ensure_schema,
    get_agent_last_seen,
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

# ── PostgreSQL 커넥션 풀 (최대 5개, 스레드 안전) ──
# 매 쿼리마다 psycopg2.connect()를 호출하면 ~1ms의 오버헤드가 쿼리당 발생.
# 풀을 사용하면 이미 열린 연결을 재사용하여 connect 비용을 제거.
_pg_pool = []           # 사용 가능한 커넥션 리스트 (db별 (conn, db) 튜플)
_pg_pool_lock = threading.Lock()  # 풀 접근 동기화 락
_PG_POOL_MAX = 5        # 풀에 보관할 최대 커넥션 수
_tool_install_lock = threading.Lock()
_tool_install_state: dict[str, dict] = {}

def _get_pg_conn(db: str = "postgres"):
    """풀에서 커넥션을 꺼내거나, 풀이 비었으면 새로 생성하여 반환.

    같은 db 이름의 커넥션만 재사용. 다른 db의 커넥션은 풀에 그대로 둠.
    연결이 끊어졌으면(OperationalError) 버리고 새로 생성.
    """
    import psycopg2
    with _pg_pool_lock:
        # 풀에서 같은 db의 커넥션 탐색
        for i, (conn, conn_db) in enumerate(_pg_pool):
            if conn_db == db:
                _pg_pool.pop(i)
                # 커넥션 유효성 검증 (끊어진 연결 감지)
                try:
                    conn.cursor().execute("SELECT 1")
                    return conn
                except (psycopg2.OperationalError, psycopg2.InterfaceError):
                    # 끊어진 커넥션 — 조용히 폐기하고 새로 생성
                    try:
                        conn.close()
                    except Exception:
                        pass
                    break
    # 풀에 적합한 커넥션 없음 → 새로 생성
    conn = psycopg2.connect(host='127.0.0.1', port=int(PG_PORT), user='postgres', dbname=db)
    conn.autocommit = True
    return conn

def _return_pg_conn(conn, db: str = "postgres"):
    """사용 완료된 커넥션을 풀에 반환. 풀이 가득 차면 연결을 닫고 폐기."""
    with _pg_pool_lock:
        if len(_pg_pool) < _PG_POOL_MAX:
            _pg_pool.append((conn, db))
        else:
            # 풀 용량 초과 — 연결 닫기
            try:
                conn.close()
            except Exception:
                pass

# DB 데이터: %APPDATA%\VibeCoding\pgdata (배포/개발 모두 동일)
# [2026-04-05 Claude] 개발 모드에서 소스 트리 내 data/ 사용 시 PG 버전 불일치 문제 발생
# → 배포/개발 모두 %APPDATA% 경로로 통일하여 바이너리 업그레이드 시 충돌 방지
_PG_DATA_DIR = Path(os.getenv('APPDATA', '')) / "VibeCoding" / "pgdata"


def ensure_postgres_running():
    """배포(frozen) 모드 전용: PostgreSQL이 실행 중이지 않으면 자동으로 초기화하고 시작합니다.

    1) pgsql 바이너리가 없으면 스킵 (설치 안 된 환경 — 개발 모드 등)
    2) pgdata 디렉터리가 없으면 initdb로 초기화
    3) pg_ctl status로 실행 여부 확인 후, 미실행 시 pg_ctl start
    4) 확장(vector, pg_trgm) 활성화 SQL 실행
    """
    global PG_PORT
    if not PG_CTL_BIN.exists():
        print(f"[PG] pg_ctl.exe 없음 → PG 자동시작 스킵 ({PG_CTL_BIN})")
        return

    _no_window = getattr(subprocess, 'CREATE_NO_WINDOW', 0x08000000)
    pg_log = _PG_DATA_DIR.parent / "pgsql.log"

    # 1) initdb — pgdata 없으면 최초 DB 클러스터 생성
    if not _PG_DATA_DIR.exists():
        print(f"[PG] pgdata 없음 → initdb 실행: {_PG_DATA_DIR}")
        _PG_DATA_DIR.mkdir(parents=True, exist_ok=True)
        try:
            res = subprocess.run(
                [str(INITDB_BIN), "-D", str(_PG_DATA_DIR),
                 "-U", "postgres", "-E", "UTF8", "--no-locale"],
                capture_output=True, text=True, encoding='utf-8', errors='replace',
                creationflags=_no_window
            )
            if res.returncode != 0:
                print(f"[PG] initdb 오류:\n{res.stderr}")
                return
            print(f"[PG] initdb 완료")

            # postgresql.conf에서 포트를 5433으로 변경
            pg_conf = _PG_DATA_DIR / "postgresql.conf"
            if pg_conf.exists():
                conf_text = pg_conf.read_text(encoding='utf-8')
                # 기본 포트(5432) → 5433으로 교체, listen_addresses 활성화
                conf_text = conf_text.replace("#listen_addresses = 'localhost'", "listen_addresses = 'localhost'")
                conf_text = conf_text.replace("#port = 5432", f"port = {PG_PORT}")
                conf_text = conf_text.replace("port = 5432", f"port = {PG_PORT}")
                pg_conf.write_text(conf_text, encoding='utf-8')
                print(f"[PG] postgresql.conf 포트 {PG_PORT} 설정 완료")
        except Exception as e:
            print(f"[PG] initdb 예외: {e}")
            return

    # 2) 실행 여부 확인 — pg_ctl status + 포트 바인딩 이중 검증
    try:
        status_res = subprocess.run(
            [str(PG_CTL_BIN), "status", "-D", str(_PG_DATA_DIR)],
            capture_output=True, text=True, encoding='utf-8', errors='replace',
            creationflags=_no_window
        )
        if "server is running" in status_res.stdout:
            print("[PG] 이미 실행 중")
            return
    except Exception as e:
        print(f"[PG ERROR] pg_ctl status 확인: {e}")

    # 2-1) 포트 점유 확인 — 다른 PostgreSQL(예: 시스템 서비스)이 포트를 선점한 경우 자동 회피
    # [2026-04-05 Claude] 기존: 포트 점유 시 스킵 → 기존 PG에 우리 DB가 없어 에러 발생
    # 변경: 우리 pgdata의 PG가 아닌 외부 프로세스가 포트를 점유하면 빈 포트를 자동 탐색
    import socket as _pg_sock
    try:
        _pg_test = _pg_sock.socket(_pg_sock.AF_INET, _pg_sock.SOCK_STREAM)
        _pg_result = _pg_test.connect_ex(('127.0.0.1', PG_PORT))
        _pg_test.close()
        if _pg_result == 0:
            # 포트가 열려 있음 — 우리 PG인지 확인 (pgdata로 판별)
            # pg_ctl status가 "not running"이면 외부 프로세스가 점유 중
            print(f"[PG] 포트 {PG_PORT}이 이미 사용 중 (외부 프로세스) → 빈 포트 탐색")
            _found_port = False
            for _try_port in range(PG_PORT + 1, PG_PORT + 20):
                _s = _pg_sock.socket(_pg_sock.AF_INET, _pg_sock.SOCK_STREAM)
                _r = _s.connect_ex(('127.0.0.1', _try_port))
                _s.close()
                if _r != 0:  # 포트가 비어있음
                    PG_PORT = _try_port
                    print(f"[PG] 빈 포트 발견: {PG_PORT}")
                    # postgresql.conf 포트도 갱신
                    pg_conf = _PG_DATA_DIR / "postgresql.conf"
                    if pg_conf.exists():
                        conf_text = pg_conf.read_text(encoding='utf-8')
                        import re as _pg_re
                        # 활성 설정(port = XXXX) 또는 주석(#port = XXXX) 모두 대응
                        if _pg_re.search(r'^\s*port\s*=', conf_text, flags=_pg_re.MULTILINE):
                            conf_text = _pg_re.sub(r'^\s*port\s*=\s*\d+', f'port = {PG_PORT}', conf_text, flags=_pg_re.MULTILINE)
                        elif _pg_re.search(r'^\s*#\s*port\s*=', conf_text, flags=_pg_re.MULTILINE):
                            conf_text = _pg_re.sub(r'^\s*#\s*port\s*=\s*\d+', f'port = {PG_PORT}', conf_text, flags=_pg_re.MULTILINE)
                        else:
                            conf_text += f'\nport = {PG_PORT}\n'
                        pg_conf.write_text(conf_text, encoding='utf-8')
                    # 환경변수도 갱신하여 pg_store.py 등 다른 모듈이 새 포트를 인식
                    os.environ['VIBE_PG_PORT'] = str(PG_PORT)
                    _found_port = True
                    break
            if not _found_port:
                print(f"[PG ERROR] 포트 {PG_PORT-19}~{PG_PORT} 범위에서 빈 포트를 찾지 못함")
                return
    except Exception:
        pass  # 소켓 테스트 실패 시 그냥 시작 시도

    # 3) pg_ctl start
    # [수정 2026-04-07] capture_output=True → DEVNULL — pg_ctl start가 postgres를
    # 자식으로 생성하면 PIPE 핸들을 상속받아 subprocess.run()이 영원히 반환 안 하는
    # Windows 전용 치명적 버그 수정. DEVNULL로 출력을 버리면 pg_ctl이 즉시 반환됨.
    # timeout=15는 pgdata 락 충돌 시 폴백용으로 유지.
    print(f"[PG] PostgreSQL 시작 중 (port={PG_PORT})...")
    try:
        subprocess.run(
            [str(PG_CTL_BIN), "start", "-D", str(_PG_DATA_DIR),
             "-l", str(pg_log), "-o", f"-p {PG_PORT}"],
            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
            creationflags=_no_window, timeout=15
        )
        # [v3.7.62 수정] 고정 2초 대기 → 실제 ready 폴링으로 교체
        # pg_ctl start 직후 psql SELECT 1로 100ms 간격으로 최대 5초 폴링.
        # PG가 빠르게 뜨면 (보통 0.3~0.5초) 즉시 통과 → 기동 시간 단축.
        import time as _time
        _pg_ready = False
        for _i in range(50):  # 최대 5초 (100ms × 50회)
            _time.sleep(0.1)
            try:
                _chk = subprocess.run(
                    [str(PG_CTL_BIN), "status", "-D", str(_PG_DATA_DIR)],
                    capture_output=True, text=True, encoding='utf-8', errors='replace',
                    creationflags=_no_window, timeout=1
                )
                if "server is running" in _chk.stdout:
                    _pg_ready = True
                    break
            except Exception as e:
                pass  # PG ready 폴링 중 일시적 실패 허용
        print(f"[PG] PostgreSQL 시작 완료 ({(_i+1)*100}ms 소요)")
    except subprocess.TimeoutExpired:
        # [2026-04-06] pg_ctl start가 15초 내 완료 못 함 → pgdata 락 충돌 가능성 높음
        # 이전 실행의 PG가 살아있으면 원래 포트(5433)로 연결 시도
        print(f"[PG] pg_ctl start 타임아웃 (pgdata 락 충돌 가능) → 기존 PG 인스턴스 재사용 시도")
        import socket as _pg_sock2
        for _fallback_port in [5433, 5434, 5435, 5432]:
            try:
                _s = _pg_sock2.socket(_pg_sock2.AF_INET, _pg_sock2.SOCK_STREAM)
                _r = _s.connect_ex(('127.0.0.1', _fallback_port))
                _s.close()
                if _r == 0:
                    PG_PORT = _fallback_port
                    os.environ['VIBE_PG_PORT'] = str(PG_PORT)
                    print(f"[PG] 기존 PG 인스턴스 발견 (port={PG_PORT}) → 재사용")
                    break
            except Exception:
                continue
        else:
            print("[PG ERROR] 실행 중인 PostgreSQL을 찾지 못함")
            return

    # 4) 확장 + 테이블 + 트리거를 단일 배치 SQL로 실행 (기동 속도 최적화)
    # [2026-04-13] Claude: 13번 개별 run_pg_sql() → 1번 배치로 합침
    # psql subprocess 폴백 시 프로세스 생성 13회 → 1회로 줄여 ~5초 단축
    try:
        import time as _schema_time
        _schema_start = _schema_time.monotonic()
        run_pg_sql("""
            CREATE EXTENSION IF NOT EXISTS vector;
            CREATE EXTENSION IF NOT EXISTS pg_trgm;
            CREATE EXTENSION IF NOT EXISTS fuzzystrmatch;

            CREATE TABLE IF NOT EXISTS pg_logs (
                id BIGSERIAL PRIMARY KEY,
                agent TEXT NOT NULL,
                terminal_id TEXT DEFAULT '',
                task TEXT NOT NULL,
                status TEXT DEFAULT 'success',
                project_id TEXT DEFAULT '',
                created_at TIMESTAMPTZ DEFAULT NOW()
            );
            ALTER TABLE pg_logs ADD COLUMN IF NOT EXISTS project_id TEXT DEFAULT '';
            CREATE INDEX IF NOT EXISTS idx_pg_logs_project_id ON pg_logs(project_id);

            CREATE TABLE IF NOT EXISTS vibe_notifications (
                id BIGSERIAL PRIMARY KEY,
                agent TEXT NOT NULL DEFAULT 'unknown',
                title TEXT NOT NULL,
                subtitle TEXT,
                body TEXT NOT NULL,
                source TEXT DEFAULT 'cli',
                is_read BOOLEAN DEFAULT FALSE,
                created_at TIMESTAMPTZ DEFAULT NOW()
            );

            CREATE TABLE IF NOT EXISTS vibe_agent_state (
                agent TEXT NOT NULL,
                key TEXT NOT NULL,
                value TEXT,
                icon TEXT,
                color TEXT,
                updated_at TIMESTAMPTZ DEFAULT NOW(),
                PRIMARY KEY (agent, key)
            );

            CREATE TABLE IF NOT EXISTS vibe_agent_logs (
                id BIGSERIAL PRIMARY KEY,
                agent TEXT NOT NULL DEFAULT 'unknown',
                message TEXT NOT NULL,
                level TEXT DEFAULT 'info',
                source TEXT,
                created_at TIMESTAMPTZ DEFAULT NOW()
            );

            CREATE OR REPLACE FUNCTION notify_vibe_notification() RETURNS trigger AS $$
            BEGIN
                PERFORM pg_notify('vibe_notification', json_build_object(
                    'table', 'vibe_notifications',
                    'data', row_to_json(NEW)
                )::text);
                RETURN NEW;
            END;
            $$ LANGUAGE plpgsql;

            DO $$ BEGIN
                IF NOT EXISTS (
                    SELECT 1 FROM pg_trigger WHERE tgname = 'trg_vibe_notification'
                ) THEN
                    CREATE TRIGGER trg_vibe_notification
                        AFTER INSERT ON vibe_notifications
                        FOR EACH ROW EXECUTE FUNCTION notify_vibe_notification();
                END IF;
            END $$;

            CREATE OR REPLACE FUNCTION notify_vibe_state_change() RETURNS trigger AS $$
            BEGIN
                PERFORM pg_notify('vibe_notification', json_build_object(
                    'table', 'vibe_agent_state',
                    'data', row_to_json(NEW)
                )::text);
                RETURN NEW;
            END;
            $$ LANGUAGE plpgsql;

            DO $$ BEGIN
                IF NOT EXISTS (
                    SELECT 1 FROM pg_trigger WHERE tgname = 'trg_vibe_state_change'
                ) THEN
                    CREATE TRIGGER trg_vibe_state_change
                        AFTER INSERT OR UPDATE ON vibe_agent_state
                        FOR EACH ROW EXECUTE FUNCTION notify_vibe_state_change();
                END IF;
            END $$;
        """)
        _schema_ms = (_schema_time.monotonic() - _schema_start) * 1000
        print(f"[PG] 스키마 및 확장 초기화 완료 ({_schema_ms:.0f}ms)")
    except Exception as e:
        print(f"[PG] 시작 오류: {e}")


def _init_project_db(project_id: str):
    """프로젝트별 PostgreSQL 데이터베이스를 생성하고 PG_PROJECT_DB를 갱신합니다.

    [2026-03-22] 하나의 PG 인스턴스에서 프로젝트별 DB 분리 — 포트 충돌 없이 다중 프로젝트 지원.
    DB 이름 규칙: vibe_{project_id} (소문자, 하이픈→언더스코어, 최대 63자)
    예: PROJECT_ID="D--vibe-coding" → DB="vibe_d__vibe_coding"
    """
    global PG_PROJECT_DB
    # DB 이름 생성: PostgreSQL 식별자 규칙 (소문자, _ 허용, 63자 제한)
    safe_id = project_id.lower().replace('-', '_').replace(' ', '_')
    # 알파벳/숫자/밑줄만 허용
    safe_id = ''.join(c for c in safe_id if c.isalnum() or c == '_')
    db_name = f"vibe_{safe_id}"[:63]

    if not db_name or db_name == "vibe_":
        db_name = "vibe_default"

    # postgres DB에 연결하여 프로젝트 DB 존재 여부 확인 후 생성
    try:
        result = run_pg_sql(
            "SELECT 1 FROM pg_database WHERE datname = %s;",
            (db_name,), db="postgres"
        )
        if not result or not result.strip():
            # DB가 없으면 생성 (CREATE DATABASE는 parameterized 불가 → 안전한 이름 직접 삽입)
            run_pg_sql(f'CREATE DATABASE "{db_name}";', db="postgres")
            print(f"[PG] 프로젝트 DB 생성 완료: {db_name}")
        else:
            print(f"[PG] 프로젝트 DB 확인: {db_name} (이미 존재)")

        PG_PROJECT_DB = db_name
        print(f"[PG] PG_PROJECT_DB = {PG_PROJECT_DB}")

        # pg_store 모듈에도 프로젝트 DB 이름 전파
        try:
            from src.pg_store import set_project_db
            set_project_db(db_name)
        except Exception as e:
            print(f"[PG] pg_store.set_project_db 전파 실패 (무시): {e}")

        # 환경변수로도 전파 — mission_control.py, mcp_server.py 등 하위 프로세스용
        os.environ['VIBE_PG_DB'] = db_name

        # 프로젝트 DB에 확장 설치 (배치)
        run_pg_sql("""
            CREATE EXTENSION IF NOT EXISTS vector;
            CREATE EXTENSION IF NOT EXISTS pg_trgm;
            CREATE EXTENSION IF NOT EXISTS fuzzystrmatch;
        """, db=PG_PROJECT_DB)

    except Exception as e:
        print(f"[PG] 프로젝트 DB 생성 실패 (postgres DB 폴백): {e}")
        PG_PROJECT_DB = "postgres"


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
# PROJECT_ROOT: 개발 모드 → git 루트, 배포 모드 → exe 옆, pip → 사용자 홈
if getattr(sys, 'frozen', False):
    BASE_DIR = Path(sys._MEIPASS)
    PROJECT_ROOT = Path(sys.executable).resolve().parent
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
def _current_project_root() -> Path:
    """현재 활성 프로젝트 루트를 반환합니다.

    [개발 vs 배포 버전 차이 해소]
    배포(frozen) 버전에서 PROJECT_ROOT가 exe 폴더나 임시 폴더로 잘못 설정되는 문제 방지.
    config.json의 last_path(UI에서 사용자가 선택한 경로)를 최우선으로 사용합니다.
    config.json이 없거나 경로가 없으면 시작 시 결정된 PROJECT_ROOT를 사용합니다.
    """
    try:
        if CONFIG_FILE.exists():
            cfg = json.loads(CONFIG_FILE.read_text(encoding='utf-8'))
            lp = cfg.get('last_path', '')
            if lp and Path(lp).is_dir():
                return Path(lp)
    except Exception as e:
        print(f"[FILE ERROR] _current_project_root config 로드: {e}")
    return PROJECT_ROOT


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


def _current_project_id() -> str:
    """현재 활성 프로젝트의 PROJECT_ID 문자열을 반환합니다.

    UI에서 폴더를 전환하면 즉시 반영됩니다 (_current_project_root 기반).
    형식: 경로의 드라이브/슬래시를 '--'로 치환 (예: D--vibe-coding)
    """
    root = _current_project_root()
    return str(root).replace('\\', '/').replace(':', '').replace('/', '--').lstrip('-')


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


def _tool_status(name: str) -> dict:
    """Return local CLI installation status for a supported tool."""
    if not name:
        return {"installed": False, "path": "", "version": ""}

    candidates = [name]
    if os.name == 'nt':
        path_name = Path(name).name
        if '.' not in path_name:
            candidates.extend([f'{name}.exe', f'{name}.cmd', f'{name}.bat'])
        else:
            candidates.append(f'{name}.cmd')

    exe_path = ''
    for candidate in candidates:
        found = shutil.which(candidate)
        if found:
            exe_path = found
            break

    if not exe_path:
        return {"installed": False, "path": "", "version": ""}

    version = ''
    try:
        _no_window = getattr(subprocess, 'CREATE_NO_WINDOW', 0x08000000)
        proc = subprocess.run(
            [exe_path, '--version'],
            capture_output=True,
            text=True,
            encoding='utf-8',
            errors='replace',
            timeout=10,
            creationflags=_no_window,
        )
        output = (proc.stdout or proc.stderr or '').strip()
        version = output.splitlines()[0] if output else ''
    except Exception:
        version = ''

    return {"installed": True, "path": exe_path, "version": version}


_TOOL_INSTALL_TARGETS = {
    'gemini': {
        'package': '@google/gemini-cli',
        'display': 'Gemini CLI',
        'command': 'gemini',
    },
    'claude': {
        'package': '@anthropic-ai/claude-code',
        'display': 'Claude Code',
        'command': 'claude',
    },
    'codex': {
        'package': '@openai/codex',
        'display': 'Codex CLI',
        'command': 'codex',
    },
}


def _tool_install_now() -> str:
    """Return a compact local timestamp for tool install progress snapshots."""
    return time.strftime('%Y-%m-%dT%H:%M:%S', time.localtime())


def _default_tool_install_state(name: str) -> dict:
    """Return the default install state payload for a supported tool."""
    tool_meta = _TOOL_INSTALL_TARGETS.get(name, {})
    return {
        'tool': name,
        'display': tool_meta.get('display', name),
        'status': 'idle',
        'message': '',
        'last_line': '',
        'logs': [],
        'started_at': '',
        'finished_at': '',
        'pid': None,
        'exit_code': None,
    }


def _get_npm_executable() -> str:
    """Resolve npm executable with Windows-first lookup for background installs."""
    candidates = ['npm']
    if os.name == 'nt':
        candidates = ['npm.cmd', 'npm.exe', 'npm']

    for candidate in candidates:
        found = shutil.which(candidate)
        if found:
            return found
    return ''


def _get_tool_install_state(name: str) -> dict:
    """Return a thread-safe snapshot of the current install state."""
    base = _default_tool_install_state(name)
    with _tool_install_lock:
        current = _tool_install_state.get(name, {})
        snapshot = dict(base)
        snapshot.update(current)
        logs = snapshot.get('logs') or []
        snapshot['logs'] = list(logs[-20:])
        return snapshot


def _set_tool_install_state(name: str, **updates) -> dict:
    """Update a tool install snapshot and return the merged state."""
    with _tool_install_lock:
        current = _tool_install_state.get(name, _default_tool_install_state(name))
        next_state = dict(current)
        next_state.update(updates)
        logs = next_state.get('logs') or []
        next_state['logs'] = list(logs[-20:])
        _tool_install_state[name] = next_state
        return dict(next_state)


def _watch_tool_install(name: str, proc: subprocess.Popen, command_name: str, display_name: str):
    """Capture npm install output so the UI can poll live progress lines."""
    logs: list[str] = []
    last_line = ''

    try:
        if proc.stdout is not None:
            for raw_line in proc.stdout:
                line = (raw_line or '').strip()
                if not line:
                    continue
                last_line = line
                logs.append(line)
                _set_tool_install_state(name, last_line=line, logs=logs)

        exit_code = proc.wait()
        tool_info = _tool_status(command_name)
        installed = bool(tool_info.get('installed'))

        if exit_code == 0 and installed:
            message = f'{display_name} installation completed.'
            status = 'completed'
        else:
            fallback = last_line or f'npm exited with code {exit_code}.'
            message = f'{display_name} installation failed: {fallback}'
            status = 'failed'

        _set_tool_install_state(
            name,
            status=status,
            message=message,
            last_line=last_line,
            logs=logs,
            finished_at=_tool_install_now(),
            exit_code=exit_code,
            pid=None,
        )
    except Exception as exc:
        failure_line = str(exc)
        if failure_line:
            logs.append(failure_line)
        _set_tool_install_state(
            name,
            status='failed',
            message=f'{display_name} installation failed: {failure_line or "unknown error"}',
            last_line=failure_line,
            logs=logs,
            finished_at=_tool_install_now(),
            pid=None,
        )


def _start_tool_install(name: str) -> dict:
    """Start a background npm install and expose pollable progress for the UI."""
    tool_meta = _TOOL_INSTALL_TARGETS.get(name)
    if not tool_meta:
        return {'status': 'error', 'message': f'Unsupported tool: {name}'}

    current = _get_tool_install_state(name)
    if current.get('status') == 'running':
        return {
            'status': 'success',
            'message': f'{tool_meta["display"]} installation is already running.',
            'install': current,
        }

    npm_exe = _get_npm_executable()
    if not npm_exe:
        failed = _set_tool_install_state(
            name,
            status='failed',
            message='npm executable was not found.',
            last_line='npm executable was not found.',
            logs=['npm executable was not found.'],
            finished_at=_tool_install_now(),
            pid=None,
            exit_code=None,
        )
        return {'status': 'error', 'message': failed['message'], 'install': failed}

    display_name = tool_meta['display']
    package_name = tool_meta['package']
    command_name = tool_meta['command']
    creationflags = getattr(subprocess, 'CREATE_NO_WINDOW', 0x08000000) if os.name == 'nt' else 0

    try:
        proc = subprocess.Popen(
            [npm_exe, 'install', '-g', package_name],
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            stdin=subprocess.DEVNULL,
            text=True,
            encoding='utf-8',
            errors='replace',
            creationflags=creationflags,
        )
    except Exception as exc:
        failed = _set_tool_install_state(
            name,
            status='failed',
            message=f'Could not start {display_name} installation: {exc}',
            last_line=str(exc),
            logs=[str(exc)],
            finished_at=_tool_install_now(),
            pid=None,
            exit_code=None,
        )
        return {'status': 'error', 'message': failed['message'], 'install': failed}

    initial = _set_tool_install_state(
        name,
        display=display_name,
        status='running',
        message=f'{display_name} installation is in progress.',
        last_line=f'Running npm install -g {package_name}',
        logs=[f'Running npm install -g {package_name}'],
        started_at=_tool_install_now(),
        finished_at='',
        pid=proc.pid,
        exit_code=None,
    )

    watcher = threading.Thread(
        target=_watch_tool_install,
        args=(name, proc, command_name, display_name),
        daemon=True,
    )
    watcher.start()

    return {
        'status': 'success',
        'message': f'{display_name} installation started.',
        'install': initial,
    }


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


def _parse_gemini_session(path: Path):
    """Gemini CLI 세션 JSON 파일에서 최신 토큰 usage 정보 추출.

    ~/.gemini/tmp/{project}/chats/session-*.json 파일을 읽어
    가장 최근 gemini 타입 메시지의 tokens 필드를 파싱합니다.
    tokens 구조: { input, output, cached, thoughts, tool, total }
    [2026-02-27] Claude: Gemini 컨텍스트 사용량 표시 기능 추가
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

        # 역순으로 gemini 타입 메시지 탐색 → 가장 최신 usage 우선
        for msg in reversed(messages):
            if msg.get('type') == 'gemini':
                tokens = msg.get('tokens', {})
                if tokens.get('input'):
                    input_tokens  = tokens.get('input', 0)
                    output_tokens = tokens.get('output', 0)
                    cached_tokens = tokens.get('cached', 0)
                    model = msg.get('model', 'gemini')
                    break

        return {
            'session_id':   session_id,
            'slug':         session_id[:8],        # 앞 8자리로 슬러그 대체
            'model':        model or 'gemini',
            'input_tokens': input_tokens,
            'output_tokens': output_tokens,
            'cache_read':   cached_tokens,
            'last_ts':      last_updated,
            'cwd':          '',
        }
    except Exception as e:
        print(f"[FILE ERROR] _parse_gemini_session: {e}")
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


# ── MUX API 핸들러 — cmux-style 터미널 멀티플렉서 REST 인터페이스 ────────────
# [2026-03-18] Claude: P6 Task 34 — vibe_mux Named Pipe 서버에 대한 HTTP 래퍼.
# 대시보드(프론트엔드)가 REST API로 MUX 명령을 보내면, 여기서 Named Pipe를 통해
# vibe_mux 서버에 전달합니다. MUX 서버 미실행 시 에러를 반환합니다.

def _handle_mux_terminals_get(handler):
    """GET /api/mux/terminals — 활성 터미널 목록 조회."""
    try:
        sys.path.insert(0, str(PROJECT_ROOT / 'scripts'))
        from vibe_mux import list_terminals
        result = list_terminals()
        _send_json_response(handler, result)
    except Exception as e:
        _send_json_response(handler, {'ok': False, 'error': f'MUX 서버 연결 실패: {e}'}, status=503)


def _handle_mux_send_text(handler, body):
    """POST /api/mux/send-text — 터미널에 텍스트 전송.

    [요청 본문] {"terminal": "T2", "text": "보안 점검해줘"}
    [응답] {"ok": true, "result": {"terminal": "T2", "sent": true}}
    """
    try:
        sys.path.insert(0, str(PROJECT_ROOT / 'scripts'))
        from vibe_mux import send_text
        terminal = body.get('terminal', '')
        text = body.get('text', '')
        from_agent = body.get('from', 'mux')
        metadata = body.get('metadata', {})
        if not terminal or not text:
            _send_json_response(handler, {'ok': False, 'error': 'terminal과 text 필수'}, status=400)
            return
        result = send_text(
            terminal,
            text,
            from_agent=str(from_agent or 'mux'),
            metadata=metadata if isinstance(metadata, dict) else {},
        )
        _send_json_response(handler, result)
    except Exception as e:
        _send_json_response(handler, {'ok': False, 'error': f'MUX 전송 실패: {e}'}, status=503)


def _handle_mux_send_key(handler, body):
    """POST /api/mux/send-key — 터미널에 특수 키 전송.

    [요청 본문] {"terminal": "T2", "key": "enter"}
    """
    try:
        sys.path.insert(0, str(PROJECT_ROOT / 'scripts'))
        from vibe_mux import _send_to_mux
        terminal = body.get('terminal', '')
        key = body.get('key', '')
        if not terminal or not key:
            _send_json_response(handler, {'ok': False, 'error': 'terminal과 key 필수'}, status=400)
            return
        result = _send_to_mux({
            'id': f'api-mux-key',
            'method': 'surface.send_key',
            'params': {'terminal': terminal, 'key': key},
        })
        _send_json_response(handler, result)
    except Exception as e:
        _send_json_response(handler, {'ok': False, 'error': f'MUX 키 전송 실패: {e}'}, status=503)


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

        # ─── 신규: 사고 과정 실시간 스트리밍 ───
        if path == '/api/events/thoughts':
            self.send_response(200)
            self.send_header('Content-Type', 'text/event-stream')
            self.send_header('Access-Control-Allow-Origin', self._cors_origin())
            self.send_header('Cache-Control', 'no-cache')
            self.send_header('Connection', 'keep-alive')
            self.end_headers()
            
            # 초기 데이터 전송 (메모리에 쌓인 로그)
            for log in THOUGHT_LOGS:
                self.wfile.write(f"data: {json.dumps(log, ensure_ascii=False)}\n\n".encode('utf-8'))
                self.wfile.flush()
            
            # 실시간 업데이트를 위해 클라이언트 등록
            with _SSE_LOCK:
                THOUGHT_CLIENTS.add(self)
            try:
                self.connection.settimeout(None)  # 타임아웃 제거 — 하트비트로 연결 관리
                while True:
                    time.sleep(30)
                    self.wfile.write(b": heartbeat\n\n")
                    self.wfile.flush()
            except Exception:
                pass  # SSE thought 클라이언트 연결 끊김 — finally에서 정리
            finally:
                with _SSE_LOCK:
                    THOUGHT_CLIENTS.discard(self)
            return

        # ─── 자율 에이전트 출력 실시간 스트리밍 ───
        # _agent_broadcast_worker가 cli_agent 큐를 읽어 AGENT_CLIENTS 세트의
        # 각 클라이언트 전용 큐로 팬아웃 — 다중 연결/재연결 시 이벤트 손실 없음
        if path == '/api/events/agent':
            self.send_response(200)
            self.send_header('Content-Type', 'text/event-stream')
            self.send_header('Access-Control-Allow-Origin', self._cors_origin())
            self.send_header('Cache-Control', 'no-cache')
            self.send_header('Connection', 'keep-alive')
            self.end_headers()
            from queue import Queue as _ClientQueue, Empty as _QEmpty
            client_q = _ClientQueue(maxsize=0)  # 클라이언트별 전용 큐 (무제한 — done 이벤트 드롭 방지)
            with _SSE_LOCK:
                AGENT_CLIENTS.add(client_q)
            try:
                self.connection.settimeout(None)
                while True:
                    try:
                        msg = client_q.get(timeout=1.0)
                        try:
                            self.wfile.write(f"data: {msg}\n\n".encode('utf-8'))
                            self.wfile.flush()
                        except Exception as e:
                            break  # 클라이언트 연결 끊김
                    except _QEmpty:
                        # 큐 비어있으면 하트비트 전송 (연결 유지)
                        try:
                            self.wfile.write(b": heartbeat\n\n")
                            self.wfile.flush()
                        except Exception as e:
                            break  # 클라이언트 연결 끊김
            except Exception as e:
                pass  # SSE agent 클라이언트 연결 끊김
            finally:
                with _SSE_LOCK:
                    AGENT_CLIENTS.discard(client_q)
            return

        # ─── 신규: 파일 시스템 변경 이벤트 스트리밍 ───
        if path == '/api/events/fs':
            self.send_response(200)
            self.send_header('Content-Type', 'text/event-stream')
            self.send_header('Access-Control-Allow-Origin', self._cors_origin())
            self.send_header('Cache-Control', 'no-cache')
            self.send_header('Connection', 'keep-alive')
            self.end_headers()
            
            with _SSE_LOCK:
                FS_CLIENTS.add(self)
            try:
                # SSE 연결 타임아웃 완화 (60초)
                self.connection.settimeout(60.0)
                # 연결 유지를 위한 하트비트 루프
                while True:
                    time.sleep(30) # 하트비트 주기를 30초로 완화
                    self.wfile.write(b": heartbeat\n\n")
                    self.wfile.flush()
            except Exception as e:
                pass  # SSE FS 클라이언트 연결 끊김
            finally:
                with _SSE_LOCK:
                    FS_CLIENTS.discard(self)
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
            
            # 1. 초기 데이터 전송 (최근 50개 - PostgreSQL에서 조회)
            try:
                rows = run_pg_sql_csv(
                    "SELECT agent, level, message as trigger, task_id as session_id, "
                    "metadata->>'terminal_id' as terminal_id, metadata->>'project' as project, "
                    "metadata->>'raw_status' as status, to_char(timestamp, 'YYYY-MM-DD HH24:MI:SS') as timestamp "
                    "FROM hive_logs ORDER BY id DESC LIMIT 50"
                )
                if rows:
                    for row in reversed(rows):
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
                        
                        # 프론트엔드 호환 포맷 변환
                        meta = payload.get('metadata', {})
                        if isinstance(meta, str): meta = json.loads(meta)
                        
                        out_row = {
                            "agent": payload.get('agent'),
                            "level": payload.get('level'),
                            "trigger": payload.get('message'),
                            "session_id": payload.get('task_id'),
                            "terminal_id": meta.get('terminal_id'),
                            "project": meta.get('project'),
                            "status": meta.get('raw_status'),
                            "timestamp": payload.get('timestamp')
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
            self.send_response(200)
            self.send_header('Content-Type', 'application/json;charset=utf-8')
            self.send_header('Access-Control-Allow-Origin', self._cors_origin())
            self.end_headers()
            projects = []
            if PROJECTS_FILE.exists():
                try:
                    with open(PROJECTS_FILE, 'r', encoding='utf-8') as f:
                        projects = json.load(f)
                except: pass
            
            # GET 요청이면 목록 반환, POST 처리는 아래 do_POST에서 함
            self.wfile.write(json.dumps(projects).encode('utf-8'))
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
                        result = {"status": "success", "message": f"Gemini CLI & Claude Desktop에 vibe-coding MCP 등록 완료!\n{output}"}
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
            self.send_response(200)
            self.send_header('Content-Type', 'application/json;charset=utf-8')
            self.send_header('Access-Control-Allow-Origin', self._cors_origin())
            self.end_headers()
            query = parse_qs(parsed_path.query)
            target_path = query.get('path', [''])[0]
            
            result = {"status": "error", "message": "Invalid path"}
            if target_path and os.path.exists(target_path) and os.path.isdir(target_path):
                try:
                    # .gemini, scripts, GEMINI.md 등을 복사
                    source_base = BASE_DIR.parent
                    
                    # .gemini 복사
                    gemini_src = source_base / ".gemini"
                    if gemini_src.exists():
                        shutil.copytree(gemini_src, Path(target_path) / ".gemini", dirs_exist_ok=True)
                    
                    # scripts 복사 — 배포 범용화: SCRIPTS_DIR이 None이면 skip
                    scripts_src = SCRIPTS_DIR
                    if scripts_src and scripts_src.exists():
                        shutil.copytree(scripts_src, Path(target_path) / "scripts", dirs_exist_ok=True)
                        
                    # GEMINI.md 복사
                    gemini_md_src = source_base / "GEMINI.md"
                    if gemini_md_src.exists():
                        shutil.copy(gemini_md_src, Path(target_path) / "GEMINI.md")
                        
                    # CLAUDE.md 복사
                    claude_md_src = source_base / "CLAUDE.md"
                    if claude_md_src.exists():
                        shutil.copy(claude_md_src, Path(target_path) / "CLAUDE.md")
                        
                    # RULES.md 복사 (누락 방지)
                    rules_md_src = source_base / "RULES.md"
                    if rules_md_src.exists():
                        shutil.copy(rules_md_src, Path(target_path) / "RULES.md")
                        
                    # PROJECT_MAP.md 복사 — 소스에 없으면 파일 구조 자동 분석으로 생성
                    # [배포 버전] exe 번들에 PROJECT_MAP.md가 없을 때 빨간불 방지
                    project_map_dst = Path(target_path) / "PROJECT_MAP.md"
                    project_map_src = source_base / "PROJECT_MAP.md"
                    if project_map_src.exists():
                        shutil.copy(project_map_src, project_map_dst)
                    elif not project_map_dst.exists():
                        # 실제 프로젝트 파일 구조를 분석하여 PROJECT_MAP.md 자동 생성
                        # LLM 없이도 유용한 맵을 만들 수 있도록 구조 탐색
                        proj_name = Path(target_path).name
                        proj_root = Path(target_path)

                        # 무시할 디렉터리/패턴 목록
                        IGNORE_DIRS = {
                            '.git', '.ai_monitor', 'node_modules', '__pycache__',
                            '.venv', 'venv', '.ruff_cache', 'dist', 'build',
                            '.cache', '.tox', 'coverage', '.pytest_cache',
                        }
                        IGNORE_EXTS = {'.pyc', '.pyo', '.db', '.db-shm', '.db-wal',
                                       '.log', '.tmp', '.exe', '.dll', '.so'}

                        # 기술 스택 감지 (특정 파일 존재 여부로 판단)
                        tech_hints = []
                        if (proj_root / 'package.json').exists():
                            try:
                                pkg = json.loads((proj_root / 'package.json').read_text(encoding='utf-8'))
                                deps = list((pkg.get('dependencies', {}) or {}).keys())
                                if 'react' in deps: tech_hints.append('React')
                                if 'vue' in deps: tech_hints.append('Vue')
                                if 'next' in deps: tech_hints.append('Next.js')
                                if 'vite' in deps or 'vite' in str(pkg.get('devDependencies', {})): tech_hints.append('Vite')
                                if 'typescript' in str(pkg.get('devDependencies', {})): tech_hints.append('TypeScript')
                            except Exception as e: pass  # package.json 파싱 실패 허용
                            if not tech_hints: tech_hints.append('Node.js')
                        if (proj_root / 'requirements.txt').exists() or (proj_root / 'pyproject.toml').exists():
                            tech_hints.append('Python')
                        if (proj_root / 'Cargo.toml').exists(): tech_hints.append('Rust')
                        if (proj_root / 'go.mod').exists(): tech_hints.append('Go')
                        if (proj_root / '.claude').is_dir(): tech_hints.append('Claude Code')
                        if (proj_root / '.gemini').is_dir(): tech_hints.append('Gemini')

                        # 파일 역할 추론 (파일명 패턴 → 설명)
                        FILE_ROLES = {
                            'server.py': 'HTTP/WebSocket 서버 진입점',
                            'main.py': '메인 진입점',
                            'app.py': '앱 진입점',
                            'index.ts': '메인 진입점',
                            'index.js': '메인 진입점',
                            'App.tsx': 'React 루트 컴포넌트',
                            'App.vue': 'Vue 루트 컴포넌트',
                            'package.json': 'Node.js 패키지 설정',
                            'requirements.txt': 'Python 패키지 목록',
                            'pyproject.toml': 'Python 프로젝트 설정',
                            'Cargo.toml': 'Rust 패키지 설정',
                            'go.mod': 'Go 모듈 설정',
                            'CLAUDE.md': 'Claude AI 지침',
                            'GEMINI.md': 'Gemini AI 지침',
                            'RULES.md': 'AI 에이전트 공통 규칙',
                            '.env': '환경 변수 (민감 정보 포함)',
                            'docker-compose.yml': 'Docker Compose 설정',
                            'Dockerfile': 'Docker 빌드 설정',
                        }

                        # 최상위 구조 탐색 (2레벨)
                        structure_lines = []
                        key_files = []

                        def _scan_dir(path: Path, depth: int, prefix: str = '') -> None:
                            if depth > 2: return
                            try:
                                items = sorted(path.iterdir(), key=lambda x: (x.is_file(), x.name.lower()))
                            except PermissionError:
                                return
                            for item in items:
                                if item.name.startswith('.') and item.name not in ('.claude', '.gemini'):
                                    continue
                                if item.is_dir() and item.name in IGNORE_DIRS:
                                    continue
                                if item.is_file() and item.suffix in IGNORE_EXTS:
                                    continue
                                rel = f"{prefix}{'📁 ' if item.is_dir() else '📄 '}{item.name}"
                                role = FILE_ROLES.get(item.name, '')
                                structure_lines.append(f"- {rel}" + (f" — {role}" if role else ''))
                                if item.is_file() and role:
                                    key_files.append((str(item.relative_to(proj_root)), role))
                                if item.is_dir() and depth < 2:
                                    _scan_dir(item, depth + 1, prefix + '  ')

                        _scan_dir(proj_root, 1)

                        # PROJECT_MAP.md 내용 조립
                        tech_str = ' + '.join(tech_hints) if tech_hints else '미확인'
                        now_str = datetime.now().strftime('%Y-%m-%d')
                        map_content = (
                            f"# 📁 {proj_name} — PROJECT MAP\n\n"
                            f"> **자동 생성:** {now_str} (Vibe Coding 스킬 복구)\n"
                            f"> 이 파일은 프로젝트 파일 구조를 분석하여 자동으로 생성되었습니다.\n"
                            f"> 내용을 검토하고 필요한 부분을 보완해주세요.\n\n"
                            f"## 기술 스택\n\n"
                            f"- **감지된 기술:** {tech_str}\n\n"
                            f"## 프로젝트 구조\n\n"
                            + ('\n'.join(structure_lines[:60]) or '- (파일 없음)')
                            + '\n\n'
                            + (
                                "## 핵심 파일\n\n"
                                + '\n'.join(f"- `{f}` — {r}" for f, r in key_files[:20])
                                + '\n'
                                if key_files else
                                "## 핵심 파일\n\n- (자동 감지 없음 — 직접 기록해주세요)\n"
                            )
                        )
                        project_map_dst.write_text(map_content, encoding='utf-8')

                    # 대상 프로젝트의 .ai_monitor/data 폴더와 DB 초기화
                    # — 스킬 설치 후 하이브 워치독이 정상 동작하려면 DB가 있어야 함
                    target_data = Path(target_path) / ".ai_monitor" / "data"
                    target_data.mkdir(parents=True, exist_ok=True)
                    ensure_schema(target_data)

                    result = {"status": "success", "message": f"Skills installed to {target_path}"}
                except Exception as e:
                    result = {"status": "error", "message": str(e)}
            
            self.wfile.write(json.dumps(result).encode('utf-8'))

        # ── [모듈 위임] hive_api — /api/hive/*, /api/orchestrator/*, /api/superpowers/status,
        #    /api/skill-results, /api/context-usage, /api/gemini-context-usage, /api/local-models ──
        elif (parsed_path.path.startswith('/api/hive/') or
              parsed_path.path.startswith('/api/orchestrator/') or
              parsed_path.path in ('/api/superpowers/status', '/api/skill-results',
                                   '/api/skill-ab-test', '/api/skill/predict',
                                   '/api/context-usage', '/api/gemini-context-usage',
                                   '/api/local-models')):
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
                _parse_gemini_session=_parse_gemini_session,
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

        # ── [모듈 위임] MUX API — /api/mux/* (cmux-style 터미널 멀티플렉서) ──
        elif parsed_path.path == '/api/mux/terminals':
            _handle_mux_terminals_get(self)

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

        elif parsed_path.path == '/api/hive/health/repair':
            self.send_response(200)
            self.send_header('Content-Type', 'application/json;charset=utf-8')
            self.send_header('Access-Control-Allow-Origin', self._cors_origin())
            self.end_headers()
            try:
                if not SCRIPTS_DIR:
                    raise Exception('설치 버전에서는 워치독 기능을 사용할 수 없습니다')
                watchdog_script = SCRIPTS_DIR / "hive_watchdog.py"
                # CREATE_NO_WINDOW: Python 서브프로세스 콘솔 창 방지
                _no_window = getattr(subprocess, 'CREATE_NO_WINDOW', 0x08000000)
                result_proc = subprocess.run(
                    [sys.executable, str(watchdog_script), "--check"],
                    capture_output=True, text=True, encoding='utf-8',
                    creationflags=_no_window
                )
                output = result_proc.stdout
                json_start = output.find('{')
                if json_start != -1:
                    result = json.loads(output[json_start:])
                else:
                    result = {"status": "error", "message": "Failed to parse watchdog output"}
            except Exception as e:
                result = {"status": "error", "message": str(e)}
            self.wfile.write(json.dumps(result, ensure_ascii=False).encode('utf-8'))
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
            self.send_response(200)
            self.send_header('Content-Type', 'application/json;charset=utf-8')
            self.send_header('Access-Control-Allow-Origin', self._cors_origin())
            self.end_headers()
            update_file = DATA_DIR / "update_ready.json"
            if update_file.exists():
                try:
                    with open(update_file, "r", encoding="utf-8") as f:
                        data = json.load(f)
                    # update_ready.json에 저장된 버전이 현재 실행 중인 버전보다
                    # 낮거나 같으면 → 이미 해당 버전 이상으로 업데이트된 것이므로
                    # 파일을 삭제하고 "업데이트 없음" 상태로 반환한다.
                    # [버그수정] 이전 코드는 == 비교만 했기 때문에 v3.6.9 캐시가
                    # v3.6.10에서도 "업데이트 있음"으로 잘못 표시되는 문제가 있었음.
                    file_ver = data.get("version", "").lstrip("v").strip()
                    cur_ver  = __version__.lstrip("v").strip()

                    def _parse_ver(v):
                        """'3.6.10' → (3, 6, 10) 정수 튜플로 변환"""
                        parts = v.split(".")
                        result = []
                        for p in parts:
                            try: result.append(int(p))
                            except ValueError: result.append(0)
                        while len(result) < 3:
                            result.append(0)
                        return tuple(result)

                    # 저장된 업데이트 버전이 현재 버전보다 실제로 높을 때만 알림 표시
                    if file_ver and _parse_ver(file_ver) > _parse_ver(cur_ver):
                        self.wfile.write(json.dumps(data).encode('utf-8'))
                    else:
                        # 같거나 낮은 버전 → 오래된 캐시이므로 삭제
                        update_file.unlink(missing_ok=True)
                        self.wfile.write(json.dumps({"ready": False, "downloading": False}).encode('utf-8'))
                except Exception as e:
                    self.wfile.write(json.dumps({"error": str(e)}).encode('utf-8'))
            else:
                self.wfile.write(json.dumps({"ready": False, "downloading": False}).encode('utf-8'))

        elif parsed_path.path == '/api/trigger-update-check':
            self.send_response(200)
            self.send_header('Content-Type', 'application/json;charset=utf-8')
            self.send_header('Access-Control-Allow-Origin', self._cors_origin())
            self.end_headers()
            try:
                from updater import check_and_update
                threading.Thread(target=check_and_update, args=(DATA_DIR,), daemon=True).start()
                self.wfile.write(json.dumps({"started": True}).encode('utf-8'))
            except Exception as e:
                self.wfile.write(json.dumps({"started": False, "reason": str(e)}).encode('utf-8'))

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

        elif parsed_path.path == '/api/orchestrator/skill-chain':
            # 스킬 체인 실행 상태 반환 — skill_chain.db(SQLite) 조회
            # 응답: {skill_registry: [...], terminals: {T1: {steps:[...]}, ...}}
            # 대시보드가 3초마다 폴링하여 터미널별 스킬 실행 흐름을 실시간 표시
            self.send_response(200)
            self.send_header('Content-Type', 'application/json;charset=utf-8')
            self.send_header('Access-Control-Allow-Origin', self._cors_origin())
            self.end_headers()
            try:
                if not SCRIPTS_DIR:
                    raise Exception('설치 버전에서는 오케스트레이터 기능을 사용할 수 없습니다')
                _orch_dir = str(SCRIPTS_DIR)
                if _orch_dir not in sys.path:
                    sys.path.insert(0, _orch_dir)
                from skill_orchestrator import _build_response
                result = _build_response()
                self.wfile.write(json.dumps(result, ensure_ascii=False).encode('utf-8'))
            except Exception as e:
                self.wfile.write(json.dumps({
                    "skill_registry": [], "terminals": {}, "error": str(e)
                }, ensure_ascii=False).encode('utf-8'))

        elif parsed_path.path == '/api/orchestrator/status':
            # 오케스트레이터 현황 — 에이전트 활동 상태, 태스크 분배, 최근 액션 로그 반환
            self.send_response(200)
            self.send_header('Content-Type', 'application/json;charset=utf-8')
            self.send_header('Access-Control-Allow-Origin', self._cors_origin())
            self.end_headers()
            try:
                KNOWN_AGENTS = ['claude', 'gemini', 'codex']
                IDLE_SEC = 300  # 5분

                # 에이전트 마지막 활동 시각 (Postgres 우선, 파일 레거시 폴백)
                agent_last_seen: dict = get_agent_last_seen(KNOWN_AGENTS)
                for agent_name, last_seen in get_agent_last_seen_from_sessions(DATA_DIR, KNOWN_AGENTS).items():
                    if last_seen and (agent_last_seen.get(agent_name) is None or last_seen > agent_last_seen[agent_name]):
                        agent_last_seen[agent_name] = last_seen

                # 메모리 작성 시각으로 보완 — 더 최신 활동 기록 포함
                for row in list_memory(top_k=100, project_id=_current_project_id()):
                    author_lower = str(row.get('author', '')).lower()
                    last = row.get('updated_at')
                    for agent_name in KNOWN_AGENTS:
                        if agent_name in author_lower:
                            current = agent_last_seen.get(agent_name)
                            if last and (current is None or last > current):
                                agent_last_seen[agent_name] = last

                # in-memory AGENT_STATUS 로 보완 (가장 실시간 하트비트)
                with AGENT_STATUS_LOCK:
                    for a_name, st in AGENT_STATUS.items():
                        a_key = (
                            'claude' if 'claude' in a_name.lower()
                            else 'gemini' if 'gemini' in a_name.lower()
                            else 'codex' if 'codex' in a_name.lower()
                            else None
                        )
                        if a_key and st.get('last_seen'):
                            hb_dt = datetime.fromtimestamp(st['last_seen'])
                            hb_iso = hb_dt.isoformat()
                            if agent_last_seen.get(a_key) is None or hb_iso > agent_last_seen[a_key]:
                                agent_last_seen[a_key] = hb_iso

                # ── 터미널별 실시간 에이전트 현황 (PTY 세션 기반) ────────────────
                # pty_sessions에 저장된 실제 실행 중인 에이전트를 슬롯 1~8 기준으로 반환.
                # 슬롯이 비어 있으면 빈 문자열, 에이전트 이름이 없으면 'shell'로 표시.
                terminal_agents: dict = {}
                pty_active_agents: set = set()  # 현재 PTY에 살아 있는 에이전트 집합
                _pty_snap = _get_node_pty_sessions()  # Node PTY 서버 REST 조회
                for slot_num in range(1, 9):
                    info = _pty_snap.get(f'T{slot_num}')
                    if info and info.get('running'):
                        a = info.get('agent', '') or 'shell'
                        terminal_agents[str(slot_num)] = a
                        if a in KNOWN_AGENTS:
                            pty_active_agents.add(a)
                    else:
                        terminal_agents[str(slot_num)] = ''

                # 에이전트 상태 — PTY 실행 중이면 무조건 active, 아니면 DB 타임스탬프 fallback
                now_dt = datetime.now()
                agent_status = {}
                for agent, seen in agent_last_seen.items():
                    if agent in pty_active_agents:
                        # 현재 PTY 터미널에서 실행 중 → 즉시 active
                        agent_status[agent] = {'state': 'active', 'last_seen': now_dt.isoformat(), 'idle_sec': 0}
                    elif seen is None:
                        agent_status[agent] = {'state': 'unknown', 'last_seen': None, 'idle_sec': None}
                    else:
                        try:
                            seen_dt = datetime.fromisoformat(seen.replace('Z', ''))
                            idle = int((now_dt - seen_dt).total_seconds())
                            agent_status[agent] = {
                                'state': 'idle' if idle > IDLE_SEC else 'active',
                                'last_seen': seen, 'idle_sec': idle
                            }
                        except Exception as e:
                            agent_status[agent] = {'state': 'unknown', 'last_seen': seen, 'idle_sec': None}

                # 태스크 분배 현황
                tasks_list: list = []
                if TASKS_FILE.exists():
                    with open(TASKS_FILE, 'r', encoding='utf-8') as f:
                        tasks_list = json.load(f)
                task_dist: dict = {a: {'pending': 0, 'in_progress': 0, 'done': 0} for a in KNOWN_AGENTS + ['all']}
                for t in tasks_list:
                    key = t.get('assigned_to', 'all') if t.get('assigned_to') in task_dist else 'all'
                    s = t.get('status', 'pending')
                    if s in task_dist[key]:
                        task_dist[key][s] += 1

                # 오케스트레이터 최근 액션 로그
                # orchestrator_log.jsonl 없으면 task_logs.jsonl 폴백으로 표시
                orch_log = DATA_DIR / 'orchestrator_log.jsonl'
                recent_actions: list = []
                if orch_log.exists():
                    for line in reversed(orch_log.read_text(encoding='utf-8').strip().splitlines()[-20:]):
                        try:
                            recent_actions.append(json.loads(line))
                        except Exception as e:
                            pass  # orchestrator_log JSONL 개별 행 파싱 실패 허용
                if not recent_actions:
                    # task_logs.jsonl에서 최근 20개 폴백 — 에이전트 활동 이력으로 표시
                    task_log_file = DATA_DIR / 'task_logs.jsonl'
                    if task_log_file.exists():
                        lines = task_log_file.read_text(encoding='utf-8').strip().splitlines()
                        for line in reversed(lines[-20:]):
                            try:
                                entry = json.loads(line)
                                recent_actions.append({
                                    'action': entry.get('agent', 'agent'),
                                    'detail': entry.get('task', ''),
                                    'timestamp': entry.get('timestamp', ''),
                                })
                            except Exception as e:
                                pass  # task_logs JSONL 개별 행 파싱 실패 허용

                # 현재 경고
                warnings: list = []
                for agent, st in agent_status.items():
                    if st['state'] == 'idle' and st.get('idle_sec'):
                        warnings.append(f"{agent} {st['idle_sec'] // 60}분째 비활성")
                for agent, dist in task_dist.items():
                    if agent == 'all': continue
                    active = dist['pending'] + dist['in_progress']
                    if active >= 5:
                        warnings.append(f"{agent} 태스크 {active}개 (과부하)")

                self.wfile.write(json.dumps({
                    'agent_status': agent_status,
                    'task_distribution': task_dist,
                    'recent_actions': recent_actions,
                    'warnings': warnings,
                    'terminal_agents': terminal_agents,  # 슬롯별 실시간 에이전트
                    'timestamp': now_dt.strftime('%Y-%m-%dT%H:%M:%S'),
                }, ensure_ascii=False).encode('utf-8'))
            except Exception as e:
                self.wfile.write(json.dumps({'error': str(e)}).encode('utf-8'))
        # [2026-04-18] /api/dispatcher/* 제거 — 멀티 LLM 디스패처 정리 (실사용 0)

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
        """DELETE 메소드 — 오피스 API는 오피스 서버로 프록시."""
        parsed_path = urlparse(self.path)
        path = parsed_path.path
        if path.startswith('/api/office/'):
            length = int(self.headers.get('Content-Length', '0') or 0)
            body = self.rfile.read(length) if length > 0 else None
            _proxy_to_office_server(self, method='DELETE', body=body)
            return
        self.send_response(404)
        self.send_header('Content-Type', 'application/json;charset=utf-8')
        self.send_header('Access-Control-Allow-Origin', self._cors_origin())
        self.end_headers()
        self.wfile.write(b'{"error":"not found"}')

    def do_POST(self):
        parsed_path = urlparse(self.path)
        path = parsed_path.path

        # ─── Telegram 설정 저장 + 테스트 ───────────────────────────────────
        if path == '/api/config/telegram':
            self._handle_telegram_config_post()
            return
        elif path == '/api/telegram/test':
            self._handle_telegram_test()
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

        # ── [모듈 위임 - POST] tools_api — /api/tools/install (도구 설치 실행) ─
        if parsed_path.path.startswith('/api/tools/'):
            from api import tools_api
            content_length = int(self.headers.get('Content-Length', 0))
            _body = json.loads(self.rfile.read(content_length).decode('utf-8')) if content_length else {}
            tools_api.handle_post(self, parsed_path.path, _body)

        # ── [모듈 위임 - POST] files_api — /api/save-file, /api/file-rename, /api/files/* ─
        elif parsed_path.path in ('/api/save-file', '/api/file-rename', '/api/files/create', '/api/files/delete'):
            content_length = int(self.headers.get('Content-Length', 0))
            _body = json.loads(self.rfile.read(content_length).decode('utf-8')) if content_length else {}
            files_api.handle_post(
                self, parsed_path.path, _body,
                validate_file_path=_validate_file_path,
            )

        elif parsed_path.path == '/api/apply-update':
            # [업데이트 적용] — 응답 전송 후 비동기로 exe 교체 실행
            self.send_response(200)
            self.send_header('Content-Type', 'application/json;charset=utf-8')
            self.send_header('Access-Control-Allow-Origin', self._cors_origin())
            self.end_headers()

            update_file = DATA_DIR / "update_ready.json"
            if not update_file.exists():
                self.wfile.write(json.dumps({"success": False, "error": "No update ready"}).encode('utf-8'))
                self.wfile.flush()
                return

            try:
                with open(update_file, "r", encoding="utf-8") as f:
                    update_data = json.load(f)

                exe_path = update_data.get("exe_path")
                if not exe_path or not os.path.exists(exe_path):
                    self.wfile.write(json.dumps({"success": False, "error": "New executable not found", "path": exe_path}).encode('utf-8'))
                    self.wfile.flush()
                    return

                # 응답을 먼저 완전히 전송 — os._exit() 전에 클라이언트가 수신하도록 보장
                self.wfile.write(json.dumps({"success": True}).encode('utf-8'))
                self.wfile.flush()
                try:
                    update_file.unlink()
                except OSError: pass

                from updater import apply_update_from_temp
                _exe = Path(exe_path)

                def _do_apply():
                    """응답 전송 완료 후 실행되는 업데이트 스레드.
                    오류 발생 시 update_ready.json + update_error.log에 기록.
                    """
                    # 소켓 버퍼 플러시 대기 (0.3s) — 응답이 클라이언트에 도달할 시간 확보
                    time.sleep(0.3)
                    try:
                        apply_update_from_temp(_exe)
                    except Exception as ex:
                        import traceback
                        err_detail = traceback.format_exc()
                        print(f"[!] apply_update_from_temp 실패: {ex}\n{err_detail}")
                        # 에러 로그 파일에 기록 — 디버깅용
                        try:
                            with open(DATA_DIR / "update_error.log", "w", encoding="utf-8") as lf:
                                lf.write(f"[{time.strftime('%Y-%m-%d %H:%M:%S')}] {err_detail}\n")
                        except OSError:
                            pass
                        # 실패 시 update_ready.json 복원 — UI에 에러 메시지 표시
                        try:
                            _ver = update_data.get("version", _exe.stem)
                            _update_info = {"ready": True, "downloading": False,
                                            "version": _ver, "exe_path": str(_exe),
                                            "error": str(ex)}
                            with open(DATA_DIR / "update_ready.json", "w", encoding="utf-8") as ef:
                                json.dump(_update_info, ef)
                        except OSError:
                            pass

                # daemon=False: 메인 프로세스가 종료되어도 업데이트 스레드는 완료까지 실행
                threading.Thread(target=_do_apply, daemon=False).start()
            except Exception as e:
                self.wfile.write(json.dumps({"success": False, "error": str(e)}).encode('utf-8'))
                self.wfile.flush()

        elif parsed_path.path == '/api/agents/heartbeat':
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
        elif parsed_path.path == '/api/trigger-update-check':
            # 업데이트 확인 트리거 — do_GET과 동일 로직 (프론트엔드가 POST로 호출)
            self.send_response(200)
            self.send_header('Content-Type', 'application/json;charset=utf-8')
            self.send_header('Access-Control-Allow-Origin', self._cors_origin())
            self.end_headers()
            try:
                from updater import check_and_update
                threading.Thread(target=check_and_update, args=(DATA_DIR,), daemon=True).start()
                self.wfile.write(json.dumps({"started": True}).encode('utf-8'))
            except Exception as e:
                self.wfile.write(json.dumps({"started": False, "reason": str(e)}).encode('utf-8'))

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
        elif parsed_path.path == '/api/projects':
            self.send_response(200)
            self.send_header('Content-Type', 'application/json;charset=utf-8')
            self.send_header('Access-Control-Allow-Origin', self._cors_origin())
            self.end_headers()
            try:
                data = json.loads(self.rfile.read(int(self.headers['Content-Length'])).decode('utf-8'))
                new_path = data.get('path', '').strip().replace('\\', '/')
                if not new_path:
                    self.wfile.write(json.dumps({"error": "Invalid path"}).encode('utf-8'))
                    return
                
                projects = []
                if PROJECTS_FILE.exists():
                    with open(PROJECTS_FILE, 'r', encoding='utf-8') as f:
                        projects = json.load(f)
                
                if new_path in projects:
                    projects.remove(new_path)
                projects.insert(0, new_path) # 최신 프로젝트를 위로
                projects = projects[:20] # 최대 20개 저장
                with open(PROJECTS_FILE, 'w', encoding='utf-8') as f:
                    json.dump(projects, f, ensure_ascii=False, indent=2)
                
                self.wfile.write(json.dumps({"status": "success", "projects": projects}).encode('utf-8'))
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

        # ── [모듈 위임 - POST] vibe_api — /api/vibe/* (cmux 호환 CLI API) ─
        elif parsed_path.path == '/api/vibe/notify':
            vibe_api.handle_notify(self)
        elif parsed_path.path == '/api/vibe/progress':
            vibe_api.handle_progress(self, method='POST')
        elif parsed_path.path == '/api/vibe/progress/clear':
            vibe_api.handle_progress(self, method='DELETE')
        elif parsed_path.path == '/api/vibe/status':
            vibe_api.handle_status(self, method='POST')
        elif parsed_path.path == '/api/vibe/status/clear':
            vibe_api.handle_status(self, method='DELETE')
        elif parsed_path.path == '/api/vibe/log':
            vibe_api.handle_log(self, method='POST')
        elif parsed_path.path == '/api/vibe/log/clear':
            vibe_api.handle_log(self, method='DELETE')

        # ── [모듈 위임 - POST] MUX API — /api/mux/* (cmux-style 텍스트 주입) ──
        elif parsed_path.path == '/api/mux/send-text':
            _handle_mux_send_text(self, _body)
        elif parsed_path.path == '/api/mux/send-key':
            _handle_mux_send_key(self, _body)

        # ── [모듈 위임 - POST] agent_api — /api/agent/run, /api/agent/stop ─
        elif parsed_path.path.startswith('/api/agent/'):
            agent_api.handle_post(self, parsed_path.path)
        elif parsed_path.path.startswith('/api/pty/'):
            pty_api.handle_post(self, parsed_path.path)

        # ── [모듈 위임 - POST] experience_api — /api/experience ───────
        elif parsed_path.path == '/api/experience':
            experience_api.handle_post(self, parsed_path.path)

        # ── [모듈 위임 - POST] zettel_api — /api/zettel/* ─────────────
        elif parsed_path.path.startswith('/api/zettel/'):
            content_length = int(self.headers.get('Content-Length', 0))
            _body = json.loads(self.rfile.read(content_length).decode('utf-8')) if content_length else {}
            zettel_api.handle_post(
                self, parsed_path.path, _body,
                DATA_DIR=DATA_DIR, PROJECT_ID=PROJECT_ID,
            )

        # ── [모듈 위임 - POST] codegraph_api — /api/codegraph/* ──────────
        elif parsed_path.path.startswith('/api/codegraph/'):
            content_length = int(self.headers.get('Content-Length', 0))
            _body = json.loads(self.rfile.read(content_length).decode('utf-8')) if content_length else {}
            codegraph_api.handle_post(
                self, parsed_path.path, _body,
                DATA_DIR=DATA_DIR, PROJECT_ID=PROJECT_ID,
            )

        # ── [모듈 위임 - POST] memory_api ────────────────────────────────
        # /api/memory/set, /api/memory/delete
        elif parsed_path.path.startswith('/api/memory/'):
            from api import memory_api
            content_length = int(self.headers.get('Content-Length', 0))
            _body = json.loads(self.rfile.read(content_length).decode('utf-8')) if content_length else {}
            memory_api.handle_post(
                self, parsed_path.path, _body,
                DATA_DIR=DATA_DIR, PROJECT_ID=PROJECT_ID,
            )

        elif parsed_path.path == '/api/hive/approve-skill':
            self.send_response(200)
            self.send_header('Content-Type', 'application/json;charset=utf-8')
            self.send_header('Access-Control-Allow-Origin', self._cors_origin())
            self.end_headers()
            try:
                content_length = int(self.headers['Content-Length'])
                data = json.loads(self.rfile.read(content_length).decode('utf-8'))
                skill_name = data.get('skill_name')
                keyword = data.get('keyword', skill_name)
                
                if not skill_name:
                    self.wfile.write(json.dumps({"status": "error", "message": "Skill name is required"}).encode('utf-8'))
                    return

                skill_dir = PROJECT_ROOT / ".gemini" / "skills" / skill_name
                skill_dir.mkdir(parents=True, exist_ok=True)
                
                skill_file = skill_dir / "SKILL.md"
                template = f"""# 🧠 스킬: {skill_name}

이 스킬은 '{keyword}' 관련 작업을 최적화하기 위해 자동으로 제안된 스킬입니다.

## 🏁 사용 시점
- '{keyword}' 키워드가 포함된 작업 요청 시
- 반복적인 {keyword} 관련 파일 수정이 필요할 때

## 🛠️ 핵심 패턴
1. 관련 파일 분석
2. {keyword} 표준 가이드라인 적용
3. 변경 사항 검증

---
**생성일**: {datetime.now().strftime("%Y-%m-%d")}
**상태**: 초안 (Draft)
"""
                with open(skill_file, "w", encoding="utf-8") as f:
                    f.write(template)
                
                self.wfile.write(json.dumps({"status": "success", "path": str(skill_file)}).encode('utf-8'))
            except Exception as e:
                self.wfile.write(json.dumps({"status": "error", "message": str(e)}).encode('utf-8'))
        elif parsed_path.path == '/api/config/update':
            self.send_response(200)
            self.send_header('Content-Type', 'application/json;charset=utf-8')
            self.send_header('Access-Control-Allow-Origin', self._cors_origin())
            self.end_headers()
            try:
                content_length = int(self.headers['Content-Length'])
                data = json.loads(self.rfile.read(content_length).decode('utf-8'))
                config = {}
                if CONFIG_FILE.exists():
                    try:
                        with open(CONFIG_FILE, 'r', encoding='utf-8') as f:
                            config = json.load(f)
                    except: pass
                config.update(data)
                with open(CONFIG_FILE, 'w', encoding='utf-8') as f:
                    json.dump(config, f, ensure_ascii=False, indent=2)

                # last_path 변경 시 projects.json에도 동기화 → 다음 서버 시작 시 PROJECT_ROOT 정확히 설정
                # 배포 버전에서 프로젝트 전환 후 재시작해도 올바른 PROJECT_ROOT를 사용하기 위함
                if 'last_path' in data and data['last_path']:
                    try:
                        _lp = str(data['last_path']).replace('\\', '/')
                        _projs = []
                        if PROJECTS_FILE.exists():
                            _projs = json.loads(PROJECTS_FILE.read_text(encoding='utf-8'))
                        if _lp in _projs:
                            _projs.remove(_lp)
                        _projs.insert(0, _lp)  # 가장 최근 경로를 0번으로
                        PROJECTS_FILE.write_text(
                            json.dumps(_projs[:20], ensure_ascii=False, indent=2),
                            encoding='utf-8'
                        )
                    except Exception:
                        pass

                self.wfile.write(json.dumps({"status": "success"}).encode('utf-8'))
            except Exception as e:
                self.wfile.write(json.dumps({"status": "error", "message": str(e)}).encode('utf-8'))

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

        elif parsed_path.path == '/api/launch':
            try:
                content_length = int(self.headers['Content-Length'])
                post_data = self.rfile.read(content_length)
                data = json.loads(post_data.decode('utf-8'))

                agent = data.get('agent')
                target_dir = data.get('path', 'C:\\')
                is_yolo = data.get('yolo', False)
                # ── 오피스 모드 확장 파라미터: 모델, 역할, 슬롯 ──
                req_model = data.get('model', '')
                req_role = data.get('role', '')
                req_slot = data.get('slot', 0)

                # 경로 검증 — 커맨드 인젝션 방지: 실제 존재하는 디렉터리만 허용
                _resolved_dir = Path(target_dir).resolve()
                if not _resolved_dir.is_dir():
                    raise ValueError(f"Invalid directory: {target_dir}")
                _safe_dir = str(_resolved_dir)
                # 셸 메타 문자 차단 (& | ; ` $ 등)
                import re as _re_launch
                if _re_launch.search(r'[&|;`$<>!]', _safe_dir):
                    raise ValueError(f"Directory path contains invalid characters: {_safe_dir}")

                # 모델/역할 파라미터 안전 문자 검증
                if req_model and not _re_launch.match(r'^[a-zA-Z0-9\-_.]+$', req_model):
                    req_model = ''
                if req_role and not _re_launch.match(r'^[a-zA-Z0-9_]+$', req_role):
                    req_role = ''

                # ── 역할별 초기 프롬프트 매핑 ──
                # Claude/Gemini에 --prompt 또는 초기 입력으로 역할 지시를 전달
                _role_prompts = {
                    'developer': '코드 구현과 기능 개발에 집중해줘. 버그 수정, 리팩토링, 새 기능 추가가 주 업무야.',
                    'reviewer': '코드 리뷰어로 활동해줘. /vibe-code-review 스킬을 활용하여 품질, 성능, 보안을 검토해.',
                    'tester': '테스터로 활동해줘. /vibe-tdd 스킬로 테스트를 작성하고, 회귀 버그를 방지해.',
                    'architect': '설계자로 활동해줘. /vibe-brainstorm 으로 아키텍처를 설계하고, 기술 결정을 문서화해.',
                }
                _role_prompt = _role_prompts.get(req_role, '')

                # 슬롯 번호로 터미널 타이틀 구분
                _slot_label = f"T{req_slot}" if req_slot else ""

                if agent == 'claude':
                    yolo_flag = " --dangerously-skip-permissions" if is_yolo else ""
                    # Claude Code는 --prompt 플래그로 초기 프롬프트 전달 가능
                    prompt_flag = f' -p "{_role_prompt}"' if _role_prompt else ""
                    # 모델 선택: claude --model opus|sonnet|haiku
                    model_flag = f' --model {req_model}' if req_model else ""
                    title = f"[Claude Code] {_slot_label}" if _slot_label else "[Claude Code]"
                    cmd = f'start "Claude Code" cmd.exe /k "cd /d "{_safe_dir}" && title {title} && echo Launching Claude Code... && claude{yolo_flag}{model_flag}{prompt_flag}"'
                elif agent == 'gemini':
                    yolo_flag = " --yolo" if is_yolo else ""
                    gemini_bat = str(PROJECT_ROOT / 'run_gemini.bat')
                    # Gemini CLI: --model 플래그로 모델 선택
                    model_flag = f' --model {req_model}' if req_model else ""
                    title = f"[Gemini CLI] {_slot_label}" if _slot_label else "[Gemini CLI]"
                    # 역할 프롬프트는 Gemini의 -p 옵션으로 전달
                    prompt_flag = f' -p "{_role_prompt}"' if _role_prompt else ""
                    cmd = f'start "{title}" cmd.exe /k ""{gemini_bat}"{yolo_flag}{model_flag}{prompt_flag} --cwd "{_safe_dir}""'
                elif agent == 'codex':
                    yolo_flag = " --dangerously-bypass-approvals-and-sandbox" if is_yolo else ""
                    # 요청된 모델 우선, 없으면 config에서 읽기
                    model_name = req_model if req_model else _codex_main_model()
                    if model_name and not _re_launch.match(r'^[a-zA-Z0-9\-_/:.]+$', model_name):
                        model_name = None
                    model_flag = f' --model {model_name}' if model_name else ""
                    title = f"[Codex CLI] {_slot_label}" if _slot_label else "[Codex CLI]"
                    # Codex는 초기 프롬프트를 위치 인자로 전달
                    prompt_arg = f' "{_role_prompt}"' if _role_prompt else ""
                    cmd = f'start "{title}" cmd.exe /k "cd /d "{_safe_dir}" && title {title} && echo Launching Codex CLI... && codex{yolo_flag}{model_flag}{prompt_arg}"'
                else:
                    cmd = f'start "Terminal" cmd.exe /k "cd /d "{_safe_dir}""'

                subprocess.Popen(cmd, shell=True)

                self.send_response(200)
                self.send_header('Content-Type', 'application/json;charset=utf-8')
                self.send_header('Access-Control-Allow-Origin', self._cors_origin())
                self.end_headers()
                self.wfile.write(json.dumps({
                    "status": "launched", "agent": agent,
                    "model": req_model, "role": req_role, "slot": req_slot
                }).encode('utf-8'))
            except Exception as e:
                self.send_response(500)
                self.send_header('Access-Control-Allow-Origin', self._cors_origin())
                self.end_headers()
                self.wfile.write(json.dumps({"error": str(e)}).encode('utf-8'))
        elif parsed_path.path == '/api/send-command':
            self.send_response(200)
            self.send_header('Content-Type', 'application/json;charset=utf-8')
            self.send_header('Access-Control-Allow-Origin', self._cors_origin())
            self.end_headers()
            try:
                content_length = int(self.headers['Content-Length'])
                post_data = self.rfile.read(content_length)
                data = json.loads(post_data.decode('utf-8'))
                
                target_slot = str(data.get('target'))
                command = data.get('command', '')
                
                # Node PTY 서버의 REST API로 명령 전송 (직접 PTY 접근 → HTTP 프록시)
                try:
                    import urllib.request
                    processed_cmd = command.replace('\r\n', '\r').replace('\n', '\r')
                    final_cmd = processed_cmd if processed_cmd.endswith('\r') else processed_cmd + '\r'
                    payload = json.dumps({"command": final_cmd}).encode('utf-8')
                    _req = urllib.request.Request(
                        f"{_NODE_PTY_REST_URL}/api/pty/interrupt/{target_slot}",
                        data=payload,
                        headers={'Content-Type': 'application/json'},
                        method='POST'
                    )
                    # 실제로는 interrupt가 아닌 write가 필요하므로, 직접 WS로 전송하는 방식으로 전환 필요
                    # 임시: interrupt 엔드포인트 대신 WS 클라이언트로 명령 전송은 향후 구현
                    # 현재는 Node PTY 서버 세션 존재 여부만 확인
                    _snap = _get_node_pty_sessions()
                    _info = _snap.get(f'T{target_slot}')
                    if _info and _info.get('running'):
                        self.wfile.write(json.dumps({"status": "success", "message": f"Command queued for Terminal {target_slot}"}).encode('utf-8'))
                    else:
                        self.wfile.write(json.dumps({"status": "error", "message": f"Terminal {target_slot} is not running."}).encode('utf-8'))
                except Exception as _e:
                    self.wfile.write(json.dumps({"status": "error", "message": str(_e)}).encode('utf-8'))
            except Exception as e:
                self.wfile.write(json.dumps({"status": "error", "message": str(e)}).encode('utf-8'))
        elif parsed_path.path == '/api/locks':
            self.send_response(200)
            self.send_header('Content-Type', 'application/json;charset=utf-8')
            self.send_header('Access-Control-Allow-Origin', self._cors_origin())
            self.end_headers()
            try:
                content_length = int(self.headers['Content-Length'])
                post_data = self.rfile.read(content_length)
                data = json.loads(post_data.decode('utf-8'))
                
                file_path = data.get('file')
                agent = data.get('agent', 'Unknown')
                action = data.get('action', 'lock') # 'lock' or 'unlock'
                
                with open(LOCKS_FILE, 'r', encoding='utf-8') as f:
                    locks = json.load(f)
                
                if action == 'lock':
                    if file_path in locks and locks[file_path] != agent:
                        self.wfile.write(json.dumps({"status": "conflict", "owner": locks[file_path]}).encode('utf-8'))
                        return
                    locks[file_path] = agent
                    log_msg = f"Locked file: {file_path}"
                elif action == 'unlock':
                    if file_path in locks:
                        del locks[file_path]
                        log_msg = f"Unlocked file: {file_path}"
                    else:
                        log_msg = None
                
                with open(LOCKS_FILE, 'w', encoding='utf-8') as f:
                    json.dump(locks, f, ensure_ascii=False, indent=2)
                
                # 하이브 로그에 기록
                if log_msg:
                    try:
                        sys.path.append(str(BASE_DIR))
                        from src.secure import mask_sensitive_data
                        from src.db_helper import insert_log
                        safe_msg = mask_sensitive_data(log_msg)
                        
                        insert_log(
                            session_id=f"lock_{int(time.time())}_{agent}",
                            terminal_id="LOCK_API",
                            agent=agent,
                            trigger_msg=safe_msg,
                            project_id="hive",
                            status="success"
                        )
                    except Exception as e:
                        print(f"Error logging lock to session_logs: {e}")
                
                self.wfile.write(json.dumps({"status": "success", "locks": locks}).encode('utf-8'))
            except Exception as e:
                self.wfile.write(json.dumps({"status": "error", "message": str(e)}).encode('utf-8'))
        elif parsed_path.path == '/api/message':
            # 에이전트 간 메시지 전송 (SQLite 기반)
            self.send_response(200)
            self.send_header('Content-Type', 'application/json;charset=utf-8')
            self.send_header('Access-Control-Allow-Origin', self._cors_origin())
            self.end_headers()
            try:
                content_length = int(self.headers['Content-Length'])
                post_data = self.rfile.read(content_length)
                data = json.loads(post_data.decode('utf-8'))

                # 메시지 객체 생성 (ID: 밀리초 타임스탬프)
                msg = {
                    'id': str(int(time.time() * 1000)),
                    'timestamp': time.strftime("%Y-%m-%dT%H:%M:%S"),
                    'from': str(data.get('from', 'unknown')),
                    'to': str(data.get('to', 'all')),
                    'type': str(data.get('type', 'info')),
                    'content': str(data.get('content', '')),
                    'read': False,
                }

                # SQLite 에 삽입
                send_message(msg['id'], msg['from'], msg['to'], msg['type'], msg['content'])

                # 활성화된 모든 PTY 세션에 메시지 전송 (터미널 화면에 출력)
                # 터미널은 \r\n (CRLF)을 필요로 하므로 변환하여 전송합니다.
                content_to_send = msg['content']
                content_display = content_to_send.replace('\n', '\r\n')
                terminal_msg = f"\r\n\x1b[38;5;39m[{msg['from']} \u2192 {msg['to']}] {content_display}\x1b[0m\r\n"
                
                # [개선] 메시지가 '>'로 시작하면 명령어로 간주하여 즉시 실행 유도
                is_manual_cmd = content_to_send.startswith('>')
                if is_manual_cmd:
                    cmd_to_exec = content_to_send[1:].strip() + '\r\n'
                else:
                    cmd_to_exec = None

                # PTY inject: to 대상 터미널에 메시지 전달
                # CEO(사람)는 PTY 없으므로 스킵, 나머지 에이전트는 PTY write
                # office_chat도 에이전트에게 전달 (양방향 통신)
                _to = msg['to'].lower()
                if _to not in ('ceo', 'all', 'broadcast', ''):
                    try:
                        import urllib.request as _ureq
                        # /api/pty/sessions 는 {"T1": {"agent":"claude","running":true,...}, ...} 형식 반환
                        _sessions_url = f'http://127.0.0.1:{WS_PORT}/api/pty/sessions'
                        with _ureq.urlopen(_sessions_url, timeout=2) as _r:
                            _sessions = json.loads(_r.read().decode())
                        # to와 매칭되는 세션 찾기 (agent 필드 기준)
                        for _slot_id, _sess in (_sessions.items() if isinstance(_sessions, dict) else []):
                            _agent = str(_sess.get('agent', '')).lower()
                            _slot_name = str(_sess.get('slot_name', '')).lower()
                            if not _sess.get('running', False):
                                continue
                            if _to in _agent or _agent.startswith(_to) or _to in _slot_name:
                                _write_url = f'http://127.0.0.1:{WS_PORT}/api/pty/write/{_slot_id}'
                                _payload = json.dumps({'text': content_to_send}).encode()
                                _req = _ureq.Request(
                                    _write_url, data=_payload,
                                    headers={'Content-Type': 'application/json'},
                                    method='POST',
                                )
                                _ureq.urlopen(_req, timeout=2)
                                print(f'[msg→PTY] {msg["from"]} → {_slot_id}({_agent}) : {content_to_send[:40]}')
                                break
                    except Exception as _e:
                        print(f'[msg inject error] to={_to} err={_e}')

                # SSE 스트림 (session_logs 테이블) 에도 알림 기록하여 로그 뷰에 반영
                try:
                    sys.path.append(str(BASE_DIR))
                    from src.secure import mask_sensitive_data
                    from src.db_helper import insert_log
                    safe_content = mask_sensitive_data(msg['content'])
                    
                    insert_log(
                        session_id=f"msg_{int(time.time())}",
                        terminal_id="MSG_CHANNEL",
                        agent=msg['from'],
                        trigger_msg=f"[메시지→{msg['to']}] {safe_content[:100]}",
                        project_id="hive",
                        status="success"
                    )
                except Exception as e:
                    print(f"Error logging message to session_logs: {e}")

                self.wfile.write(json.dumps({'status': 'success', 'msg': msg}, ensure_ascii=False).encode('utf-8'))
            except Exception as e:
                self.wfile.write(json.dumps({'status': 'error', 'message': str(e)}).encode('utf-8'))
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

        elif parsed_path.path == '/api/memory/sync':
            # APPDATA DB → 현재 프로젝트 로컬 DB 동기화
            # 배포 버전에서 APPDATA DB에 있는 항목을 로컬 DB로 가져옴 (updated_at 기준 최신 우선)
            self.send_response(200)
            self.send_header('Content-Type', 'application/json;charset=utf-8')
            self.send_header('Access-Control-Allow-Origin', self._cors_origin())
            self.end_headers()
            try:
                src_data_dir = DATA_DIR
                tgt_data_dir = _legacy_memory_data_dir()
                merged = 0
                skipped = 0
                if src_data_dir != tgt_data_dir:
                    merged, skipped = merge_memory_files(src_data_dir, tgt_data_dir)
                    msg = f'동기화 완료: {merged}개 병합, {skipped}개 최신 유지'
                else:
                    msg = '로컬 저장소와 활성 프로젝트 저장소가 동일하여 동기화 불필요'
                self.wfile.write(json.dumps(
                    {'status': 'ok', 'message': msg, 'merged': merged, 'skipped': skipped},
                    ensure_ascii=False
                ).encode('utf-8'))
            except Exception as e:
                self.wfile.write(json.dumps(
                    {'status': 'error', 'message': str(e)}
                ).encode('utf-8'))

        elif parsed_path.path == '/api/screenshot/analyze':
            # 멀티모달 버그 감지 — 스크린샷을 Gemini Vision API로 분석
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

        elif parsed_path.path == '/api/memory/set':
            # 공유 메모리 항목 저장/갱신 — key 기준 UPSERT (file store)
            self.send_response(200)
            self.send_header('Content-Type', 'application/json;charset=utf-8')
            self.send_header('Access-Control-Allow-Origin', self._cors_origin())
            self.end_headers()
            try:
                content_length = int(self.headers['Content-Length'])
                post_data = self.rfile.read(content_length)
                data = json.loads(post_data.decode('utf-8'))

                key     = str(data.get('key', '')).strip()[:200]
                content = str(data.get('content', '')).strip()
                if not key or not content:
                    self.wfile.write(json.dumps({'status': 'error', 'message': 'key와 content는 필수입니다'}).encode('utf-8'))
                    return

                now     = time.strftime('%Y-%m-%dT%H:%M:%S')
                title   = str(data.get('title', key)).strip()[:300]
                project_id = str(data.get('project_id', PROJECT_ID)).strip() or PROJECT_ID
                legacy_dir = _legacy_memory_data_dir()
                existing = get_memory_entry(legacy_dir, key)
                # 레거시 파일(shared_memory.json) 포맷은 'project' key로 고정돼 있어 그대로 저장
                entry = upsert_memory_entry(legacy_dir, {
                    'key': key,
                    'title': title,
                    'content': content,
                    'tags': data.get('tags', []),
                    'author': str(data.get('author', 'unknown')),
                    'project': project_id,
                    'created_at': existing.get('created_at', now) if existing else now,
                    'updated_at': now,
                })
                self.wfile.write(json.dumps({'status': 'success', 'entry': entry}, ensure_ascii=False).encode('utf-8'))
            except Exception as e:
                self.wfile.write(json.dumps({'status': 'error', 'message': str(e)}).encode('utf-8'))
        elif parsed_path.path == '/api/memory/delete':
            # 공유 메모리 항목 삭제 (key 기준)
            self.send_response(200)
            self.send_header('Content-Type', 'application/json;charset=utf-8')
            self.send_header('Access-Control-Allow-Origin', self._cors_origin())
            self.end_headers()
            try:
                content_length = int(self.headers['Content-Length'])
                post_data = self.rfile.read(content_length)
                data = json.loads(post_data.decode('utf-8'))
                key = str(data.get('key', '')).strip()
                delete_memory_entry(_legacy_memory_data_dir(), key)
                self.wfile.write(json.dumps({'status': 'success'}, ensure_ascii=False).encode('utf-8'))
            except Exception as e:
                self.wfile.write(json.dumps({'status': 'error', 'message': str(e)}).encode('utf-8'))
        elif parsed_path.path == '/api/superpowers/install':
            # Vibe Coding 자체 스킬 설치 — 외부 GitHub 의존 없이 내장 파일 복사
            # Claude: skills/claude/vibe-*.md → PROJECT_ROOT/.claude/commands/ (프로젝트별)
            # Gemini: BASE_DIR 내장 → PROJECT_ROOT/.gemini/skills/ (프로젝트별)
            self.send_response(200)
            self.send_header('Content-Type', 'application/json;charset=utf-8')
            self.send_header('Access-Control-Allow-Origin', self._cors_origin())
            self.end_headers()
            try:
                content_length = int(self.headers['Content-Length'])
                body = json.loads(self.rfile.read(content_length).decode('utf-8'))
                tool = str(body.get('tool', 'claude'))
                home = Path.home()

                # 현재 활성 프로젝트 경로 동적 조회 (배포 버전 호환)
                _proj = _current_project_root()

                if tool == 'claude':
                    # 내장 스킬 소스 경로: exe 기준 BASE_DIR/../skills/claude/ 또는 개발 환경
                    import shutil as _shutil
                    skills_src = BASE_DIR / 'skills' / 'claude'
                    if not skills_src.exists():
                        skills_src = _proj / 'skills' / 'claude'
                    if not skills_src.exists():
                        raise Exception('내장 스킬 파일을 찾을 수 없습니다 (skills/claude/)')
                    cmd_dir = _proj / '.claude' / 'commands'
                    cmd_dir.mkdir(parents=True, exist_ok=True)
                    installed = []
                    for md in skills_src.glob('vibe-*.md'):
                        _shutil.copy(md, cmd_dir / md.name)
                        installed.append(md.name)
                    if not installed:
                        raise Exception('설치할 스킬 파일이 없습니다')
                    self.wfile.write(json.dumps({
                        'status': 'success',
                        'message': f'Claude 스킬 설치 완료 ({len(installed)}개): {", ".join(installed)}'
                    }, ensure_ascii=False).encode('utf-8'))

                elif tool == 'gemini':
                    # .gemini/skills 를 프로젝트에 복사
                    import shutil as _shutil
                    gemini_skills_src = BASE_DIR / '.gemini' / 'skills'
                    if not gemini_skills_src.exists():
                        gemini_skills_src = _proj / '.gemini' / 'skills'
                    if not gemini_skills_src.exists():
                        raise Exception('설치 버전에서는 Gemini 스킬이 포함되지 않습니다. 소스 개발 환경에서 사용하세요.')
                    target_dir = _proj / '.gemini' / 'skills'
                    # 소스와 대상이 다를 때만 복사 (설치 버전에서 실제 파일 배포)
                    if gemini_skills_src.resolve() != target_dir.resolve():
                        _shutil.copytree(str(gemini_skills_src), str(target_dir), dirs_exist_ok=True)
                    installed = [d.name for d in target_dir.iterdir() if d.is_dir() and (d / 'SKILL.md').exists()]
                    self.wfile.write(json.dumps({
                        'status': 'success',
                        'message': f'Gemini 스킬 설치 완료 ({len(installed)}개): {", ".join(installed)}'
                    }, ensure_ascii=False).encode('utf-8'))
                else:
                    self.wfile.write(json.dumps({'status': 'error', 'message': '알 수 없는 tool'}, ensure_ascii=False).encode('utf-8'))
            except Exception as e:
                self.wfile.write(json.dumps({'status': 'error', 'message': str(e)}, ensure_ascii=False).encode('utf-8'))

        elif parsed_path.path == '/api/superpowers/uninstall':
            # Superpowers 제거 — tool: 'claude' | 'gemini'
            self.send_response(200)
            self.send_header('Content-Type', 'application/json;charset=utf-8')
            self.send_header('Access-Control-Allow-Origin', self._cors_origin())
            self.end_headers()
            try:
                content_length = int(self.headers['Content-Length'])
                body = json.loads(self.rfile.read(content_length).decode('utf-8'))
                tool = str(body.get('tool', 'claude'))
                home = Path.home()
                _proj = _current_project_root()  # 현재 활성 프로젝트 경로
                if tool == 'claude':
                    # 프로젝트별 설치 경로에서 제거 (배포 버전 호환)
                    cmd_dir = _proj / '.claude' / 'commands'
                    removed = []
                    for md in cmd_dir.glob('vibe-*.md'):
                        md.unlink()
                        removed.append(md.name)
                    msg = f"제거 완료: {', '.join(removed)}" if removed else '삭제할 파일 없음'
                    self.wfile.write(json.dumps({'status': 'success', 'message': msg}, ensure_ascii=False).encode('utf-8'))

                elif tool == 'gemini':
                    # Gemini 스킬은 프로젝트 내에 있어 실제 삭제하지 않고 상태만 반환
                    self.wfile.write(json.dumps({'status': 'success', 'message': 'Gemini 스킬은 프로젝트 내장형입니다 (삭제 불필요)'}, ensure_ascii=False).encode('utf-8'))
                else:
                    self.wfile.write(json.dumps({'status': 'error', 'message': '알 수 없는 tool'}, ensure_ascii=False).encode('utf-8'))
            except Exception as e:
                self.wfile.write(json.dumps({'status': 'error', 'message': str(e)}, ensure_ascii=False).encode('utf-8'))

        elif parsed_path.path == '/api/orchestrator/skill-chain/update':
            # 스킬 체인 단계 상태 갱신 — skill_chain.db에 직접 UPDATE
            # body: {"step": 0, "status": "done", "summary": "...", "terminal_id": 1}
            self.send_response(200)
            self.send_header('Content-Type', 'application/json;charset=utf-8')
            self.send_header('Access-Control-Allow-Origin', self._cors_origin())
            self.end_headers()
            try:
                content_length = int(self.headers.get('Content-Length', 0))
                body = json.loads(self.rfile.read(content_length).decode('utf-8'))
                step = int(body.get('step', 0))
                status = body.get('status', 'done')
                summary = body.get('summary', '')
                terminal_id = int(body.get('terminal_id', 0))
                if not SCRIPTS_DIR:
                    raise Exception('설치 버전에서는 오케스트레이터 기능을 사용할 수 없습니다')
                _orch_dir = str(SCRIPTS_DIR)
                if _orch_dir not in sys.path:
                    sys.path.insert(0, _orch_dir)
                from skill_orchestrator import cmd_update as _orch_update
                _orch_update(terminal_id, step, status, summary)
                self.wfile.write(json.dumps({'status': 'success'}, ensure_ascii=False).encode('utf-8'))
            except Exception as e:
                self.wfile.write(json.dumps({'status': 'error', 'message': str(e)}).encode('utf-8'))

        elif parsed_path.path == '/api/orchestrator/run':
            # 오케스트레이터 수동 트리거 — 즉시 한 사이클 조율 수행
            self.send_response(200)
            self.send_header('Content-Type', 'application/json;charset=utf-8')
            self.send_header('Access-Control-Allow-Origin', self._cors_origin())
            self.end_headers()
            try:
                if not SCRIPTS_DIR:
                    raise Exception('설치 버전에서는 오케스트레이터 기능을 사용할 수 없습니다')
                # scripts/orchestrator.py를 subprocess로 실행
                orch_script = str(SCRIPTS_DIR / 'orchestrator.py')
                result = subprocess.run(
                    [sys.executable, orch_script],
                    capture_output=True, text=True, timeout=15, encoding='utf-8',
                    creationflags=0x08000000
                )
                output = (result.stdout + result.stderr).strip()
                self.wfile.write(json.dumps({
                    'status': 'success',
                    'output': output or '이상 없음',
                }, ensure_ascii=False).encode('utf-8'))
            except Exception as e:
                self.wfile.write(json.dumps({'status': 'error', 'message': str(e)}).encode('utf-8'))
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
    _proj_hash    = int(_hl.md5(str(PROJECT_ROOT).encode()).hexdigest()[:4], 16)
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

    def run_watchdog():
        if not SCRIPTS_DIR:
            return
        watchdog_script = SCRIPTS_DIR / "hive_watchdog.py"
        if watchdog_script.exists():
            _python_cmds = _python_runner_cmds()
            if not _python_cmds:
                print("[!] run_watchdog: Python 인터프리터를 찾을 수 없어 워치독 스킵")
                return
            python_exe = _python_cmds[0]
            proc = subprocess.Popen(
                [python_exe, str(watchdog_script), "--data-dir", str(DATA_DIR)],
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
                encoding='utf-8',
                errors='replace',
                creationflags=getattr(subprocess, 'CREATE_NO_WINDOW', 0x08000000)
            )
            _child_procs.append(proc)

    _tg_bridge_launched = [False]
    def run_telegram_bridge():
        if _tg_bridge_launched[0]:
            return
        _tg_bridge_launched[0] = True
        if not SCRIPTS_DIR:
            return
        tg_script = SCRIPTS_DIR / "telegram_bridge.py"
        env_file = PROJECT_ROOT / ".env"
        tg_log = DATA_DIR / "telegram_bridge.log"
        if not tg_script.exists():
            return
        tg_pid_file = DATA_DIR / "telegram_bridge.pid"
        if tg_pid_file.exists():
            try:
                old_pid = int(tg_pid_file.read_text().strip())
                check = subprocess.run(
                    ['tasklist', '/FI', f'PID eq {old_pid}', '/NH'],
                    capture_output=True, text=True, timeout=5,
                    creationflags=0x08000000,
                )
                if str(old_pid) in check.stdout and 'python' in check.stdout.lower():
                    print(f"[*] Telegram Bridge 이미 실행 중 (PID={old_pid}) — 스킵")
                    return
                else:
                    tg_pid_file.unlink(missing_ok=True)
            except Exception:
                tg_pid_file.unlink(missing_ok=True)
        try:
            env_content = env_file.read_text(encoding='utf-8') if env_file.exists() else ""
            has_token = False
            for line in env_content.splitlines():
                stripped = line.strip()
                if stripped.startswith("TELEGRAM_BOT_T") and "=" in stripped:
                    token_val = stripped.split("=", 1)[1].strip()
                    if token_val:
                        has_token = True
                        break
                elif stripped.startswith("TELEGRAM_BOT_TOKEN="):
                    token_val = stripped.split("=", 1)[1].strip()
                    if token_val:
                        has_token = True
                        break
            if not has_token:
                return
        except Exception:
            return
        _python_cmds = _python_runner_cmds()
        if not _python_cmds:
            print("[!] run_telegram_bridge: Python 인터프리터를 찾을 수 없어 Telegram 브릿지 스킵")
            return
        python_exe = _python_cmds[0]
        child_env = os.environ.copy()
        child_env['VIBE_SERVER_PORT'] = str(HTTP_PORT)
        tg_log.parent.mkdir(parents=True, exist_ok=True)
        log_handle = open(tg_log, 'a', encoding='utf-8')
        proc = subprocess.Popen(
            [python_exe, str(tg_script)],
            cwd=str(PROJECT_ROOT),
            stdout=log_handle,
            stderr=log_handle,
            env=child_env,
            encoding='utf-8',
            errors='replace',
            creationflags=getattr(subprocess, 'CREATE_NO_WINDOW', 0x08000000),
        )
        proc._vibe_log_handle = log_handle
        _child_procs.append(proc)
        try:
            tg_pid_file.write_text(str(proc.pid))
        except Exception:
            pass
        print(f"[*] Telegram Bridge 자동 시작됨 (PID={proc.pid})")

    def run_heal_daemon():
        if not SCRIPTS_DIR:
            return
        heal_script = SCRIPTS_DIR / "heal_daemon.py"
        if heal_script.exists():
            _python_cmds = _python_runner_cmds()
            if not _python_cmds:
                print("[!] run_heal_daemon: Python 인터프리터를 찾을 수 없어 힐데몬 스킵")
                return
            python_exe = _python_cmds[0]
            proc = subprocess.Popen(
                [python_exe, str(heal_script), "--interval", "300"],
                cwd=str(PROJECT_ROOT),
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                encoding='utf-8',
                errors='replace',
                creationflags=getattr(subprocess, 'CREATE_NO_WINDOW', 0x08000000),
            )
            _child_procs.append(proc)
            print("[*] 자기치유 데몬(heal_daemon) 자동 시작됨")

    def run_orchestrator_daemon():
        # 하이브 오케스트레이터 데몬 — assigned_to='all' 태스크를
        # 살아있는 에이전트로 자동 재배정. wiki_generator 등 'all' 발행자가
        # 만든 태스크가 영원히 적체되는 것을 방지한다.
        if not SCRIPTS_DIR:
            return
        orch_script = SCRIPTS_DIR / "orchestrator.py"
        if orch_script.exists():
            _python_cmds = _python_runner_cmds()
            if not _python_cmds:
                print("[!] run_orchestrator_daemon: Python 인터프리터를 찾을 수 없어 오케스트레이터 스킵")
                return
            python_exe = _python_cmds[0]
            proc = subprocess.Popen(
                [python_exe, str(orch_script), "--daemon", "--interval", "60"],
                cwd=str(PROJECT_ROOT),
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                encoding='utf-8',
                errors='replace',
                creationflags=getattr(subprocess, 'CREATE_NO_WINDOW', 0x08000000),
            )
            _child_procs.append(proc)
            print("[*] 하이브 오케스트레이터 데몬(orchestrator) 자동 시작됨")

    def run_doc_generators_daemon():
        # PROJECT_MAP.md / HIVEMIND.md 자동 갱신 데몬.
        # 시동 시 즉시 1회 + 이후 30분마다 갱신.
        # 원인: 두 자동 생성기가 시동 시퀀스에서 빠져있어 17일/15일째 stale.
        if not SCRIPTS_DIR:
            return
        pm_script = SCRIPTS_DIR / "generate_project_map.py"
        hv_script = SCRIPTS_DIR / "generate_hivemind_doc.py"
        _python_cmds = _python_runner_cmds()
        if not _python_cmds:
            print("[!] run_doc_generators_daemon: Python 인터프리터를 찾을 수 없어 스킵")
            return
        python_exe = _python_cmds[0]
        interval_sec = 30 * 60  # 30분 주기

        while True:
            # PROJECT_MAP.md 갱신
            if pm_script.exists():
                try:
                    subprocess.run(
                        [python_exe, str(pm_script)],
                        cwd=str(PROJECT_ROOT),
                        timeout=120,
                        capture_output=True,
                        creationflags=getattr(subprocess, 'CREATE_NO_WINDOW', 0x08000000),
                    )
                    print("[*] PROJECT_MAP.md 자동 갱신 완료")
                except Exception as e:
                    print(f"[!] PROJECT_MAP.md 갱신 실패: {e}")

            # HIVEMIND.md 갱신
            if hv_script.exists():
                try:
                    subprocess.run(
                        [python_exe, str(hv_script)],
                        cwd=str(PROJECT_ROOT),
                        timeout=120,
                        capture_output=True,
                        creationflags=getattr(subprocess, 'CREATE_NO_WINDOW', 0x08000000),
                    )
                    print("[*] HIVEMIND.md 자동 갱신 완료")
                except Exception as e:
                    print(f"[!] HIVEMIND.md 갱신 실패: {e}")

            time.sleep(interval_sec)

    def _agent_sync_daemon():
        while True:
            try:
                time.sleep(60)
                now_ts = time.time()
                with AGENT_STATUS_LOCK:
                    snapshot = dict(AGENT_STATUS)
                for agent_name, info in snapshot.items():
                    status = info.get('status', 'idle')
                    if status in ('active', 'running', 'working'):
                        try:
                            record_heartbeat(agent_name, status=status,
                                             current_task=info.get('task'))
                        except Exception:
                            pass
                try:
                    db_rows = list_agent_status()
                    with AGENT_STATUS_LOCK:
                        for row in db_rows:
                            aid = row.get('agent_id', '')
                            if not aid:
                                continue
                            if aid not in AGENT_STATUS:
                                try:
                                    from datetime import datetime as _dt
                                    lb = _dt.fromisoformat(row.get('last_beat', '')).timestamp()
                                except Exception:
                                    lb = now_ts - 600
                                age = now_ts - lb
                                AGENT_STATUS[aid] = {
                                    'status': 'offline' if age > 300 else row.get('status', 'idle'),
                                    'task': row.get('current_task'),
                                    'last_seen': lb,
                                    'beat_count': row.get('beat_count', 0),
                                }
                        for aid, info in AGENT_STATUS.items():
                            last = info.get('last_seen', 0)
                            if now_ts - last > 300 and info.get('status') not in ('offline',):
                                AGENT_STATUS[aid]['status'] = 'offline'
                except Exception:
                    pass
            except Exception:
                pass

    def run_mux_server():
        if not SCRIPTS_DIR:
            return
        mux_script = SCRIPTS_DIR / "vibe_mux.py"
        if mux_script.exists():
            _python_cmds = _python_runner_cmds()
            if not _python_cmds:
                print("[!] run_mux_server: Python 인터프리터를 찾을 수 없어 MUX 서버 스킵")
                return
            python_exe = _python_cmds[0]
            proc = subprocess.Popen(
                [python_exe, str(mux_script), "server"],
                cwd=str(PROJECT_ROOT),
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                creationflags=getattr(subprocess, 'CREATE_NO_WINDOW', 0x08000000),
            )
            _child_procs.append(proc)
            print("[*] MUX 서버(vibe_mux) 자동 시작됨 — Named Pipe: \\\\.\\pipe\\vibe-mux")

    # ── 제텔카스텐 Vault 동기화 데몬 (DB ↔ Obsidian 60초 주기) ────────────
    def run_zettel_sync():
        """PostgreSQL zettel_notes ↔ Obsidian vault 양방향 동기화 데몬.
        [v3.7.179] 서버 시작 시 자동 실행 — 이전에는 수동 실행만 가능했음."""
        try:
            _sync_dir = SCRIPTS_DIR or (BASE_DIR / 'scripts')
            _sync_script = _sync_dir / 'zettel_sync.py'
            if not _sync_script.exists():
                return
            # zettel_sync 모듈 직접 import하여 스레드 내에서 실행 (subprocess 대신)
            import importlib.util as _ilu
            _spec = _ilu.spec_from_file_location('zettel_sync', str(_sync_script))
            _mod = _ilu.module_from_spec(_spec)
            _spec.loader.exec_module(_mod)

            # config.json에서 사용자 지정 vault 경로 읽기 (없으면 전역 기본값)
            _vault = GLOBAL_VAULT_DIR
            try:
                if CONFIG_FILE.exists():
                    _cfg = json.loads(CONFIG_FILE.read_text(encoding='utf-8'))
                    _user_vault = _cfg.get('vault_dir', '')
                    if _user_vault:
                        _vault = Path(_user_vault)
            except Exception:
                pass
            _vault.mkdir(parents=True, exist_ok=True)

            # 기존 .zettel-vault 마이그레이션 (최초 1회)
            import shutil as _shutil
            _old_vault = _current_project_root() / '.zettel-vault'
            if _old_vault.exists() and not (_vault / '_migrated').exists():
                try:
                    _shutil.copytree(str(_old_vault), str(_vault), dirs_exist_ok=True)
                    (_vault / '_migrated').touch()
                    print(f'[zettel_sync] 기존 vault 마이그레이션 완료: {_old_vault} -> {_vault}')
                except Exception as _me:
                    print(f'[zettel_sync] 마이그레이션 오류 (무시): {_me}')

            # 현재 활성 프로젝트명
            _proj_name = _current_project_root().name
            print(f'[*] 제텔카스텐 Vault 동기화 데몬 시작됨 — vault={_vault}, project={_proj_name}, 60초 양방향')

            # Google Drive vault — config.json에서 경로 읽기
            def _get_gdrive_vault():
                try:
                    if CONFIG_FILE.exists():
                        _cfg = json.loads(CONFIG_FILE.read_text(encoding='utf-8'))
                        _gd = _cfg.get('gdrive_vault_path', '')
                        if _gd:
                            return Path(_gd)
                except Exception:
                    pass
                return None

            def _sync_with_gdrive():
                while True:
                    try:
                        _gdrive_vault = _get_gdrive_vault()
                        if _gdrive_vault and _gdrive_vault.exists():
                            _mod.export_to_vault(_gdrive_vault, project_id=_proj_name)
                    except Exception as _ge:
                        print(f'[zettel_sync] Google Drive 동기화 오류: {_ge}')
                    time.sleep(120)
            threading.Thread(target=_sync_with_gdrive, daemon=True,
                             name='ZettelGDrive').start()
            _mod.watch_and_sync(_vault, project_id=_proj_name, interval=60, bidirectional=True)
        except Exception as e:
            print(f"[!] 제텔카스텐 동기화 데몬 오류: {e}")

    # ── fleeting 노트 자동 정제 데몬 (10분 주기) ──────────────────────────
    def run_zettel_refine():
        """24시간 이상 된 fleeting 노트를 자동으로 permanent로 승격.
        [v3.7.179] 수동 refine_note() 없이도 지식이 자동 정제됨."""
        try:
            time.sleep(120)  # 서버 안정화 대기 (2분)
            sys.path.insert(0, str(BASE_DIR))
            from src.zettelkasten import list_notes, refine_note, auto_link
            from src.pg_store import ensure_schema
            while True:
                try:
                    ensure_schema()
                    notes = list_notes(note_type='fleeting', limit=100)
                    from datetime import datetime, timezone, timedelta
                    now = datetime.now(timezone.utc)
                    cutoff = now - timedelta(hours=24)
                    promoted = 0
                    for n in notes:
                        # created가 문자열이면 파싱
                        created = n.get('created_at') or n.get('created', '')
                        if isinstance(created, str):
                            try:
                                created = datetime.fromisoformat(created.replace('Z', '+00:00'))
                            except Exception:
                                continue
                        if hasattr(created, 'tzinfo') and created.tzinfo is None:
                            created = created.replace(tzinfo=timezone.utc)
                        if created < cutoff:
                            nid = n.get('id') or n.get('zettel_id', '')
                            if nid:
                                refine_note(nid, new_type='permanent')
                                auto_link(nid, content=n.get('content', ''),
                                         tags=n.get('tags', []), created_by='system')
                                promoted += 1
                    if promoted:
                        print(f"[zettel_refine] {promoted}개 fleeting 노트 → permanent 승격 완료")
                except Exception as e:
                    print(f"[!] 제텔 자동 정제 오류: {e}")
                time.sleep(600)  # 10분 주기
        except Exception as e:
            print(f"[!] 제텔 자동 정제 데몬 시작 실패: {e}")

    # ── git 커밋 감지 → 제텔카스텐 자동 캡처 데몬 (60초 폴링) ──────────────
    def run_commit_watcher():
        """새 git 커밋을 폴링하여 zettel_capture.capture_commit() 자동 호출.
        [v3.7.179] git hook 없이도 커밋 노트가 자동 생성됨."""
        try:
            time.sleep(60)  # 서버 안정화 대기
            _no_window = getattr(subprocess, 'CREATE_NO_WINDOW', 0x08000000)
            # 마지막으로 처리한 커밋 해시
            _last_hash = None
            try:
                r = subprocess.run(
                    ['git', 'rev-parse', 'HEAD'],
                    cwd=str(PROJECT_ROOT), capture_output=True, text=True,
                    timeout=5, creationflags=_no_window,
                )
                if r.returncode == 0:
                    _last_hash = r.stdout.strip()
            except Exception:
                pass

            while True:
                try:
                    time.sleep(60)
                    r = subprocess.run(
                        ['git', 'rev-parse', 'HEAD'],
                        cwd=str(PROJECT_ROOT), capture_output=True, text=True,
                        timeout=5, creationflags=_no_window,
                    )
                    if r.returncode != 0:
                        continue
                    current_hash = r.stdout.strip()
                    if current_hash == _last_hash:
                        continue

                    # 새 커밋 감지 — 커밋 메시지 + 변경 파일 조회
                    r2 = subprocess.run(
                        ['git', 'log', '-1', '--pretty=format:%B', current_hash],
                        cwd=str(PROJECT_ROOT), capture_output=True, text=True,
                        timeout=5, encoding='utf-8', errors='replace',
                        creationflags=_no_window,
                    )
                    commit_msg = r2.stdout.strip() if r2.returncode == 0 else ''

                    r3 = subprocess.run(
                        ['git', 'diff-tree', '--no-commit-id', '--name-only', '-r', current_hash],
                        cwd=str(PROJECT_ROOT), capture_output=True, text=True,
                        timeout=5, encoding='utf-8', errors='replace',
                        creationflags=_no_window,
                    )
                    files = [f for f in r3.stdout.strip().split('\n') if f] if r3.returncode == 0 else []

                    if commit_msg and 'auto-bump version' not in commit_msg:
                        try:
                            _cap_dir = SCRIPTS_DIR or (BASE_DIR.parent / 'scripts')
                            _cap_script = _cap_dir / 'zettel_capture.py'
                            if _cap_script.exists():
                                import importlib.util as _ilu2
                                _spec2 = _ilu2.spec_from_file_location('zettel_capture', str(_cap_script))
                                _mod2 = _ilu2.module_from_spec(_spec2)
                                _spec2.loader.exec_module(_mod2)
                                _mod2.capture_commit(commit_msg, files=files, agent='system')
                        except Exception as e:
                            print(f"[commit_watcher] 캡처 오류: {e}")

                    _last_hash = current_hash
                except Exception as e:
                    print(f"[commit_watcher] 폴링 오류: {e}")
        except Exception as e:
            print(f"[!] 커밋 감시 데몬 시작 실패: {e}")

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
                _pg_mod._SCHEMA_READY = False
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
            threading.Thread(target=run_heal_daemon, daemon=True).start()
            threading.Thread(target=run_orchestrator_daemon, daemon=True,
                             name='OrchestratorDaemon').start()
            threading.Thread(target=run_doc_generators_daemon, daemon=True,
                             name='DocGeneratorsDaemon').start()
            threading.Thread(target=_agent_sync_daemon, daemon=True,
                             name='AgentSyncDaemon').start()
            threading.Thread(target=run_mux_server, daemon=True).start()
            threading.Thread(target=run_zettel_sync, daemon=True,
                             name='ZettelSync').start()
            threading.Thread(target=run_zettel_refine, daemon=True,
                             name='ZettelRefine').start()
            threading.Thread(target=run_commit_watcher, daemon=True,
                             name='CommitWatcher').start()

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
