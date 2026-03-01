# ------------------------------------------------------------------------
# 📄 파일명: server.py
# 🗺️ 메인 프로젝트 맵: PROJECT_MAP.md
# 📝 설명: 하이브 마인드(Gemini & Claude)의 중앙 통제 서버.
#          에이전트 간의 통신 중계, 상태 모니터링, 데이터 영속성을 관리합니다.
#
# 🕒 변경 이력 (History):
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
import sqlite3
import re
import threading
import sys
import asyncio
import string
import socket
from pathlib import Path

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
    from db_helper import insert_log, get_recent_logs, send_message, get_messages
except ImportError as e:
    print(f"Critical Import Error: {e}")
    # src 폴더가 없는 경우 대비하여 한 번 더 경로 확인
    sys.path.append(str(BASE_DIR))
    from src.db import init_db
    from src.db_helper import insert_log, get_recent_logs, send_message, get_messages

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
# 에이전트 간 공유 메모리/지식 베이스 (SQLite — 동시성·검색 안정성 확보)
MEMORY_DB = DATA_DIR / "shared_memory.db"
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

# 작업 큐 파일 초기화 (없을 경우)
if not TASKS_FILE.exists():
    with open(TASKS_FILE, 'w', encoding='utf-8') as f:
        json.dump([], f)

# ── 공유 메모리 SQLite 초기화 ────────────────────────────────────────────────
def _memory_conn() -> sqlite3.Connection:
    """요청마다 새 커넥션 생성 (스레드 안전 — ThreadedHTTPServer 대응)

    [배포 버전 DATA_DIR 불일치 해소]
    배포(frozen) 버전에서 DATA_DIR = APPDATA/VibeCoding로 설정되더라도,
    현재 활성 프로젝트(config.json last_path)의 로컬 DB가 있으면 우선 사용합니다.
    이를 통해 CLI(개발 버전)가 저장한 공유 메모리를 배포 대시보드에서도 표시합니다.
    """
    # 현재 활성 프로젝트 로컬 DB 우선 확인 (config.json last_path 참조)
    try:
        if CONFIG_FILE.exists():
            cfg_data = json.loads(CONFIG_FILE.read_text(encoding='utf-8'))
            last_path = cfg_data.get('last_path', '')
            if last_path:
                local_db = Path(last_path) / ".ai_monitor" / "data" / "shared_memory.db"
                if local_db.exists():
                    conn = sqlite3.connect(str(local_db), timeout=5, check_same_thread=False)
                    conn.row_factory = sqlite3.Row
                    return conn
    except Exception:
        pass
    # 폴백: 서버 시작 시 결정된 MEMORY_DB (APPDATA 또는 로컬 data/)
    conn = sqlite3.connect(str(MEMORY_DB), timeout=5, check_same_thread=False)
    conn.row_factory = sqlite3.Row
    return conn

def _migrate_project_column(conn: sqlite3.Connection) -> None:
    """project 컬럼이 없는 기존 행을 마이그레이션: tags 패턴으로 출처 프로젝트 추론"""
    rows = conn.execute("SELECT key, tags FROM memory WHERE project = ''").fetchall()
    for row in rows:
        try:
            tags = json.loads(row['tags']) if row['tags'] else []
            project = ''
            if 'claude' in tags and len(tags) > 3:
                project = tags[3]      # ['claude', 'terminal-N', stem, proj_dir_name]
            elif 'gemini' in tags and len(tags) > 2:
                project = tags[2]      # ['gemini', 'terminal-N', proj_name, type]
            else:
                project = PROJECT_ID   # 수동 추가 항목 → 현재 프로젝트 귀속
            if project:
                conn.execute("UPDATE memory SET project = ? WHERE key = ?", (project, row['key']))
        except Exception:
            pass


def _init_memory_db() -> None:
    """shared_memory.db 스키마 초기화 (서버 시작 시 1회 실행)"""
    with _memory_conn() as conn:
        conn.execute('''
            CREATE TABLE IF NOT EXISTS memory (
                key        TEXT PRIMARY KEY,
                id         TEXT NOT NULL,
                title      TEXT NOT NULL DEFAULT '',
                content    TEXT NOT NULL,
                tags       TEXT NOT NULL DEFAULT '[]',
                author     TEXT NOT NULL DEFAULT 'unknown',
                timestamp  TEXT NOT NULL,
                updated_at TEXT NOT NULL,
                project    TEXT NOT NULL DEFAULT '',
                embedding  BLOB         -- 의미 벡터 (fastembed, float32 bytes)
            )
        ''')
        conn.execute('CREATE INDEX IF NOT EXISTS idx_memory_author ON memory(author)')
        conn.execute('CREATE INDEX IF NOT EXISTS idx_memory_updated ON memory(updated_at)')
        # 기존 DB 마이그레이션 — 없는 컬럼 추가
        cols = [r[1] for r in conn.execute('PRAGMA table_info(memory)').fetchall()]
        if 'embedding' not in cols:
            conn.execute('ALTER TABLE memory ADD COLUMN embedding BLOB')
        if 'project' not in cols:
            conn.execute("ALTER TABLE memory ADD COLUMN project TEXT NOT NULL DEFAULT ''")
            _migrate_project_column(conn)
        conn.execute('CREATE INDEX IF NOT EXISTS idx_memory_project ON memory(project)')

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
            with _memory_conn() as conn:
                rows = conn.execute(
                    "SELECT key,title,content,author,tags,updated_at "
                    "FROM memory "
                    "WHERE key NOT LIKE 'claude:T%' "
                    "ORDER BY updated_at DESC LIMIT 15"
                ).fetchall()
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

    # ── 내부: DB 저장 (HTTP 없이 직접 SQLite, 임베딩 포함) ──────────────────
    def _upsert(self, key: str, title: str, content: str,
                author: str, tags: list, project: str = '') -> None:
        now = time.strftime('%Y-%m-%dT%H:%M:%S')
        tags_json = json.dumps(tags, ensure_ascii=False)
        emb = _embed(f"{title}\n{content}")  # 제목+내용 합쳐서 벡터화
        proj = project or PROJECT_ID
        
        # [수정] 전역 DATA_DIR 내의 shared_memory.db 경로를 사용하도록 강제
        db_path = DATA_DIR / "shared_memory.db"
        
        try:
            conn = sqlite3.connect(str(db_path), timeout=10)
            conn.row_factory = sqlite3.Row
            # 테이블 자동 생성 보장 (없을 경우 대비)
            conn.execute('''
                CREATE TABLE IF NOT EXISTS memory (
                    key TEXT PRIMARY KEY, id TEXT NOT NULL,
                    title TEXT NOT NULL DEFAULT '', content TEXT NOT NULL,
                    tags TEXT NOT NULL DEFAULT '[]', author TEXT NOT NULL DEFAULT 'unknown',
                    timestamp TEXT NOT NULL, updated_at TEXT NOT NULL,
                    embedding BLOB, project TEXT NOT NULL DEFAULT ''
                )
            ''')
            
            existing = conn.execute(
                'SELECT timestamp FROM memory WHERE key=?', (key,)
            ).fetchone()
            orig_ts = existing['timestamp'] if existing else now
            conn.execute(
                'INSERT OR REPLACE INTO memory '
                '(key,id,title,content,tags,author,timestamp,updated_at,project,embedding) '
                'VALUES (?,?,?,?,?,?,?,?,?,?)',
                (key, str(int(time.time() * 1000)), title,
                 content, tags_json, author, orig_ts, now, proj, emb)
            )
            conn.commit()
            conn.close()
            print(f"[MemoryWatcher] 동기화 완료: {key} (경로: {db_path})")
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

