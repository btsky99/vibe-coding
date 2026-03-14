# ------------------------------------------------------------------------
# 📄 파일명: server.py
# 🗺️ 메인 프로젝트 맵: PROJECT_MAP.md
# 📝 설명: 하이브 마인드(Gemini & Claude)의 중앙 통제 서버.
#          에이전트 간의 통신 중계, 상태 모니터링, 데이터 영속성을 관리합니다.
#
# 🕒 변경 이력 (History):
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
#   - run_watchdog/run_discord_bridge/run_heal_daemon: sys.executable → _python_runner_cmds()[0]
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
#   - _mcp_config_path(): BASE_DIR.parent(임시폴더) → _current_project_root() 교체
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
import api.mcp_api as mcp_api
import api.hive_api as hive_api
import api.git_api as git_api
import api.memory_api as memory_api
import api.agent_api as agent_api
import api.pty_api as pty_api
import api.config_api as config_api
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
)

# ── PostgreSQL 18 연동 헬퍼 (Postgres-First 고도화) ─────────────────────────
# [수정] frozen(배포) 모드에서는 exe 옆의 pgsql\ 폴더를 사용하고,
#        개발 모드에서는 .ai_monitor/bin/pgsql/ 을 사용합니다.
#        installer가 {app}\pgsql\ 에 바이너리를 설치하므로 frozen 시 exe 옆 경로 우선.
if getattr(sys, 'frozen', False):
    # 배포 버전: vibe-coding.exe 옆에 installer가 설치한 pgsql\ 폴더
    _PG_DIR = Path(sys.executable).resolve().parent / "pgsql"
else:
    # 개발 버전: 소스 트리 내 .ai_monitor/bin/pgsql/
    _PG_DIR = Path(__file__).resolve().parent / "bin" / "pgsql"

PG_BIN     = _PG_DIR / "bin" / "psql.exe"
PG_CTL_BIN = _PG_DIR / "bin" / "pg_ctl.exe"
INITDB_BIN = _PG_DIR / "bin" / "initdb.exe"
PG_PORT = 5433

# 배포 버전 DB 데이터 디렉터리: %APPDATA%\VibeCoding\pgdata
# 개발 버전: 소스 트리 내 .ai_monitor/bin/pgsql/data
if getattr(sys, 'frozen', False):
    _PG_DATA_DIR = Path(os.getenv('APPDATA', '')) / "VibeCoding" / "pgdata"
else:
    _PG_DATA_DIR = _PG_DIR / "data"


def ensure_postgres_running():
    """배포(frozen) 모드 전용: PostgreSQL이 실행 중이지 않으면 자동으로 초기화하고 시작합니다.

    1) pgsql 바이너리가 없으면 스킵 (설치 안 된 환경 — 개발 모드 등)
    2) pgdata 디렉터리가 없으면 initdb로 초기화
    3) pg_ctl status로 실행 여부 확인 후, 미실행 시 pg_ctl start
    4) 확장(vector, pg_trgm) 활성화 SQL 실행
    """
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

    # 2) 실행 여부 확인
    try:
        status_res = subprocess.run(
            [str(PG_CTL_BIN), "status", "-D", str(_PG_DATA_DIR)],
            capture_output=True, text=True, encoding='utf-8', errors='replace',
            creationflags=_no_window
        )
        if "server is running" in status_res.stdout:
            print("[PG] 이미 실행 중")
            return
    except Exception:
        pass

    # 3) pg_ctl start
    print(f"[PG] PostgreSQL 시작 중 (port={PG_PORT})...")
    try:
        subprocess.run(
            [str(PG_CTL_BIN), "start", "-D", str(_PG_DATA_DIR),
             "-l", str(pg_log), "-o", f"-p {PG_PORT}"],
            capture_output=True, text=True, encoding='utf-8', errors='replace',
            creationflags=_no_window
        )
        import time as _time
        _time.sleep(2)  # PG 기동 대기
        print("[PG] PostgreSQL 시작 완료")

        # 4) pgvector 확장 설치 시도
        run_pg_sql("CREATE EXTENSION IF NOT EXISTS vector;")
        run_pg_sql("CREATE EXTENSION IF NOT EXISTS pg_trgm;")
        run_pg_sql("CREATE EXTENSION IF NOT EXISTS fuzzystrmatch;")
        run_pg_sql("""
            CREATE TABLE IF NOT EXISTS pg_thoughts (
                id BIGSERIAL PRIMARY KEY,
                agent TEXT NOT NULL,
                terminal_id TEXT DEFAULT '',
                skill TEXT DEFAULT '',
                thought JSONB NOT NULL DEFAULT '{}',
                parent_id BIGINT REFERENCES pg_thoughts(id),
                created_at TIMESTAMPTZ DEFAULT NOW()
            );
        """)
        run_pg_sql("""
            CREATE TABLE IF NOT EXISTS pg_logs (
                id BIGSERIAL PRIMARY KEY,
                agent TEXT NOT NULL,
                terminal_id TEXT DEFAULT '',
                task TEXT NOT NULL,
                status TEXT DEFAULT 'success',
                created_at TIMESTAMPTZ DEFAULT NOW()
            );
        """)
        print("[PG] 스키마 및 확장 초기화 완료")
    except Exception as e:
        print(f"[PG] 시작 오류: {e}")

def run_pg_sql(sql: str, db: str = "postgres"):
    """psql.exe를 사용하여 SQL을 실행하고 결과를 반환합니다 (psycopg2 미설치 대비)"""
    if not PG_BIN.exists():
        return None
    try:
        # 윈도우 cp949 인코딩 문제 방지를 위해 CREATE_NO_WINDOW 사용
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

def log_to_pg(agent: str, terminal_id: str, task: str, status: str = "success"):
    """pg_logs 테이블에 로그 기록"""
    # 따옴표 이스케이프 (단순 SQL 인젝션 방지)
    safe_task = task.replace("'", "''")
    sql = f"INSERT INTO pg_logs (agent, terminal_id, task, status) VALUES ('{agent}', '{terminal_id}', '{safe_task}', '{status}');"
    run_pg_sql(sql)
    # PGMQ에도 동시에 쌓기 (실시간 큐)
    mq_msg = json.dumps({"agent": agent, "tid": terminal_id, "task": task, "status": status}, ensure_ascii=False).replace("'", "''")
    run_pg_sql(f"SELECT pgmq.send('hive_queue', '{mq_msg}');")

def thought_to_pg(agent: str, skill: str, thought: dict, parent_id: int = None) -> int:
    """pg_thoughts 테이블에 사고 과정 기록 (JSONB).

    parent_id를 지정하면 이전 thought와 연결선이 생성되어 지식 그래프에 계보 표시.
    parent_id가 없으면 같은 에이전트의 마지막 thought를 자동으로 부모로 연결
    → hive_bridge.py가 매 호출마다 새 프로세스로 실행되어 인메모리 체인이 깨지는 문제 해결.
    ensure_ascii=True: 한글을 \\uXXXX 이스케이프로 변환하여 psql.exe -c 인수 인코딩 오류 방지.
    JSONB는 유니코드 이스케이프를 정상 처리하므로 조회 시 한글이 정상 표시됩니다.

    Returns:
        int: 삽입된 행의 id (RETURNING id), 실패 시 0
    """
    safe_thought = json.dumps(thought, ensure_ascii=True).replace("'", "''")

    # parent_id 미지정 시 같은 에이전트의 직전 thought를 자동으로 부모로 설정
    # 이 덕분에 hive_bridge.py가 매번 새 프로세스로 호출되어도 연결선이 끊기지 않음
    if not parent_id:
        safe_agent = agent.replace("'", "''")
        prev_result = run_pg_sql(
            f"SELECT id FROM pg_thoughts WHERE agent='{safe_agent}' ORDER BY id DESC LIMIT 1;"
        )
        try:
            for line in (prev_result or '').splitlines():
                line = line.strip()
                if line.isdigit():
                    parent_id = int(line)
                    break
        except Exception:
            pass

    if parent_id:
        sql = (f"INSERT INTO pg_thoughts (agent, skill, thought, parent_id) "
               f"VALUES ('{agent}', '{skill}', '{safe_thought}'::jsonb, {int(parent_id)}) RETURNING id;")
    else:
        sql = (f"INSERT INTO pg_thoughts (agent, skill, thought) "
               f"VALUES ('{agent}', '{skill}', '{safe_thought}'::jsonb) RETURNING id;")
    result = run_pg_sql(sql)
    # RETURNING id 출력 파싱: psql --csv가 아닌 기본 출력 형식 → " id\n----\n 42\n(1 row)" 형태
    try:
        for line in (result or '').splitlines():
            line = line.strip()
            if line.isdigit():
                return int(line)
    except Exception:
        pass
    return 0

def run_pg_sql_csv(sql: str, db: str = "postgres") -> list:
    """CSV 형식으로 Postgres 쿼리 결과를 dict 리스트로 반환 (칸반/대시보드 조회용)"""
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
    except Exception:
        pass

# [수정] pythonw.exe로 실행 시(터미널 없음) 에러 로그를 파일로 기록하도록 개선
if sys.stdout is None or sys.stderr is None:
    try:
        # DATA_DIR 정의 전이므로 임시 경로 사용 후 아래에서 재지정 가능성 검토
        _log_p = Path(__file__).resolve().parent / "server.log"
        _f = open(_log_p, "a", encoding="utf-8")
        sys.stdout = _f
        sys.stderr = _f
        print(f"\n--- Server Started (Log Redirected) at {time.strftime('%Y-%m-%d %H:%M:%S')} ---")
    except Exception:
        pass

# 전역 소켓 타임아웃 제거 (SSE 등 장기 연결 방해 요소)
# socket.setdefaulttimeout(60)  <-- 제거됨

# BASE_DIR: 개발 모드에선 server.py 위치, 배포(frozen) 모드에선 PyInstaller 임시 압축 해제 폴더(sys._MEIPASS)
# 이 상수는 winpty DLL 경로 등 초기화 코드보다 반드시 먼저 정의되어야 함
if getattr(sys, 'frozen', False):
    BASE_DIR = Path(sys._MEIPASS)
    PROJECT_ROOT = Path(sys.executable).resolve().parent
else:
    BASE_DIR = Path(__file__).resolve().parent
    PROJECT_ROOT = BASE_DIR.parent


def _python_runner_cmds() -> list[str]:
    """Python 스크립트를 실행할 인터프리터 후보 목록을 반환합니다."""
    candidates: list[str] = []
    seen: set[str] = set()

    for path in (
        BASE_DIR / 'venv' / 'Scripts' / 'python.exe',
        PROJECT_ROOT / '.ai_monitor' / 'venv' / 'Scripts' / 'python.exe',
        PROJECT_ROOT / 'venv' / 'Scripts' / 'python.exe',
    ):
        path_str = str(path)
        if path.exists() and path_str not in seen:
            candidates.append(path_str)
            seen.add(path_str)

    exe_name = Path(sys.executable).name.lower()
    if exe_name.startswith('python') and sys.executable not in seen:
        candidates.append(sys.executable)
        seen.add(sys.executable)

    for name in ('python', 'py'):
        resolved = shutil.which(name)
        if resolved and resolved not in seen:
            candidates.append(resolved)
            seen.add(resolved)

    return candidates or ['python']

try:
    import websockets
except ImportError:
    websockets = None

# 전역 상태 관리
THOUGHT_LOGS = [] # AI 사고 과정 로그 (최근 50개 유지)
THOUGHT_CLIENTS = set() # SSE 클라이언트 연결 리스트

def _load_task_logs_into_thoughts():
    """서버 시작 시 task_logs.jsonl의 최근 20개 항목을 THOUGHT_LOGS에 미리 로드합니다.
    이렇게 해야 클라이언트 접속 즉시 과거 작업 내역이 사고 패널에 표시됩니다.

    [경로 주의] DATA_DIR는 이 함수가 호출되는 시점(서버 코드 상단)에 아직 정의되지 않으므로,
    frozen(배포) 모드와 개발 모드를 직접 판별하여 올바른 데이터 디렉토리를 사용합니다.
    - frozen 모드: %APPDATA%\\VibeCoding (Windows) / ~/.vibe-coding (기타)
    - 개발 모드 : server.py 위치 기준 ./data/
    """
    _self = Path(__file__).resolve()
    if getattr(sys, 'frozen', False):
        # PyInstaller 배포 버전: __file__ = sys._MEIPASS/server.py → 데이터는 APPDATA에 있음
        if os.name == 'nt':
            _early_data_dir = Path(os.getenv('APPDATA', '')) / "VibeCoding"
        else:
            _early_data_dir = Path.home() / ".vibe-coding"
    else:
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
            except Exception:
                pass
        print(f"[*] ThoughtTrace: {len(recent)}개 task_logs 항목 사전 로드 완료")
    except Exception as e:
        print(f"[!] ThoughtTrace 사전 로드 실패: {e}")

_load_task_logs_into_thoughts()

# --- 신규: 파일 시스템 실시간 감시 (Watchdog) ---
try:
    from watchdog.observers import Observer
    from watchdog.events import FileSystemEventHandler
except ImportError:
    Observer = None
    FileSystemEventHandler = object

FS_CLIENTS = set() # SSE 클라이언트 연결 세트
THOUGHT_CLIENTS = set() # 사고 과정 SSE 클라이언트 연결 세트
# 자율 에이전트 SSE: 클라이언트별 개별 Queue 세트 (브로드캐스트 방식)
# 단일 Queue 방식은 다중 연결 시 이벤트를 한 클라이언트만 소비하는 버그가 있어 교체
AGENT_CLIENTS: set = set()


def _agent_broadcast_worker():
    """cli_agent._output_queue를 읽어 모든 연결된 SSE 클라이언트에게 팬아웃합니다.

    단일 생산자(cli_agent) → 다중 소비자(SSE 클라이언트) 패턴 구현.
    cli_agent가 Queue에 이벤트를 넣으면 이 워커가 즉시 모든 클라이언트 큐에 복사합니다.
    """
    from queue import Empty as _Empty
    _scripts = str(Path(__file__).resolve().parent.parent / 'scripts')
    if _scripts not in sys.path:
        sys.path.insert(0, _scripts)
    try:
        import cli_agent as _ca
    except ImportError:
        return  # cli_agent 미설치 시 종료

    while True:
        try:
            msg = _ca._output_queue.get(timeout=1.0)
            # 연결된 모든 클라이언트 큐에 동일 메시지 복사 전송
            for cq in list(AGENT_CLIENTS):
                try:
                    cq.put_nowait(msg)
                except Exception:
                    pass  # 클라이언트 큐 가득 참 등 무시
        except _Empty:
            pass  # 1초 타임아웃 — 정상, 계속 대기
        except Exception:
            pass  # 기타 오류 무시 후 재시도

class FSChangeHandler(FileSystemEventHandler):
    """파일 시스템 변경 이벤트를 감지하여 SSE 클라이언트들에게 알립니다."""
    def on_any_event(self, event):
        if event.is_directory: return
        # 노이즈가 심한 파일/폴더는 제외 (시스템 레벨 필터링이 안 될 경우 대비)
        path = event.src_path.replace('\\', '/')
        # DATA_DIR 경로도 동적으로 제외 — 설치버전은 AppData에 있어서 하드코딩 필터 불충분
        data_dir_str = str(DATA_DIR).replace('\\', '/')
        if any(x in path for x in ['.git', '.ai_monitor/data', '__pycache__', '.ruff_cache',
                                    '.ico', '.png', '.jpg', '.tmp', 'node_modules', 'dist', 'build',
                                    '.db-wal', '.db-shm']):  # SQLite WAL/SHM 파일 제외
            return
        if data_dir_str and path.startswith(data_dir_str):
            return  # DATA_DIR 하위 파일 전체 제외 (DB, 로그 등 런타임 데이터)
        
        # 브로드캐스트 메시지 생성
        msg_obj = {'type': 'fs_change', 'path': path, 'event': event.event_type}
        msg = f"data: {json.dumps(msg_obj, ensure_ascii=False)}\n\n"
        
        # 연결된 모든 클라이언트에게 전송 (비정상 연결 조기 제거)
        disconnected = []
        for client in list(FS_CLIENTS):
            try:
                # 소켓 타임아웃 설정 (1초 내에 전송 못하면 실패 처리)
                client.connection.settimeout(1.0)
                client.wfile.write(msg.encode('utf-8'))
                client.wfile.flush()
            except Exception:
                disconnected.append(client)
        
        for d in disconnected:
            FS_CLIENTS.discard(d)

def start_fs_watcher(root_path):
    if Observer is None:
        print("[!] watchdog 라이브러리가 없어 실시간 파일 감시를 시작할 수 없습니다.")
        return None
    handler = FSChangeHandler()
    observer = Observer()
    observer.schedule(handler, str(root_path), recursive=True)
    observer.start()
    print(f"[*] File System Watcher started on {root_path}")
    return observer
