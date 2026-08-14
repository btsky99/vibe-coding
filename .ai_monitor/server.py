"""
FILE: .ai_monitor/server.py
DESCRIPTION: 하이브 마인드 중앙 통제 서버 — 에이전트 간 통신 중계, 상태 모니터링, 데이터 영속성 관리.

REVISION HISTORY:
- 2026-07-28 Codex: Route first-run automatic dependency installation.
- 2026-07-28 Codex: Wire the existing Setup Doctor status endpoint into GET routing.
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
#   - daemon subprocess: sys.executable → _python_runner_cmds()[0]
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
import api.update_api as update_api
import api.install_api as install_api
import api.events_api as events_api
import api.logs_api as logs_api
import api.static_api as static_api
import api.heal_api as heal_api
import api.locks_api as locks_api
import api.projects_api as projects_api
import api.message_api as message_api
import api.launch_api as launch_api
import api.commands_api as commands_api
import api.config_api as config_api
import api.daemons_api as daemons_api
import api.fs_dialog_api as fs_dialog_api
import api.dashboard_api as dashboard_api
import api.setup_api as setup_api
import api.office_launch_api as office_launch_api
import api.hive_ingest_api as hive_ingest_api
import api.screenshot_api as screenshot_api
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

# [플랫폼] 실행파일 확장자는 Windows에만 붙는다. macOS/Linux는 확장자 없음 —
# `.exe`를 하드코딩하면 번들 PG가 있어도 전부 "없음"으로 판정돼 DB가 안 뜬다.
_EXE = ".exe" if os.name == "nt" else ""
PG_BIN     = _PG_DIR / "bin" / f"psql{_EXE}"
PG_CTL_BIN = _PG_DIR / "bin" / f"pg_ctl{_EXE}"
INITDB_BIN = _PG_DIR / "bin" / f"initdb{_EXE}"
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
# [R14] _get_pg_conn/_return_pg_conn 얇은 위임 제거 — run_pg_sql/csv를 pg_base로 이관하며
#   유일 소비처가 사라져 죽은 코드가 됨. 외부(office_api/pg_tasks)는 pg_store의 동명 함수를
#   직접 import하므로 영향 없음.

# DB 데이터: %APPDATA%\VibeCoding\pgdata (배포/개발 모두 동일)
# [2026-04-05 Claude] 개발 모드에서 소스 트리 내 data/ 사용 시 PG 버전 불일치 문제 발생
# → 배포/개발 모두 %APPDATA% 경로로 통일하여 바이너리 업그레이드 시 충돌 방지
# [플랫폼] APPDATA는 Windows 전용 — 맥에서 os.getenv('APPDATA','')가 ''가 되면
# Path('') / ... 는 **상대경로** "VibeCoding/pgdata"가 되어 cwd에 DB가 생긴다
# (앱을 어디서 실행했느냐에 따라 DB가 갈리는 최악의 형태). OS별 표준 위치로 분기.
if os.name == 'nt':
    _PG_DATA_DIR = Path(os.getenv('APPDATA', '')) / "VibeCoding" / "pgdata"
elif sys.platform == 'darwin':
    _PG_DATA_DIR = Path.home() / "Library" / "Application Support" / "VibeCoding" / "pgdata"
else:
    _PG_DATA_DIR = Path.home() / ".vibe-coding" / "pgdata"


# ── PG 런타임은 infra/postgres_runtime.py로 이관 (단계 8b) ────────────────
# [2026-04-21] server.py L230~536 (ensure_postgres_running + _init_project_db)
# 블록 분리. PG_PORT/PG_PROJECT_DB 글로벌 mutation은 caller 래퍼가 담당.
from infra import postgres_runtime as _postgres_runtime
from infra import proc as _proc  # [표준] 콘솔 숨김 subprocess 래퍼 — 인라인 CREATE_NO_WINDOW 금지


def ensure_postgres_running() -> None:
    """PG 기동 + 공용 스키마 초기화. PG_PORT 글로벌을 갱신한다."""
    global PG_PORT
    PG_PORT = _postgres_runtime.start_server(
        PG_CTL_BIN, INITDB_BIN, _PG_DATA_DIR, PG_PORT
    )
    os.environ['VIBE_PG_PORT'] = str(PG_PORT)
    # [R14 포트 이중전역 통합] 확정 포트를 pg_base 전역에 push — set_project_db(DB)와 대칭.
    #   이걸 빼면 psycopg2 풀/psql 폴백이 stale import-time 포트(5433)를 써서, 동적 폴백
    #   발동 환경에서만 터지는 잠복 연결버그. 아래 run_pg_sql(스키마 초기화) 호출 전에 동기화.
    _pg_store_mod.set_pg_port(PG_PORT)
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


def _switch_project(path: str) -> dict:
    """실행 중 프로젝트를 재시작 없이 전환한다(라이브 스위치).

    [WHY] 부팅 시 1회 고정되던 활성 프로젝트(DB 커넥션/PROJECT_ROOT/UNRESOLVED 플래그)를
      폴더 선택 즉시 재초기화. 기존엔 폴더를 골라도 last_path만 저장되고 서버는 옛 프로젝트를
      계속 봐서 패널이 비고 배너가 안 사라지는 사고(2026-07-19).
    [불변식] DB 전환은 set_project_db가 단일 _pg_conn + db-키잉된 풀을 모두 새 DB로 유도하므로
      교차오염 없음. reset_schema_cache→ensure_schema로 새 DB 스키마 보장.
    [롤백] 전환 중 실패하면 이전 프로젝트로 되돌린다 — 반쪽 상태로 앱이 불능이 되지 않게.
    반환: {ok, project_id} | {ok:false, error}.
    """
    global PROJECT_ROOT, PROJECT_CONTEXT_UNRESOLVED, _FS_OBSERVER
    from src.pg_store import reset_schema_cache as _reset_schema_cache
    p = Path(str(path).replace('\\', '/'))
    if not p.is_dir():
        return {'ok': False, 'error': f'존재하지 않는 폴더: {path}'}
    prev_root = PROJECT_ROOT
    prev_id = _current_project_id()
    try:
        # ① last_path + projects.json MRU 저장 (다음 부팅에도 유지)
        _norm = str(p).replace('\\', '/')
        cfg = {}
        if CONFIG_FILE.exists():
            try:
                cfg = json.loads(CONFIG_FILE.read_text(encoding='utf-8'))
            except Exception:
                cfg = {}
        cfg['last_path'] = _norm
        CONFIG_FILE.write_text(json.dumps(cfg, ensure_ascii=False, indent=2), encoding='utf-8')
        try:
            _projs = json.loads(PROJECTS_FILE.read_text(encoding='utf-8')) if PROJECTS_FILE.exists() else []
        except Exception:
            _projs = []
        if _norm in _projs:
            _projs.remove(_norm)
        _projs.insert(0, _norm)
        PROJECTS_FILE.write_text(json.dumps(_projs[:20], ensure_ascii=False, indent=2), encoding='utf-8')

        # ② 새 슬러그 확정 — last_path 저장 후라 _current_project_id()가 새 값을 돌려준다.
        PROJECT_ROOT = p
        new_id = _current_project_id()

        # ③ DB 전환 + 스키마 보장 (커넥션은 set_project_db가 폐기→재연결 유도)
        _init_project_db(new_id)
        _reset_schema_cache()
        ensure_schema(DATA_DIR)

        # ④ 배너 해제 — 명시적 선택은 마커 유무와 무관하게 '해석됨'으로 본다.
        PROJECT_CONTEXT_UNRESOLVED = False

        # ⑤ fs 감시 재지정 (best-effort — 실패해도 전환 자체는 성공 처리)
        try:
            if _FS_OBSERVER is not None:
                _FS_OBSERVER.stop()
        except Exception as _e:
            print(f'[switch] fs 옵저버 정지 실패(무시): {_e}')
        try:
            start_fs_watcher(str(p))
        except Exception as _e:
            print(f'[switch] fs 옵저버 재시작 실패(무시): {_e}')

        print(f'[switch] 프로젝트 라이브 전환: {prev_id} → {new_id} ({_norm})')
        return {'ok': True, 'project_id': new_id, 'path': _norm}
    except Exception as e:
        # 롤백 — 이전 프로젝트 DB로 복구
        try:
            PROJECT_ROOT = prev_root
            _init_project_db(prev_id)
            _reset_schema_cache()
            ensure_schema(DATA_DIR)
        except Exception as _re:
            print(f'[switch] 롤백도 실패(치명): {_re}')
        return {'ok': False, 'error': f'전환 실패(이전 프로젝트로 롤백): {e}'}


# [이관 R14] run_pg_sql/csv 본문을 pg_base로 이동 — DB I/O는 데이터 계층에 집중
#   (architecture.md "DB 쓰기 함수는 pg_store에 집중"). server 측은 얇은 재노출만 유지 →
#   호출부 무변경(from server import run_pg_sql, wrapper 인자 주입 모두 그대로 동작).
#   db=None 기본은 pg_base.PG_DB — _init_project_db가 set_project_db로 PG_PROJECT_DB와
#   동일값 동기화하므로 이관 전(PG_PROJECT_DB 기본)과 동작 동일.
run_pg_sql = _pg_store_mod.run_pg_sql

_pgmq_available: bool | None = None  # pgmq 확장 존재 여부 캐시 — 한 번 확인 후 재확인 안 함

def log_to_pg(agent: str, terminal_id: str, task: str, status: str = "success", project_id: str = None):
    """pg_logs 테이블에 로그 기록 — parameterized query로 SQL 인젝션 방지.

    [크로스 프로젝트 경계] 호출 세션이 project_id를 넘기면 그것으로 태깅한다(예: ons 터미널이
    이 vibe-coding 서버로 로그를 보내도 'D--ons'로 기록 → 회상/컨텍스트가 project_id로 필터해
    서로 안 섞임). 미지정 시 서버 자기 PROJECT_ID로 폴백 — 단일 프로젝트 실행 시 기존 동작 불변."""
    _pid = project_id or PROJECT_ID
    run_pg_sql(
        "INSERT INTO pg_logs (agent, terminal_id, task, status, project_id) VALUES (%s, %s, %s, %s, %s);",
        (agent, terminal_id, task, status, _pid)
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

# [이관 R14] pg_base.run_pg_sql_csv 재노출 (본문 이동, 위 run_pg_sql과 동일 규칙).
run_pg_sql_csv = _pg_store_mod.run_pg_sql_csv

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
# 프로젝트 루트 마커 탐색 + frozen PROJECT_ROOT 해석은 infra/project_context.py로 분리
# (2026-07-06, Phase 2 Task 13 / R15). [제약] 바로 아래 frozen 초기화 블록에서 호출되므로
# infra가 sys.path에 오른 뒤(위 postgres_runtime import 시점)여야 함 — 정의 순서 이동 금지.
from infra.project_context import (
    resolve_frozen_project_root as _resolve_frozen_project_root,
)


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
    # [WHY 이름은 그대로 두는가] fs_dialog_api 가 이 callable 을 주입받아 쓴다. 내부 구현만
    #   네이티브 우선으로 바뀌었고(runtime.open_folder_dialog), 서브프로세스는 폴백이다.
    # EXE 빌드에서 sys.executable은 vibe-coding.exe → 폴백용 실제 Python을 인자로 전달
    return _runtime.open_folder_dialog(_python_runner_cmds()[0])


def _open_file_dialog_subprocess() -> str:
    # [WHY] LAN 파일 전송 '찾아보기'용 — 폴더가 아닌 파일 1개 선택. EXE에선 실제 Python 전달.
    return _runtime.open_file_dialog_subprocess(_python_runner_cmds()[0])

# [제거됨 2026-03-22] websockets import → Node.js ws 라이브러리로 대체

# 전역 상태 관리
main_window = None  # pywebview 창 핸들 — main()에서 초기화, SSEHandler에서 참조
THOUGHT_LOGS = [] # AI 사고 과정 로그 (최근 50개 유지)
# THOUGHT_CLIENTS는 아래(라인 658 근처)에서 한 번만 선언 — 중복 선언 제거

def _load_task_logs_into_thoughts():
    # 본체는 infra/lifecycle.py로 분리 (2026-07-06, Phase 2 Task 13 / R15).
    # [제약] early_data_dir는 반드시 server.py 위치 기준 ./data — 원본이 __file__로 계산했고
    # lifecycle.py의 __file__는 infra/ 라 경로가 오염되므로 여기(server.py)서 계산해 주입.
    _lifecycle.load_task_logs_into_thoughts(
        THOUGHT_LOGS, Path(__file__).resolve().parent / 'data'
    )

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


# [WHY 전역 보관] 라이브 프로젝트 전환(_switch_project) 시 옛 루트를 감시하던 옵저버를
#   멈추고 새 루트로 재시작해야 한다. app_boot는 반환값을 버려서 핸들이 유실되므로
#   여기서 모듈 전역에 잡아둔다(전환 재지정 전용).
_FS_OBSERVER = None


def start_fs_watcher(root_path):
    global _FS_OBSERVER
    _FS_OBSERVER = _fs_watcher.start_fs_watcher(root_path, FS_CLIENTS, _SSE_LOCK, DATA_DIR)
    return _FS_OBSERVER
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
# [격리 2026-08-01] VIBE_DATA_DIR로 강제 지정 가능.
#   [WHY] smoke_test는 frozen EXE를 띄우므로 **설치본과 같은 %APPDATA%\VibeCoding**을 썼다.
#   그 결과 테스트가 설치본의 soft_update_ready.json / orchestrator.pid /
#   운영 PID 파일을 덮어썼다. 테스트 후 설치본의 daemon 생존 판정이 오염될 수 있었다.
#   포트는 VIBE_PORT_BASE로 이미 격리했으나 데이터 디렉토리는 공유라 반쪽 격리였다.
#   [실측] 2026-08-01 smoke 실행이 설치본 데이터 디렉토리에 15:36/15:40 흔적을 남겨,
#   설치본이 그 시각에 업데이트를 확인한 것처럼 보이는 오진까지 유발했다.
_data_override = os.environ.get('VIBE_DATA_DIR', '').strip()
if _data_override:
    DATA_DIR = Path(_data_override)
elif getattr(sys, 'frozen', False):
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

# [R14] STATIC_DIR 초기 대입은 906행으로 일원화 — 여기(구 697) 중복 대입은 698~905 사이
#   미참조로 906이 즉시 덮어쓰던 죽은 코드라 제거. 906만이 존재검증+alt_dist 폴백을 가진 canonical.
# [은퇴 2026-07-18] SESSIONS_FILE(sessions.jsonl) 정의 제거 — tasks_api write-only 미러
#   철거로 미참조. 로깅은 pg_logs 단일 경로.
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

# 활성 프로젝트 컨텍스트 고정은 infra/project_context.py로 분리 (2026-07-06, Phase 2 Task 13 / R15).
# [불변식] PROJECT_CONTEXT_UNRESOLVED 전역은 server.py가 소유 — infra는 bool(unresolved)만
# 반환하고, 세팅은 caller가 한다(다른 모듈이 server 전역을 global로 못 씀).
from infra.project_context import persist_active_project_context as _persist_active_project_context

if getattr(sys, 'frozen', False):
    PROJECT_CONTEXT_UNRESOLVED = _persist_active_project_context(
        PROJECT_ROOT, CONFIG_FILE, PROJECTS_FILE
    )

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


# 세션 파서 2종은 infra/session_parse.py로 분리 (2026-07-06, Phase 2 Task 12 / R13).
# [WHY] 순수 함수(외부 전역 캡처 전무, Path 인자만)라 모듈 전역 별칭으로 재노출 —
#       호출부(_g_hive → hive_api.handle_get 주입)를 건드리지 않아 diff 최소·롤백 안전.
from infra import session_parse as _session_parse
_parse_session_tail = _session_parse.parse_session_tail
_parse_antigravity_session = _session_parse.parse_antigravity_session


# ── .env 파일 읽기/쓰기 유틸 ─────────────────────────────────────────────────

# ─────────────────────────────────────────────────────────────────────────────

# 정적 파일 경로
# [WHY 체크아웃을 먼저 보나 — 2026-08-07] frozen에서 BASE_DIR은 _MEIPASS(=EXE에 구워진 사본)다.
#   그것만 쓰면 **화면 변경이 경량 소스 업데이트로 절대 전달되지 않는다** — .py는 체크아웃에서
#   새것을 읽는데 UI만 EXE 안의 옛것이라, UI를 고칠 때마다 설치본 풀빌드가 강제됐다.
#   server.py는 boot.py가 체크아웃에서 runpy 하므로 __file__이 곧 체크아웃 경로다. 이를 이용해
#   체크아웃 dist를 우선하고, 없거나 깨졌으면 번들 사본으로 물러난다.
# [불변식] 체크아웃의 .py와 dist는 같은 커밋에서 함께 갱신되므로 항상 서로 정합적이다.
#   (그래서 체크아웃이 EXE보다 옛것이어도 '옛 .py + 옛 dist' 조합이라 깨지지 않는다.)
def _dist_is_usable(d: Path) -> bool:
    """index.html이 있고 그것이 참조하는 번들이 실제로 존재하는지까지 확인한다.

    [WHY 참조까지 보나] 존재 검사만으로는 부족하다 — dist가 커밋 규칙 문제로 반쪽만 들어간
    상태(index.html은 새것, 번들은 없음)가 실제로 있었다. 그대로 서빙하면 화면이 **빈 채로**
    뜨고, 정적 파일 404라 원인 추적이 오래 걸린다. 참조 검증 실패 시 번들 사본으로 물러나면
    최소한 옛 화면이라도 정상 동작한다.
    """
    index = d / "index.html"
    if not index.is_file():
        return False
    try:
        html = index.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return False
    refs = re.findall(r'(?:src|href)="\.?/?(assets/[^"]+)"', html)
    return all((d / r).is_file() for r in refs)


_bundled_dist = (BASE_DIR / "vibe-view" / "dist").resolve()
_checkout_dist = (Path(__file__).resolve().parent / "vibe-view" / "dist").resolve()

STATIC_DIR = _bundled_dist
if _checkout_dist != _bundled_dist and _dist_is_usable(_checkout_dist):
    STATIC_DIR = _checkout_dist
    print(f"[*] 체크아웃 dist 사용(경량 업데이트로 UI 갱신 가능): {STATIC_DIR}")

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
    # 본체는 infra/lifecycle.py로 분리 (2026-07-06, Phase 2 Task 13 / R15).
    # [불변식] AGENT_STATUS(가변 dict)·락·list_agent_status를 동일 identity로 주입 —
    # 사본을 넘기면 대시보드가 조용히 빈 값을 표시한다.
    _lifecycle.restore_agent_status_from_db(AGENT_STATUS, AGENT_STATUS_LOCK, list_agent_status)


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
# [R14] PROJECT_ID는 callee에서 요청 project_id 누락 시의 fallback default — 현재 활성 폴더
#   슬러그(_current_project_id())를 넘겨 폴더 전환 후에도 기본값이 옛 프로젝트로 새지 않게 한다.
def _g_zettel(h, pp):     zettel_api.handle_get(h, pp.path, parse_qs(pp.query), DATA_DIR=DATA_DIR, PROJECT_ID=_current_project_id())
def _g_codegraph(h, pp):  codegraph_api.handle_get(h, pp.path, parse_qs(pp.query), DATA_DIR=DATA_DIR, PROJECT_ID=_current_project_id())
def _g_office(h, pp):     _proxy_to_office_server(h, method='GET')
def _g_tools(h, pp):
    from api import tools_api
    tools_api.handle_get(h, pp.path, parse_qs(pp.query))
def _g_lan(h, pp):
    from api import lan_api
    lan_api.handle_get(h, pp.path, parse_qs(pp.query), DATA_DIR=DATA_DIR, PROJECT_ID=_current_project_id())

def _g_recycle(h, pp):
    from api import recycle_api
    if not recycle_api.handle_get(h, pp.path, parse_qs(pp.query),
                                  PROJECT_ID=_current_project_id()):
        h.send_error(404)

GET_PREFIX_ROUTES = [
    ('/api/git/', _g_git),
    ('/api/agent/', _g_agent),
    ('/api/pty/', _g_pty),
    ('/api/session/recycle', _g_recycle),
    ('/api/experience', _g_experience),
    ('/api/zettel/', _g_zettel),
    ('/api/codegraph/', _g_codegraph),
    ('/api/office/', _g_office),
    ('/api/tools/', _g_tools),
    ('/api/lan/', _g_lan),
]

# GET exact 라우트 테이블 (Phase 2 R1: 파일시스템 다이얼로그 3종)
# [불변식] do_GET에서 exact 먼저 → prefix 나중 조회(POST와 동형). fs_dialog 3종은
#   어떤 GET prefix와도 비충돌(browse-folder/drives/dirs). late-binding으로 전역 주입.
def _g_fs_dialog(h, pp):
    fs_dialog_api.handle_get(h, pp.path, parse_qs(pp.query),
                             open_folder_dialog=_open_folder_dialog_subprocess,
                             open_file_dialog=_open_file_dialog_subprocess)

# GET exact 라우트 (Phase 2 R2: 도구 설치 3종) — install_api로 본문 이전, 전역 헬퍼는 주입.
# [불변식] 전역(_tool_status/_get_tool_install_state/_python_runner_cmds/BASE_DIR/PROJECT_ROOT)은
#   호출 시점 해석(late-binding). install-*-cli 복합조건은 legacy elif 잔류(R9 예정).
def _g_tool_status(h, pp):         install_api.tool_status(h, pp, _tool_status)
def _g_install_tool_status(h, pp): install_api.install_tool_status(h, pp, _get_tool_install_state)
# [WHY 별도] Antigravity는 npm 배포가 없어 install-cli(npm 전용) 튜플에 넣으면 안 된다.
def _g_install_antigravity(h, pp): install_api.install_antigravity(h)
def _g_register_codex(h, pp):      install_api.register_codex_to_ai(h, _python_runner_cmds, BASE_DIR, PROJECT_ROOT)

# GET exact 라우트 (Phase 2 R3: 로그/스트림 3종) — api/logs_api.py로 본문 이전, 전역은 주입.
# [불변식/late-binding] _g_stream은 wrapper 바디에서 PG_PORT/PG_PROJECT_DB를 참조 —
#   동적 포트 폴백 시 global로 갱신된 최신값을 매 호출 재조회한다. 디폴트 인자 바인딩 금지
#   (def _g_stream(h, pp, port=PG_PORT) 하면 테이블 정의 시점 값에 고정되는 버그).
# [구조 유지] logs_api.stream의 psycopg2 직접연결은 풀 미경유 원본 그대로(전환은 별도 작업).
def _g_stream(h, pp):       logs_api.stream(h, PG_PORT, PG_PROJECT_DB, run_pg_sql_csv)
def _g_server_logs(h, pp):  logs_api.server_logs(h, DATA_DIR)
def _g_messages(h, pp):     logs_api.messages(h, get_messages)

# GET exact 라우트 (Phase 2 R4: 도움말/이미지 2종) — api/static_api.py로 본문 이전, 전역은 주입.
# [불변식] docs 경로는 server.py의 Path(__file__).parent/'docs'를 넘긴다(static_api의 __file__은
#   api/ 하위라 경로가 달라짐 — 반드시 주입). _validate_file_path는 late-binding 호출.
# [주의] 정적서빙 serve()는 exact 테이블 등록 금지 — do_GET 최후미 else 폴백으로만 호출한다.
def _g_help(h, pp):       static_api.help_doc(h, pp, Path(__file__).parent / 'docs')
def _g_image_file(h, pp): static_api.image_file(h, pp, _validate_file_path)

# GET exact 라우트 (Phase 2 R5: 에이전트 상태) — api/dashboard_api.py로 본문 이전.
# [불변식] AGENT_STATUS/AGENT_STATUS_LOCK은 wrapper 바디에서 전역 참조 → heartbeat writer와
#   동일 dict identity 주입(사본 금지: 대시보드가 조용히 빈 값 표시). list_agent_status도 late-binding.
def _g_agents(h, pp):
    dashboard_api.list_agents(h, AGENT_STATUS, AGENT_STATUS_LOCK, list_agent_status)

# GET exact 라우트 (Phase 2 R8: 설정/vibe/칸반/메모리 long-tail) — 인라인 로직 모듈 이전 + 순수위임 3종.
# [불변식/late-binding] 아래 wrapper는 런타임에 mutation되는 전역(PROJECT_CONTEXT_UNRESOLVED,
#   GLOBAL_VAULT_DIR, PG_PORT/PG_PROJECT_DB)과 함수(_current_project_id/run_pg_sql_csv/query_rows)를
#   호출 시점에 해석한다 — 디폴트 인자 바인딩 금지(테이블 정의 시점 값 고정 버그).
# [순수위임] vibe 3종(sidebar/notifications/skills)은 원본이 이미 1~3줄 모듈 위임 → 테이블 등록만.
def _g_config(h, pp):
    config_api.handle_get(h, CONFIG_FILE, GLOBAL_VAULT_DIR,
                          PROJECT_CONTEXT_UNRESOLVED, _current_project_id(),
                          _current_project_root())
def _g_daemons(h, pp):             daemons_api.handle_get(h, CONFIG_FILE)
def _g_vibe_sidebar(h, pp):        vibe_api.handle_sidebar_state(h)
def _g_vibe_notifications(h, pp):  vibe_api.handle_notifications(h)
def _g_vibe_skills(h, pp):         vibe_skills_api.handle_get(h, pp.path, parse_qs(pp.query), PROJECT_ROOT)
# [9차 정리 2026-07-16] _g_kanban_activity(/api/kanban/pg-activity) 은퇴 — 소비자였던
#   오케스트레이션 보드(TaskBoardPanel)가 은퇴되어 프론트 호출자 0.
def _g_memory_db_info(h, pp):      memory_api.db_info(h, DATA_DIR, PG_PORT, PG_PROJECT_DB, query_rows)

# GET exact 라우트 (Phase 2 R16: do_GET 잔여 legacy elif 완전 흡수 → 테이블 완성).
# [WHY] do_POST는 이미 exact→prefix→cond 뒤 404 폴백뿐(legacy 없음). do_GET만 elif 11종 잔류라
#   비대칭이었다. 순수위임 6·SSE 3·인라인 3을 모두 wrapper화해 GET_ROUTES로 흡수, do_GET을
#   exact→prefix→cond→(SPA else 폴백)만 남긴다. else 정적 폴백은 테이블 미등록 유지(아래 [불변식]).
# [순수위임 6종] 원본 elif가 이미 1줄 모듈 위임 → wrapper는 인자 주입만.
def _g_projects(h, pp):            projects_api.handle_get(h, PROJECTS_FILE)
def _g_install_skills(h, pp):      install_api.install_skills(h, BASE_DIR, SCRIPTS_DIR, ensure_schema)
def _g_check_update_ready(h, pp):  update_api.check_update_ready(h, DATA_DIR, __version__)
def _g_trigger_update_chk(h, pp):  update_api.trigger_update_check(h, DATA_DIR)
def _g_soft_update_check(h, pp):   update_api.soft_update_check(h, DATA_DIR, _soft_src_dir())
def _g_soft_update_progress(h, pp): update_api.soft_update_progress(h, DATA_DIR)
# [불변식] heal은 전체(global) 집계 — project_id 슬러그 불일치로 0 오도 방지(설치/dev 분기).
def _g_heal_metrics(h, pp):        heal_api.handle_get(h, '')
def _g_setup_status(h, pp):        setup_api.handle_get(h, pp.path, parse_qs(pp.query))

# SSE 실시간 스트리밍 3종 → api/events_api.py.
# [불변식] THOUGHT_LOGS/THOUGHT_CLIENTS/AGENT_CLIENTS/FS_CLIENTS/_SSE_LOCK는 전역 참조로 주입 —
#   POST writer(_p_thoughts_add) 및 fs_watcher/broadcast worker와 동일 객체 identity 유지 필수.
#   사본 주입 시 구독자는 붙어있는데 이벤트 미도달(런타임에만 드러나는 치명 버그).
def _g_events_thoughts(h, pp):     events_api.stream_thoughts(h, THOUGHT_LOGS, THOUGHT_CLIENTS, _SSE_LOCK)
def _g_events_agent(h, pp):        events_api.stream_agent(h, AGENT_CLIENTS, _SSE_LOCK)
def _g_events_fs(h, pp):           events_api.stream_fs(h, FS_CLIENTS, _SSE_LOCK)

# 인라인 로직 3종 — server.py 고유(프로세스 정리·클립보드·하트비트)라 모듈 분리 대신 wrapper 바디 유지.
# [불변식] _cors_origin/_cleanup_* 은 handler 메서드·모듈 전역 → 호출 시점 해석(late-binding).
def _g_heartbeat(h, pp):
    # 하트비트 수신 — 자동 종료 로직 제거됨 (밤새 실행 지원)
    h.send_response(200)
    h.send_header('Content-Type', 'application/json;charset=utf-8')
    h.send_header('Access-Control-Allow-Origin', h._cors_origin())
    h.end_headers()
    h.wfile.write(json.dumps({"status": "ok", "ts": datetime.now().isoformat()}).encode('utf-8'))

def _g_shutdown(h, pp):
    # 안전한 셧다운: 서버와 자식 프로세스를 정리한 뒤 종료
    # [설계 의도] 프론트엔드 TopMenuBar에서 호출. 확인 다이얼로그를 거친 후에만 도달.
    # 좀비 프로세스 방지를 위해 PTY 세션 정리 후 os._exit() 호출.
    h.send_response(200)
    h.send_header('Content-Type', 'application/json;charset=utf-8')
    h.send_header('Access-Control-Allow-Origin', h._cors_origin())
    h.end_headers()
    h.wfile.write(json.dumps({"status": "ok", "message": "서버 종료 중..."}).encode('utf-8'))
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

def _g_copy_path(h, pp):
    h.send_response(200)
    h.send_header('Content-Type', 'application/json;charset=utf-8')
    h.send_header('Access-Control-Allow-Origin', h._cors_origin())
    h.end_headers()
    query = parse_qs(pp.query)
    target_path = query.get('path', [''])[0]
    try:
        # Windows 클립보드에 경로 복사 (PowerShell 콘솔 깜빡임은 _proc가 CREATE_NO_WINDOW로 차단)
        if os.name == 'nt':
            _proc.run(
                ['powershell', '-WindowStyle', 'Hidden', '-Command', f'Set-Clipboard -Value "{target_path}"'],
                check=True, encoding='utf-8'
            )
        h.wfile.write(json.dumps({"status": "success", "message": "Path copied to clipboard"}).encode('utf-8'))
    except Exception as e:
        h.wfile.write(json.dumps({"status": "error", "message": str(e)}).encode('utf-8'))

# 상태판(독립 창 + tui.py) 콘솔 목록 — api/nodes_api.py 위임.
# [제약] consoles는 CIM 스냅샷(~700ms)이라 무겁다. 상태판은 5초 주기로만 부른다.
def _g_nodes_consoles(h, pp):
    from api import nodes_api
    nodes_api.consoles(h)

GET_ROUTES = {
    '/api/nodes/consoles': _g_nodes_consoles,
    '/api/browse-folder': _g_fs_dialog,
    '/api/browse-file': _g_fs_dialog,
    '/api/drives': _g_fs_dialog,
    '/api/dirs': _g_fs_dialog,
    '/api/tool-status': _g_tool_status,
    '/api/install-tool-status': _g_install_tool_status,
    '/api/install-antigravity': _g_install_antigravity,
    '/api/register-codex-to-ai': _g_register_codex,
    '/stream': _g_stream,
    '/api/server-logs': _g_server_logs,
    '/api/messages': _g_messages,
    '/api/help': _g_help,
    '/api/image-file': _g_image_file,
    '/api/agents': _g_agents,
    # Phase 2 R8 — 설정/vibe/칸반/메모리 exact. 순수위임(vibe 3종) + 인라인 모듈 이전.
    '/api/config': _g_config,
    '/api/daemons': _g_daemons,
    '/api/vibe/sidebar': _g_vibe_sidebar,
    '/api/vibe/notifications': _g_vibe_notifications,
    '/api/vibe/skills': _g_vibe_skills,
    '/api/memory/db-info': _g_memory_db_info,
    # Phase 2 R16 — do_GET 잔여 legacy elif 흡수. 순수위임 6 + SSE 3 + 인라인 3.
    '/api/projects': _g_projects,
    '/api/install-skills': _g_install_skills,
    '/api/check-update-ready': _g_check_update_ready,
    '/api/trigger-update-check': _g_trigger_update_chk,
    '/api/soft-update/check': _g_soft_update_check,
    '/api/soft-update/progress': _g_soft_update_progress,
    '/api/heal/metrics': _g_heal_metrics,
    '/api/setup/status': _g_setup_status,
    '/api/events/thoughts': _g_events_thoughts,
    '/api/events/agent': _g_events_agent,
    '/api/events/fs': _g_events_fs,
    '/api/heartbeat': _g_heartbeat,
    '/api/shutdown': _g_shutdown,
    '/api/copy-path': _g_copy_path,
}

# GET 복합조건 라우트 테이블 (Phase 2 R9) — (조건fn, 핸들러fn) 리스트.
# [WHY] exact/prefix로 표현 불가한 복합조건(startswith OR, in-튜플, endswith 혼합)을 테이블화.
#   조건 리터럴을 server.py 본문에 verbatim 보존해 완전성 가드(tests/test_route_table.py)가
#   startswith/`path ==` 리터럴을 계속 추출하게 한다. dict 키 억지 매핑 금지(Critic 원칙).
# [디스패치 순서] do_GET 진입부: exact → prefix → cond → legacy. cond는 exact/prefix 뒤라
#   이미 그 테이블에 등록된 라우트(예: /api/memory/db-info)는 cond보다 먼저 걸린다(순서 보존).
# [불변식] 조건fn/핸들러fn은 원본 elif verbatim. 전역·모듈은 호출 시점 해석(late-binding).
# install-cli: in-튜플 3종 (본문은 R2에서 install_api 이전 완료).
def _cg_install_cli(path):
    return path in ('/api/install-gemini-cli', '/api/install-claude-code', '/api/install-codex-cli')
def _g_install_cli(h, pp):
    install_api.handle_install_cli(h, pp.path, _get_npm_executable)

# hive: prefix2 + exact8 혼합 → hive_api 위임.
# [과거사고 2026-07-04] agent-quota 누락 — hive_api에 핸들러 추가하고 이 allowlist를 안 갱신해
#   SPA 폴백(index.html)이 응답 → 쿼터 배지 미표시. hive_api 단건 라우트 추가 시 이 튜플도 동기 갱신.
def _cg_hive(path):
    return (path.startswith('/api/hive/') or
            path.startswith('/api/orchestrator/') or
            path in ('/api/superpowers/status', '/api/skill-results',
                     '/api/skill-ab-test', '/api/skill/predict',
                     '/api/context-usage', '/api/antigravity-context-usage',
                     '/api/agent-quota', '/api/local-models',
                     '/api/heartbeat/status'))
def _g_hive(h, pp):
    _params = parse_qs(pp.query)
    from api import hive_api
    hive_api.handle_get(
        h, pp.path, _params,
        DATA_DIR=DATA_DIR, SCRIPTS_DIR=SCRIPTS_DIR, BASE_DIR=BASE_DIR,
        PROJECT_ROOT=PROJECT_ROOT, PROJECT_ID=PROJECT_ID,
        TASKS_FILE=TASKS_FILE, AGENT_STATUS=AGENT_STATUS,
        AGENT_STATUS_LOCK=AGENT_STATUS_LOCK,
        pty_sessions=_get_node_pty_sessions(),
        _current_project_root=_current_project_root,
        # [R14] PTY 슬롯/Claude 세션 경로가 static PROJECT_ID를 소비 → 폴더 전환 미반영.
        #   동적 슬러그 ref를 넘겨 hive_api가 현재 활성 폴더 기준으로 매칭하게 한다.
        _current_project_id=_current_project_id,
        _parse_session_tail=_parse_session_tail,
        _parse_antigravity_session=_parse_antigravity_session,
        run_pg_sql_csv=run_pg_sql_csv
    )

# memory: exact 2종 → memory_api 위임.
# [R14 버그수정] /api/memory·/api/project-info는 요청 런타임 조회다. static PROJECT_ID/PROJECT_ROOT를
#   넘기면 memory_api가 부팅 시점 슬러그로 필터·응답 → UI 폴더 전환 후 옛 프로젝트 이름/메모리 반환.
#   _current_project_id()/_current_project_root()로 현재 활성 폴더를 반영한다(?project_id= override 포함).
def _cg_memory(path):
    return path in ('/api/memory', '/api/project-info')
def _g_memory(h, pp):
    _params = parse_qs(pp.query)
    memory_api.handle_get(
        h, pp.path, _params,
        DATA_DIR=DATA_DIR, PROJECT_ID=_current_project_id(), PROJECT_ROOT=_current_project_root(),
        __version__=__version__,
    )

# tasks: exact4 + (/api/tasks/ prefix AND endswith '/comments') → tasks_api 위임.
def _cg_tasks(path):
    return (path in ('/api/tasks', '/api/tasks/kanban', '/api/task-logs',
                     '/api/agents/status')
            or path.startswith('/api/tasks/') and path.endswith('/comments'))
def _g_tasks(h, pp):
    _params = parse_qs(pp.query)
    tasks_api.handle_get(
        h, pp.path, _params,
        DATA_DIR=DATA_DIR,
        list_tasks=list_tasks,
        current_project_id=_current_project_id(),
        list_task_comments=list_task_comments,
        list_agent_status=list_agent_status,
    )

# files: exact 2종 → files_api 위임.
def _cg_files(path):
    return path in ('/api/files', '/api/read-file')
def _g_files(h, pp):
    _params = parse_qs(pp.query)
    files_api.handle_get(
        h, pp.path, _params,
        PROJECT_ROOT=_current_project_root(),
        validate_file_path=_validate_file_path,
    )

GET_COND_ROUTES: list = [
    (_cg_install_cli, _g_install_cli),
    (_cg_hive, _g_hive),
    (_cg_memory, _g_memory),
    (_cg_tasks, _g_tasks),
    (_cg_files, _g_files),
]
# ─────────────────────────────────────────────────────────────────────────────
# POST 라우트 디스패치 테이블 (Phase 1 Task 3: 순수 위임만)
# [WHY] do_POST의 if/elif 사슬 중 "인라인 로직 없는 순수 위임" 라우트만 테이블로 이전
#   (do_GET Task 2 동형). 인라인 핸들러(dashboard/launch, screenshot/analyze, heartbeat 등)와
#   복합조건 라우트는 legacy 잔류 → 테이블 miss 시 do_POST 하위 if/elif로 폴백(하이브리드).
# [불변식/안전] GET과 달리 POST는 exact-prefix 충돌이 있어 이전 대상을 엄격히 제한한다:
#   - /api/git/rollback·/api/git/diff(인라인) ⊂ /api/git/  → git 계열 전부 legacy 잔류(이전 금지)
#   - /api/hive/log/pg·/api/hive/thought/pg(인라인) ⊂ /api/hive/ → hive/orchestrator/superpowers 잔류
#   - /api/office/*(복합조건 프록시), /api/tasks/*(endswith) 잔류 (agents/*/trigger는 8차 정리로 은퇴)
#   따라서 이전한 prefix(tools/agent/pty/zettel/codegraph/memory)는 어떤 인라인 exact와도 비충돌(검증됨).
#   [디스패치 순서] exact 먼저 → prefix 나중 → legacy 폴백. exact-first라서 prefix가 exact를 가리지 않음.
# [불변식] wrapper는 전역(update_api/_soft_src_dir/_get_node_pty_sessions 등)을 **호출 시점** 해석 —
#   모듈 뒤쪽에서 정의되는 심볼(_NODE_PTY_REST_URL 등)도 런타임 해석이라 안전(GET 테이블과 동일 규칙).
def _p_body(h):
    _cl = int(h.headers.get('Content-Length', 0))
    return json.loads(h.rfile.read(_cl).decode('utf-8')) if _cl else {}

# exact 위임
def _p_apply_update(h, pp):    update_api.apply_update(h, DATA_DIR)
def _p_soft_update(h, pp):     update_api.soft_update_apply(h, DATA_DIR, _soft_src_dir())
def _p_soft_stage(h, pp):      update_api.soft_update_stage(h, DATA_DIR, _soft_src_dir())
def _p_trigger_update(h, pp):  update_api.trigger_update_check(h, DATA_DIR)
def _p_projects(h, pp):        projects_api.handle_post(h, PROJECTS_FILE)
def _p_experience(h, pp):      experience_api.handle_post(h, pp.path)
def _p_config_update(h, pp):   config_api.handle_update(h, CONFIG_FILE, PROJECTS_FILE)
def _p_daemons(h, pp):         daemons_api.handle_update(h, CONFIG_FILE)
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
def _p_fs_dialog(h, pp):
    # [불변식] body 선읽기 금지 — handle_post가 h.rfile을 직접 소비(open-external)하거나
    #   전혀 안 읽음(select-folder). 전역은 호출 시점 해석(late-binding).
    fs_dialog_api.handle_post(h, pp.path,
                              open_folder_dialog=_open_folder_dialog_subprocess,
                              config_file=CONFIG_FILE)

def _p_switch_project(h, pp):
    # 라이브 프로젝트 전환 — {path} 받아 재시작 없이 DB/컨텍스트 전환.
    body = _p_body(h) or {}
    res = _switch_project(body.get('path', ''))
    _send_json_response(h, res, status=200 if res.get('ok') else 400)

# 도구 설치 POST 2종 (Phase 2 R2) — install_api로 본문 이전, 전역 헬퍼 주입.
# [불변식] body 선읽기 금지 — 각 핸들러가 h.rfile을 직접 소비. late-binding.
def _p_install_playwright(h, pp):
    install_api.install_playwright_cli(h, _current_project_root,
                                       _resolve_playwright_install_script,
                                       _project_python_runner_cmds)
def _p_run_script(h, pp):
    install_api.run_script(h, _current_project_root)

# 메시지 채널 초기화 POST (Phase 2 R3) — logs_api로 본문 이전, clear_messages 주입.
def _p_messages_clear(h, pp): logs_api.clear(h, clear_messages)

# 대시보드/에이전트 POST 3종 (Phase 2 R5) — api/dashboard_api.py로 본문 이전.
# [불변식] heartbeat는 AGENT_STATUS/LOCK을 전역 참조로 주입 → /api/agents(_g_agents)와 동일 dict.
#   HTTP_PORT는 __main__에서 슬롯 재설정되므로 wrapper 호출 시점 값 전달(late-binding). body 직접 소비.
def _p_dashboard_launch(h, pp):
    dashboard_api.dashboard_launch(h, BASE_DIR, HTTP_PORT, _python_runner_cmds)
# [9차 정리 2026-07-16] _p_kanban_launch(/api/kanban/launch) 은퇴 — 오케스트레이션 보드 은퇴로
#   호출 버튼 소멸. dashboard_window.py kanban 탭도 동시 제거.
def _p_agents_heartbeat(h, pp):
    dashboard_api.heartbeat(h, AGENT_STATUS, AGENT_STATUS_LOCK, record_heartbeat, insert_pg_log)

# 오피스 독립 서버 실행 POST 3종 (Phase 2 R6) — api/office_launch_api.py로 본문 이전.
# [불변식] _office_state/_launch_office_server/_restart_office_server는 모듈 뒤쪽(~2156)에서
#   정의되므로 반드시 late-binding(wrapper 바디에서 호출 시점 해석)으로 주입 — 프록시 라우트와
#   동일한 OfficeServerState 객체를 공유해야 생존/포트 판정이 갈리지 않는다.
# [주의] exact 3종을 POST_ROUTES에 등록하면 exact-first 디스패치로 프록시 복합조건(not in 제외)보다
#   먼저 걸린다 → 프록시의 launch/restart/status 제외 조건은 그대로 둬도 무해(방어적).
# 상태판 POST — api/nodes_api.py 위임. 본문을 핸들러가 직접 소비한다
# (위임 규칙: body 선읽기 금지 대상 아님 — nodes_api._read_body가 Content-Length만큼 읽음).
def _p_nodes_console_kill(h, pp):
    from api import nodes_api
    nodes_api.console_kill(h)

def _p_office_launch(h, pp):
    office_launch_api.launch(h, _office_state, _launch_office_server, BASE_DIR, _python_runner_cmds)
def _p_office_restart(h, pp):
    office_launch_api.restart(h, _restart_office_server)
def _p_office_status(h, pp):
    office_launch_api.status(h, _office_state)

# prefix 위임 (일부는 body 선읽기)
def _p_tools(h, pp):
    from api import tools_api
    tools_api.handle_post(h, pp.path, _p_body(h))
def _p_setup_auto_install(h, pp):
    setup_api.handle_post(h, pp.path, _p_body(h))
def _p_agent(h, pp): agent_api.handle_post(h, pp.path)
def _p_pty(h, pp):   pty_api.handle_post(h, pp.path)
def _p_zettel(h, pp):
    zettel_api.handle_post(h, pp.path, _p_body(h), DATA_DIR=DATA_DIR, PROJECT_ID=_current_project_id())
def _p_codegraph(h, pp):
    codegraph_api.handle_post(h, pp.path, _p_body(h), DATA_DIR=DATA_DIR, PROJECT_ID=_current_project_id())
def _p_memory(h, pp):
    from api import memory_api
    memory_api.handle_post(h, pp.path, _p_body(h), DATA_DIR=DATA_DIR, PROJECT_ID=_current_project_id())

# 하이브 수집 3종 → api/hive_ingest_api.py (Phase 2 R7)
# [불변식] _p_thoughts_add는 SSE 팬아웃 writer 측 — THOUGHT_LOGS/THOUGHT_CLIENTS/_SSE_LOCK
#   3개 전역을 '호출 시점 이름'으로 그대로 넘겨야 events_api.stream_thoughts(broadcaster,
#   위 1473행)가 등록한 구독자 집합과 동일 객체가 된다. 디폴트 인자 바인딩/사본 금지 —
#   사본이면 구독자는 붙어있는데 새 thought가 도달 안 함(런타임에만 드러나는 치명 버그).
def _p_hive_log_pg(h, pp):
    hive_ingest_api.hive_log_pg(h, log_to_pg)
def _p_hive_thought_pg(h, pp):
    hive_ingest_api.hive_thought_pg(h, thought_to_pg)
def _p_thoughts_add(h, pp):
    # [R14] thought는 memory에 project_id 네임스페이스로 저장 → 현재 활성 폴더 슬러그 사용.
    hive_ingest_api.thoughts_add(h, THOUGHT_LOGS, THOUGHT_CLIENTS, _SSE_LOCK, set_memory, _current_project_id())

# git exact 2종 + 스크린샷 분석 (Phase 2 R8) — do_POST exact 인라인 verbatim 이전.
# [불변식/순서] exact-first 디스패치라 아래 '/api/git/' prefix 위임(startswith)보다 먼저 걸린다 —
#   원본 do_POST에서 git/rollback·git/diff exact 인라인이 git prefix 위임 앞에 있던 순서를 그대로 재현.
# [주의] git_api.rollback/diff는 handle_post()의 동명 분기와 동작이 다르다(원본 exact 보존, R9 수렴).
#   diff는 body 미사용·쿼리스트링 방식 → parse_qs(pp.query)를 주입한다.
def _p_git_rollback(h, pp):    git_api.rollback(h, BASE_DIR)
def _p_git_diff(h, pp):        git_api.diff(h, parse_qs(pp.query), BASE_DIR)
def _p_screenshot_analyze(h, pp): screenshot_api.analyze(h, SCRIPTS_DIR, PROJECT_ID)

POST_ROUTES = {
    '/api/setup/auto-install': _p_setup_auto_install,
    '/api/apply-update': _p_apply_update,
    '/api/soft-update/apply': _p_soft_update,
    '/api/soft-update/stage': _p_soft_stage,
    '/api/trigger-update-check': _p_trigger_update,
    '/api/projects': _p_projects,
    '/api/experience': _p_experience,
    '/api/config/update': _p_config_update,
    '/api/daemons': _p_daemons,
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
    '/api/open-external': _p_fs_dialog,
    '/api/select-folder': _p_fs_dialog,
    '/api/switch-project': _p_switch_project,
    '/api/install-playwright-cli': _p_install_playwright,
    '/api/run-script': _p_run_script,
    '/api/messages/clear': _p_messages_clear,
    '/api/dashboard/launch': _p_dashboard_launch,
    '/api/agents/heartbeat': _p_agents_heartbeat,
    '/api/nodes/console/kill': _p_nodes_console_kill,
    '/api/office/launch': _p_office_launch,
    '/api/office/restart': _p_office_restart,
    '/api/office/status': _p_office_status,
    # 하이브 수집 3종 (Phase 2 R7). exact-first라 아래 '/api/hive/' prefix 위임보다 먼저 걸림.
    '/api/hive/log/pg': _p_hive_log_pg,
    '/api/hive/thought/pg': _p_hive_thought_pg,
    '/api/thoughts/add': _p_thoughts_add,
    # git exact 2종 + 스크린샷 (Phase 2 R8). exact-first라 '/api/git/' prefix 위임보다 먼저 걸림.
    '/api/git/rollback': _p_git_rollback,
    '/api/git/diff': _p_git_diff,
    '/api/screenshot/analyze': _p_screenshot_analyze,
}

def _p_lan(h, pp):
    from api import lan_api
    lan_api.handle_post(h, pp.path, _p_body(h), DATA_DIR=DATA_DIR, PROJECT_ID=_current_project_id())

def _p_recycle(h, pp):
    from api import recycle_api
    if not recycle_api.handle_post(h, pp.path, PROJECT_ID=_current_project_id()):
        h.send_error(404)

POST_PREFIX_ROUTES = [
    ('/api/tools/', _p_tools),
    ('/api/agent/', _p_agent),
    ('/api/pty/', _p_pty),
    ('/api/session/recycle', _p_recycle),
    ('/api/zettel/', _p_zettel),
    ('/api/codegraph/', _p_codegraph),
    ('/api/memory/', _p_memory),
    ('/api/lan/', _p_lan),
]

# POST 복합조건 라우트 테이블 (Phase 2 R9) — GET_COND_ROUTES와 동형.
# [디스패치 순서] do_POST 진입부: exact → prefix → cond → legacy.
#   office launch/restart/status·git rollback/diff는 POST_ROUTES exact 등록됨 → exact-first로
#   cond보다 먼저 걸린다. 따라서 office cond의 not-in·git cond의 diff 서브분기는 방어적 중복(원본 보존).
# office: prefix AND not-in(launch/restart/status) → 오피스 서버 프록시.
def _cp_office(path):
    return path.startswith('/api/office/') and path not in (
        '/api/office/launch', '/api/office/restart', '/api/office/status',
    )
def _p_office_proxy(h, pp):
    _cl = int(h.headers.get('Content-Length', '0') or 0)
    _raw = h.rfile.read(_cl) if _cl > 0 else None
    _proxy_to_office_server(h, method='POST', body=_raw)

# hive: prefix3 (hive/orchestrator/superpowers) → hive_api 위임.
def _cp_hive(path):
    return (path.startswith('/api/hive/') or
            path.startswith('/api/orchestrator/') or
            path.startswith('/api/superpowers/') or
            path == '/api/heartbeat/toggle')
def _p_hive(h, pp):
    from api import hive_api
    content_length = int(h.headers.get('Content-Length', 0))
    _body = json.loads(h.rfile.read(content_length).decode('utf-8')) if content_length else {}
    hive_api.handle_post(
        h, pp.path, _body,
        DATA_DIR=DATA_DIR, SCRIPTS_DIR=SCRIPTS_DIR, BASE_DIR=BASE_DIR,
        PROJECT_ROOT=PROJECT_ROOT,
        _current_project_root=_current_project_root,
    )

# git: prefix → git_api 위임. diff는 쿼리스트링 방식(body 미사용) 서브분기 원본 보존.
# [주의] /api/git/diff·/api/git/rollback exact는 POST_ROUTES가 exact-first로 먼저 처리 →
#   여기 diff 서브분기는 방어적 중복(도달 시엔 handle_post 동명 분기, 원본 elif verbatim).
def _cp_git(path):
    return path.startswith('/api/git/')
def _p_git(h, pp):
    from api import git_api
    from urllib.parse import parse_qs as _parse_qs
    _qs = _parse_qs(pp.query)
    if pp.path == '/api/git/diff':
        git_api.handle_post(h, pp.path, _qs, BASE_DIR=BASE_DIR)
    else:
        content_length = int(h.headers.get('Content-Length', 0))
        _body = json.loads(h.rfile.read(content_length).decode('utf-8')) if content_length else {}
        git_api.handle_post(h, pp.path, _body, BASE_DIR=BASE_DIR)

# tasks: exact4 OR (/api/tasks/ + endswith comments|checkout).
# [8차 정리 2026-07-15] /api/agents/*/trigger 라우팅 제거 — 리스너 미가동 무기능 경로 은퇴.
def _cp_tasks(path):
    return (path in ('/api/tasks', '/api/tasks/update', '/api/tasks/delete', '/api/tasks/claim')
            or (path.startswith('/api/tasks/') and
                (path.endswith('/comments') or path.endswith('/checkout'))))
def _p_tasks(h, pp):
    content_length = int(h.headers.get('Content-Length', 0))
    _body = json.loads(h.rfile.read(content_length).decode('utf-8')) if content_length else {}
    tasks_api.handle_post(
        h, pp.path, _body,
        save_task=save_task, update_task=update_task, delete_task=delete_task,
        # [R14 버그수정] write/read 모두 current_project_id(동적)로 통일. 기존엔 read는 동적,
        #   write(save_task)는 static PROJECT_ID라 폴더 전환 후 새 태스크가 옛 슬러그로 저장돼
        #   목록에 안 뜨던 모순. static PROJECT_ID 인자 제거(tasks_api에서도 미사용화).
        current_project_id=_current_project_id(),
        add_task_comment=add_task_comment,
        atomic_checkout=atomic_checkout,
        release_checkout=release_checkout,
    )

POST_COND_ROUTES: list = [
    (_cp_office, _p_office_proxy),
    (_cp_hive, _p_hive),
    (_cp_git, _p_git),
    (_cp_tasks, _p_tasks),
]
# ─────────────────────────────────────────────────────────────────────────────

class SSEHandler(BaseHTTPRequestHandler):
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

        # ── 라우트 테이블 우선 조회 → miss 시 아래 elif 폴백 ──
        # [불변식] exact 먼저 → prefix 나중(POST와 동형). exact-first라 prefix가 exact를 가리지 않음.
        _exact_g = GET_ROUTES.get(path)
        if _exact_g is not None:
            _exact_g(self, parsed_path)
            return
        for _pfx, _fn in GET_PREFIX_ROUTES:
            if path.startswith(_pfx):
                _fn(self, parsed_path)
                return
        # cond 조회(exact/prefix miss 시) → 복합조건 라우트. miss 시 아래 legacy elif 폴백.
        for _cond, _cfn in GET_COND_ROUTES:
            if _cond(path):
                _cfn(self, parsed_path)
                return

        # [Phase 2 R16] SSE 3종·heartbeat·shutdown·copy-path·projects·install-skills·
        #   check-update-ready·trigger-update-check·soft-update/check·heal/metrics 잔여 elif 11종을
        #   모두 GET_ROUTES exact로 흡수 완료 → do_GET은 do_POST와 동형(exact→prefix→cond→SPA 폴백).
        #   조건 리터럴 원본은 각 _g_* wrapper와 GET_ROUTES 키에 verbatim 보존(완전성 가드 대응).

        # do_GET 최후미 폴백 — Vite dist 정적 서빙 → api/static_api.py로 분리(Phase 2 R4).
        # [불변식] exact/prefix/cond 어디에도 안 걸린 모든 GET의 SPA 폴백. 테이블 등록 금지 —
        #   미매칭 GET이 404가 되어 SPA 라우팅이 깨진다(반드시 최후미 무조건 실행).
        # [경로] STATIC_DIR은 동적 폴백(alt_dist)으로 갱신될 수 있어 호출 시점 값을 주입.
        static_api.serve(self, parsed_path.path, STATIC_DIR)

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
        # cond 조회(exact/prefix miss 시) → 복합조건 라우트. miss 시 아래 legacy if/elif 폴백.
        for _cond, _cfn in POST_COND_ROUTES:
            if _cond(path):
                _cfn(self, parsed_path)
                return

        # [Phase 2 R9] POST office 프록시(startswith + not-in launch/restart/status) →
        #   POST_COND_ROUTES(_cp_office, _p_office_proxy)로 이전. launch/restart/status는 POST_ROUTES exact.

        # [Phase 2 R5] POST /api/dashboard/launch·/api/kanban/launch →
        #   POST_ROUTES(_p_dashboard_launch/_p_kanban_launch, dashboard_api)로 이전.

        # [Phase 2 R6] POST /api/office/launch·restart·status →
        #   POST_ROUTES(_p_office_launch/_p_office_restart/_p_office_status, office_launch_api)로 이전.
        #   프록시 복합조건(위 not in 제외)은 R9에서 처리 예정 — 여기서 건드리지 말 것.

        # [2026-03-22] /api/graph/launch 제거 (지식그래프 삭제)
        # [2026-04-18] /api/eval-review/launch 제거 (디스패처 정리)

        # [Phase 2 R7] POST /api/hive/log/pg·/api/hive/thought/pg·/api/thoughts/add →
        #   POST_ROUTES(_p_hive_log_pg/_p_hive_thought_pg/_p_thoughts_add, hive_ingest_api)로 이전.
        #   thoughts/add는 SSE 팬아웃 writer — THOUGHT_LOGS/THOUGHT_CLIENTS/_SSE_LOCK 3개 전역을
        #   wrapper에서 이름 그대로 주입(events_api.stream_thoughts와 동일 객체 identity 유지).
        #   exact-first라 아래 '/api/hive/' prefix 프록시/위임보다 먼저 걸림 — 순서 보장.

        # [Phase 1 Task 3] tools/files/apply-update/soft-update/trigger-update/projects/experience/
        #   config-update/launch/send-command/locks/message/vibe·zettel·codegraph·memory·agent·pty는
        #   상단 POST_ROUTES/POST_PREFIX_ROUTES로 이전 — 아래는 인라인 로직 + 복합조건 라우트만 잔류.
        # [Phase 2 R5] POST /api/agents/heartbeat → POST_ROUTES(_p_agents_heartbeat, dashboard_api)로 이전.
        # [Phase 2 R8] POST /api/git/rollback·/api/git/diff(exact 인라인) →
        #   POST_ROUTES(_p_git_rollback/_p_git_diff, git_api)로 verbatim 이전. exact-first라 아래
        #   '/api/git/' prefix 위임보다 먼저 걸림(원본 순서 보존). prefix 위임 블록은 R9 대상 — 유지.
        # [Phase 2 R9] POST hive(prefix3 hive/orchestrator/superpowers)·git(prefix + diff 쿼리스트링 서브분기)·
        #   tasks(exact4 + /api/tasks/ endswith comments|checkout + /api/agents/ endswith trigger) →
        #   POST_COND_ROUTES(_cp_hive/_cp_git/_cp_tasks)로 이전. 조건 리터럴은 각 _cp_* 조건fn에 보존.
        # [Phase 2 R8] POST /api/git/rollback·diff, /api/screenshot/analyze는 POST_ROUTES exact 처리.

        # 미매칭 POST → 404. 모든 라우트가 exact/prefix/cond 테이블에서 처리됨 — 여기 도달 = 미등록 경로.
        #
        # [과거사고 2026-08-05] 예전에는 여기서 본문을 읽지 않고 헤더만 보낸 뒤 닫았다.
        #   BaseHTTPRequestHandler는 HTTP/1.0(Connection: close)이라 응답 직후 소켓을 닫는데,
        #   수신 버퍼에 안 읽은 요청 본문이 남아 있으면 Windows가 RST를 보낸다. curl은 이미
        #   응답을 파싱해서 404로 보이지만, 브라우저 fetch는 응답을 버리고 TypeError로 실패한다
        #   → UI에 원인 불명의 'Failed to fetch'만 뜬다. 실제로 설치본에서 구버전 백엔드가
        #   신규 라우트(당시 /api/config/discord — 지금은 제거됨)를 모르는 상황이 정확히
        #   이렇게 보여서, 라우트 부재라는 진짜 원인이 네트워크 장애로 오인됐다.
        # [불변식] 응답 전에 본문을 반드시 비운다. 본문 있는 POST에만 해당되므로 GET 폴백엔 불필요.
        try:
            _unread = int(self.headers.get('Content-Length', 0) or 0)
        except ValueError:
            _unread = 0
        # 상한을 두는 이유: 미등록 경로에 대용량 업로드가 오면 버리려고 메모리에 다 담게 된다.
        while _unread > 0:
            _chunk = self.rfile.read(min(_unread, 65536))
            if not _chunk:
                break
            _unread -= len(_chunk)
        _body = json.dumps({'status': 'error', 'error': 'route_not_found', 'path': path},
                           ensure_ascii=False).encode('utf-8')
        self.send_response(404)
        self.send_header('Content-Type', 'application/json;charset=utf-8')
        self.send_header('Access-Control-Allow-Origin', self._cors_origin())
        self.send_header('Content-Length', str(len(_body)))
        self.end_headers()
        self.wfile.write(_body)

    def log_message(self, format, *args):
        # 불필요한 콘솔 로그 제거하여 터미널 깔끔하게 유지
        pass

# [제거됨 2026-03-22] pty_sessions, pty_output_buffers, pty_output_seq 글로벌 → Node PTY 서버로 이전
# Python 서버에서 PTY 세션 정보가 필요한 경우 Node PTY 서버의 REST API를 호출합니다.
# URL: http://127.0.0.1:{WS_PORT}/api/pty/sessions
_NODE_PTY_REST_URL = None  # 부팅 기본값 — app_boot가 set_node_pty_rest_url로 실제 URL 재설정(R14/R20)


def set_node_pty_rest_url(url: str) -> None:
    """[R20] PTY REST URL을 모듈 전역 + pty_api/agent_api에 일괄 반영.

    [WHY] 부팅 로직을 infra/app_boot.py로 이관하면서, 다른 모듈에서는 server.py의
      모듈 전역 _NODE_PTY_REST_URL을 global로 직접 대입할 수 없다. 소비자
      (_p_send_command·_get_node_pty_sessions)가 이 전역을 call-time 참조하므로
      setter로 캡슐화해 app_boot가 콜백으로 호출한다.
    """
    global _NODE_PTY_REST_URL
    _NODE_PTY_REST_URL = url
    pty_api.set_pty_rest_url(url)
    agent_api.set_pty_rest_url(url)


# PTY 프로세스 관리 로직은 infra/pty_process.py로 분리 (2026-07-06, Phase 2 Task 11).
# [WHY] 얇은 위임 유지 — _NODE_PTY_REST_URL은 호출 시점의 모듈 전역 값을 그대로 넘겨
#   원본(모듈 전역을 call-time 해석)과 동작을 완전히 보존한다.
from infra import pty_process as _pty_process


def _get_node_pty_sessions() -> dict:
    """Node PTY 서버에서 세션 정보를 REST로 조회합니다 (pty_process 위임)."""
    return _pty_process.get_node_pty_sessions(_NODE_PTY_REST_URL)


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

# 워치독/힐데몬 등 서버가 직접 spawn한 서브프로세스 참조 목록
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
HTTP_PORT = 9000  # 부팅 기본값 — main()이 슬롯 탐색 후 global로 실제 포트 재설정(R14)
WS_PORT   = 9001  # 부팅 기본값 — main()이 슬롯 탐색 후 global로 실제 포트 재설정(R14)

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
    # [R14 이중전역 통합] HTTP_PORT/WS_PORT를 모듈 전역으로 재대입 — global 없으면 아래 슬롯탐색
    #   대입이 main() 지역변수가 되어 모듈 전역(9000/9001)을 shadowing한다. 그러면 모듈 스코프
    #   소비자(_p_dashboard_launch/_p_kanban_launch/_p_message/_cors_origin/fs_watcher/cleanup)가
    #   stale한 9000/9001을 참조 → 포트 폴백(9000 점유 시) 발동하면 wrapper가 틀린 포트를 가리키는
    #   잠재 버그. global 선언으로 재대입을 실제 전역 갱신으로 만들어 소비자와 값 일치를 보장한다.
    global HTTP_PORT, WS_PORT
    # ── CLI 인자 처리: --install / --uninstall / --create-shortcut ──
    # 로직 본체는 infra/cli_commands.py로 분리 (2026-07-08, Phase 3 R17).
    # server_dir는 pty-server 경로 계산 기준 — __file__ 부모를 명시 주입.
    from infra.cli_commands import handle_cli_command
    if handle_cli_command(sys.argv, Path(__file__).resolve().parent):
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

    # ── 단일 인스턴스 락 + 포트 확정 — infra/instance_lock.py로 분리 (Phase 3 R17-2) ──
    # [불변식] resolve_server_ports 반환값을 반드시 모듈 전역 HTTP_PORT/WS_PORT에
    # 재대입(위 global 선언) — 모듈 스코프 소비자가 stale 9000/9001을 참조하는
    # R14 이중전역 버그 재발 방지. 락은 실패 시 내부에서 os._exit(0) 하므로
    # 반환되면 획득 성공. _lock_sock은 종료 정리(아래 GUI 콜백)에서 close.
    from infra.instance_lock import acquire_single_instance_lock, resolve_server_ports
    _lock_sock = acquire_single_instance_lock(PROJECT_ROOT)
    HTTP_PORT, WS_PORT = resolve_server_ports(_find_free_port, PROJECT_ROOT)

    # ── [v3.7.248] 부팅 초기 자가치유 — 업데이트/크래시로 남은 '깨진 _MEI'(python DLL 누락)와
    #    그걸 잠근 고아 node 선제 청소. 단일 인스턴스 락 획득 후(= 우리가 생존 인스턴스) 실행하여
    #    누적 잔여물의 "Failed to remove temporary directory" 경고 + 다음 업데이트 DLL 충돌을 예방.
    try:
        _lifecycle.heal_broken_mei_at_startup()
    except Exception:
        pass

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
    #   [자동 적용 2026-08-07] 감지에서 멈추지 않고 **받아두기(stage)** 까지 여기서 끝낸다.
    #   느린 fetch를 앱이 떠 있는 동안 처리해야 다음 부팅에서 boot.py가 로컬 reset만으로
    #   즉시 최신이 된다(= 재시작 1번, 부팅 지연 0). 트리 이동은 안 하므로 실행 중 코드는 불변.
    try:
        from soft_updater import check_soft_update as _check_soft
        from soft_updater import stage_soft_update as _stage_soft
        from soft_updater import auto_update_enabled as _soft_auto

        def _soft_update_loop():
            while True:
                try:
                    res = _check_soft(DATA_DIR, _soft_src_dir()) or {}
                    # 이미 같은 SHA를 받아뒀으면 재fetch 하지 않는다(매 5분 네트워크 낭비 방지).
                    if res.get("ready") and not res.get("staged") and _soft_auto(DATA_DIR):
                        st = _stage_soft(DATA_DIR, _soft_src_dir())
                        if st.get("staged"):
                            print(f"[soft-update] 예약됨 {str(st.get('sha'))[:7]} — 재시작 시 적용")
                        elif not st.get("ok"):
                            print(f"[soft-update] 예약 실패: {st.get('error')}")
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
    # [불변식] _pty_server_state(가변 dict)는 워치독과 start가 동일 객체를 공유해야
    # 프로세스 사망 감지가 성립한다 — 아래 위임 래퍼들은 모두 이 동일 dict를 주입한다.
    # 재생성 금지(재생성 시 워치독이 죽은 proc을 못 잡음).
    _pty_server_state = {'proc': None}  # 현재 PTY 서버 프로세스 핸들 (워치독이 참조)

    # [R19] PTY 부팅 시퀀스는 pty_process.prepare_pty_async /
    #   start_pty_server_and_watchdog로 이관 — main() nested 래퍼 6종 제거.
    #   _pty_server_state(가변 dict)만 여기서 소유하고 두 함수에 동일 객체로 주입한다.

    # ── [v3.7.179] GUI 창 선행 표시 → 백그라운드 초기화 → 앱 로드 ────────────
    # 모든 무거운 초기화(PG, PTY, 데몬, HTTP)를 WebView 콜백에서 실행.
    # 사용자는 스플래시를 즉시 보고, 초기화 진행 상황을 텍스트로 확인.
    _http_server_ref = [None]  # HTTP 서버 참조 (콜백 → 정리 코드 공유)
    
    # ── 데몬 함수 정의 (실행은 _init_and_load_app 콜백에서) ──────────────────

    # ── 데몬 본문은 infra/daemons.py로 분리 (2026-06-10 단계 9) ──────────────
    # [WHY] env는 매 호출 시 생성 — HTTP_PORT가 main() 후반(포트 슬롯 결정)에
    # 재바인딩되므로 함수 정의 시점에 값을 고정하면 안 된다.
    from infra import daemons as _daemons

    # [R18] 데몬 시작은 daemons.start_all_daemons로 일괄 위임 — 개별 run_* 래퍼 제거.
    # _daemon_env() 팩토리만 유지(HTTP_PORT late-binding — 호출 시점 생성 계약).
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
    # ── GUI 부팅은 infra/app_boot.py로 이관 (Phase 3 R20) ──────────────────────
    # _init_and_load_app + webview 창 생성/시작/종료정리 전체를 run_gui_app으로.
    # server.py 고유 함수/객체/값은 BootConfig로 명시 주입(main() nested 클로저 대체).
    # [불변식] _pty_server_state/_child_procs/_http_server_ref는 caller 소유 가변 객체를
    #   그대로 주입 — 재생성 금지(워치독/정리 코드가 동일 객체 공유). official_icon은
    #   server.py __file__ 기준(bin/ 경로 오염 방지). window_title은 create_window와
    #   force_win32_icon이 동일 문자열이어야 hwnd 매칭 성립.
    from infra.app_boot import BootConfig, run_gui_app
    from infra.win32_icon import resolve_app_icon
    from infra.splash import build_splash_html
    _window_title = f'바이브 코딩 [{PROJECT_ROOT.name}]'
    run_gui_app(BootConfig(
        http_port=HTTP_PORT,
        ws_port=WS_PORT,
        base_dir=BASE_DIR,
        data_dir=DATA_DIR,
        project_root=PROJECT_ROOT,
        project_id=PROJECT_ID,
        official_icon=resolve_app_icon(os.path.dirname(__file__)),
        splash_html=build_splash_html(PROJECT_ROOT.name),
        window_title=_window_title,
        pty_server_state=_pty_server_state,
        child_procs=_child_procs,
        agent_status=AGENT_STATUS,
        agent_status_lock=AGENT_STATUS_LOCK,
        http_server_ref=_http_server_ref,
        lock_sock=_lock_sock,
        http_server_factory=ThreadedHTTPServer,
        handler_cls=SSEHandler,
        memory_watcher_factory=MemoryWatcher,
        daemon_env_factory=_daemon_env,
        find_free_port=_find_free_port,
        ensure_postgres_running=ensure_postgres_running,
        cleanup_postgres=_cleanup_postgres,
        cleanup_child_procs=_cleanup_child_procs,
        init_project_db=_init_project_db,
        restore_agent_status=_restore_agent_status_from_db,
        load_task_logs=_load_task_logs_into_thoughts,
        agent_broadcast_worker=_agent_broadcast_worker,
        start_fs_watcher=start_fs_watcher,
        set_node_pty_rest_url=set_node_pty_rest_url,
        open_app_window=open_app_window,
        # [헤드리스] 데스크톱이 없는 세션(SSH 원격 상주 노드)에서 창 없이 서버만 띄운다.
        #   환경변수도 받는 이유: 설치본 바로가기/작업 스케줄러처럼 인자를 넘기기
        #   번거로운 실행 경로에서도 켤 수 있어야 한다.
        headless=('--headless' in sys.argv or os.environ.get('VIBE_HEADLESS') == '1'),
    ))


if __name__ == '__main__':
    main()