# ── MCP 설정 파일 경로 헬퍼 ──────────────────────────────────────────────────
def _mcp_config_path(tool: str, scope: str) -> Path:
    """
    도구(tool)와 범위(scope)에 따른 MCP 설정 파일 경로를 반환합니다.
    - claude / global  → ~/.claude/settings.json
    - claude / project → {현재프로젝트루트}/.claude/settings.local.json
    - gemini / global  → ~/.gemini/settings.json
    - gemini / project → {현재프로젝트루트}/.gemini/settings.json

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
    # PyInstaller로 빌드된 경우, dist 폴더는 보통 _MEIPASS 직하에 위치하도록 패키징함
    STATIC_DIR = (BASE_DIR / "dist").resolve()
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

main_window = None

import string
from urllib.parse import urlparse, parse_qs

class SSEHandler(BaseHTTPRequestHandler):
    def do_GET(self):
        parsed_path = urlparse(self.path)
        path = parsed_path.path
        
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
            
            # SSE 스트리밍 루프 (SQLite 기반)
            last_id = 0
            
            # 초기 진입 시 최신 50개 전송
            try:
                recent_logs = get_recent_logs(50)
                if recent_logs:
                    last_id = recent_logs[-1]['id'] # 가장 최신 id 저장
                    for log in recent_logs:
                        self.wfile.write(f"data: {json.dumps(log, ensure_ascii=False)}\n\n".encode('utf-8'))
                        self.wfile.flush()
            except Exception as e:
                print(f"Initial DB Read error: {e}")
            
            # SSE 연결 타임아웃 완화 (60초)
            self.connection.settimeout(60.0)
            heartbeat_tick = 0

            while True:
                try:
                    # 새로운 로그가 있는지 확인 (last_id 보다 큰 id 조회)
                    # DB 락 대응을 위해 timeout=20.0으로 설정
                    conn = sqlite3.connect(str(DATA_DIR / "hive_mind.db"), timeout=20.0)
                    conn.row_factory = sqlite3.Row
                    cursor = conn.execute("SELECT * FROM session_logs WHERE id > ? ORDER BY id ASC", (last_id,))
                    new_rows = [dict(row) for row in cursor.fetchall()]
                    conn.close()
                    
                    if new_rows:
                        for row in new_rows:
                            # 프론트엔드가 기대하는 포맷으로 키 이름 매핑
                            out_row = dict(row)
                            if 'trigger_msg' in out_row:
                                out_row['trigger'] = out_row.pop('trigger_msg')
                            
                            self.wfile.write(f"data: {json.dumps(out_row, ensure_ascii=False)}\n\n".encode('utf-8'))
                            self.wfile.flush()
                        last_id = new_rows[-1]['id']
                        heartbeat_tick = 0
                    else:
                        heartbeat_tick += 1
                        # 30초마다 하트비트 전송
                        if heartbeat_tick >= 30:
                            self.wfile.write(b": heartbeat\n\n")
                            self.wfile.flush()
                            heartbeat_tick = 0
                    
                    time.sleep(1.0) # 감시 주기를 1.0s로 유지
                except (BrokenPipeError, ConnectionResetError, TimeoutError, socket.timeout):
                    break
                except Exception as e:
                    # 에러가 반복되면 루프 중단 (서버 먹통 방지)
                    print(f"SSE DB Stream error: {e}")
                    time.sleep(2)
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
            self.wfile.write(body)        elif parsed_path.path == '/api/install-skills':
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
                    for db_name in ("shared_memory.db", "hive_mind.db"):
                        db_path = target_data / db_name
                        if not db_path.exists():
                            conn = sqlite3.connect(str(db_path))
                            if db_name == "shared_memory.db":
                                conn.execute("""CREATE TABLE IF NOT EXISTS memory (
                                    key TEXT PRIMARY KEY, title TEXT, content TEXT,
                                    tags TEXT, author TEXT, project TEXT,
                                    created_at TEXT, updated_at TEXT)""")
                            conn.commit()
                            conn.close()

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
            from api import hive_api
            from urllib.parse import parse_qs
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
            )

        # ── [모듈 위임] git_api — /api/git/* ─────────────────────────────
        elif parsed_path.path.startswith('/api/git/'):
            from api import git_api
            from urllib.parse import parse_qs
            _params = parse_qs(parsed_path.query)
            git_api.handle_get(self, parsed_path.path, _params, BASE_DIR=BASE_DIR)

        # ── [모듈 위임] mcp_api — /api/mcp/* ─────────────────────────────
        elif parsed_path.path.startswith('/api/mcp/'):
            from api import mcp_api
            from urllib.parse import parse_qs
            _params = parse_qs(parsed_path.query)
            mcp_api.handle_get(
                self, parsed_path.path, _params,
                _smithery_api_key=_smithery_api_key,
                _mcp_config_path=_mcp_config_path,
            )

        # ── [모듈 위임] memory_api — /api/memory, /api/project-info ──────
        elif parsed_path.path in ('/api/memory', '/api/project-info'):
            from api import memory_api
            from urllib.parse import parse_qs
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
            tasks = []
            if TASKS_FILE.exists():
                with open(TASKS_FILE, 'r', encoding='utf-8') as f:
                    tasks = json.load(f)
            self.wfile.write(json.dumps(tasks, ensure_ascii=False).encode('utf-8'))
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
                KNOWN_AGENTS = ['claude', 'gemini']
                IDLE_SEC = 300  # 5분

                # 에이전트 마지막 활동 시각 (hive_mind.db session_logs)
                agent_last_seen: dict = {a: None for a in KNOWN_AGENTS}
                try:
                    # hive_mind.db session_logs에서 에이전트 활동 시각 조회
                    # 실제 agent 값이 'Claude', 'Gemini CLI', 'Gemini-1' 등 대소문자 혼합이므로 LOWER/LIKE 사용
                    conn_h = sqlite3.connect(str(DATA_DIR / 'hive_mind.db'), timeout=5, check_same_thread=False)
                    conn_h.row_factory = sqlite3.Row
                    for row in conn_h.execute(
                        "SELECT agent, MAX(ts_start) as last_seen FROM session_logs "
                        "WHERE LOWER(agent) LIKE '%claude%' OR LOWER(agent) LIKE '%gemini%' "
                        "GROUP BY LOWER(agent) ORDER BY last_seen DESC"
                    ).fetchall():
                        agent_lower = row['agent'].lower()
                        if 'claude' in agent_lower and agent_last_seen.get('claude') is None:
                            agent_last_seen['claude'] = row['last_seen']
                        elif 'gemini' in agent_lower and agent_last_seen.get('gemini') is None:
                            agent_last_seen['gemini'] = row['last_seen']
                    conn_h.close()
                except Exception:
                    pass

                # shared_memory.db author 필드로 보완 — 더 최신 활동 기록 포함
                try:
                    conn_sm = sqlite3.connect(str(DATA_DIR / 'shared_memory.db'), timeout=5, check_same_thread=False)
                    conn_sm.row_factory = sqlite3.Row
                    for row in conn_sm.execute(
                        "SELECT author, MAX(updated_at) as last_seen FROM memory "
                        "WHERE LOWER(author) LIKE '%claude%' OR LOWER(author) LIKE '%gemini%' "
                        "GROUP BY LOWER(author) ORDER BY last_seen DESC"
                    ).fetchall():
                        author_lower = row['author'].lower()
                        last = row['last_seen']
                        if 'claude' in author_lower:
                            if agent_last_seen.get('claude') is None or (last and last > (agent_last_seen['claude'] or '')):
                                agent_last_seen['claude'] = last
                        elif 'gemini' in author_lower:
                            if agent_last_seen.get('gemini') is None or (last and last > (agent_last_seen['gemini'] or '')):
                                agent_last_seen['gemini'] = last
                    conn_sm.close()
                except Exception:
                    pass

                # in-memory AGENT_STATUS 로 보완 (가장 실시간 하트비트)
                with AGENT_STATUS_LOCK:
                    for a_name, st in AGENT_STATUS.items():
                        a_key = 'claude' if 'claude' in a_name.lower() else 'gemini' if 'gemini' in a_name.lower() else None
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
        elif parsed_path.path == '/api/git/status':
            # Git 저장소 실시간 상태 조회 — ?path=경로 로 대상 디렉토리 지정
            self.send_response(200)
            self.send_header('Content-Type', 'application/json;charset=utf-8')
            self.send_header('Access-Control-Allow-Origin', '*')
            self.end_headers()
            query = parse_qs(parsed_path.query)
            git_path = query.get('path', [''])[0].strip() or str(BASE_DIR.parent)
            try:
                # git status --porcelain=v1 -b : 머신 파싱용 간결 포맷
                result = subprocess.run(
                    ['git', 'status', '--porcelain=v1', '-b'],
                    cwd=git_path, capture_output=True, text=True, timeout=5, encoding='utf-8',
                    creationflags=0x08000000
                )
                if result.returncode != 0:
                    self.wfile.write(json.dumps({'is_git_repo': False, 'error': result.stderr.strip()}).encode('utf-8'))
                    return
                lines = result.stdout.splitlines()
                # 첫 줄: ## branch...origin/branch [ahead N] [behind N]
                branch_line = lines[0] if lines else ''
                branch = 'unknown'
                ahead = 0
                behind = 0
                if branch_line.startswith('## '):
                    branch_info = branch_line[3:]
                    # "No commits yet on main" 처리
                    if branch_info.startswith('No commits yet on '):
                        branch = branch_info.split(' ')[-1]
                    else:
                        branch = branch_info.split('...')[0].split(' ')[0]
                        ahead_m = re.search(r'\[ahead (\d+)', branch_info)
                        behind_m = re.search(r'behind (\d+)', branch_info)
                        if ahead_m: ahead = int(ahead_m.group(1))
                        if behind_m: behind = int(behind_m.group(1))
                staged, unstaged, untracked, conflicts = [], [], [], []
                for line in lines[1:]:
                    if len(line) < 2:
                        continue
                    xy = line[:2]
                    fname = line[3:]
                    # 충돌 (양쪽 수정: UU, AA, DD 등)
                    if xy in ('UU', 'AA', 'DD', 'AU', 'UA', 'DU', 'UD'):
                        conflicts.append(fname)
                    elif xy[0] != ' ' and xy[0] != '?':
                        staged.append(fname)      # 인덱스(스테이징) 변경
                    if xy[1] == 'M' or xy[1] == 'D':
                        unstaged.append(fname)    # 워킹트리 변경
                    elif xy == '??':
                        untracked.append(fname)   # 미추적 파일
                status_data = {
                    'is_git_repo': True,
                    'branch': branch,
                    'ahead': ahead,
                    'behind': behind,
                    'staged': staged,
                    'unstaged': unstaged,
                    'untracked': untracked,
                    'conflicts': conflicts,
                }
                self.wfile.write(json.dumps(status_data, ensure_ascii=False).encode('utf-8'))
            except subprocess.TimeoutExpired:
                self.wfile.write(json.dumps({'is_git_repo': False, 'error': 'git timeout'}).encode('utf-8'))
            except FileNotFoundError:
                self.wfile.write(json.dumps({'is_git_repo': False, 'error': 'git not found'}).encode('utf-8'))
            except Exception as e:
                self.wfile.write(json.dumps({'is_git_repo': False, 'error': str(e)}).encode('utf-8'))
        elif parsed_path.path == '/api/git/log':
            # 최근 커밋 로그 — ?path=경로&n=개수
            self.send_response(200)
            self.send_header('Content-Type', 'application/json;charset=utf-8')
            self.send_header('Access-Control-Allow-Origin', '*')
            self.end_headers()
            query = parse_qs(parsed_path.query)
            git_path = query.get('path', [''])[0].strip() or str(BASE_DIR.parent)
            n = min(int(query.get('n', ['10'])[0]), 50)  # 최대 50개
            try:
                result = subprocess.run(
                    ['git', 'log', f'--format=%h\x1f%s\x1f%an\x1f%ar', f'-n{n}'],
                    cwd=git_path, capture_output=True, text=True, timeout=5, encoding='utf-8',
                    creationflags=0x08000000
                )
                commits = []
                for line in result.stdout.strip().splitlines():
                    parts = line.split('\x1f')
                    if len(parts) == 4:
                        commits.append({'hash': parts[0], 'message': parts[1], 'author': parts[2], 'date': parts[3]})
                self.wfile.write(json.dumps(commits, ensure_ascii=False).encode('utf-8'))
            except Exception as e:
                self.wfile.write(json.dumps([]).encode('utf-8'))
        elif parsed_path.path == '/api/memory/db-info':
            # 현재 사용 중인 공유 메모리 DB 경로 및 항목 수 반환
            # 배포 버전에서 어떤 DB를 바라보고 있는지 UI에서 확인할 수 있게 함
            self.send_response(200)
            self.send_header('Content-Type', 'application/json;charset=utf-8')
            self.send_header('Access-Control-Allow-Origin', '*')
            self.end_headers()
            try:
                # _memory_conn()과 동일한 로직으로 실제 DB 경로 결정
                actual_db = str(MEMORY_DB)
                is_local = False
                if CONFIG_FILE.exists():
                    cfg_data = json.loads(CONFIG_FILE.read_text(encoding='utf-8'))
                    last_path = cfg_data.get('last_path', '')
                    if last_path:
                        local_db = Path(last_path) / ".ai_monitor" / "data" / "shared_memory.db"
                        if local_db.exists():
                            actual_db = str(local_db)
                            is_local = True
                # 항목 수 조회
                with _memory_conn() as conn:
                    count = conn.execute('SELECT COUNT(*) FROM memory').fetchone()[0]
                self.wfile.write(json.dumps({
                    'db_path': actual_db,
                    'is_local': is_local,
                    'count': count,
                }, ensure_ascii=False).encode('utf-8'))
            except Exception as e:
                self.wfile.write(json.dumps({'error': str(e), 'count': 0}).encode('utf-8'))

        elif parsed_path.path == '/api/memory':
            # 공유 메모리 조회 — 임베딩 의미 검색 우선, 폴백 키워드 LIKE
            # ?q=검색어  ?top=N(기본20)  ?threshold=0.5  ?all=true(전체 프로젝트)
            self.send_response(200)
            self.send_header('Content-Type', 'application/json;charset=utf-8')
            self.send_header('Access-Control-Allow-Origin', '*')
            self.end_headers()
            query = parse_qs(parsed_path.query)
            q         = query.get('q',         [''])[0].strip()
            top_k     = int(query.get('top',   ['20'])[0])
            threshold = float(query.get('threshold', ['0.45'])[0])
            show_all  = query.get('all', ['false'])[0].lower() == 'true'
            # 프로젝트 필터: all=true가 아니면 현재 프로젝트만 표시
            proj_filter = '' if show_all else PROJECT_ID
            try:
                with _memory_conn() as conn:
                    if q:
                        q_emb = _embed(q)
                        if q_emb:
                            # ── 임베딩 의미 검색 ──────────────────────────
                            if proj_filter:
                                all_rows = conn.execute(
                                    'SELECT * FROM memory WHERE project=? ORDER BY updated_at DESC',
                                    (proj_filter,)
                                ).fetchall()
                            else:
                                all_rows = conn.execute(
                                    'SELECT * FROM memory ORDER BY updated_at DESC'
                                ).fetchall()
                            scored = []
                            for row in all_rows:
                                r_emb = row['embedding']
                                if r_emb:
                                    score = _cosine_sim(q_emb, r_emb)
                                    if score >= threshold:
                                        scored.append((dict(row), score))
                                else:
                                    # 임베딩 없는 항목은 키워드 폴백
                                    pattern = f'%{q}%'
                                    if any(q.lower() in str(row[f]).lower()
                                           for f in ('key','title','content','tags')):
                                        scored.append((dict(row), 0.0))
                            scored.sort(key=lambda x: -x[1])
                            rows_data = [r for r, _ in scored[:top_k]]
                            # 유사도 점수를 결과에 포함
                            for (r, s), rd in zip(scored[:top_k], rows_data):
                                rd['_score'] = round(s, 4)
                        else:
                            # 임베딩 모델 미로드 → 키워드 폴백
                            pattern = f'%{q}%'
                            if proj_filter:
                                rows_raw = conn.execute(
                                    'SELECT * FROM memory WHERE project=? AND '
                                    '(key LIKE ? OR title LIKE ? OR content LIKE ? OR tags LIKE ?) '
                                    'ORDER BY updated_at DESC LIMIT ?',
                                    (proj_filter, pattern, pattern, pattern, pattern, top_k)
                                ).fetchall()
                            else:
                                rows_raw = conn.execute(
                                    'SELECT * FROM memory WHERE key LIKE ? OR title LIKE ? '
                                    'OR content LIKE ? OR tags LIKE ? ORDER BY updated_at DESC LIMIT ?',
                                    (pattern, pattern, pattern, pattern, top_k)
                                ).fetchall()
                            rows_data = [dict(r) for r in rows_raw]
                    else:
                        if proj_filter:
                            rows_raw = conn.execute(
                                'SELECT * FROM memory WHERE project=? ORDER BY updated_at DESC LIMIT ?',
                                (proj_filter, top_k)
                            ).fetchall()
                        else:
                            rows_raw = conn.execute(
                                'SELECT * FROM memory ORDER BY updated_at DESC LIMIT ?', (top_k,)
                            ).fetchall()
                        rows_data = [dict(r) for r in rows_raw]

                entries = []
                for entry in rows_data:
                    entry['tags'] = json.loads(entry.get('tags', '[]'))
                    entry.pop('embedding', None)  # bytes는 JSON 직렬화 불가 — 제거
                    entries.append(entry)
                self.wfile.write(json.dumps(entries, ensure_ascii=False).encode('utf-8'))
            except Exception as e:
                self.wfile.write(json.dumps({'error': str(e)}).encode('utf-8'))
        elif parsed_path.path == '/api/project-info':
            # 현재 서버가 서비스하는 프로젝트 정보 반환
            self.send_response(200)
            self.send_header('Content-Type', 'application/json;charset=utf-8')
            self.send_header('Access-Control-Allow-Origin', '*')
            self.end_headers()
            self.wfile.write(json.dumps({
                'project_id':   PROJECT_ID,
                'project_name': PROJECT_ROOT.name,
                'project_root': str(PROJECT_ROOT).replace('\\', '/'),
                'version':      __version__,
            }, ensure_ascii=False).encode('utf-8'))

        elif parsed_path.path == '/api/context-usage':
            # Claude Code 세션별 컨텍스트 창 사용량 반환
            # ~/.claude/projects/{PROJECT_ID}/*.jsonl 파일의 마지막 usage 필드를 파싱하여
            # 각 터미널 슬롯의 토큰 사용량을 최근 활동 순으로 반환합니다.
            self.send_response(200)
            self.send_header('Content-Type', 'application/json;charset=utf-8')
            self.send_header('Access-Control-Allow-Origin', '*')
            self.end_headers()
            try:
                claude_proj_dir = Path.home() / '.claude' / 'projects' / PROJECT_ID
                sessions = []
                if claude_proj_dir.exists():
                    for jsonl_file in claude_proj_dir.glob('*.jsonl'):
                        try:
                            info = _parse_session_tail(jsonl_file)
                            if info:
                                sessions.append(info)
                        except Exception:
                            continue
                # 최근 활동(last_ts) 기준 내림차순 정렬 → 상위 8개 (최대 터미널 슬롯 수)
                sessions.sort(key=lambda s: s.get('last_ts', ''), reverse=True)
                self.wfile.write(json.dumps(
                    {'sessions': sessions[:8]}, ensure_ascii=False
                ).encode('utf-8'))
            except Exception as e:
                self.wfile.write(json.dumps(
                    {'sessions': [], 'error': str(e)}
                ).encode('utf-8'))

        elif parsed_path.path == '/api/gemini-context-usage':
            # Gemini CLI 세션별 컨텍스트 창 사용량 반환
            # ~/.gemini/tmp/{project_name}/chats/session-*.json 파일을 파싱하여
            # 각 터미널 슬롯의 토큰 사용량을 최근 활동 순으로 반환합니다.
            # [2026-02-27] Claude: 신규 추가
            self.send_response(200)
            self.send_header('Content-Type', 'application/json;charset=utf-8')
            self.send_header('Access-Control-Allow-Origin', '*')
            self.end_headers()
            try:
                # Gemini CLI는 ~/.gemini/tmp/{프로젝트명}/chats/ 에 세션 저장
                gemini_chat_dir = Path.home() / '.gemini' / 'tmp' / PROJECT_ROOT.name / 'chats'
                sessions = []
                if gemini_chat_dir.exists():
                    for json_file in gemini_chat_dir.glob('session-*.json'):
                        try:
                            info = _parse_gemini_session(json_file)
                            if info:
                                sessions.append(info)
                        except Exception:
                            continue
                # 최근 활동(last_ts) 기준 내림차순 정렬 → 상위 8개
                sessions.sort(key=lambda s: s.get('last_ts', ''), reverse=True)
                self.wfile.write(json.dumps(
                    {'sessions': sessions[:8]}, ensure_ascii=False
                ).encode('utf-8'))
            except Exception as e:
                self.wfile.write(json.dumps(
                    {'sessions': [], 'error': str(e)}
                ).encode('utf-8'))

        elif parsed_path.path == '/api/local-models':
            # [2026-03-01] Claude: 로컬/클라우드 AI 모델 호환성 위젯용 엔드포인트
            # 하드웨어(RAM, GPU) 감지 + Ollama 로컬 모델 목록 + 클라우드 모델 상태 반환
            self.send_response(200)
            self.send_header('Content-Type', 'application/json;charset=utf-8')
            self.send_header('Access-Control-Allow-Origin', '*')
            self.end_headers()
            import urllib.request as _urllib
            result = {"hardware": {"ram_gb": 0, "gpus": []}, "models": [], "ollama_available": False, "error": None}
            # 1) RAM 감지 (Windows wmic)
            # CREATE_NO_WINDOW: wmic 실행 시 콘솔 창이 순간 뜨는 문제 방지
            _no_window = getattr(subprocess, 'CREATE_NO_WINDOW', 0x08000000)
            try:
                mem = subprocess.run(
                    ['wmic', 'OS', 'get', 'TotalVisibleMemorySize', '/value'],
                    capture_output=True, text=True, encoding='utf-8', timeout=5,
                    creationflags=_no_window
                )
                for line in mem.stdout.split('\n'):
                    if 'TotalVisibleMemorySize=' in line:
                        kb = int(line.split('=')[1].strip())
                        result["hardware"]["ram_gb"] = round(kb / 1024 / 1024, 1)
            except Exception:
                pass
            # 2) GPU 감지 (nvidia-smi — 없으면 빈 배열)
            try:
                gpu = subprocess.run(
                    ['nvidia-smi', '--query-gpu=name,memory.total', '--format=csv,noheader,nounits'],
                    capture_output=True, text=True, encoding='utf-8', timeout=5,
                    creationflags=_no_window
                )
                if gpu.returncode == 0:
                    for line in gpu.stdout.strip().split('\n'):
                        parts = line.split(',')
                        if len(parts) >= 2:
                            result["hardware"]["gpus"].append({
                                "name": parts[0].strip(),
                                "vram_gb": round(int(parts[1].strip()) / 1024, 1)
                            })
            except Exception:
                pass
            # 3) Ollama 로컬 모델 목록 (localhost:11434)
            try:
                with _urllib.urlopen('http://localhost:11434/api/tags', timeout=3) as resp:
                    ollama_data = json.loads(resp.read().decode('utf-8'))
                    result["ollama_available"] = True
                    ram_gb = result["hardware"]["ram_gb"]
                    for m in ollama_data.get('models', []):
                        size_gb = round(m.get('size', 0) / 1024 / 1024 / 1024, 1)
                        # VRAM이 있으면 VRAM 기준, 없으면 RAM 기준으로 호환 여부 판정
                        gpus = result["hardware"]["gpus"]
                        if gpus:
                            fits = size_gb < gpus[0]["vram_gb"] * 0.9
                        elif ram_gb > 0:
                            fits = size_gb < ram_gb * 0.7
                        else:
                            fits = None
                        result["models"].append({
                            "name": m.get("name", ""),
                            "size_gb": size_gb,
                            "source": "ollama",
                            "fits": fits
                        })
            except Exception as e:
                result["ollama_error"] = str(e)
            self.wfile.write(json.dumps(result, ensure_ascii=False).encode('utf-8'))

        elif parsed_path.path == '/api/hive/logs':
            # 하이브 통합 로그 조회 (SQLite session_logs)
            self.send_response(200)
            self.send_header('Content-Type', 'application/json;charset=utf-8')
            self.send_header('Access-Control-Allow-Origin', '*')
            self.end_headers()
            try:
                conn_h = sqlite3.connect(str(DATA_DIR / 'hive_mind.db'), timeout=5, check_same_thread=False)
                conn_h.row_factory = sqlite3.Row
                # 최근 200개 로그 조회
                logs = conn_h.execute(
                    "SELECT * FROM session_logs ORDER BY ts_start DESC LIMIT 200"
                ).fetchall()
                conn_h.close()
                self.wfile.write(json.dumps([dict(r) for r in logs], ensure_ascii=False).encode('utf-8'))
            except Exception as e:
                self.wfile.write(json.dumps({'error': str(e)}).encode('utf-8'))

        elif parsed_path.path == '/api/hive/health':
            # 하이브 시스템 건강 상태 진단
            # hive_health.json(워치독 엔진 상태) + 파일 존재 여부 실시간 검사를 병합하여 반환
            self.send_response(200)
            self.send_header('Content-Type', 'application/json;charset=utf-8')
            self.send_header('Access-Control-Allow-Origin', '*')
            self.end_headers()

            def check_exists(p): return Path(p).exists()

            # hive_health.json에서 워치독 엔진 상태(DB, 에이전트, 복구 횟수) 로드
            # 파일이 없으면 실제 DB 파일 존재 여부로 기본값 생성
            engine_data = {}
            health_file = DATA_DIR / "hive_health.json"
            if health_file.exists():
                try:
                    with open(health_file, 'r', encoding='utf-8') as f:
                        engine_data = json.load(f)
                except: pass
            if 'db_ok' not in engine_data:
                # watchdog 미실행 상태 — 실제 DB 파일 존재 여부로 대체 판단
                engine_data['db_ok'] = (DATA_DIR / 'shared_memory.db').exists() and (DATA_DIR / 'hive_mind.db').exists()
                engine_data.setdefault('agent_active', False)
                engine_data.setdefault('repair_count', 0)

            # 현재 활성 프로젝트 경로 동적 조회 (UI에서 변경한 경로 즉시 반영)
            # 배포 버전에서 PROJECT_ROOT가 exe 폴더로 잘못 설정될 때도 정확한 경로 사용
            _proj = _current_project_root()

            # 파일 존재 여부 실시간 검사 결과와 병합
            health = {
                **engine_data,
                "constitution": {
                    "rules_md": check_exists(_proj / "RULES.md"),
                    "gemini_md": check_exists(_proj / "GEMINI.md"),
                    "claude_md": check_exists(_proj / "CLAUDE.md"),
                    "project_map": check_exists(_proj / "PROJECT_MAP.md")
                },
                "skills": {
                    "master": check_exists(_proj / ".gemini/skills/master/SKILL.md"),
                    "brainstorm": check_exists(_proj / ".gemini/skills/brainstorming/SKILL.md"),
                    "memory_script": check_exists(SCRIPTS_DIR / "memory.py")
                },
                "agents": {
                    "claude_config": check_exists(_proj / ".claude/commands/vibe-master.md"),
                    "gemini_config": check_exists(_proj / ".gemini/settings.json")
                },
                "data": {
                    "shared_memory": check_exists(DATA_DIR / "shared_memory.db"),
                    "hive_db": check_exists(DATA_DIR / "hive_mind.db")
                }
            }
            self.wfile.write(json.dumps(health, ensure_ascii=False).encode('utf-8'))
        elif parsed_path.path == '/api/mcp/catalog':
            # MCP 카탈로그 — 내장 큐레이션 목록 반환
            self.send_response(200)
            self.send_header('Content-Type', 'application/json;charset=utf-8')
            self.send_header('Access-Control-Allow-Origin', '*')
            self.end_headers()
            catalog = [
                {
                    "name": "context7",
                    "package": "@upstash/context7-mcp",
                    "description": "최신 라이브러리 공식 문서를 실시간으로 조회합니다",
                    "category": "문서",
                    "args": [],
                },
                {
                    "name": "github",
                    "package": "@modelcontextprotocol/server-github",
                    "description": "GitHub API — 이슈, PR, 저장소 조회·관리",
                    "category": "개발",
                    "requiresEnv": ["GITHUB_PERSONAL_ACCESS_TOKEN"],
                    "args": [],
                },
                {
                    "name": "memory",
                    "package": "@modelcontextprotocol/server-memory",
                    "description": "세션 간 메모리를 유지합니다 (지식 그래프 기반)",
                    "category": "AI",
                    "args": [],
                },
                {
                    "name": "fetch",
                    "package": "@modelcontextprotocol/server-fetch",
                    "description": "URL에서 웹페이지 내용을 가져와 마크다운으로 변환합니다",
                    "category": "검색",
                    "args": [],
                },
                {
                    "name": "playwright",
                    "package": "@playwright/mcp",
                    "description": "Playwright 브라우저 자동화 — 스크린샷, 폼 입력, 클릭",
                    "category": "브라우저",
                    "args": [],
                },
                {
                    "name": "sequential-thinking",
                    "package": "@modelcontextprotocol/server-sequential-thinking",
                    "description": "복잡한 문제를 단계적으로 분해하여 사고합니다",
                    "category": "AI",
                    "args": [],
                },
                {
                    "name": "sqlite",
                    "package": "@modelcontextprotocol/server-sqlite",
                    "description": "SQLite 데이터베이스에 직접 쿼리합니다",
                    "category": "DB",
                    "args": [],
                },
                {
                    "name": "brave-search",
                    "package": "@modelcontextprotocol/server-brave-search",
                    "description": "Brave Search API로 웹 검색합니다",
                    "category": "검색",
                    "requiresEnv": ["BRAVE_API_KEY"],
                    "args": [],
                },
            ]
            self.wfile.write(json.dumps(catalog, ensure_ascii=False).encode('utf-8'))

        elif parsed_path.path == '/api/mcp/apikey':
            # Smithery API 키 조회
            self.send_response(200)
            self.send_header('Content-Type', 'application/json;charset=utf-8')
            self.send_header('Access-Control-Allow-Origin', '*')
            self.end_headers()
            key = _smithery_api_key()
            # 키가 있으면 앞 6자리만 노출 (보안)
            masked = (key[:6] + '…' + key[-4:]) if len(key) > 12 else ('*' * len(key) if key else '')
            self.wfile.write(json.dumps({'has_key': bool(key), 'masked': masked}).encode('utf-8'))

        elif parsed_path.path == '/api/mcp/search':
            # Smithery 레지스트리 검색 — ?q=...&page=1&pageSize=20
            self.send_response(200)
            self.send_header('Content-Type', 'application/json;charset=utf-8')
            self.send_header('Access-Control-Allow-Origin', '*')
            self.end_headers()
            query   = parse_qs(parsed_path.query)
            q       = query.get('q',        [''])[0].strip()
            page    = int(query.get('page',     ['1'])[0])
            page_sz = int(query.get('pageSize', ['20'])[0])
            api_key = _smithery_api_key()
            if not api_key:
                self.wfile.write(json.dumps({'error': 'NO_KEY', 'message': 'Smithery API 키가 설정되지 않았습니다'}).encode('utf-8'))
                return
            if not q:
                self.wfile.write(json.dumps({'servers': [], 'pagination': {'currentPage': 1, 'totalPages': 0, 'totalCount': 0}}).encode('utf-8'))
                return
            try:
                params = urlencode({'q': q, 'page': page, 'pageSize': page_sz})
                req = urllib.request.Request(
                    f'https://registry.smithery.ai/servers?{params}',
                    headers={'Authorization': f'Bearer {api_key}', 'Accept': 'application/json'},
                )
                with urllib.request.urlopen(req, timeout=10) as resp:
                    data = json.loads(resp.read().decode('utf-8'))
                self.wfile.write(json.dumps(data, ensure_ascii=False).encode('utf-8'))
            except urllib.error.HTTPError as e:
                code = e.code
                msg = 'API 키가 유효하지 않습니다' if code == 401 else f'Smithery API 오류 ({code})'
                self.wfile.write(json.dumps({'error': f'HTTP_{code}', 'message': msg}).encode('utf-8'))
            except Exception as e:
                self.wfile.write(json.dumps({'error': 'NETWORK', 'message': str(e)}).encode('utf-8'))

        elif parsed_path.path == '/api/mcp/installed':
            # 설치 현황 조회 — ?tool=claude|gemini&scope=global|project
            self.send_response(200)
            self.send_header('Content-Type', 'application/json;charset=utf-8')
            self.send_header('Access-Control-Allow-Origin', '*')
            self.end_headers()
            query = parse_qs(parsed_path.query)
            tool  = query.get('tool',  ['claude'])[0]   # claude | gemini
            scope = query.get('scope', ['global'])[0]   # global | project
            config_path = _mcp_config_path(tool, scope)
            try:
                if config_path.exists():
                    data = json.loads(config_path.read_text(encoding='utf-8'))
                    installed = list(data.get('mcpServers', {}).keys())
                else:
                    installed = []
                self.wfile.write(json.dumps({'installed': installed}, ensure_ascii=False).encode('utf-8'))
            except Exception as e:
                self.wfile.write(json.dumps({'installed': [], 'error': str(e)}).encode('utf-8'))

        elif parsed_path.path == '/api/superpowers/status':
            # Vibe Coding 자체 스킬 설치 상태 조회
            # Claude: PROJECT_ROOT/.claude/commands/vibe-master.md 존재 여부 (프로젝트별)
            # Gemini: 현재 프로젝트 .gemini/skills/master/SKILL.md 존재 여부 (프로젝트별)
            self.send_response(200)
            self.send_header('Content-Type', 'application/json;charset=utf-8')
            self.send_header('Access-Control-Allow-Origin', '*')
            self.end_headers()
            VIBE_SKILL_NAMES = ['master', 'brainstorm', 'debug', 'write-plan', 'execute-plan', 'tdd', 'code-review']
            # 현재 활성 프로젝트 경로 동적 조회 (배포 버전 호환)
            _proj = _current_project_root()
            # Claude: 프로젝트별 설치 — {현재프로젝트}/.claude/commands/vibe-master.md 존재 여부로 판단
            claude_cmd_dir = _proj / '.claude' / 'commands'
            claude_installed = (claude_cmd_dir / 'vibe-master.md').exists()
            claude_skills = [f.stem.replace('vibe-', '') for f in claude_cmd_dir.glob('vibe-*.md')] if claude_installed else []
            # Gemini: 현재 프로젝트 .gemini/skills/master 존재 여부로 판단
            gemini_skills_dir = _proj / '.gemini' / 'skills'
            gemini_installed = (gemini_skills_dir / 'master' / 'SKILL.md').exists()
            gemini_skills = [d.name for d in gemini_skills_dir.iterdir() if d.is_dir() and (d / 'SKILL.md').exists()] if gemini_installed and gemini_skills_dir.exists() else []
            result = {
                'claude': {
                    'installed': claude_installed,
                    'version': 'vibe-skills' if claude_installed else None,
                    'skills': claude_skills,
                    'commands': [f'/vibe-{s}' for s in VIBE_SKILL_NAMES],
                    'repo': 'btsky99/vibe-coding (내장)',
                },
                'gemini': {
                    'installed': gemini_installed,
                    'version': 'vibe-skills' if gemini_installed else None,
                    'skills': gemini_skills,
                    'commands': [f'/{s}' for s in VIBE_SKILL_NAMES],
                    'repo': 'btsky99/vibe-coding (내장)',
                },
            }
            self.wfile.write(json.dumps(result, ensure_ascii=False).encode('utf-8'))

        elif parsed_path.path == '/api/skill-results':
            # 스킬 오케스트레이터 실행 결과 조회 (최근 50개)
            # skill_orchestrator.py가 skill_results.jsonl에 저장한 세션별 결과 반환
            self.send_response(200)
            self.send_header('Content-Type', 'application/json;charset=utf-8')
            self.send_header('Access-Control-Allow-Origin', '*')
            self.end_headers()
            try:
                results_file = DATA_DIR / 'skill_results.jsonl'
                rows = []
                if results_file.exists():
                    for line in results_file.read_text(encoding='utf-8').splitlines():
                        line = line.strip()
                        if line:
                            try:
                                rows.append(json.loads(line))
                            except json.JSONDecodeError:
                                pass
                # 최신 50개만 반환 (최신순)
                rows = rows[-50:][::-1]
                self.wfile.write(json.dumps(rows, ensure_ascii=False).encode('utf-8'))
            except Exception as e:
                self.wfile.write(json.dumps({'error': str(e)}).encode('utf-8'))

        else:
            # 정적 파일 서비스 로직 (Vite 빌드 결과물)
            # 요청 경로를 정리
            path = self.path
            if path == '/':
                path = '/index.html'
            
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
        
        # ─── 신규: 사고 과정 로그 추가 (v5.0) ───
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
                    emb  = _embed(f"{title}\n{content}")

                    with _memory_conn() as conn:
                        conn.execute(
                            'INSERT OR REPLACE INTO memory '
                            '(key,id,title,content,tags,author,timestamp,updated_at,project,embedding) '
                            'VALUES (?,?,?,?,?,?,?,?,?,?)',
                            (key, ts_ms, title, content,
                             json.dumps(tags, ensure_ascii=False),
                             agent, data['timestamp'], data['timestamp'],
                             PROJECT_ID, emb)
                        )
                    

                    print(f"🧠 [Thought→DB] {key} (임베딩: {'✓' if emb else '✗'})")
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
        # /api/mcp/apikey, /api/mcp/install, /api/mcp/uninstall
        elif parsed_path.path.startswith('/api/mcp/'):
            from api import mcp_api
            content_length = int(self.headers.get('Content-Length', 0))
            _body = json.loads(self.rfile.read(content_length).decode('utf-8')) if content_length else {}
            mcp_api.handle_post(
                self, parsed_path.path, _body,
                _smithery_api_key_setter=_SMITHERY_CFG,
                _mcp_config_path=_mcp_config_path,
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
                    processed_cmd = command.replace('\n', '\r\n')
                    final_cmd = processed_cmd if processed_cmd.endswith('\r\n') or processed_cmd.endswith('\r') else processed_cmd + '\r\n'
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
                }

                # 기존 작업 목록 읽기 후 새 항목 추가
                tasks = []
                if TASKS_FILE.exists():
                    with open(TASKS_FILE, 'r', encoding='utf-8') as f:
                        tasks = json.load(f)
                tasks.append(task)
                with open(TASKS_FILE, 'w', encoding='utf-8') as f:
                    json.dump(tasks, f, ensure_ascii=False, indent=2)

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
                tasks = []
                if TASKS_FILE.exists():
                    with open(TASKS_FILE, 'r', encoding='utf-8') as f:
                        tasks = json.load(f)

                updated_task = None
                for i, t in enumerate(tasks):
                    if t['id'] == task_id:
                        # 허용된 필드만 업데이트 (임의 키 주입 방지)
                        for key in ('status', 'assigned_to', 'priority', 'title', 'description'):
                            if key in data:
                                tasks[i][key] = str(data[key])
                        tasks[i]['updated_at'] = time.strftime('%Y-%m-%dT%H:%M:%S')
                        updated_task = tasks[i]
                        break

                with open(TASKS_FILE, 'w', encoding='utf-8') as f:
                    json.dump(tasks, f, ensure_ascii=False, indent=2)

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
                tasks = []
                if TASKS_FILE.exists():
                    with open(TASKS_FILE, 'r', encoding='utf-8') as f:
                        tasks = json.load(f)

                tasks = [t for t in tasks if t['id'] != task_id]
                with open(TASKS_FILE, 'w', encoding='utf-8') as f:
                    json.dump(tasks, f, ensure_ascii=False, indent=2)

                self.wfile.write(json.dumps({'status': 'success'}, ensure_ascii=False).encode('utf-8'))
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
                # 소스: APPDATA DB / 타겟: 현재 프로젝트 로컬 DB
                src_db_path = str(MEMORY_DB)  # 서버 시작 시 결정된 DB (APPDATA 또는 로컬)
                # 현재 로컬 DB 경로 결정 (_memory_conn 로직과 동일)
                tgt_db_path = src_db_path
                if CONFIG_FILE.exists():
                    cfg_data = json.loads(CONFIG_FILE.read_text(encoding='utf-8'))
                    last_path = cfg_data.get('last_path', '')
                    if last_path:
                        local_db = Path(last_path) / ".ai_monitor" / "data" / "shared_memory.db"
                        if local_db.exists():
                            tgt_db_path = str(local_db)
                merged = 0
                skipped = 0
                if src_db_path != tgt_db_path:
                    # 두 DB가 다를 때만 동기화 의미 있음
                    src_conn = sqlite3.connect(src_db_path, timeout=5)
                    src_conn.row_factory = sqlite3.Row
                    tgt_conn = sqlite3.connect(tgt_db_path, timeout=5)
                    tgt_conn.row_factory = sqlite3.Row
                    try:
                        src_rows = src_conn.execute('SELECT * FROM memory').fetchall()
                        for row in src_rows:
                            key = row['key']
                            src_updated = row['updated_at'] or ''
                            # 타겟에 같은 key가 있는지 확인
                            existing = tgt_conn.execute(
                                'SELECT updated_at FROM memory WHERE key=?', (key,)
                            ).fetchone()
                            if existing is None or (existing['updated_at'] or '') < src_updated:
                                # 타겟에 없거나 더 오래됐으면 병합
                                tgt_conn.execute('''
                                    INSERT OR REPLACE INTO memory
                                    (key, id, title, content, tags, author, project, embedding, created_at, updated_at)
                                    VALUES (?,?,?,?,?,?,?,?,?,?)
                                ''', (
                                    row['key'], row['id'], row['title'], row['content'],
                                    row['tags'], row['author'], row['project'],
                                    row['embedding'] if 'embedding' in row.keys() else None,
                                    row['created_at'], row['updated_at'],
                                ))
                                merged += 1
                            else:
                                skipped += 1
                        tgt_conn.commit()
                    finally:
                        src_conn.close()
                        tgt_conn.close()
                    msg = f'동기화 완료: {merged}개 병합, {skipped}개 최신 유지'
                else:
                    msg = '로컬 DB와 APPDATA DB가 동일하여 동기화 불필요'
                self.wfile.write(json.dumps(
                    {'status': 'ok', 'message': msg, 'merged': merged, 'skipped': skipped},
                    ensure_ascii=False
                ).encode('utf-8'))
            except Exception as e:
                self.wfile.write(json.dumps(
                    {'status': 'error', 'message': str(e)}
                ).encode('utf-8'))

        elif parsed_path.path == '/api/memory/set':
            # 공유 메모리 항목 저장/갱신 — key 기준 UPSERT (SQLite INSERT OR REPLACE)
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
                entry = {
                    'key':        key,
                    'id':         str(int(time.time() * 1000)),
                    'title':      title,
                    'content':    content,
                    'tags':       json.dumps(data.get('tags', []), ensure_ascii=False),
                    'author':     str(data.get('author', 'unknown')),
                    'timestamp':  now,
                    'updated_at': now,
                    'project':    project,
                }

                # 임베딩 생성 (백그라운드 스레드에서 비동기로 수행해도 되지만
                # 여기서는 단순화를 위해 동기 처리 — 보통 0.05초 이내)
                emb = _embed(f"{title}\n{content}")

                with _memory_conn() as conn:
                    # 기존 항목이면 timestamp(최초)는 유지, updated_at만 갱신
                    existing = conn.execute('SELECT timestamp FROM memory WHERE key=?', (key,)).fetchone()
                    if existing:
                        entry['timestamp'] = existing['timestamp']
                    conn.execute(
                        'INSERT OR REPLACE INTO memory '
                        '(key,id,title,content,tags,author,timestamp,updated_at,project,embedding) '
                        'VALUES (?,?,?,?,?,?,?,?,?,?)',
                        (entry['key'], entry['id'], entry['title'], entry['content'],
                         entry['tags'], entry['author'], entry['timestamp'], entry['updated_at'],
                         entry['project'], emb)
                    )

                entry['tags'] = json.loads(entry['tags'])
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
                with _memory_conn() as conn:
                    conn.execute('DELETE FROM memory WHERE key=?', (key,))
                
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

async def pty_handler(websocket):
    try:
        path = websocket.request.path
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

        # [개선] 윈도우 터미널 한글 지원을 위해 환경 변수 및 인코딩 설정 강제
        env = os.environ.copy()
        env["PYTHONIOENCODING"] = "utf-8"
        env["LANG"] = "ko_KR.UTF-8"
        
        pty = PtyProcess.spawn('cmd.exe', cwd=cwd, dimensions=(rows, cols), env=env)
        
        # [추가] 터미널 시작 직후 UTF-8로 코드페이지 변경
        pty.write("chcp 65001\r\n")
        pty.write("cls\r\n")
        
        is_yolo = qs.get('yolo', ['false'])[0].lower() == 'true'

        # ── session_id를 에이전트 실행 전에 먼저 계산 ──────────────────────────
        # TERMINAL_ID/HIVE_AGENT 환경변수 주입에 session_id가 필요하므로 순서 이동.
        match = re.search(r'/pty/slot(\d+)', path)
        if match:
            # UI의 Terminal 1, Terminal 2 와 맞추기 위해 slot + 1 을 ID로 사용
            session_id = str(int(match.group(1)) + 1)
        else:
            session_id = str(id(websocket))

        if agent == 'claude':
            # 클로드는 --dangerously-skip-permissions 플래그 지원 (YOLO)
            yolo_flag = " --dangerously-skip-permissions" if is_yolo else ""
            # TERMINAL_ID/HIVE_AGENT 자동 주입 — skill_orchestrator가 --terminal 없이도 올바른 터미널로 저장되도록 함
            pty.write(f'set TERMINAL_ID={session_id}\r\n')
            pty.write(f'set HIVE_AGENT=claude\r\n')
            pty.write(f'claude{yolo_flag}\r\n')
        elif agent == 'gemini':
            # 제미나이는 -y 또는 --yolo 플래그 지원
            yolo_flag = " -y" if is_yolo else ""
            # TERMINAL_ID/HIVE_AGENT 자동 주입 — skill_orchestrator가 --terminal 없이도 올바른 터미널로 저장되도록 함
            pty.write(f'set TERMINAL_ID={session_id}\r\n')
            pty.write(f'set HIVE_AGENT=gemini\r\n')
            pty.write(f'gemini{yolo_flag}\r\n')

        # 슬롯별 에이전트 실시간 감지를 위해 agent/yolo 정보도 함께 저장
        pty_sessions[session_id] = {'pty': pty, 'agent': agent, 'yolo': is_yolo, 'started': datetime.now().isoformat()}

        # ── [세션 시작 로그] ──────────────────────────────────────────────
        # PTY 터미널에서 에이전트가 시작될 때 즉시 session_logs에 기록.
        # 이를 통해 대시보드가 Gemini/Claude 작업 시작 시점을 즉각 인지 가능.
        # 강제 종료 감지를 위한 기준점 역할도 수행.
        if agent:
            try:
                from src.db_helper import insert_log as _db_insert_log
                mode_tag = "[YOLO]" if is_yolo else "[일반]"
                _db_insert_log(
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

    async def read_from_pty():
        loop = asyncio.get_running_loop()
        while True:
            try:
                data = await loop.run_in_executor(None, pty.read, 4096)
                if not data:
                    await asyncio.sleep(0.01)
                    continue
                await websocket.send(data)
            except EOFError:
                print("PTY read EOFError")
                break
            except Exception as e:
                print("PTY read Exception:", e)
                break

    async def read_from_ws():
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
                    if message == "\r":
                        pty.write("\r")
                    else:
                        # 일반 텍스트 입력의 경우 개행 문자를 \r로 통일하여 전송
                        processed = message.replace('\r\n', '\r').replace('\n', '\r')
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

# 포트 설정: 9571(HTTP) / 9572(WS) — 충돌 시 빈 포트 자동 탐색 (최대 20개)
# 9571/9572는 IANA 미등록 범위로 일반 앱과 충돌이 적음
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

HTTP_PORT = _find_free_port(9571)
WS_PORT = _find_free_port(HTTP_PORT + 1)  # HTTP 포트 다음부터 탐색 — 포트 충돌 방지

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

    if os.name == 'nt':
        try:
            import ctypes
            import ctypes.wintypes

            # ── 단일 인스턴스 강제 (Named Mutex) ──────────────────────────
            # 이미 실행 중인 인스턴스가 있으면 해당 창을 앞으로 가져오고 종료.
            # ERROR_ALREADY_EXISTS(183) 코드로 중복 실행 여부를 판단한다.
            _MUTEX_NAME = "Global\\VibeCodingAppMutex_v1"
            _mutex_handle = ctypes.windll.kernel32.CreateMutexW(None, True, _MUTEX_NAME)
            if ctypes.windll.kernel32.GetLastError() == 183:  # ERROR_ALREADY_EXISTS
                # 기존 창을 최상단으로 올리기
                _hwnd = ctypes.windll.user32.FindWindowW(None, "바이브 코딩")
                if _hwnd:
                    ctypes.windll.user32.ShowWindow(_hwnd, 9)   # SW_RESTORE
                    ctypes.windll.user32.SetForegroundWindow(_hwnd)
                print("[!] 이미 실행 중인 Vibe Coding 인스턴스가 있습니다. 종료합니다.")
                os._exit(0)
            # ──────────────────────────────────────────────────────────────

            myappid = f'com.vibe.coding.{__version__}'
            ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID(myappid)
        except: pass

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
    
    # 실시간 파일 감시 시작
    start_fs_watcher(PROJECT_ROOT)

    MemoryWatcher().start()  # 에이전트 메모리 파일 → shared_memory.db 자동 동기화
    
    # 하이브 워치독(Watchdog) 엔진 실행
    # --data-dir 인자로 실제 DATA_DIR 전달 — 설치 버전에서 경로 오탐 방지
    def run_watchdog():
        watchdog_script = SCRIPTS_DIR / "hive_watchdog.py"
        if watchdog_script.exists():
            # 윈도우 환경에서 CP949 인코딩 에러 방지를 위해 encoding 및 errors 설정 추가
            # CREATE_NO_WINDOW: 워치독 데몬 시작 시 콘솔 창 표시 방지
            subprocess.Popen(
                [sys.executable, str(watchdog_script), "--data-dir", str(DATA_DIR)],
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
                encoding='utf-8',
                errors='replace',
                creationflags=getattr(subprocess, 'CREATE_NO_WINDOW', 0x08000000)
            )
    threading.Thread(target=run_watchdog, daemon=True).start()
    
    # 2. HTTP 서버 시작 (포트 충돌 시 자동 탐색된 포트로 재시도)
    try:
        server = ThreadedHTTPServer(('0.0.0.0', HTTP_PORT), SSEHandler)
        print(f"[*] Server running on http://localhost:{HTTP_PORT}")
        threading.Thread(target=server.serve_forever, daemon=True).start()
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
                    
                    # 바이브 코딩 창 핸들 찾기
                    hwnd = ctypes.windll.user32.FindWindowW(None, "바이브 코딩")
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
        main_window = webview.create_window('바이브 코딩', f"http://localhost:{HTTP_PORT}", 
                              width=1400, height=900)
        
        # 아이콘 교체 스레드 별도 실행
        threading.Thread(target=force_win32_icon, daemon=True).start()
        
        webview.start()
        # 창 닫힘 = 서버 소켓 정상 종료 후 프로세스 종료
        # os._exit()는 소켓을 강제 종료 → 포트 TIME_WAIT 잔류 원인
        # server.shutdown() + server_close()로 포트를 먼저 해제한 뒤 종료
        print("[*] GUI 창이 닫혔습니다. 서버 소켓 종료 중...")
        try:
            server.shutdown()
            server.server_close()
        except Exception:
            pass
        print("[*] 프로세스를 종료합니다.")
        os._exit(0)
    except Exception as e:
        print(f"[!] GUI Error: {e}")
        open_app_window(f"http://localhost:{HTTP_PORT}")
        while True: time.sleep(10)