# ----------------------------------------------

# 윈도우 배포 버전에서 winpty DLL 로딩 문제 해결
if getattr(sys, 'frozen', False) and os.name == 'nt':
    winpty_dll_path = BASE_DIR / 'winpty'
    if winpty_dll_path.exists():
        try:
            os.add_dll_directory(str(winpty_dll_path))
            print(f"[*] Added DLL directory: {winpty_dll_path}")
        except AttributeError:
            # Python < 3.8
            os.environ['PATH'] = str(winpty_dll_path) + os.pathsep + os.environ['PATH']

if os.name == 'nt':
    try:
        from winpty import PtyProcess
    except ImportError as e:
        print(f"[!] winpty load failed: {e}")
        PtyProcess = None
else:
    PtyProcess = None

from datetime import datetime
from pathlib import Path
from http.server import BaseHTTPRequestHandler, HTTPServer
from socketserver import ThreadingMixIn
from urllib.parse import urlparse, parse_qs, urlencode
import urllib.request
from _version import __version__

# 데이터 디렉토리 설정 (BASE_DIR 설정 이후로 이동)
if getattr(sys, 'frozen', False):
    # [수정] 현재 프로젝트 폴더 내의 .ai_monitor/data 가 있으면 이를 우선적으로 사용 (CLI와 데이터 공유 강제)
    _local_data = PROJECT_ROOT / ".ai_monitor" / "data"
    if _local_data.exists():
        DATA_DIR = _local_data
        print(f"[*] Local project data found: {DATA_DIR}")
    elif os.name == 'nt':
        DATA_DIR = Path(os.getenv('APPDATA')) / "VibeCoding"
    else:
        DATA_DIR = Path.home() / ".vibe-coding"
else:
    DATA_DIR = BASE_DIR / "data"

if not DATA_DIR.exists():
    try:
        os.makedirs(DATA_DIR, exist_ok=True)
    except Exception as e:
        # 마지막 보루: 현재 실행 위치 옆 (하지만 권한 에러 가능성 있음)
        DATA_DIR = Path(sys.executable).resolve().parent / "data"
        os.makedirs(DATA_DIR, exist_ok=True)

# 현재 서버가 서비스하는 프로젝트 루트 + 식별자
def _find_project_root(start: Path) -> Path:
    """배포 모드에서 실제 프로젝트 루트를 탐색합니다.

    실행 파일 위치에서 위로 올라가며 .git / CLAUDE.md / GEMINI.md 중
    하나라도 존재하는 디렉터리를 프로젝트 루트로 판단합니다.
    exe 가 dist/ 또는 .ai_monitor/dist/ 서브폴더에 있어도 올바른 루트를 반환합니다.
    """
    markers = ['.git', 'CLAUDE.md', 'GEMINI.md']
    for p in [start, *start.parents]:
        if any((p / m).exists() for m in markers):
            return p
    return start  # 마커를 찾지 못하면 exe 위치 그대로 사용

if getattr(sys, 'frozen', False):
    _exe_parent = Path(sys.executable).resolve().parent
    _root_candidate = _find_project_root(_exe_parent)
    # _find_project_root가 마커(.git 등)를 못 찾아 exe 위치 자체를 반환했으면
    # → DATA_DIR/projects.json에서 마지막 사용 프로젝트 경로를 PROJECT_ROOT로 사용
    # [버그 수정] 설치 경로(C:\...\Programs\)에서 실행 시 PROJECT_ID가 틀려
    #             공유 메모리 현재 프로젝트 필터가 빈 결과를 반환하는 문제 해결
    _no_marker = not any((_root_candidate / m).exists() for m in ['.git', 'CLAUDE.md', 'GEMINI.md'])
    if _no_marker:
        _projs_file = DATA_DIR / 'projects.json'
        try:
            _saved_projs = json.loads(_projs_file.read_text(encoding='utf-8'))
            if _saved_projs and isinstance(_saved_projs, list):
                _first = Path(str(_saved_projs[0]).replace('/', os.sep))
                if _first.exists():
                    _root_candidate = _first
        except Exception:
            pass
    PROJECT_ROOT = _root_candidate
else:
    PROJECT_ROOT = BASE_DIR.parent

# [추가] 내부 스크립트 경로 결정 (개발 vs 배포)
SCRIPTS_DIR = (BASE_DIR / 'scripts') if getattr(sys, 'frozen', False) else (PROJECT_ROOT / 'scripts')
# Claude Code 프로젝트 디렉터리 명명 규칙(: 제거, /·\ → --) 과 동일하게 인코딩
_proj_raw = str(PROJECT_ROOT).replace('\\', '/').replace(':', '').replace('/', '--')
PROJECT_ID: str = _proj_raw.lstrip('-') or 'default'   # e.g. "D--vibe-coding"

# 배포 버전에서 크래시 발생 시 에러 로그 기록 (os.devnull 대신 파일 사용)
if getattr(sys, 'frozen', False) and sys.stdout is None:
    error_log = open(DATA_DIR / "server_error.log", "a", encoding="utf-8")
    sys.stdout = error_log
    sys.stderr = error_log
    print(f"\n--- Server Started at {time.strftime('%Y-%m-%d %H:%M:%S')} ---")

sys.path.append(str(BASE_DIR / 'src'))
# api 모듈 패키지 경로 등록 — frozen(PyInstaller) 및 개발 모드 모두 대응
# BASE_DIR = _MEIPASS(frozen) 또는 server.py 위치(개발) → api/ 패키지가 동일 위치에 있음
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

# Postgres-backed state schema 초기화
ensure_schema(DATA_DIR)

# ── 지식 그래프: 기존 고아 노드 parent_id 소급 연결 (서버 기동 시 1회) ────────
# hive_bridge.py가 새 프로세스로 호출될 때마다 인메모리 체인이 끊겨
# parent_id 없이 삽입된 고아 노드들을 동일 에이전트의 이전 thought와 연결.
def _backfill_thought_parent_ids():
    """pg_thoughts에서 parent_id가 NULL인 노드를 같은 에이전트의 직전 id로 소급 연결."""
    try:
        backfill_sql = (
            "UPDATE pg_thoughts t "
            "SET parent_id = prev.id "
            "FROM ("
            "  SELECT id, agent, "
            "         LAG(id) OVER (PARTITION BY agent ORDER BY id) AS prev_id "
            "  FROM pg_thoughts"
            ") prev "
            "WHERE t.id = prev.id "
            "  AND prev.prev_id IS NOT NULL "
            "  AND t.parent_id IS NULL;"
        )
        run_pg_sql(backfill_sql)
    except Exception:
        pass

_backfill_thought_parent_ids()

# ── 파일 기반 레거시 메모리 저장소 초기화 ─────────────────────────────────────
def _legacy_memory_data_dir() -> Path:
    try:
        if CONFIG_FILE.exists():
            cfg_data = json.loads(CONFIG_FILE.read_text(encoding='utf-8'))
            last_path = cfg_data.get('last_path', '')
            if last_path:
                local_dir = Path(last_path) / '.ai_monitor' / 'data'
                if local_dir.exists():
                    ensure_legacy_store(local_dir)
                    return local_dir
    except Exception:
        pass
    return DATA_DIR


def _memory_conn():
    return None


def _init_memory_db() -> None:
    """Initialize the Postgres-backed memory schema."""
    ensure_schema(DATA_DIR)

_init_memory_db()
# ─────────────────────────────────────────────────────────────────────────────

# ── 임베딩 헬퍼 (fastembed 기반, 한국어 포함 다국어 지원) ────────────────────
_embedder = None
_embedder_lock = threading.Lock()
_EMBED_MODEL = "sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2"

def _get_embedder():
    """fastembed 모델 lazy 초기화 — 첫 호출 시 한 번만 로드"""
    global _embedder
    if _embedder is None:
        with _embedder_lock:
            if _embedder is None:
                try:
                    from fastembed import TextEmbedding
                    _embedder = TextEmbedding(model_name=_EMBED_MODEL)
                    print(f"[Embedding] 모델 로드 완료: {_EMBED_MODEL}")
                except Exception as e:
                    print(f"[Embedding] 모델 로드 실패: {e}")
                    _embedder = False  # 실패 표시 (재시도 방지)
    return _embedder if _embedder else None

def _embed(text: str) -> bytes | None:
    """텍스트 → float32 벡터 bytes 변환. 실패 시 None 반환."""
    try:
        import numpy as np
        embedder = _get_embedder()
        if embedder is None:
            return None
        vec = list(embedder.embed([text[:512]]))[0]  # 512자 제한
        return np.array(vec, dtype=np.float32).tobytes()
    except Exception as e:
        print(f"[Embedding] 변환 실패: {e}")
        return None

def _cosine_sim(a_bytes: bytes, b_bytes: bytes) -> float:
    """두 float32 벡터 bytes 간 코사인 유사도 (0~1)"""
    try:
        import numpy as np
        a = np.frombuffer(a_bytes, dtype=np.float32)
        b = np.frombuffer(b_bytes, dtype=np.float32)
        denom = np.linalg.norm(a) * np.linalg.norm(b)
        return float(np.dot(a, b) / denom) if denom > 1e-10 else 0.0
    except Exception:
        return 0.0
# ─────────────────────────────────────────────────────────────────────────────

# ── 에이전트 메모리 워처 ──────────────────────────────────────────────────────
class MemoryWatcher(threading.Thread):
    """
    Claude Code / Gemini CLI 의 메모리 파일을 감시하여
    변경 발생 시 shared_memory.db 에 자동 동기화하는 백그라운드 워처.

    - Claude Code : ~/.claude/projects/*/memory/*.md
    - Gemini CLI  : ~/.gemini/tmp/{프로젝트명}/logs.json
                    ~/.gemini/tmp/{프로젝트명}/chats/session-*.json

    터미널 번호(T1, T2 …)는 최초 감지된 순서로 자동 부여된다.
    """

    POLL_INTERVAL = 30  # 초 단위 폴링 간격 (리소스 아끼기 위해 30초로 완화)

    def __init__(self) -> None:
        super().__init__(daemon=True, name='MemoryWatcher')
        self._mtimes: dict[str, float] = {}           # 파일경로 → 마지막 mtime
        self._terminal_map: dict[str, int] = {}        # source_key → 터미널 번호
        self._next_terminal: int = 1

    # ── 공개 메서드 ─────────────────────────────────────────────────────────
    def run(self) -> None:
        print("[MemoryWatcher] 에이전트 메모리 감시 시작")
        _sync_tick = 0  # 역방향 동기화 주기 카운터 (40 * 15초 = 10분)
        while True:
            try:
                self._scan_claude_memories()
                self._scan_gemini_logs()
                self._scan_gemini_chats()
                # 10분마다 shared_memory.db → MEMORY.md 역방향 동기화 실행
                _sync_tick += 1
                if _sync_tick >= 40:
                    self._sync_to_claude_memory()
                    _sync_tick = 0
            except Exception as e:
                print(f"[MemoryWatcher] 스캔 오류: {e}")
            time.sleep(self.POLL_INTERVAL)

    # ── 내부: 역방향 동기화 (shared_memory.db → MEMORY.md) ──────────────────
    def _sync_to_claude_memory(self) -> None:
        """
        Gemini·외부 에이전트가 DB에 쓴 항목을 Claude Code auto-memory 파일에
        역동기화한다. claude:T* 키(Claude가 직접 쓴 메모리)는 제외하여 순환 방지.
        MEMORY.md 의 '## 하이브 공유 메모리' 섹션을 교체/추가한다.
        """
        memory_file = (
            Path.home() / '.claude' / 'projects' / PROJECT_ID / 'memory' / 'MEMORY.md'
        )
        if not memory_file.exists():
            return
        try:
            rows = [
                row for row in list_memory(top_k=30, show_all=True)
                if not str(row.get('key', '')).startswith('claude:T')
            ][:15]
            if not rows:
                return

            entries = []
            for r in rows:
                e = dict(r)
                e['tags'] = json.loads(e.get('tags', '[]'))
                entries.append(e)

            # 섹션 구성
            HEADER = '## 하이브 공유 메모리 (자동 동기화)'
            lines = [
                HEADER,
                f'_업데이트: {time.strftime("%Y-%m-%dT%H:%M:%S")} | {len(entries)}개 항목_\n',
            ]
            for e in entries:
                tags_str = ' '.join(f'#{t}' for t in e.get('tags', []))
                preview = e['content'][:90].replace('\n', ' ')
                if len(e['content']) > 90:
                    preview += '...'
                lines.append(f"- **[{e['key']}]** `{e.get('author', '?')}` {tags_str}")
                lines.append(f"  {preview}")

            new_section = '\n'.join(lines) + '\n'
            content = memory_file.read_text(encoding='utf-8', errors='replace')

            if HEADER in content:
                start = content.index(HEADER)
                nxt = content.find('\n## ', start + len(HEADER))
                if nxt == -1:
                    content = content[:start].rstrip() + '\n\n' + new_section
                else:
                    content = (
                        content[:start].rstrip() + '\n\n' + new_section
                        + '\n' + content[nxt + 1:]
                    )
            else:
                content = content.rstrip() + '\n\n' + new_section

            memory_file.write_text(content, encoding='utf-8')
            print(f"[MemoryWatcher] MEMORY.md 역동기화 완료: {len(entries)}개 항목")
        except Exception as e:
            print(f"[MemoryWatcher] MEMORY.md 역동기화 오류: {e}")

    # ── 내부: 터미널 번호 부여 ───────────────────────────────────────────────
    def _terminal_id(self, source_key: str) -> int:
        if source_key not in self._terminal_map:
            self._terminal_map[source_key] = self._next_terminal
            self._next_terminal += 1
        return self._terminal_map[source_key]

    # ── 내부: DB 저장 (Postgres-backed memory store) ───────────────────────
    def _upsert(self, key: str, title: str, content: str,
                author: str, tags: list, project: str = '') -> None:
        now = time.strftime('%Y-%m-%dT%H:%M:%S')
        proj = project or PROJECT_ID
        try:
            existing = get_memory(key)
            created_at = existing.get('created_at', now) if existing else now
            set_memory(
                key=key,
                title=title,
                content=content,
                tags=tags,
                author=author,
                project=proj,
                created_at=created_at,
                updated_at=now,
            )
            print(f"[MemoryWatcher] 동기화 완료: {key}")
        except Exception as e:
            print(f"[MemoryWatcher] DB 쓰기 오류: {e}")

    # ── 내부: 파일 변경 여부 확인 ───────────────────────────────────────────
    def _changed(self, path: Path) -> bool:
        try:
            mtime = path.stat().st_mtime
        except OSError:
            return False
        key = str(path)
        # 메모리 누수 방지: 감시 대상 파일 정보가 너무 많아지면 비우기
        if len(self._mtimes) > 5000:
            self._mtimes.clear()
            
        if self._mtimes.get(key) == mtime:
            return False
        self._mtimes[key] = mtime
        return True

    # ── Claude Code 메모리 스캔 ─────────────────────────────────────────────
    def _scan_claude_memories(self) -> None:
        projects_root = Path.home() / '.claude' / 'projects'
        if not projects_root.exists():
            return
        for proj_dir in projects_root.iterdir():
            if not proj_dir.is_dir():
                continue
            memory_dir = proj_dir / 'memory'
            if not memory_dir.exists():
                continue
            for md_file in memory_dir.glob('*.md'):
                if not self._changed(md_file):
                    continue
                try:
                    content = md_file.read_text(encoding='utf-8', errors='replace').strip()
                    if not content:
                        continue
                    tid = self._terminal_id(f"claude:{proj_dir.name}")
                    stem = md_file.stem  # 예: 'current-work', 'MEMORY'
                    key = f"claude:T{tid}:{stem}"
                    self._upsert(
                        key=key,
                        title=f"[CLAUDE T{tid}] {stem} ({proj_dir.name[:12]})",
                        content=content,
                        author=f"claude-code:terminal-{tid}",
                        tags=['claude', f'terminal-{tid}', stem, proj_dir.name],
                        project=proj_dir.name,
                    )
                except Exception as e:
                    print(f"[MemoryWatcher] Claude 파일 오류 {md_file}: {e}")

    # ── Gemini logs.json 스캔 (최신 세션 요약) ─────────────────────────────
    def _scan_gemini_logs(self) -> None:
        gemini_tmp = Path.home() / '.gemini' / 'tmp'
        if not gemini_tmp.exists():
            return
        for proj_dir in gemini_tmp.iterdir():
            if not proj_dir.is_dir():
                continue
            logs_file = proj_dir / 'logs.json'
            if not logs_file.exists() or not self._changed(logs_file):
                continue
            try:
                raw = logs_file.read_text(encoding='utf-8', errors='replace')
                entries = json.loads(raw)
                if not isinstance(entries, list) or not entries:
                    continue

                # 최신 세션 ID 파악
                latest_session = next(
                    (e['sessionId'] for e in reversed(entries) if e.get('sessionId')),
                    None
                )
                if not latest_session:
                    continue

                # 최신 세션 user 메시지 최대 5개
                msgs = [
                    e for e in entries
                    if e.get('sessionId') == latest_session
                    and e.get('type') == 'user'
                ][-5:]
                if not msgs:
                    continue

                proj_name = proj_dir.name
                tid = self._terminal_id(f"gemini:{proj_name}")
                lines = [
                    f"[Gemini 세션: {latest_session[:8]}…] 프로젝트: {proj_name}",
                    f"최근 사용자 메시지 ({len(msgs)}개):",
                ]
                for m in msgs:
                    ts = str(m.get('timestamp', ''))[:16]
                    text = str(m.get('message', ''))[:300]
                    lines.append(f"- [{ts}] {text}")

                self._upsert(
                    key=f"gemini:T{tid}:{proj_name}:log",
                    title=f"[GEMINI T{tid}] {proj_name} 활동 로그",
                    content='\n'.join(lines),
                    author=f"gemini:terminal-{tid}",
                    tags=['gemini', f'terminal-{tid}', proj_name, 'log'],
                    project=proj_name,
                )
            except Exception as e:
                print(f"[MemoryWatcher] Gemini logs 오류 {logs_file}: {e}")

    # ── Gemini chats 세션 파일 스캔 ────────────────────────────────────────
    def _scan_gemini_chats(self) -> None:
        gemini_tmp = Path.home() / '.gemini' / 'tmp'
        if not gemini_tmp.exists():
            return
        for proj_dir in gemini_tmp.iterdir():
            if not proj_dir.is_dir():
                continue
            chats_dir = proj_dir / 'chats'
            if not chats_dir.exists():
                continue
            # 가장 최근 세션 파일 하나만 처리 (mtime 기준)
            # 수천 개의 세션 파일이 있을 경우 sorted()는 비효율적이므로 max() 사용
            try:
                session_files = list(chats_dir.glob('session-*.json'))
                if not session_files:
                    continue
                latest = max(session_files, key=lambda p: p.stat().st_mtime)
            except (ValueError, OSError):
                continue
                
            if not self._changed(latest):
                continue
            try:
                raw = latest.read_text(encoding='utf-8', errors='replace')
                msgs = json.loads(raw)
                if not isinstance(msgs, list) or not msgs:
                    continue

                # model 응답 중 마지막 요약 추출
                model_msgs = [
                    m for m in msgs if m.get('role') == 'model'
                ]
                summary_parts = []
                if model_msgs:
                    last_model = model_msgs[-1]
                    parts = last_model.get('parts', [])
                    for p in parts:
                        if isinstance(p, dict) and p.get('text'):
                            summary_parts.append(p['text'][:400])
                            break

                proj_name = proj_dir.name
                tid = self._terminal_id(f"gemini:{proj_name}")
                content = (
                    f"[Gemini 채팅 세션] 프로젝트: {proj_name}\n"
                    f"파일: {latest.name}\n"
                    f"메시지 수: {len(msgs)}\n"
                )
                if summary_parts:
                    content += f"마지막 응답 요약:\n{summary_parts[0]}"

                self._upsert(
                    key=f"gemini:T{tid}:{proj_name}:chat",
                    title=f"[GEMINI T{tid}] {proj_name} 채팅",
                    content=content,
                    author=f"gemini:terminal-{tid}",
                    tags=['gemini', f'terminal-{tid}', proj_name, 'chat'],
                    project=proj_name,
                )
            except Exception as e:
                print(f"[MemoryWatcher] Gemini chat 오류 {latest}: {e}")
# ─────────────────────────────────────────────────────────────────────────────

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
    except Exception:
        pass
    return PROJECT_ROOT


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
    except Exception:
        pass

    return ''

# ── MCP 설정 파일 경로 헬퍼 ──────────────────────────────────────────────────
def _mcp_config_path(tool: str, scope: str) -> Path:
    """
    도구(tool)와 범위(scope)에 따른 MCP 설정 파일 경로를 반환합니다.
    - claude / global  → ~/.claude/settings.json
    - claude / project → {현재프로젝트루트}/.claude/settings.local.json
    - gemini / global  → ~/.gemini/settings.json
    - gemini / project → {현재프로젝트루트}/.gemini/settings.json
    - codex  / global  → ~/.codex/config.toml
    - codex  / project → {현재프로젝트루트}/.codex/config.toml

    [수정] BASE_DIR.parent 대신 _current_project_root() 사용.
    배포 버전에서 BASE_DIR = sys._MEIPASS(임시 폴더)라서 project_root가 잘못 지정되던 버그 수정.
    """
    home = Path.home()
    project_root = _current_project_root()  # config.json last_path 우선 참조
    if tool == 'claude':
        if scope == 'global':
            return home / '.claude' / 'settings.json'
        else:
            return project_root / '.claude' / 'settings.local.json'
    elif tool == 'codex':
        # OpenAI Codex CLI — mcpServers 포맷 동일 (JSON)
        if scope == 'global':
            return home / '.codex' / 'config.toml'
        else:
            return project_root / '.codex' / 'config.toml'
    else:  # gemini
        if scope == 'global':
            return home / '.gemini' / 'settings.json'
        else:
            return project_root / '.gemini' / 'settings.json'

# ── Smithery API 키 설정 파일 경로 ──────────────────────────────────────────
_SMITHERY_CFG = DATA_DIR / 'smithery_config.json'

def _smithery_api_key() -> str:
    """저장된 Smithery API 키를 반환합니다. 없으면 빈 문자열."""
    if _SMITHERY_CFG.exists():
        try:
            return json.loads(_SMITHERY_CFG.read_text(encoding='utf-8')).get('api_key', '')
        except Exception:
            pass
    return ''


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
                continue

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
                    input_tokens  = usage.get('input_tokens', 0)
                    output_tokens = usage.get('output_tokens', 0)
                    cache_read    = usage.get('cache_read_input_tokens', 0)
                    cache_write   = usage.get('cache_creation_input_tokens', 0)
                    if not last_ts:
                        last_ts = obj.get('timestamp', '')
                    break  # 가장 최신 usage 찾으면 즉시 종료

        if not session_id:
            return None  # 유효한 세션 파일 아님

        return {
            'session_id':   session_id,
            'slug':         slug or path.stem[:12],   # slug 없으면 파일명 앞 12자
            'model':        model or 'unknown',
            'input_tokens': input_tokens,
            'output_tokens': output_tokens,
            'cache_read':   cache_read,
            'cache_write':  cache_write,
            'last_ts':      last_ts,
            'cwd':          str(cwd).replace('\\', '/'),
        }
    except Exception:
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
    except Exception:
        return None


# ── .env 파일 읽기/쓰기 유틸 ─────────────────────────────────────────────────

# ─────────────────────────────────────────────────────────────────────────────

# 정적 파일 경로 결정 (PyInstaller 배포 환경 대응 최적화)
if getattr(sys, 'frozen', False):
    # [수정] spec에서 'vibe-view/dist'로 패키징하므로 _MEIPASS/vibe-view/dist가 실제 경로
    # 이전: BASE_DIR / "dist" → _MEIPASS/dist 존재하지 않아 exe_dir/dist(빌드 산출물)로 오탐
    STATIC_DIR = (BASE_DIR / "vibe-view" / "dist").resolve()
else:
    # 개발 환경: 최신 UI인 vibe-view를 우선 확인
    STATIC_DIR = (BASE_DIR / "vibe-view" / "dist").resolve()
    if not STATIC_DIR.exists():
        STATIC_DIR = (BASE_DIR / "vibe-view" / "dist").resolve()

print(f"[*] Static files directory: {STATIC_DIR}")
if not STATIC_DIR.exists():
    print(f"[!] WARNING: Static directory NOT FOUND at {STATIC_DIR}")
    # 실행 중인 파일 주변에서 dist 폴더를 한 번 더 찾아봄 (휴리스틱)
    alt_dist = (Path(sys.executable).parent / "dist").resolve()
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
# ─────────────────────────────────────────────────────────────────────────────

class SSEHandler(BaseHTTPRequestHandler):
    def do_GET(self):
        parsed_path = urlparse(self.path)
        path = parsed_path.path

        # MCP API 연동 (POST)
        try:
            content_length = int(self.headers.get('Content-Length', 0))
            post_data = self.rfile.read(content_length).decode('utf-8') if content_length > 0 else '{}'
            data = json.loads(post_data)
            if mcp_api.handle_post(self, path, data, _smithery_api_key_setter=_SMITHERY_CFG, _mcp_config_path=_mcp_config_path):
                return
        except Exception as e: print(f'[MCP Router Error] {e}')

        # MCP API 연동 (GET)
        if mcp_api.handle_get(self, path, urllib.parse.parse_qs(parsed_path.query), _smithery_api_key=_smithery_api_key, _mcp_config_path=_mcp_config_path):
            return
        
        # ─── 신규: 사고 과정 실시간 스트리밍 ───
        if path == '/api/events/thoughts':
            self.send_response(200)
            self.send_header('Content-Type', 'text/event-stream')
            self.send_header('Access-Control-Allow-Origin', '*')
            self.send_header('Cache-Control', 'no-cache')
            self.send_header('Connection', 'keep-alive')
            self.end_headers()
            
            # 초기 데이터 전송 (메모리에 쌓인 로그)
            for log in THOUGHT_LOGS:
                self.wfile.write(f"data: {json.dumps(log, ensure_ascii=False)}\n\n".encode('utf-8'))
                self.wfile.flush()
            
            # 실시간 업데이트를 위해 클라이언트 등록
            THOUGHT_CLIENTS.add(self)
            try:
                # SSE 연결 타임아웃 완화 (60초)
                self.connection.settimeout(60.0)
                while True:
                    time.sleep(30) # 하트비트 주기를 30초로 완화
                    self.wfile.write(b": heartbeat\n\n")
                    self.wfile.flush()
            except Exception:
                pass
            finally:
                THOUGHT_CLIENTS.discard(self)
            return

        # ─── 자율 에이전트 출력 실시간 스트리밍 ───
        # _agent_broadcast_worker가 cli_agent 큐를 읽어 AGENT_CLIENTS 세트의
        # 각 클라이언트 전용 큐로 팬아웃 — 다중 연결/재연결 시 이벤트 손실 없음
        if path == '/api/events/agent':
            self.send_response(200)
            self.send_header('Content-Type', 'text/event-stream')
            self.send_header('Access-Control-Allow-Origin', '*')
            self.send_header('Cache-Control', 'no-cache')
            self.send_header('Connection', 'keep-alive')
            self.end_headers()
            from queue import Queue as _ClientQueue, Empty as _QEmpty
            client_q = _ClientQueue(maxsize=0)  # 클라이언트별 전용 큐 (무제한 — done 이벤트 드롭 방지)
            AGENT_CLIENTS.add(client_q)
            try:
                self.connection.settimeout(None)
                while True:
                    try:
                        msg = client_q.get(timeout=1.0)
                        try:
                            self.wfile.write(f"data: {msg}\n\n".encode('utf-8'))
                            self.wfile.flush()
                        except Exception:
                            break  # 클라이언트 연결 끊김
                    except _QEmpty:
                        # 큐 비어있으면 하트비트 전송 (연결 유지)
                        try:
                            self.wfile.write(b": heartbeat\n\n")
                            self.wfile.flush()
                        except Exception:
                            break  # 클라이언트 연결 끊김
            except Exception:
                pass
            finally:
                AGENT_CLIENTS.discard(client_q)  # 연결 종료 시 세트에서 제거
            return

        # ─── 신규: 파일 시스템 변경 이벤트 스트리밍 ───
        if path == '/api/events/fs':
            self.send_response(200)
            self.send_header('Content-Type', 'text/event-stream')
            self.send_header('Access-Control-Allow-Origin', '*')
            self.send_header('Cache-Control', 'no-cache')
            self.send_header('Connection', 'keep-alive')
            self.end_headers()
            
            FS_CLIENTS.add(self)
            try:
                # SSE 연결 타임아웃 완화 (60초)
                self.connection.settimeout(60.0)
                # 연결 유지를 위한 하트비트 루프
                while True:
                    time.sleep(30) # 하트비트 주기를 30초로 완화
                    self.wfile.write(b": heartbeat\n\n")
                    self.wfile.flush()
            except Exception:
                pass
            finally:
                FS_CLIENTS.discard(self)
            return

        if parsed_path.path == '/stream':
            self.send_response(200)
            self.send_header('Content-Type', 'text/event-stream')
            self.send_header('Access-Control-Allow-Origin', '*')
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
                pg_conn = psycopg2.connect(host="localhost", port=5433, user="postgres", database="postgres")
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
            self.send_header('Access-Control-Allow-Origin', '*')
            self.end_headers()
            self.wfile.write(b"OK")
        elif parsed_path.path == '/api/projects':
            self.send_response(200)
            self.send_header('Content-Type', 'application/json;charset=utf-8')
            self.send_header('Access-Control-Allow-Origin', '*')
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
            self.send_response(200)
            self.send_header('Content-Type', 'application/json;charset=utf-8')
            self.send_header('Access-Control-Allow-Origin', '*')
            self.end_headers()
            with AGENT_STATUS_LOCK:
                self.wfile.write(json.dumps(AGENT_STATUS, ensure_ascii=False).encode('utf-8'))
        elif parsed_path.path == '/api/browse-folder':
            self.send_response(200)
            self.send_header('Content-Type', 'application/json;charset=utf-8')
            self.send_header('Access-Control-Allow-Origin', '*')
            self.end_headers()
            try:
                # PowerShell을 사용하여 폴더 선택창 띄우기
                ps_cmd = (
                    "$app = New-Object -ComObject Shell.Application; "
                    "$folder = $app.BrowseForFolder(0, '프로젝트 폴더를 선택하세요', 0, 0); "
                    "if ($folder) { $folder.Self.Path } else { '' }"
                )
                # CREATE_NO_WINDOW: PowerShell 콘솔 창이 화면에 잠깐 뜨는 문제 방지
                _no_window = getattr(subprocess, 'CREATE_NO_WINDOW', 0x08000000)
                res = subprocess.run(
                    ['powershell', '-WindowStyle', 'Hidden', '-Command', ps_cmd],
                    capture_output=True, text=True, encoding='utf-8',
                    creationflags=_no_window
                )
                selected_path = res.stdout.strip().replace('\\', '/')
                self.wfile.write(json.dumps({"path": selected_path}).encode('utf-8'))
            except Exception as e:
                self.wfile.write(json.dumps({"error": str(e)}).encode('utf-8'))
        elif parsed_path.path == '/api/config':
            self.send_response(200)
            self.send_header('Content-Type', 'application/json;charset=utf-8')
            self.send_header('Access-Control-Allow-Origin', '*')
            self.end_headers()
            config = {}
            if CONFIG_FILE.exists():
                try:
                    with open(CONFIG_FILE, 'r', encoding='utf-8') as f:
                        config = json.load(f)
                except: pass
            self.wfile.write(json.dumps(config).encode('utf-8'))
        elif parsed_path.path == '/api/drives':
            self.send_response(200)
            self.send_header('Content-Type', 'application/json;charset=utf-8')
            self.send_header('Access-Control-Allow-Origin', '*')
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
        elif parsed_path.path == '/api/install-gemini-cli':
            self.send_response(200)
            self.send_header('Content-Type', 'application/json;charset=utf-8')
            self.send_header('Access-Control-Allow-Origin', '*')
            self.end_headers()
            try:
                # Gemini CLI 설치 (전역)
                subprocess.Popen('cmd.exe /k "echo Installing Gemini CLI... && npm install -g @google/gemini-cli"', shell=True)
                result = {"status": "success", "message": "Gemini CLI installation started in a new window."}
            except Exception as e:
                result = {"status": "error", "message": str(e)}
            self.wfile.write(json.dumps(result).encode('utf-8'))
        elif parsed_path.path == '/api/install-claude-code':
            self.send_response(200)
            self.send_header('Content-Type', 'application/json;charset=utf-8')
            self.send_header('Access-Control-Allow-Origin', '*')
            self.end_headers()
            try:
                # Claude Code 설치 (전역)
                subprocess.Popen('cmd.exe /k "echo Installing Claude Code... && npm install -g @anthropic-ai/claude-code"', shell=True)
                result = {"status": "success", "message": "Claude Code installation started in a new window."}
            except Exception as e:
                result = {"status": "error", "message": str(e)}
            self.wfile.write(json.dumps(result).encode('utf-8'))
        elif parsed_path.path == '/api/install-codex-cli':
            self.send_response(200)
            self.send_header('Content-Type', 'application/json;charset=utf-8')
            self.send_header('Access-Control-Allow-Origin', '*')
            self.end_headers()
            try:
                subprocess.Popen('cmd.exe /k "echo Installing Codex CLI... && npm install -g @openai/codex"', shell=True)
                result = {"status": "success", "message": "Codex CLI installation started in a new window."}
            except Exception as e:
                result = {"status": "error", "message": str(e)}
            self.wfile.write(json.dumps(result).encode('utf-8'))
        elif parsed_path.path == '/api/register-codex-to-ai':
            self.send_response(200)
            self.send_header('Content-Type', 'application/json;charset=utf-8')
            self.send_header('Access-Control-Allow-Origin', '*')
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
        elif parsed_path.path == '/api/shutdown-disabled':
            # 24시간 가동을 위해 셧다운 기능 비활성화
            self.send_response(403)
            self.send_header('Content-Type', 'application/json;charset=utf-8')
            self.end_headers()
            self.wfile.write(json.dumps({"status": "error", "message": "Shutdown is disabled for 24/7 operation."}).encode('utf-8'))
        elif parsed_path.path == '/api/files':
            # [수정] Windows 경로(드라이브 루트 등) 처리 및 응답 안정성 강화.
            # 1. 경로 구분자 표준화 및 드라이브 루트(/) 유효성 보정.
            # 2. 예외 발생 시 빈 배열([])을 안전하게 반환하여 연결 끊김 방지.
            query = parse_qs(parsed_path.query)
            target_path = query.get('path', [''])[0].replace('\\', '/')

            # [핵심] 경로가 비어있을 경우 기본값으로 PROJECT_ROOT(문자열) 사용
            if not target_path:
                target_path = str(PROJECT_ROOT).replace('\\', '/')

            # 드라이브 루트(예: D:) 처리 보정
            if target_path and len(target_path) == 2 and target_path[1] == ':':
                target_path += '/'

            items = []
            try:
                # 실제 경로 존재 여부 및 디렉터리 여부 재검증
                p = Path(target_path)
                if p.exists() and p.is_dir():
                    for entry in os.scandir(target_path):
                        # 숨김 항목 필터링 (주요 설정 파일 제외)
                        if not entry.name.startswith('.') or entry.name in ('.claude', '.ai_monitor', '.gemini', '.github', '.gitignore', '.env'):
                            items.append({
                                "name": entry.name,
                                "path": entry.path.replace('\\', '/'),
                                "isDir": entry.is_dir()
                            })
            except Exception as e:
                # 권한 문제 등으로 인한 실패 시 로그 기록 후 빈 목록 반환 (서버 중단 방지)
                print(f"[ERROR] /api/files failed for {target_path}: {e}")

            # 폴더 우선 정렬
            try:
                items.sort(key=lambda x: (not x['isDir'], x['name'].lower()))
            except Exception:
                pass

            body = json.dumps(items).encode('utf-8')
            self.send_response(200)
            self.send_header('Content-Type', 'application/json;charset=utf-8')
            self.send_header('Access-Control-Allow-Origin', '*')
            self.send_header('Content-Length', str(len(body)))
            self.end_headers()
            self.wfile.write(body)
        elif parsed_path.path == '/api/install-skills':
            self.send_response(200)
            self.send_header('Content-Type', 'application/json;charset=utf-8')
            self.send_header('Access-Control-Allow-Origin', '*')
            self.end_headers()
            query = parse_qs(parsed_path.query)
            target_path = query.get('path', [''])[0]
            
            result = {"status": "error", "message": "Invalid path"}
            if target_path and os.path.exists(target_path) and os.path.isdir(target_path):
                try:
                    # [수정] 배포 여부에 따라 소스 경로 결정
                    # .gemini, scripts, GEMINI.md 등을 복사
                    source_base = BASE_DIR if getattr(sys, 'frozen', False) else BASE_DIR.parent
                    
                    # .gemini 복사
                    gemini_src = source_base / ".gemini"
                    if gemini_src.exists():
                        shutil.copytree(gemini_src, Path(target_path) / ".gemini", dirs_exist_ok=True)
                    
                    # scripts 복사
                    scripts_src = SCRIPTS_DIR
                    if scripts_src.exists():
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
                            except Exception: pass
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
                                   '/api/context-usage', '/api/gemini-context-usage',
                                   '/api/local-models')):
            _params = parse_qs(parsed_path.query)
            hive_api.handle_get(
                self, parsed_path.path, _params,
                DATA_DIR=DATA_DIR, SCRIPTS_DIR=SCRIPTS_DIR, BASE_DIR=BASE_DIR,
                PROJECT_ROOT=PROJECT_ROOT, PROJECT_ID=PROJECT_ID,
                TASKS_FILE=TASKS_FILE, AGENT_STATUS=AGENT_STATUS,
                AGENT_STATUS_LOCK=AGENT_STATUS_LOCK,
                pty_sessions=pty_sessions,
                _current_project_root=_current_project_root,
                _parse_session_tail=_parse_session_tail,
                _parse_gemini_session=_parse_gemini_session,
                run_pg_sql_csv=run_pg_sql_csv
            )

        elif parsed_path.path.startswith('/api/git/'):
            _params = parse_qs(parsed_path.query)
            git_api.handle_get(self, parsed_path.path, _params, BASE_DIR=BASE_DIR)

        # ── [모듈 위임] mcp_api — /api/mcp/* ─────────────────────────────
        elif parsed_path.path.startswith('/api/mcp/'):
            _params = parse_qs(parsed_path.query)
            mcp_api.handle_get(
                self, parsed_path.path, _params,
                _smithery_api_key=_smithery_api_key,
                _mcp_config_path=_mcp_config_path,
            )

        # ── [모듈 위임] agent_api — /api/agent/* ─────────────────────────
        elif parsed_path.path.startswith('/api/agent/'):
            agent_api.handle_get(self, parsed_path.path)
        elif parsed_path.path.startswith('/api/pty/'):
            pty_api.handle_get(self, parsed_path.path, parse_qs(parsed_path.query))
        elif parsed_path.path == '/api/config/discord':
            config_api.handle_get_config(self)

        # ── [모듈 위임] memory_api — /api/memory, /api/project-info ──────
        elif parsed_path.path in ('/api/memory', '/api/project-info'):
            _params = parse_qs(parsed_path.query)
            memory_api.handle_get(
                self, parsed_path.path, _params,
                DATA_DIR=DATA_DIR, PROJECT_ID=PROJECT_ID, PROJECT_ROOT=PROJECT_ROOT,
                _memory_conn=_memory_conn, _embed=_embed, _cosine_sim=_cosine_sim,
                __version__=__version__,
            )

        elif parsed_path.path == '/api/hive/health/repair':
            self.send_response(200)
            self.send_header('Content-Type', 'application/json;charset=utf-8')
            self.send_header('Access-Control-Allow-Origin', '*')
            self.end_headers()
            try:
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
            self.send_header('Access-Control-Allow-Origin', '*')
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
                except Exception:
                    pass
            dirs.sort(key=lambda x: x['name'].lower())
            try:
                self.wfile.write(json.dumps(dirs).encode('utf-8'))
                self.wfile.flush()
            except Exception as _e:
                print(f'[/api/dirs write ERROR] {_e}', flush=True)
        elif parsed_path.path == '/api/help':
            self.send_response(200)
            self.send_header('Content-Type', 'application/json;charset=utf-8')
            self.send_header('Access-Control-Allow-Origin', '*')
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
            target_path = query.get('path', [''])[0]
            IMAGE_MIME = {
                'png': 'image/png', 'jpg': 'image/jpeg', 'jpeg': 'image/jpeg',
                'gif': 'image/gif', 'webp': 'image/webp', 'svg': 'image/svg+xml',
                'bmp': 'image/bmp', 'ico': 'image/x-icon',
            }
            ext = target_path.rsplit('.', 1)[-1].lower() if '.' in target_path else ''
            mime = IMAGE_MIME.get(ext, 'application/octet-stream')
            if not target_path or not os.path.exists(target_path) or not os.path.isfile(target_path):
                self.send_response(404)
                self.end_headers()
                return
            self.send_response(200)
            self.send_header('Content-Type', mime)
            self.send_header('Access-Control-Allow-Origin', '*')
            self.end_headers()
            with open(target_path, 'rb') as f:
                self.wfile.write(f.read())

        elif parsed_path.path == '/api/read-file':
            self.send_response(200)
            self.send_header('Content-Type', 'application/json;charset=utf-8')
            self.send_header('Access-Control-Allow-Origin', '*')
            self.end_headers()
            query = parse_qs(parsed_path.query)
            target_path = query.get('path', [''])[0]

            if not target_path or not os.path.exists(target_path) or not os.path.isfile(target_path):
                self.wfile.write(json.dumps({"error": "File not found or invalid path"}).encode('utf-8'))
                return

            try:
                # Try reading as UTF-8
                with open(target_path, 'r', encoding='utf-8') as f:
                    content = f.read()
                self.wfile.write(json.dumps({"content": content}).encode('utf-8'))
            except UnicodeDecodeError:
                self.wfile.write(json.dumps({"error": "Binary file cannot be displayed."}).encode('utf-8'))
            except Exception as e:
                self.wfile.write(json.dumps({"error": str(e)}).encode('utf-8'))
        
        elif parsed_path.path == '/api/check-update-ready':
            self.send_response(200)
            self.send_header('Content-Type', 'application/json;charset=utf-8')
            self.send_header('Access-Control-Allow-Origin', '*')
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
            self.send_header('Access-Control-Allow-Origin', '*')
            self.end_headers()
            if not getattr(sys, 'frozen', False):
                self.wfile.write(json.dumps({"started": False, "reason": "dev build"}).encode('utf-8'))
                return
            try:
                from updater import check_and_update
                threading.Thread(target=check_and_update, args=(DATA_DIR,), daemon=True).start()
                self.wfile.write(json.dumps({"started": True}).encode('utf-8'))
            except Exception as e:
                self.wfile.write(json.dumps({"started": False, "reason": str(e)}).encode('utf-8'))

        elif parsed_path.path == '/api/copy-path':
            self.send_response(200)
            self.send_header('Content-Type', 'application/json;charset=utf-8')
            self.send_header('Access-Control-Allow-Origin', '*')
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
            self.send_header('Access-Control-Allow-Origin', '*')
            self.end_headers()
            try:
                msgs = get_messages(100)
                self.wfile.write(json.dumps(msgs, ensure_ascii=False).encode('utf-8'))
            except Exception as e:
                self.wfile.write(json.dumps({'error': str(e)}).encode('utf-8'))
        elif parsed_path.path == '/api/tasks':
            # 공유 작업 큐 전체 목록 반환
            self.send_response(200)
            self.send_header('Content-Type', 'application/json;charset=utf-8')
            self.send_header('Access-Control-Allow-Origin', '*')
            self.end_headers()
            try:
                tasks = list_tasks()
            except Exception:
                tasks = []
            self.wfile.write(json.dumps(tasks, ensure_ascii=False).encode('utf-8'))
        elif parsed_path.path == '/api/tasks/kanban':
            # 칸반 보드 데이터 — 태스크를 5컬럼으로 그룹화하여 반환
            # kanban_status 필드 우선, 없으면 status에서 매핑 (pending→todo 하위 호환)
            self.send_response(200)
            self.send_header('Content-Type', 'application/json;charset=utf-8')
            self.send_header('Access-Control-Allow-Origin', '*')
            self.end_headers()
            try:
                tasks = list_tasks()
            except Exception:
                tasks = []
            columns: dict = {'todo': [], 'claimed': [], 'in_progress': [], 'review': [], 'done': []}
            for t in tasks:
                # kanban_status 우선 적용, 없으면 status 필드에서 변환
                st = t.get('kanban_status') or t.get('status', 'todo')
                if st == 'pending':
                    st = 'todo'
                if st in columns:
                    columns[st].append(t)
                else:
                    columns['todo'].append(t)
            total = len(tasks)
            done_cnt = len(columns['done'])
            active = total - done_cnt
            rate = round(done_cnt / total * 100) if total > 0 else 0
            result = {**columns, 'stats': {'total': total, 'active': active, 'done': done_cnt, 'rate': rate}}
            self.wfile.write(json.dumps(result, ensure_ascii=False).encode('utf-8'))
        elif parsed_path.path == '/api/task-logs':
            # task_logs.jsonl에서 최근 로그 반환 — 모니터링 뷰 직접 폴링용
            # ?agent=claude  ?terminal_id=T1  ?limit=20
            # SSE 스트림과 달리 JSONL 파일을 직접 읽어 즉시 반환합니다.
            self.send_response(200)
            self.send_header('Content-Type', 'application/json;charset=utf-8')
            self.send_header('Access-Control-Allow-Origin', '*')
            self.end_headers()
            params    = parse_qs(parsed_path.query)
            _agent_f  = params.get('agent',       [''])[0].lower()
            _tid_f    = params.get('terminal_id', [''])[0].upper()
            _limit    = int(params.get('limit',   ['20'])[0])
            _log_file = DATA_DIR / 'task_logs.jsonl'
            _results: list = []
            if _log_file.exists():
                _lines = _log_file.read_text(encoding='utf-8').strip().splitlines()
                for _ln in reversed(_lines[-500:]):
                    try:
                        _entry = json.loads(_ln)
                        # 에이전트 필터 (대소문자 무시)
                        if _agent_f and _entry.get('agent', '').lower() != _agent_f:
                            continue
                        # 터미널 ID 필터 (T1/1 모두 허용)
                        if _tid_f:
                            _raw_tid = _entry.get('terminal_id', '')
                            _norm = f'T{_raw_tid}' if _raw_tid.isdigit() else _raw_tid.upper()
                            if _norm != _tid_f and _raw_tid.upper() != _tid_f:
                                continue
                        _results.append(_entry)
                        if len(_results) >= _limit:
                            break
                    except Exception:
                        pass
            # 시간순으로 정렬하여 반환 (최신 순 → 오래된 순)
            self.wfile.write(json.dumps(_results, ensure_ascii=False).encode('utf-8'))
        elif parsed_path.path == '/api/kanban/pg-activity':
            # Postgres-First 칸반 데이터: pg_logs에서 최근 8시간 터미널별 활동 조회
            # 응답: { "T1": [{agent, task, status, ts}, ...], "T2": [...], ... }
            self.send_response(200)
            self.send_header('Content-Type', 'application/json;charset=utf-8')
            self.send_header('Access-Control-Allow-Origin', '*')
            self.end_headers()
            try:
                rows = run_pg_sql_csv(
                    "SELECT terminal_id, agent, task, status, "
                    "to_char(ts, 'HH24:MI:SS') AS ts "
                    "FROM pg_logs "
                    "WHERE ts > NOW() - INTERVAL '8 hours' "
                    "ORDER BY ts DESC LIMIT 300"
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
            self.send_header('Access-Control-Allow-Origin', '*')
            self.end_headers()
            try:
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
            self.send_header('Access-Control-Allow-Origin', '*')
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
                for row in list_memory(top_k=100, show_all=True):
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
                for slot_num in range(1, 9):
                    info = pty_sessions.get(str(slot_num))
                    if info:
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
                        except Exception:
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
                        except Exception:
                            pass
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
                            except Exception:
                                pass

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
        elif parsed_path.path == '/api/memory/db-info':
            # 현재 사용 중인 공유 메모리 DB 경로 및 항목 수 반환
            # 배포 버전에서 어떤 DB를 바라보고 있는지 UI에서 확인할 수 있게 함
            self.send_response(200)
            self.send_header('Content-Type', 'application/json;charset=utf-8')
            self.send_header('Access-Control-Allow-Origin', '*')
            self.end_headers()
            try:
                ensure_schema(DATA_DIR)
                rows = query_rows("SELECT COUNT(*) AS count FROM hive_memory;")
                count = int(rows[0].get('count', 0)) if rows else 0
                self.wfile.write(json.dumps({
                    'db_path': 'postgres://localhost:5433/postgres',
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
        self.send_header('Access-Control-Allow-Origin', '*')
        self.send_header('Access-Control-Allow-Methods', 'GET, POST, OPTIONS')
        self.send_header('Access-Control-Allow-Headers', 'Content-Type')
        self.end_headers()

    def do_POST(self):
        parsed_path = urlparse(self.path)
        path = parsed_path.path

        # ─── 칸반 보드 네이티브 창 실행 ──────────────────────────────────────
        # window.open() 대신 PySide6 네이티브 프로세스를 직접 실행하여
        # 인터넷 브라우저 창이 아닌 OS 네이티브 데스크톱 창으로 띄웁니다.
        if path == '/api/dashboard/launch':
            self.send_response(200)
            self.send_header('Content-Type', 'application/json;charset=utf-8')
            self.send_header('Access-Control-Allow-Origin', '*')
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
                if getattr(sys, 'frozen', False):
                    # 배포(frozen) 모드: vibe-coding.exe 옆의 vibe-dashboard.exe 직접 실행
                    exe_dir = Path(sys.executable).resolve().parent
                    launch_exe = exe_dir / 'vibe-dashboard.exe'
                    if not launch_exe.exists():
                        raise RuntimeError(f'vibe-dashboard.exe 없음: {launch_exe}')
                    subprocess.Popen(
                        [str(launch_exe), str(HTTP_PORT), tab],
                        creationflags=_no_window,
                        close_fds=True,
                    )
                else:
                    # 개발(dev) 모드: Python 스크립트 서브프로세스로 실행
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

        if path == '/api/kanban/launch':
            # B안 통합: kanban_board.py(PySide6 네이티브) 제거 →
            # dashboard_window.py + React TaskBoardPanel(?kanban=1)으로 일원화.
            # 동일한 API(/api/orchestrator/skill-chain 등)를 통해 데이터 일관성 확보.
            self.send_response(200)
            self.send_header('Content-Type', 'application/json;charset=utf-8')
            self.send_header('Access-Control-Allow-Origin', '*')
            self.end_headers()
            try:
                _no_window = getattr(subprocess, 'CREATE_NO_WINDOW', 0x08000000)
                if getattr(sys, 'frozen', False):
                    # 배포(frozen) 모드: vibe-dashboard.exe를 kanban 탭으로 실행
                    exe_dir = Path(sys.executable).resolve().parent
                    launch_exe = exe_dir / 'vibe-dashboard.exe'
                    if not launch_exe.exists():
                        raise RuntimeError(f'vibe-dashboard.exe 없음: {launch_exe}')
                    subprocess.Popen(
                        [str(launch_exe), str(HTTP_PORT), 'kanban'],
                        creationflags=_no_window,
                        close_fds=True,
                    )
                else:
                    # 개발(dev) 모드: dashboard_window.py kanban 탭으로 실행
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

        # ── 지식 그래프 독립 창 실행 — PySide6 QWebEngineView (?graph=1 모드) ──
        if path == '/api/graph/launch':
            self.send_response(200)
            self.send_header('Content-Type', 'application/json;charset=utf-8')
            self.send_header('Access-Control-Allow-Origin', '*')
            self.end_headers()
            try:
                _no_window = getattr(subprocess, 'CREATE_NO_WINDOW', 0x08000000)
                if getattr(sys, 'frozen', False):
                    # 배포(frozen) 모드: vibe-coding.exe 옆의 vibe-graph.exe 직접 실행
                    exe_dir = Path(sys.executable).resolve().parent
                    launch_exe = exe_dir / 'vibe-graph.exe'
                    if not launch_exe.exists():
                        raise RuntimeError(f'vibe-graph.exe 없음: {launch_exe}')
                    subprocess.Popen(
                        [str(launch_exe), str(HTTP_PORT)],
                        creationflags=_no_window,
                        close_fds=True,
                    )
                else:
                    # 개발(dev) 모드: Python 스크립트 서브프로세스로 실행
                    graph_script = BASE_DIR / 'knowledge_graph_window.py'
                    python_cmds = _python_runner_cmds()
                    if not python_cmds:
                        raise RuntimeError('Python interpreter not found for graph launch')
                    subprocess.Popen(
                        [python_cmds[0], str(graph_script), str(HTTP_PORT)],
                        creationflags=_no_window,
                        close_fds=True,
                    )
                self.wfile.write(json.dumps({"status": "launched"}).encode('utf-8'))
            except Exception as e:
                self.wfile.write(json.dumps({"status": "error", "message": str(e)}).encode('utf-8'))
            return

        # ─── 신규: 사고 과정 로그 추가 (v5.0) ───
        # ─── 신규: PostgreSQL 통합 로깅 API (v5.0) ───
        if path == '/api/hive/log/pg':
            self.send_response(200)
            self.send_header('Content-Type', 'application/json;charset=utf-8')
            self.send_header('Access-Control-Allow-Origin', '*')
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
            self.send_header('Access-Control-Allow-Origin', '*')
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
            self.send_header('Access-Control-Allow-Origin', '*')
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
                for client in list(THOUGHT_CLIENTS):
                    try:
                        client.connection.settimeout(1.0)
                        client.wfile.write(msg.encode('utf-8'))
                        client.wfile.flush()
                    except Exception:
                        disconnected.append(client)
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
                        project=PROJECT_ID,
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

        if parsed_path.path == '/api/save-file':
            # [파일 저장] 프론트엔드 VibeEditor/App.tsx 에서 POST로 호출
            self.send_response(200)
            self.send_header('Content-Type', 'application/json;charset=utf-8')
            self.send_header('Access-Control-Allow-Origin', '*')
            self.end_headers()
            try:
                content_length = int(self.headers['Content-Length'])
                data = json.loads(self.rfile.read(content_length).decode('utf-8'))
                raw_path = data.get('path')
                content = data.get('content', '')
                
                if not raw_path:
                    self.wfile.write(json.dumps({"status": "error", "message": "Path is required"}).encode('utf-8'))
                    return
                
                target_path = Path(raw_path).resolve()
                target_path.parent.mkdir(parents=True, exist_ok=True)
                
                with open(target_path, 'w', encoding='utf-8') as f:
                    f.write(content)
                
                print(f"💾 [File Saved] {target_path}")
                self.wfile.write(json.dumps({"status": "success", "path": str(target_path)}).encode('utf-8'))
            except Exception as e:
                print(f"❌ [Save Error] {e}")
                self.wfile.write(json.dumps({"status": "error", "message": str(e)}).encode('utf-8'))

        elif parsed_path.path == '/api/file-rename':
            # [이름 변경] src -> dest
            self.send_response(200)
            self.send_header('Content-Type', 'application/json;charset=utf-8')
            self.send_header('Access-Control-Allow-Origin', '*')
            self.end_headers()
            try:
                content_length = int(self.headers['Content-Length'])
                data = json.loads(self.rfile.read(content_length).decode('utf-8'))
                src = data.get('src')
                dest = data.get('dest')
                if not src or not dest:
                    self.wfile.write(json.dumps({"status": "error", "message": "src and dest are required"}).encode('utf-8'))
                    return
                # 경로 정규화 및 이름 변경
                os.rename(Path(src), Path(dest))
                self.wfile.write(json.dumps({"status": "success"}).encode('utf-8'))
            except Exception as e:
                self.wfile.write(json.dumps({"status": "error", "message": str(e)}).encode('utf-8'))

        elif parsed_path.path == '/api/files/create':
            # [생성] path, is_dir
            self.send_response(200)
            self.send_header('Content-Type', 'application/json;charset=utf-8')
            self.send_header('Access-Control-Allow-Origin', '*')
            self.end_headers()
            try:
                content_length = int(self.headers['Content-Length'])
                data = json.loads(self.rfile.read(content_length).decode('utf-8'))
                target_path = data.get('path')
                is_dir = data.get('is_dir', False)
                
                if not target_path:
                    self.wfile.write(json.dumps({"status": "error", "message": "Path is required"}).encode('utf-8'))
                    return
                
                p = Path(target_path)
                if is_dir:
                    p.mkdir(parents=True, exist_ok=True)
                else:
                    p.parent.mkdir(parents=True, exist_ok=True)
                    if not p.exists():
                        p.write_text("", encoding="utf-8")
                
                self.wfile.write(json.dumps({"status": "success"}).encode('utf-8'))
            except Exception as e:
                self.wfile.write(json.dumps({"status": "error", "message": str(e)}).encode('utf-8'))

        elif parsed_path.path == '/api/files/delete':
            # [삭제] path
            self.send_response(200)
            self.send_header('Content-Type', 'application/json;charset=utf-8')
            self.send_header('Access-Control-Allow-Origin', '*')
            self.end_headers()
            try:
                content_length = int(self.headers['Content-Length'])
                data = json.loads(self.rfile.read(content_length).decode('utf-8'))
                target_path = data.get('path')
                
                if not target_path or not os.path.exists(target_path):
                    self.wfile.write(json.dumps({"status": "error", "message": "Path not found"}).encode('utf-8'))
                    return
                
                if os.path.isdir(target_path):
                    shutil.rmtree(target_path)
                else:
                    os.remove(target_path)
                
                self.wfile.write(json.dumps({"status": "success"}).encode('utf-8'))
            except Exception as e:
                self.wfile.write(json.dumps({"status": "error", "message": str(e)}).encode('utf-8'))

        elif parsed_path.path == '/api/apply-update':
            # [업데이트 적용] — 응답 전송 후 비동기로 exe 교체 실행
            self.send_response(200)
            self.send_header('Content-Type', 'application/json;charset=utf-8')
            self.send_header('Access-Control-Allow-Origin', '*')
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
                    오류 발생 시 update_error.json에 기록 — UI가 폴링으로 확인 가능.
                    """
                    # 소켓 버퍼 플러시 대기 (0.3s) — 응답이 클라이언트에 도달할 시간 확보
                    time.sleep(0.3)
                    try:
                        apply_update_from_temp(_exe)
                    except Exception as ex:
                        print(f"[!] apply_update_from_temp 실패: {ex}")
                        # 실패 시 update_ready.json 복원 — UI에 버튼 다시 표시
                        try:
                            _update_info = {"ready": True, "downloading": False,
                                            "version": _exe.stem, "exe_path": str(_exe),
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
            self.send_header('Access-Control-Allow-Origin', '*')
            self.end_headers()
            try:
                content_length = int(self.headers['Content-Length'])
                data = json.loads(self.rfile.read(content_length).decode('utf-8'))
                agent_name = data.get('agent')
                if not agent_name:
                    self.wfile.write(json.dumps({"status": "error", "message": "Agent name is required"}).encode('utf-8'))
                    return
                
                with AGENT_STATUS_LOCK:
                    AGENT_STATUS[agent_name] = {
                        "status": data.get("status", "active"),
                        "task": data.get("task"),
                        "last_seen": time.time()
                    }
                self.wfile.write(json.dumps({"status": "success"}).encode('utf-8'))
            except Exception as e:
                self.wfile.write(json.dumps({"status": "error", "message": str(e)}).encode('utf-8'))
        elif parsed_path.path == '/api/trigger-update-check':
            # 업데이트 확인 트리거 — do_GET과 동일 로직 (프론트엔드가 POST로 호출)
            self.send_response(200)
            self.send_header('Content-Type', 'application/json;charset=utf-8')
            self.send_header('Access-Control-Allow-Origin', '*')
            self.end_headers()
            if not getattr(sys, 'frozen', False):
                self.wfile.write(json.dumps({"started": False, "reason": "dev build"}).encode('utf-8'))
            else:
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
            self.send_header('Access-Control-Allow-Origin', '*')
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
            self.send_header('Access-Control-Allow-Origin', '*')
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
            self.send_header('Access-Control-Allow-Origin', '*')
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

        # ── [모듈 위임 - POST] mcp_api ────────────────────────────────────
        # /api/mcp/apikey, /api/mcp/install, /api/mcp/uninstall, /api/mcp/rpc
        elif parsed_path.path.startswith('/api/mcp/'):
            from api import mcp_api
            content_length = int(self.headers.get('Content-Length', 0))
            _body = json.loads(self.rfile.read(content_length).decode('utf-8')) if content_length else {}
            mcp_api.handle_post(
                self, parsed_path.path, _body,
                _smithery_api_key_setter=_SMITHERY_CFG,
                _mcp_config_path=_mcp_config_path,
                DATA_DIR=DATA_DIR
            )

        # ── [모듈 위임 - POST] agent_api — /api/agent/run, /api/agent/stop ─
        elif parsed_path.path.startswith('/api/agent/'):
            agent_api.handle_post(self, parsed_path.path)
        elif parsed_path.path.startswith('/api/pty/'):
            pty_api.handle_post(self, parsed_path.path)

        # ── [모듈 위임 - POST] memory_api ────────────────────────────────
        # /api/memory/set, /api/memory/delete
        elif parsed_path.path.startswith('/api/memory/'):
            from api import memory_api
            content_length = int(self.headers.get('Content-Length', 0))
            _body = json.loads(self.rfile.read(content_length).decode('utf-8')) if content_length else {}
            memory_api.handle_post(
                self, parsed_path.path, _body,
                DATA_DIR=DATA_DIR, PROJECT_ID=PROJECT_ID,
                _memory_conn=_memory_conn, _embed=_embed,
            )

        elif parsed_path.path == '/api/hive/approve-skill':
            self.send_response(200)
            self.send_header('Content-Type', 'application/json;charset=utf-8')
            self.send_header('Access-Control-Allow-Origin', '*')
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
            self.send_header('Access-Control-Allow-Origin', '*')
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
            self.send_response(200)
            self.send_header('Content-Type', 'application/json;charset=utf-8')
            self.send_header('Access-Control-Allow-Origin', '*')
            self.end_headers()
            try:
                import webview
                # main_window가 활성화된 상태에서만 다이얼로그 가능
                if main_window:
                    selected = main_window.create_file_dialog(webview.FOLDER_DIALOG)
                    if selected and len(selected) > 0:
                        path = selected[0].replace('\\', '/')
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
                else:
                    self.wfile.write(json.dumps({"status": "error", "message": "Window not ready"}).encode('utf-8'))
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
                
                if agent == 'claude':
                    yolo_flag = " --dangerously-skip-permissions" if is_yolo else ""
                    cmd = f'start "Claude Code" cmd.exe /k "cd /d {target_dir} && title [Claude Code] && echo Launching Claude Code... && claude{yolo_flag}"'
                elif agent == 'gemini':
                    yolo_flag = " --yolo" if is_yolo else ""
                    cmd = f'start "Gemini CLI" cmd.exe /k "cd /d {target_dir} && title [Gemini CLI] && echo Launching Gemini CLI... && gemini{yolo_flag}"'
                elif agent == 'codex':
                    yolo_flag = " --dangerously-bypass-approvals-and-sandbox" if is_yolo else ""
                    cmd = f'start "Codex CLI" cmd.exe /k "cd /d {target_dir} && title [Codex CLI] && echo Launching Codex CLI... && codex{yolo_flag}"'
                else:
                    cmd = f'start "Terminal" cmd.exe /k "cd /d {target_dir}"'
                
                subprocess.Popen(cmd, shell=True)
                
                self.send_response(200)
                self.send_header('Content-Type', 'application/json;charset=utf-8')
                self.send_header('Access-Control-Allow-Origin', '*')
                self.end_headers()
                self.wfile.write(json.dumps({"status": "launched", "agent": agent}).encode('utf-8'))
            except Exception as e:
                self.send_response(500)
                self.send_header('Access-Control-Allow-Origin', '*')
                self.end_headers()
                self.wfile.write(json.dumps({"error": str(e)}).encode('utf-8'))
        elif parsed_path.path == '/api/send-command':
            self.send_response(200)
            self.send_header('Content-Type', 'application/json;charset=utf-8')
            self.send_header('Access-Control-Allow-Origin', '*')
            self.end_headers()
            try:
                content_length = int(self.headers['Content-Length'])
                post_data = self.rfile.read(content_length)
                data = json.loads(post_data.decode('utf-8'))
                
                target_slot = str(data.get('target'))
                command = data.get('command', '')
                
                if target_slot in pty_sessions:
                    pty = pty_sessions[target_slot]['pty']
                    # 명령어 중간의 \n을 \r\n으로 치환하고 끝에 개행이 없으면 추가하여 즉시 실행 유도
                    processed_cmd = command.replace('\r\n', '\r').replace('\n', '\r')
                    final_cmd = processed_cmd if processed_cmd.endswith('\r') else processed_cmd + '\r'
                    pty.write(final_cmd)
                    self.wfile.write(json.dumps({"status": "success", "message": f"Command sent to Terminal {target_slot}"}).encode('utf-8'))
                else:
                    self.wfile.write(json.dumps({"status": "error", "message": f"Terminal {target_slot} is not running."}).encode('utf-8'))
            except Exception as e:
                self.wfile.write(json.dumps({"status": "error", "message": str(e)}).encode('utf-8'))
        elif parsed_path.path == '/api/locks':
            self.send_response(200)
            self.send_header('Content-Type', 'application/json;charset=utf-8')
            self.send_header('Access-Control-Allow-Origin', '*')
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
                            project="hive",
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
            self.send_header('Access-Control-Allow-Origin', '*')
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

                for info in pty_sessions.values():
                    try:
                        pty = info['pty']
                        if is_manual_cmd:
                            pty.write(cmd_to_exec)
                        else:
                            pty.write(terminal_msg)
                    except:
                        pass

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
                        project="hive",
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
            self.send_header('Access-Control-Allow-Origin', '*')
            self.end_headers()
            ok = clear_messages()
            self.wfile.write(json.dumps({'status': 'ok' if ok else 'error'}).encode('utf-8'))
        elif parsed_path.path == '/api/tasks':
            # 새 작업 생성 — tasks.json 배열에 추가
            self.send_response(200)
            self.send_header('Content-Type', 'application/json;charset=utf-8')
            self.send_header('Access-Control-Allow-Origin', '*')
            self.end_headers()
            try:
                content_length = int(self.headers['Content-Length'])
                post_data = self.rfile.read(content_length)
                data = json.loads(post_data.decode('utf-8'))

                now = time.strftime('%Y-%m-%dT%H:%M:%S')
                # tags 필드 — 리스트 타입 검증 (문자열이면 쉼표 분리)
                raw_tags = data.get('tags', [])
                if isinstance(raw_tags, str):
                    raw_tags = [t.strip() for t in raw_tags.split(',') if t.strip()]
                task = {
                    'id': str(int(time.time() * 1000)),
                    'timestamp': now,
                    'updated_at': now,
                    'title': str(data.get('title', '제목 없음')),
                    'description': str(data.get('description', '')),
                    'status': 'pending',
                    'assigned_to': str(data.get('assigned_to', 'all')),
                    'priority': str(data.get('priority', 'medium')),
                    'created_by': str(data.get('created_by', 'user')),
                    # ── 칸반 확장 필드 ──
                    'kanban_status': str(data.get('kanban_status', 'todo')),
                    'role': str(data.get('role', '')),
                    'claimed_by': str(data.get('claimed_by', '')),
                    'tags': raw_tags,
                }
                save_task(task)

                # SSE 로그에도 반영 (태스크 보드 알림)
                try:
                    log_entry = {
                        'timestamp': now,
                        'agent': task['created_by'],
                        'terminal_id': 'TASK_BOARD',
                        'project': 'hive',
                        'status': 'success',
                        'trigger': f"[새 작업] {task['title']} → {task['assigned_to']}",
                        'ts_start': now,
                    }
                    with open(SESSIONS_FILE, 'a', encoding='utf-8') as lf:
                        lf.write(json.dumps(log_entry, ensure_ascii=False) + '\n')
                except Exception:
                    pass

                self.wfile.write(json.dumps({'status': 'success', 'task': task}, ensure_ascii=False).encode('utf-8'))
            except Exception as e:
                self.wfile.write(json.dumps({'status': 'error', 'message': str(e)}).encode('utf-8'))
        elif parsed_path.path == '/api/tasks/update':
            # 기존 작업 상태/담당자 등 업데이트
            self.send_response(200)
            self.send_header('Content-Type', 'application/json;charset=utf-8')
            self.send_header('Access-Control-Allow-Origin', '*')
            self.end_headers()
            try:
                content_length = int(self.headers['Content-Length'])
                post_data = self.rfile.read(content_length)
                data = json.loads(post_data.decode('utf-8'))

                task_id = str(data.get('id', ''))
                updates = {}
                for key in ('status', 'assigned_to', 'priority', 'title',
                            'description', 'kanban_status', 'role', 'claimed_by'):
                    if key in data:
                        updates[key] = str(data[key])
                if 'tags' in data:
                    raw_tags = data['tags']
                    if isinstance(raw_tags, str):
                        raw_tags = [t.strip() for t in raw_tags.split(',') if t.strip()]
                    updates['tags'] = list(raw_tags) if isinstance(raw_tags, list) else []
                updates['updated_at'] = time.strftime('%Y-%m-%dT%H:%M:%S')
                updated_task = update_task(task_id, updates)

                self.wfile.write(json.dumps({'status': 'success', 'task': updated_task}, ensure_ascii=False).encode('utf-8'))
            except Exception as e:
                self.wfile.write(json.dumps({'status': 'error', 'message': str(e)}).encode('utf-8'))
        elif parsed_path.path == '/api/tasks/delete':
            # 작업 삭제 (id 기준 필터링)
            self.send_response(200)
            self.send_header('Content-Type', 'application/json;charset=utf-8')
            self.send_header('Access-Control-Allow-Origin', '*')
            self.end_headers()
            try:
                content_length = int(self.headers['Content-Length'])
                post_data = self.rfile.read(content_length)
                data = json.loads(post_data.decode('utf-8'))

                task_id = str(data.get('id', ''))
                delete_task(task_id)

                self.wfile.write(json.dumps({'status': 'success'}, ensure_ascii=False).encode('utf-8'))
            except Exception as e:
                self.wfile.write(json.dumps({'status': 'error', 'message': str(e)}).encode('utf-8'))
        elif parsed_path.path == '/api/tasks/claim':
            # 터미널이 태스크를 Claim — kanban_status=claimed, claimed_by=terminal_id로 업데이트
            self.send_response(200)
            self.send_header('Content-Type', 'application/json;charset=utf-8')
            self.send_header('Access-Control-Allow-Origin', '*')
            self.end_headers()
            try:
                content_length = int(self.headers['Content-Length'])
                post_data = self.rfile.read(content_length)
                data = json.loads(post_data.decode('utf-8'))
                task_id = str(data.get('id', ''))
                terminal_id = str(data.get('terminal_id', ''))
                claimed_task = update_task(task_id, {
                    'kanban_status': 'claimed',
                    'claimed_by': terminal_id,
                    'updated_at': time.strftime('%Y-%m-%dT%H:%M:%S'),
                })
                self.wfile.write(json.dumps({'status': 'success', 'task': claimed_task}, ensure_ascii=False).encode('utf-8'))
            except Exception as e:
                self.wfile.write(json.dumps({'status': 'error', 'message': str(e)}).encode('utf-8'))
        elif parsed_path.path == '/api/memory/sync':
            # APPDATA DB → 현재 프로젝트 로컬 DB 동기화
            # 배포 버전에서 APPDATA DB에 있는 항목을 로컬 DB로 가져옴 (updated_at 기준 최신 우선)
            self.send_response(200)
            self.send_header('Content-Type', 'application/json;charset=utf-8')
            self.send_header('Access-Control-Allow-Origin', '*')
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

        elif parsed_path.path == '/api/memory/set':
            # 공유 메모리 항목 저장/갱신 — key 기준 UPSERT (file store)
            self.send_response(200)
            self.send_header('Content-Type', 'application/json;charset=utf-8')
            self.send_header('Access-Control-Allow-Origin', '*')
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
                project = str(data.get('project', PROJECT_ID)).strip() or PROJECT_ID
                legacy_dir = _legacy_memory_data_dir()
                existing = get_memory_entry(legacy_dir, key)
                entry = upsert_memory_entry(legacy_dir, {
                    'key': key,
                    'title': title,
                    'content': content,
                    'tags': data.get('tags', []),
                    'author': str(data.get('author', 'unknown')),
                    'project': project,
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
            self.send_header('Access-Control-Allow-Origin', '*')
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
        elif parsed_path.path == '/api/mcp/apikey':
            # Smithery API 키 저장
            self.send_response(200)
            self.send_header('Content-Type', 'application/json;charset=utf-8')
            self.send_header('Access-Control-Allow-Origin', '*')
            self.end_headers()
            try:
                content_length = int(self.headers['Content-Length'])
                body = json.loads(self.rfile.read(content_length).decode('utf-8'))
                api_key = str(body.get('api_key', '')).strip()
                _SMITHERY_CFG.write_text(
                    json.dumps({'api_key': api_key}, ensure_ascii=False, indent=2),
                    encoding='utf-8'
                )
                self.wfile.write(json.dumps({'status': 'success'}).encode('utf-8'))
            except Exception as e:
                self.wfile.write(json.dumps({'status': 'error', 'message': str(e)}).encode('utf-8'))

        elif parsed_path.path == '/api/mcp/install':
            # MCP 설치 — config 파일의 mcpServers 키에 엔트리 추가
            self.send_response(200)
            self.send_header('Content-Type', 'application/json;charset=utf-8')
            self.send_header('Access-Control-Allow-Origin', '*')
            self.end_headers()
            try:
                content_length = int(self.headers['Content-Length'])
                body = json.loads(self.rfile.read(content_length).decode('utf-8'))
                tool    = str(body.get('tool',  'claude'))
                scope   = str(body.get('scope', 'global'))
                name    = str(body.get('name',  ''))
                package = str(body.get('package', ''))
                req_env = body.get('requiresEnv', [])  # 필수 환경변수 목록

                if not name or not package:
                    self.wfile.write(json.dumps({'status': 'error', 'message': 'name·package 필수'}).encode('utf-8'))
                    return

                config_path = _mcp_config_path(tool, scope)
                # 디렉토리 없으면 생성
                config_path.parent.mkdir(parents=True, exist_ok=True)
                # 기존 설정 읽기 (없으면 빈 객체)
                if config_path.exists():
                    config = json.loads(config_path.read_text(encoding='utf-8'))
                else:
                    config = {}
                if 'mcpServers' not in config:
                    config['mcpServers'] = {}

                # mcpServers 엔트리 구성 (환경변수가 필요하면 플레이스홀더 삽입)
                entry: dict = {"command": "npx", "args": ["-y", package]}
                if req_env:
                    entry["env"] = {k: f"<YOUR_{k}>" for k in req_env}
                config['mcpServers'][name] = entry

                # JSON 쓰기 (들여쓰기 2칸, 한글 깨짐 방지)
                config_path.write_text(
                    json.dumps(config, ensure_ascii=False, indent=2),
                    encoding='utf-8'
                )
                msg = f"MCP '{name}' 설치 완료 → {config_path}"
                if req_env:
                    msg += f" | 환경변수 필요: {', '.join(req_env)}"
                self.wfile.write(json.dumps({'status': 'success', 'message': msg}).encode('utf-8'))
            except Exception as e:
                self.wfile.write(json.dumps({'status': 'error', 'message': str(e)}).encode('utf-8'))

        elif parsed_path.path == '/api/mcp/uninstall':
            # MCP 제거 — config 파일의 mcpServers 에서 해당 키 삭제
            self.send_response(200)
            self.send_header('Content-Type', 'application/json;charset=utf-8')
            self.send_header('Access-Control-Allow-Origin', '*')
            self.end_headers()
            try:
                content_length = int(self.headers['Content-Length'])
                body = json.loads(self.rfile.read(content_length).decode('utf-8'))
                tool  = str(body.get('tool',  'claude'))
                scope = str(body.get('scope', 'global'))
                name  = str(body.get('name',  ''))

                if not name:
                    self.wfile.write(json.dumps({'status': 'error', 'message': 'name 필수'}).encode('utf-8'))
                    return

                config_path = _mcp_config_path(tool, scope)
                if not config_path.exists():
                    self.wfile.write(json.dumps({'status': 'error', 'message': '설정 파일 없음'}).encode('utf-8'))
                    return

                config = json.loads(config_path.read_text(encoding='utf-8'))
                servers = config.get('mcpServers', {})
                if name in servers:
                    del servers[name]
                    config['mcpServers'] = servers
                    config_path.write_text(
                        json.dumps(config, ensure_ascii=False, indent=2),
                        encoding='utf-8'
                    )
                    self.wfile.write(json.dumps({'status': 'success', 'message': f"MCP '{name}' 제거 완료"}).encode('utf-8'))
                else:
                    self.wfile.write(json.dumps({'status': 'error', 'message': f"'{name}' 항목 없음"}).encode('utf-8'))
            except Exception as e:
                self.wfile.write(json.dumps({'status': 'error', 'message': str(e)}).encode('utf-8'))

        elif parsed_path.path == '/api/superpowers/install':
            # Vibe Coding 자체 스킬 설치 — 외부 GitHub 의존 없이 내장 파일 복사
            # Claude: skills/claude/vibe-*.md → PROJECT_ROOT/.claude/commands/ (프로젝트별)
            # Gemini: BASE_DIR 내장 → PROJECT_ROOT/.gemini/skills/ (프로젝트별)
            self.send_response(200)
            self.send_header('Content-Type', 'application/json;charset=utf-8')
            self.send_header('Access-Control-Allow-Origin', '*')
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
                    # 빌드 버전: BASE_DIR(sys._MEIPASS)에 내장된 스킬을 현재 프로젝트에 복사
                    # 개발 버전: _proj/.gemini/skills/ 가 이미 존재하므로 소스=대상
                    import shutil as _shutil
                    gemini_skills_src = BASE_DIR / '.gemini' / 'skills'
                    if not gemini_skills_src.exists():
                        gemini_skills_src = _proj / '.gemini' / 'skills'
                    if not gemini_skills_src.exists():
                        raise Exception('내장 Gemini 스킬을 찾을 수 없습니다 (.gemini/skills/)')
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
            self.send_header('Access-Control-Allow-Origin', '*')
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
            self.send_header('Access-Control-Allow-Origin', '*')
            self.end_headers()
            try:
                content_length = int(self.headers.get('Content-Length', 0))
                body = json.loads(self.rfile.read(content_length).decode('utf-8'))
                step = int(body.get('step', 0))
                status = body.get('status', 'done')
                summary = body.get('summary', '')
                terminal_id = int(body.get('terminal_id', 0))
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
            self.send_header('Access-Control-Allow-Origin', '*')
            self.end_headers()
            try:
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

pty_sessions = {}
pty_output_buffers = {}
pty_output_seq = {}


def _normalize_codex_stream(data: str) -> str:
    """Codex PTY 스트림 정규화.

    이전 버전에서 ANSI escape 시퀀스를 모두 제거했으나,
    xterm.js가 커서 이동/색상 코드 등을 직접 처리해야 하므로
    ANSI 코드는 그대로 통과시키고 \r\r\n 중복만 정리합니다.
    """
    # \r\r\n → \r\n: winpty가 가끔 CR을 이중으로 보내는 현상만 보정
    return data.replace('\r\r\n', '\r\n')


def _append_pty_output(session_id: str, stream_data: str, ansi_regex) -> None:
    """Store recent PTY output lines for remote bridge polling."""
    try:
        clean = ansi_regex.sub('', stream_data)
        clean = clean.replace('\r', '\n')
        lines = [line.strip() for line in clean.split('\n') if line.strip()]
        if not lines:
            return

        buf = pty_output_buffers.setdefault(session_id, deque(maxlen=400))
        next_seq = pty_output_seq.get(session_id, 0)
        for line in lines:
            next_seq += 1
            buf.append({
                'seq': next_seq,
                'text': line[:500],
            })
        pty_output_seq[session_id] = next_seq
    except Exception:
        pass
# agent_api가 PTY 세션 상태를 /api/agent/terminals 응답에 병합할 수 있도록
# pty_sessions 딕셔너리 접근 콜백을 주입합니다.
agent_api.set_pty_sessions_getter(lambda: pty_sessions)
pty_api.set_pty_sessions_getter(lambda: pty_sessions)
pty_api.set_pty_output_getter(lambda: pty_output_buffers)

async def pty_handler(websocket):
    try:
        # [버그수정 2026-03-11] websockets >= 14.0에서 websockets.serve가 legacy API로 변경됨.
        # legacy WebSocketServerProtocol에는 request 속성이 없고 path 속성을 직접 사용해야 함.
        # websocket.request.path → AttributeError → PTY Init Error → WS 즉시 닫힘 현상 수정.
        path = getattr(websocket, 'path', None) or getattr(getattr(websocket, 'request', None), 'path', '/')
        parsed = urlparse(path)
        qs = parse_qs(parsed.query)
        agent = qs.get('agent', [''])[0]
        cwd = qs.get('cwd', ['C:\\'])[0]
        try:
            cols = int(qs.get('cols', ['80'])[0])
        except ValueError:
            cols = 80
        try:
            rows = int(qs.get('rows', ['24'])[0])
        except ValueError:
            rows = 24

        # [최적화] 환경변수를 PTY spawn 전에 env dict에 직접 주입
        # Why: pty.write()로 set 명령을 날리면 cmd.exe가 각 명령을 순차 처리 후 다음으로 진행해
        #      set 명령 1개당 ~50ms, chcp는 200~500ms 지연이 발생했음.
        #      env dict에 미리 넣으면 spawn 시점에 이미 환경변수가 설정되어 지연 0.
        env = os.environ.copy()
        env["PYTHONIOENCODING"] = "utf-8"
        env["LANG"] = "ko_KR.UTF-8"
        env["TERM"] = "xterm-256color"
        env["COLORTERM"] = "truecolor"
        # 한글 UTF-8 코드페이지: 환경변수로 미리 지정 (chcp 65001 명령 실행 불필요)
        env["PYTHONLEGACYWINDOWSSTDIO"] = "0"
        # [비용 최적화] Claude Code 백그라운드 작업(파일 요약, 툴 결정 등)에 Haiku 사용.
        # Why: Claude Code는 내부적으로 수백 개의 경량 호출을 메인 모델로 처리함.
        #      ANTHROPIC_DEFAULT_HAIKU_MODEL을 지정하면 이 호출들이 Haiku로 자동 라우팅되어
        #      메인 모델(Sonnet/Opus) 비용의 ~87%를 절감할 수 있음.
        #      사용자가 이미 env에 설정한 경우 덮어쓰지 않음 (기존 설정 존중).
        if not os.environ.get('ANTHROPIC_DEFAULT_HAIKU_MODEL'):
            env["ANTHROPIC_DEFAULT_HAIKU_MODEL"] = "claude-haiku-4-5-20251001"

        is_yolo = qs.get('yolo', ['false'])[0].lower() == 'true'

        # ── session_id를 에이전트 실행 전에 먼저 계산 ──────────────────────────
        # TERMINAL_ID/HIVE_AGENT 환경변수 주입에 session_id가 필요하므로 순서 이동.
        match = re.search(r'/pty/slot(\d+)', path)
        if match:
            # UI의 Terminal 1, Terminal 2 와 맞추기 위해 slot + 1 을 ID로 사용
            session_id = str(int(match.group(1)) + 1)
        else:
            session_id = str(id(websocket))

        # TERMINAL_ID/HIVE_AGENT를 env dict에 직접 주입 (set 명령 pty.write 제거)
        env["TERMINAL_ID"] = session_id
        if agent == 'claude':
            env["HIVE_AGENT"] = "claude"
        elif agent == 'gemini':
            env["HIVE_AGENT"] = "gemini"
        elif agent == 'codex':
            env["HIVE_AGENT"] = "codex"

        pty = PtyProcess.spawn('cmd.exe', cwd=cwd, dimensions=(rows, cols), env=env)

        # [최적화] chcp + 에이전트 명령을 단일 write()로 합치고 chcp 출력 억제
        # Why: 이전에는 pty.write() 5회 호출(chcp, cls, set×2, agent) → 각 명령 처리 대기로
        #      버튼 클릭부터 에이전트 시작까지 ~700ms 이상 지연 발생.
        #      단일 write + >nul 출력 억제로 체감 지연을 제거.
        if agent == 'claude':
            yolo_flag = " --dangerously-skip-permissions" if is_yolo else ""
            pty.write(f'chcp 65001 >nul & claude{yolo_flag}\r\n')
        elif agent == 'gemini':
            yolo_flag = " -y" if is_yolo else ""
            pty.write(f'chcp 65001 >nul & gemini{yolo_flag}\r\n')
        elif agent == 'codex':
            yolo_flag = " --dangerously-bypass-approvals-and-sandbox" if is_yolo else ""
            pty.write(f'chcp 65001 >nul & codex{yolo_flag} --no-alt-screen\r\n')

        # 슬롯별 에이전트 실시간 감지를 위해 agent/yolo/cwd 정보도 함께 저장
        # cwd를 포함해야 agent_api.py가 Gemini 세션 파일을 정확히 매핑할 수 있음
        # main_model/bg_model: 터미널 슬롯 UI에서 현재 사용 모델 표시용
        _main_model = env.get('ANTHROPIC_MODEL', 'sonnet-4-6') if agent == 'claude' else ''
        _bg_model   = env.get('ANTHROPIC_DEFAULT_HAIKU_MODEL', '') if agent == 'claude' else ''
        pty_sessions[session_id] = {
            'pty': pty, 'agent': agent, 'yolo': is_yolo,
            'started': datetime.now().isoformat(), 'cwd': cwd,
            'main_model': _main_model, 'bg_model': _bg_model,
        }
        pty_output_buffers[session_id] = deque(maxlen=400)
        pty_output_seq[session_id] = 0

        # ── [세션 시작 로그] ──────────────────────────────────────────────
        # PTY 터미널에서 에이전트가 시작될 때 즉시 session_logs에 기록.
        # 이를 통해 대시보드가 Gemini/Claude 작업 시작 시점을 즉각 인지 가능.
        # 강제 종료 감지를 위한 기준점 역할도 수행.
        if agent:
            try:
                # insert_log는 모듈 레벨에서 이미 import됨 — 핸들러 내 동적 import 제거
                mode_tag = "[YOLO]" if is_yolo else "[일반]"
                insert_log(
                    session_id=f"pty_start_{session_id}_{datetime.now().strftime('%H%M%S')}",
                    terminal_id="PTY_TERMINAL",
                    agent=agent.capitalize(),
                    trigger_msg=f"─── {agent.upper()} 세션 시작 {mode_tag} ───",
                    project="hive",
                    status="running"
                )
            except Exception as _e:
                print(f"[PTY] 세션 시작 로그 실패: {_e}")

    except Exception as e:
        print(f"PTY Init Error: {e}")
        await websocket.close()
        return

    # ANSI 이스케이프 코드 제거용 정규식 — PTY last_line 정제에 사용
    # re는 모듈 레벨에서 이미 import됨 (중복 import 제거)
    _ANSI_ESCAPE = re.compile(r'\x1b(?:[@-Z\\-_]|\[[0-?]*[ -/]*[@-~])')

    async def read_from_pty():
        loop = asyncio.get_running_loop()
        while True:
            try:
                data = await loop.run_in_executor(None, pty.read, 4096)
                if not data:
                    await asyncio.sleep(0.01)
                    continue
                stream_data = _normalize_codex_stream(data) if agent == 'codex' else data
                if not stream_data:
                    continue
                await websocket.send(stream_data)
                _append_pty_output(session_id, stream_data, _ANSI_ESCAPE)
                # ── PTY 출력의 마지막 줄을 pty_sessions에 저장 ─────────────────────
                # 목적: agent_api.py가 /api/agent/terminals 응답 빌드 시 last_line을
                #       참조하여 자율 에이전트 패널에 "현재 무엇을 하고 있는지" 표시.
                # ANSI 이스케이프 코드를 제거하고 빈 줄·제어문자 줄은 무시.
                if session_id in pty_sessions:
                    try:
                        clean = _ANSI_ESCAPE.sub('', stream_data)
                        clean = clean.replace('\r', '\n')
                        lines = [l.strip() for l in clean.split('\n') if l.strip() and len(l.strip()) > 2]
                        if lines:
                            pty_sessions[session_id]['last_line'] = lines[-1][:120]
                    except Exception:
                        pass  # last_line 업데이트 실패 시 무시 (메인 흐름 보호)
            except EOFError:
                print("PTY read EOFError")
                break
            except Exception as e:
                print("PTY read Exception:", e)
                break

    # ── [자율 에이전트 자동 트리거] PTY 입력 버퍼 ────────────────────────────────
    # 사용자가 타이핑하는 문자를 누적해두고, Enter(\r) 입력 시 완성된 명령을
    # cli_agent.py로 자동 라우팅합니다.
    # Claude 터미널: UserPromptSubmit 훅(hook_bridge.py)이 이미 동작하므로 중복 방지를 위해
    #   실제 터미널이 claude가 아닌 경우(gemini, 빈 셸 등)에만 PTY 인터셉션 발동.
    # 단, 세션 시작 직후 자동 입력(set TERMINAL_ID=... 등)은 누적하지 않도록 _ws_init_done 플래그 활용.
    _ws_input_buf: list[str] = []   # 현재 줄 누적 버퍼
    _ws_init_done = False            # 초기 세팅 명령 무시 플래그

    def _dispatch_to_agent(instruction: str) -> None:
        """누적된 명령을 백그라운드 cli_agent.py로 라우팅합니다.

        Claude 터미널은 훅이 이미 동작하므로 Gemini / 기타 에이전트에만 적용합니다.
        메인 asyncio 루프를 블로킹하지 않도록 스레드로 실행합니다.
        """
        instruction = instruction.strip()
        # 너무 짧거나 제어 문자로만 이루어진 입력 무시
        if len(instruction) < 4:
            return
        # 에이전트(claude/gemini 등)가 이미 PTY에서 실행 중이면 라우팅 불필요.
        # PTY 자체가 입력을 처리하므로 cli_agent.py를 추가 spawn하면
        # 이중 실행 + CMD 창 깜빡임 발생. 빈 셸 터미널에서만 라우팅.
        if agent:
            return

        import threading as _t
        import subprocess as _sp
        scripts_dir = Path(__file__).parent.parent / 'scripts'
        cli_agent_py = scripts_dir / 'cli_agent.py'

        def _run():
            try:
                child_env = os.environ.copy()
                child_env['CLI_AGENT_JSON_STDOUT'] = '1'
                proc = _sp.Popen(
                    [sys.executable, str(cli_agent_py), instruction, 'auto'],
                    cwd=str(Path(__file__).parent.parent),
                    stdout=_sp.PIPE,
                    stderr=_sp.STDOUT,
                    text=True,
                    encoding='utf-8',
                    errors='replace',
                    env=child_env,
                    creationflags=(_sp.CREATE_NO_WINDOW if os.name == 'nt' else 0),
                )
                if proc.stdout is not None:
                    for raw_line in proc.stdout:
                        raw_line = raw_line.strip()
                        if not raw_line:
                            continue
                        try:
                            event = json.loads(raw_line)
                            line = event.get('line', '')
                            if line:
                                pty.write(line + '\r\n')
                            elif event.get('type') == 'done':
                                status = event.get('status', 'done')
                                pty.write(f'[agent:{status}]\r\n')
                        except Exception:
                            pty.write(raw_line + '\r\n')
                print(f"[PTY→AGENT] {agent or 'shell'} 터미널 자율 에이전트 라우팅: {instruction[:60]}")
            except Exception as _e:
                print(f"[PTY→AGENT] 라우팅 실패: {_e}")

        _t.Thread(target=_run, daemon=True).start()

    def _dispatch_ws_enter():
        nonlocal _ws_input_buf
        if _ws_init_done and _ws_input_buf:
            completed_line = ''.join(_ws_input_buf)
            _ws_input_buf.clear()
            # re는 모듈 레벨에서 이미 import됨 — 중복 import 제거
            cleaned = re.sub(r'[\x00-\x1f\x7f-\x9f]', '', completed_line).strip()
            if cleaned:
                _dispatch_to_agent(cleaned)
        # Gemini/Codex submits require a double Enter in the
        # underlying TUI. Normalize that here so direct XTerm
        # typing and the textarea sender behave identically.
        pty.write("\r\r" if agent in ("gemini", "codex") else "\r")

    async def read_from_ws():
        nonlocal _ws_init_done, _ws_input_buf
        # 초기화 명령(set TERMINAL_ID, chcp 등)이 모두 전송된 뒤 1초 후부터 인터셉션 활성화
        # → PTY spawn 직후 자동으로 write()하는 명령들을 에이전트에 전달하지 않기 위함
        await asyncio.sleep(1.5)
        _ws_init_done = True

        async for message in websocket:
            try:
                if isinstance(message, bytes):
                    message = message.decode('utf-8')

                if message:
                    # [추가] 제어 메시지(JSON) 처리 — 리사이즈 등
                    try:
                        if message.startswith('{') and message.endswith('}'):
                            data = json.loads(message)
                            if isinstance(data, dict) and data.get('type') == 'resize':
                                cols = int(data.get('cols', 80))
                                rows = int(data.get('rows', 24))
                                pty.setwinsize(rows, cols)
                                continue
                    except (json.JSONDecodeError, ValueError, TypeError):
                        pass

                    # [수정] 윈도우 IME 및 xterm.js 호환성 개선
                    # \r\n 중복 방지 및 조합 중인 문자 처리 안정화
                    processed = message.replace('\r\n', '\r').replace('\n', '\r')
                    if '\r' in processed:
                        segments = processed.split('\r')
                        for idx, segment in enumerate(segments):
                            if segment:
                                if _ws_init_done:
                                    if segment in ('\x7f', '\x08') and _ws_input_buf:
                                        _ws_input_buf.pop()
                                    else:
                                        _ws_input_buf.append(segment)
                                pty.write(segment)
                            if idx < len(segments) - 1:
                                _dispatch_ws_enter()
                        continue
                        # ── Enter 키: 완성된 명령을 자율 에이전트로 라우팅 ──────────
                        if _ws_init_done and _ws_input_buf:
                            completed_line = ''.join(_ws_input_buf)
                            _ws_input_buf.clear()
                            # 백스페이스(\x7f, \x08) 처리: 실제 표시 문자열 복원
                            import re as _re
                            cleaned = _re.sub(r'[\x00-\x1f\x7f-\x9f]', '', completed_line).strip()
                            if cleaned:
                                _dispatch_to_agent(cleaned)
                        # Gemini/Codex submits require a double Enter in the
                        # underlying TUI. Normalize that here so direct XTerm
                        # typing and the textarea sender behave identically.
                        pty.write("\r\r" if agent in ("gemini", "codex") else "\r")
                    else:
                        # ── 일반 문자: 버퍼에 누적 + PTY로 전달 ─────────────────────
                        processed = message.replace('\r\n', '\r').replace('\n', '\r')
                        if _ws_init_done:
                            # 백스페이스(\x7f): 버퍼의 마지막 문자 제거
                            if message in ('\x7f', '\x08') and _ws_input_buf:
                                _ws_input_buf.pop()
                            elif '\r' not in processed:
                                _ws_input_buf.append(message)
                        pty.write(processed)
            except Exception as e:
                print(f"[WS ERROR] {e}")
                break

    task1 = asyncio.create_task(read_from_pty())
    task2 = asyncio.create_task(read_from_ws())
    
    done, pending = await asyncio.wait([task1, task2], return_when=asyncio.FIRST_COMPLETED)
    for task in pending:
        task.cancel()

    # ── [세션 종료/강제종료 감지] ──────────────────────────────────────────
    # task1(PTY read) 이 먼저 완료 → 프로세스 자체가 종료됨 (정상 or 강제)
    #   → gemini_hook.py SessionEnd 훅이 실행됐으면 정상 종료
    #   → SessionEnd가 없으면 강제 종료(Ctrl+C, 프로세스 킬 등) 가능성
    # task2(WS read) 이 먼저 완료 → 브라우저/WebSocket이 먼저 닫힘
    if agent:
        try:
            from src.db_helper import insert_log as _db_insert_log
            if task1 in done:
                # PTY 프로세스 종료 — SessionEnd 훅이 없었다면 강제 종료
                exit_msg = f"─── {agent.upper()} 프로세스 종료 감지 (SessionEnd 훅 미실행 시 강제종료) ───"
            else:
                # WebSocket이 먼저 닫힘 — 브라우저 새로고침 or 탭 닫기
                exit_msg = f"─── {agent.upper()} 연결 종료 (WebSocket 닫힘) ───"
            _db_insert_log(
                session_id=f"pty_end_{session_id}_{datetime.now().strftime('%H%M%S')}",
                terminal_id="PTY_TERMINAL",
                agent=agent.capitalize(),
                trigger_msg=exit_msg,
                project="hive",
                status="success"
            )
        except Exception as _e:
            print(f"[PTY] 세션 종료 로그 실패: {_e}")

    try:
        pty.terminate(force=True)
    except:
        pass
    if session_id in pty_sessions:
        del pty_sessions[session_id]
    pty_output_buffers.pop(session_id, None)
    pty_output_seq.pop(session_id, None)

def _cleanup_all_pty_sessions():
    """X 버튼 또는 시그널 종료 시 모든 PTY 자식 프로세스를 강제 종료합니다.

    os._exit(0)은 Python 프로세스만 종료하고 자식 프로세스(Claude/Gemini/Codex 터미널)는
    좀비로 남깁니다. 이 함수를 먼저 호출해 모든 PTY 세션을 명시적으로 kill합니다.
    atexit + SIGTERM/SIGBREAK 핸들러 양쪽에 등록하여 어떤 종료 경로에서도 실행됩니다.
    """
    for sid, info in list(pty_sessions.items()):
        try:
            info['pty'].terminate(force=True)
            print(f"[cleanup] PTY 세션 종료: {sid}")
        except Exception as e:
            print(f"[cleanup] PTY 종료 실패 ({sid}): {e}")
    pty_sessions.clear()
    pty_output_buffers.clear()
    pty_output_seq.clear()


# 워치독/Discord/힐데몬 등 서버가 직접 spawn한 서브프로세스 참조 목록
# — X 버튼 종료 시 이 목록을 순회하여 모두 taskkill로 강제 종료
_child_procs: list = []


def _cleanup_child_procs():
    """_child_procs 목록에 등록된 모든 서브프로세스를 강제 종료합니다.

    Windows 환경에서 부모 프로세스가 os._exit(0)으로 종료돼도
    자식 프로세스(hive_watchdog, heal_daemon, discord_bridge 등)는
    자동으로 죽지 않아 좀비로 남습니다.
    'taskkill /F /T /PID'로 프로세스 트리 전체를 강제 종료합니다.
    """
    for proc in list(_child_procs):
        if proc is None:
            continue
        try:
            if proc.poll() is not None:
                # 이미 종료된 프로세스는 건너뜀
                continue
            if os.name == 'nt':
                # /F: 강제, /T: 자식 트리 포함
                subprocess.call(
                    ['taskkill', '/F', '/T', '/PID', str(proc.pid)],
                    creationflags=getattr(subprocess, 'CREATE_NO_WINDOW', 0x08000000),
                )
            else:
                import signal as _sig
                try:
                    os.killpg(os.getpgid(proc.pid), _sig.SIGTERM)
                except Exception:
                    proc.kill()
            print(f"[cleanup] 자식 프로세스 종료: PID {proc.pid}")
        except Exception as e:
            print(f"[cleanup] 자식 프로세스 종료 실패 (PID {getattr(proc, 'pid', '?')}): {e}")
    _child_procs.clear()


# ── atexit 등록 — 정상 종료(sys.exit, return from __main__)에도 PTY + 자식 프로세스 정리 보장 ──
import atexit, signal as _signal
atexit.register(_cleanup_all_pty_sessions)
atexit.register(_cleanup_child_procs)

def _signal_exit_handler(sig, frame):
    """SIGTERM / SIGBREAK(Ctrl+Break) 수신 시 PTY + 자식 프로세스 정리 후 즉시 종료."""
    print(f"[*] 시그널 {sig} 수신 — PTY 및 자식 프로세스 정리 후 종료합니다.")
    _cleanup_all_pty_sessions()
    _cleanup_child_procs()
    os._exit(0)

_signal.signal(_signal.SIGTERM, _signal_exit_handler)
try:
    # Windows 전용 Ctrl+Break 시그널 처리 (SIGBREAK = 21)
    _signal.signal(_signal.SIGBREAK, _signal_exit_handler)
except (AttributeError, OSError):
    pass  # 비-Windows 환경에서는 SIGBREAK 없음


# 포트 설정: 9000(HTTP) / 9001(WS) — 충돌 시 빈 포트 자동 탐색 (최대 20개)
# 9000은 개발/모니터링 도구 관례 포트 (사용자 지정)
def _find_free_port(start: int, max_tries: int = 20) -> int:
    import socket
    for port in range(start, start + max_tries):
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
            try:
                s.bind(('0.0.0.0', port))
                return port
            except OSError:
                continue
    return start  # 실패 시 원래 포트 반환 (에러는 서버 시작 시 처리)

HTTP_PORT = _find_free_port(9000)          # HTTP 포트: 9000 시작 (충돌 시 다음 포트 자동 탐색)
WS_PORT = _find_free_port(HTTP_PORT + 1)  # WebSocket 포트: HTTP+1 기반 탐색 (독립 탐색 시 동일 포트 충돌 버그 수정)

async def run_ws_server():
    try:
        async with websockets.serve(pty_handler, "0.0.0.0", WS_PORT):
            print(f"WebSocket PTY Server started on port {WS_PORT}")
            await asyncio.Future()
    except OSError:
        print(f"WebSocket Server is already running on port {WS_PORT}")

def start_ws_server():
    try:
        asyncio.run(run_ws_server())
    except Exception as e:
        print(f"WebSockets Server Error: {e}")

def open_app_window(url):
    """GUI 실행 실패 시 기본 브라우저로 대시보드를 엽니다."""
    import webbrowser
    print(f"[*] GUI 창을 띄울 수 없어 브라우저로 연결합니다: {url}")
    webbrowser.open(url)

if __name__ == '__main__':
    print(f"Vibe Coding {__version__}")

    # ── 배포 버전: PostgreSQL 자동 초기화 및 시작 ─────────────────────────────
    # installer가 {app}\pgsql\ 에 설치한 바이너리를 사용하여 pgdata 초기화 + 서버 기동.
    # 개발 버전에서는 이미 pg_manager.py가 수동으로 관리하므로 frozen 모드에서만 실행.
    if getattr(sys, 'frozen', False):
        ensure_postgres_running()

    # ── 프로젝트별 다중 인스턴스 슬롯 락 ────────────────────────────────────
    # 아이콘 클릭할 때마다 새 창이 열리고, 최대 4개까지 동시 실행 가능.
    # 같은 프로젝트라도 슬롯(0~3)이 남아 있으면 추가 실행 허용.
    # PROJECT_ROOT 경로 해시 기반으로 슬롯 포트 범위를 결정한다:
    #   슬롯 0: 19001 + (hash%96)*4 + 0
    #   슬롯 1: 19001 + (hash%96)*4 + 1  (최대 19001+95*4+3 = 19384 이내)
    _proj_hash    = hash(str(PROJECT_ROOT)) & 0xFFFF      # 경로 해시 (양수 고정)
    _BASE_PORT    = 19001 + (_proj_hash % 96) * 4         # 프로젝트별 슬롯 시작 포트 (4개 연속 확보)
    _MAX_INSTANCES = 4                                     # 최대 동시 실행 수
    _proj_id      = f"{_proj_hash:04x}"                   # 타이틀용 짧은 hex ID

    # 빈 슬롯(포트)을 순서대로 시도하여 첫 번째 빈 자리를 점유
    _lock_sock = None
    _instance_slot = -1
    for _slot in range(_MAX_INSTANCES):
        _try_port = _BASE_PORT + _slot
        try:
            _sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            _sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 0)
            _sock.bind(('127.0.0.1', _try_port))
            _lock_sock = _sock
            _instance_slot = _slot
            break  # 슬롯 확보 성공 — 루프 종료
        except OSError:
            continue  # 이미 사용 중인 슬롯 → 다음 슬롯 시도

    if _instance_slot == -1:
        # 모든 슬롯이 점유됨 — 최대 인스턴스 수 초과
        print(f"[!] 최대 {_MAX_INSTANCES}개 인스턴스가 이미 실행 중입니다 (프로젝트: {PROJECT_ROOT.name}). 종료합니다.")
        os._exit(0)

    print(f"[*] 인스턴스 슬롯 {_instance_slot + 1}/{_MAX_INSTANCES} 점유 (포트 {_BASE_PORT + _instance_slot})")

    if os.name == 'nt':
        try:
            import ctypes
            import ctypes.wintypes

            # 작업표시줄 AppUserModelID — 같은 앱으로 그룹화
            myappid = f'com.vibe.coding.{__version__}'
            ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID(myappid)
        except: pass

    # 서버 시작 시 상황판 창 플래그 초기화 (새 세션에서 창이 다시 열릴 수 있도록)
    try:
        _win_flag = DATA_DIR / '.monitor_opened'
        if _win_flag.exists():
            _win_flag.unlink()
    except Exception:
        pass

    # --- Auto-update check (non-blocking) ---
    if getattr(sys, 'frozen', False):
        try:
            from updater import check_and_update
            # 시작 즉시 1회 체크 + 이후 1시간마다 반복
            # → 앱 사용 중에도 새 버전 배포되면 배너로 알림
            def _update_loop():
                while True:
                    try:
                        # 이미 다운로드 완료 상태면 재다운로드 건너뜀
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
                    time.sleep(600)  # 10분 간격

            threading.Thread(target=_update_loop, daemon=True).start()
        except ImportError:
            print("[!] Updater module not found, skipping update check.")

    # 1. 백그라운드 스레드 시작
    threading.Thread(target=start_ws_server, daemon=True).start()

    # 자율 에이전트 브로드캐스트 워커: cli_agent 큐 → 다중 SSE 클라이언트 팬아웃
    threading.Thread(target=_agent_broadcast_worker, daemon=True,
                     name='AgentBroadcast').start()
    
    # 실시간 파일 감시 시작
    start_fs_watcher(PROJECT_ROOT)

    MemoryWatcher().start()  # 에이전트 메모리 파일 → shared_memory.db 자동 동기화
    
    # 하이브 워치독(Watchdog) 엔진 실행
    # --data-dir 인자로 실제 DATA_DIR 전달 — 설치 버전에서 경로 오탐 방지
    def run_watchdog():
        watchdog_script = SCRIPTS_DIR / "hive_watchdog.py"
        if watchdog_script.exists():
            # [버그수정] frozen(EXE) 모드에서 sys.executable = EXE 자신 → subprocess로 실행 시
            # EXE가 무한 재귀 생성되는 버그 수정.
            # _python_runner_cmds()로 실제 Python 인터프리터를 탐색하여 사용.
            _python_cmds = _python_runner_cmds()
            if not _python_cmds:
                print("[!] run_watchdog: Python 인터프리터를 찾을 수 없어 워치독 스킵")
                return
            python_exe = _python_cmds[0]
            # CREATE_NO_WINDOW: 워치독 데몬 시작 시 콘솔 창 표시 방지
            # 반환된 Popen 핸들을 _child_procs에 등록 → X 버튼 종료 시 일괄 kill
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
    threading.Thread(target=run_watchdog, daemon=True).start()

    # Discord 브릿지 자동 시작: .env에 DISCORD_BOT_TOKEN이 설정된 경우에만 실행
    # 터미널 #1~8 Discord 채널에서 지시 입력 → cli_agent.py 자동 실행 (원격 자율 에이전트)
    def run_discord_bridge():
        discord_script = SCRIPTS_DIR / "discord_bridge.py"
        env_file = PROJECT_ROOT / ".env"
        discord_log = DATA_DIR / "discord_bridge.log"
        if not discord_script.exists():
            return
        # .env 파일에 DISCORD_BOT_TOKEN이 있을 때만 시작
        try:
            env_content = env_file.read_text(encoding='utf-8') if env_file.exists() else ""
            if 'DISCORD_BOT_TOKEN' not in env_content:
                return
        except Exception:
            return
        # [버그수정] frozen 모드에서 sys.executable = EXE → 실제 Python 인터프리터 탐색
        _python_cmds = _python_runner_cmds()
        if not _python_cmds:
            print("[!] run_discord_bridge: Python 인터프리터를 찾을 수 없어 Discord 브릿지 스킵")
            return
        python_exe = _python_cmds[0]
        child_env = os.environ.copy()
        child_env['VIBE_SERVER_PORT'] = str(HTTP_PORT)
        discord_log.parent.mkdir(parents=True, exist_ok=True)
        log_handle = open(discord_log, 'a', encoding='utf-8')
        # Discord 브릿지 Popen 핸들을 _child_procs에 등록 → X 버튼 종료 시 일괄 kill
        proc = subprocess.Popen(
            [python_exe, str(discord_script)],
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
        print("[*] Discord Bridge 자동 시작됨")
    threading.Thread(target=run_discord_bridge, daemon=True).start()

    # 자기치유 데몬 자동 시작: 5분마다 task_logs 패턴 분석 → 반복 오류 자동 치유
    def run_heal_daemon():
        heal_script = SCRIPTS_DIR / "heal_daemon.py"
        if heal_script.exists():
            # [버그수정] frozen 모드에서 sys.executable = EXE → 실제 Python 인터프리터 탐색
            _python_cmds = _python_runner_cmds()
            if not _python_cmds:
                print("[!] run_heal_daemon: Python 인터프리터를 찾을 수 없어 힐데몬 스킵")
                return
            python_exe = _python_cmds[0]
            # 힐데몬 Popen 핸들을 _child_procs에 등록 → X 버튼 종료 시 일괄 kill
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
    threading.Thread(target=run_heal_daemon, daemon=True).start()

    # 2. HTTP 서버 시작 (포트 충돌 시 자동 탐색된 포트로 재시도)
    try:
        server = ThreadedHTTPServer(('0.0.0.0', HTTP_PORT), SSEHandler)
        print(f"[*] Server running on http://localhost:{HTTP_PORT}")
        threading.Thread(target=server.serve_forever, daemon=True).start()
        # 브로드캐스트 워커는 HTTP 서버 시작 전(4097~4099)에서 이미 시작됨 — 중복 시작 금지
    except Exception as e:
        print(f"[!] Server Start Error on port {HTTP_PORT}: {e}")
        import sys as _sys; _sys.exit(1)

    # 3. GUI 창 띄우기 (최우선 순위)
    try:
        import webview
        # 아이콘 경로를 실행 환경에 맞게 동적으로 결정 (D: 하드코딩 제거)
        if getattr(sys, 'frozen', False):
            # PyInstaller 빌드 시 내부 리소스 경로
            official_icon = os.path.join(sys._MEIPASS, "bin", "app_icon.ico")
            if not os.path.exists(official_icon):
                official_icon = os.path.join(sys._MEIPASS, "bin", "vibe_final.ico")
        else:
            # 개발 환경 경로
            official_icon = os.path.join(os.path.dirname(__file__), "bin", "vibe_final.ico")
            if not os.path.exists(official_icon):
                 official_icon = os.path.join(os.path.dirname(__file__), "bin", "app_icon.ico")
        
        # 윈도우 하단바 아이콘 강제 교체 함수 (Win32 API)
        def force_win32_icon():
            if os.name == 'nt' and os.path.exists(official_icon):
                try:
                    import ctypes
                    from ctypes import wintypes
                    import time
                    
                    # 창이 생성될 때까지 잠시 대기
                    time.sleep(2)
                    
                    # 바이브 코딩 창 핸들 찾기 — 프로젝트명 포함 제목으로 검색
                    hwnd = ctypes.windll.user32.FindWindowW(None, f"바이브 코딩 [{PROJECT_ROOT.name}]")
                    if hwnd:
                        # 아이콘 파일 로드 (유효한 경로인지 재확인)
                        hicon = ctypes.windll.user32.LoadImageW(
                            None, official_icon, 1, 0, 0, 0x00000010 | 0x00000040
                        )
                        if hicon:
                            # 큰 아이콘 (작업표시줄용)
                            ctypes.windll.user32.SendMessageW(hwnd, 0x80, 1, hicon)
                            # 작은 아이콘 (창 제목줄용)
                            ctypes.windll.user32.SendMessageW(hwnd, 0x80, 0, hicon)
                            print(f"[*] Win32 Taskbar Icon Forced: {official_icon}")
                except Exception as e:
                    print(f"[!] Win32 Icon Fix Error: {e}")

        print(f"[*] Launching Desktop Window with Official Icon...")
        # 창 제목에 프로젝트명 포함 — 다중 인스턴스 실행 시 작업표시줄에서 구분 가능
        main_window = webview.create_window(f'바이브 코딩 [{PROJECT_ROOT.name}]', f"http://localhost:{HTTP_PORT}",
                              width=1400, height=900)
        
        # 아이콘 교체 스레드 별도 실행
        threading.Thread(target=force_win32_icon, daemon=True).start()
        
        webview.start()
        # 창 닫힘 = 서버 소켓 정상 종료 후 프로세스 종료
        # os._exit()는 소켓을 강제 종료 → 포트 TIME_WAIT 잔류 원인
        # server.shutdown() + server_close()로 포트를 먼저 해제한 뒤 종료
        # X 버튼으로 창이 닫힘 → PTY 자식 프로세스 먼저 kill → HTTP 서버 소켓 해제 → 프로세스 종료
        print("[*] GUI 창이 닫혔습니다. 좀비 프로세스 방지 — 모든 자식 프로세스 정리 중...")
        _cleanup_all_pty_sessions()          # Claude/Gemini/Codex 터미널 자식 프로세스 종료
        _cleanup_child_procs()               # hive_watchdog / heal_daemon / discord_bridge 종료
        try:
            server.shutdown()                # HTTP 요청 처리 스레드 정지
            server.server_close()            # 포트 소켓 해제 (TIME_WAIT 방지)
        except Exception:
            pass
        print("[*] 정리 완료 — 프로세스를 종료합니다.")
        os._exit(0)
    except Exception as e:
        print(f"[!] GUI Error: {e}")
        open_app_window(f"http://localhost:{HTTP_PORT}")
        # 브라우저 모드에서는 Ctrl+C(SIGINT)로 종료 — KeyboardInterrupt 잡아서 정리 후 종료
        try:
            while True:
                time.sleep(1)
        except KeyboardInterrupt:
            print("[*] Ctrl+C 감지 — PTY 세션 및 서버 정리 후 종료합니다.")
            _cleanup_all_pty_sessions()
            _cleanup_child_procs()           # 좀비 방지: watchdog/heal/discord 종료
            try:
                server.shutdown()
                server.server_close()
            except Exception:
                pass
            os._exit(0)
