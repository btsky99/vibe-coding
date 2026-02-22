# ------------------------------------------------------------------------
# 📄 파일명: server.py
# 📂 메인 문서 링크: docs/README.md
# 🔗 개별 상세 문서: docs/server.py.md
# 📝 설명: 하이브 마인드의 백엔드를 담당하는 파이썬 서버 스크립트입니다. 
#          로컬 파일 시스템 접근, 정적 파일 서빙, PTY 웹소켓 통신, SSE 로그 스트리밍을 수행합니다.
# ------------------------------------------------------------------------

import json
import time
import os
import mimetypes
import webbrowser
import shutil
import subprocess
import sqlite3


def open_app_window(url):
    """Chrome/Edge 앱 모드로 열기 (주소창/탭 없이 GUI처럼 표시)"""
    chrome = shutil.which("chrome") or shutil.which("google-chrome")
    edge = shutil.which("msedge")
    # Windows 기본 경로 확인
    for path in [
        os.path.expandvars(r"%ProgramFiles%\Google\Chrome\Application\chrome.exe"),
        os.path.expandvars(r"%ProgramFiles(x86)%\Google\Chrome\Application\chrome.exe"),
        os.path.expandvars(r"%LocalAppData%\Google\Chrome\Application\chrome.exe"),
        os.path.expandvars(r"%ProgramFiles(x86)%\Microsoft\Edge\Application\msedge.exe"),
        os.path.expandvars(r"%ProgramFiles%\Microsoft\Edge\Application\msedge.exe"),
    ]:
        if os.path.isfile(path):
            if not chrome and "chrome" in path.lower():
                chrome = path
            if not edge and "edge" in path.lower():
                edge = path
    browser = chrome or edge
    if browser:
        subprocess.Popen([browser, f"--app={url}"])
    else:
        webbrowser.open(url)
from http.server import BaseHTTPRequestHandler, HTTPServer
from socketserver import ThreadingMixIn
from pathlib import Path

import sys
from _version import __version__

if getattr(sys, 'frozen', False):
    BASE_DIR = Path(sys._MEIPASS)
else:
    BASE_DIR = Path(__file__).resolve().parent

sys.path.append(str(BASE_DIR / 'src'))
from db import init_db
from db_helper import insert_log, get_recent_logs, send_message, get_messages

if sys.stdout is None:
    sys.stdout = open(os.devnull, 'w')
if sys.stderr is None:
    sys.stderr = open(os.devnull, 'w')

# 데이터 디렉토리 생성 보장 및 DB 초기화
DATA_DIR = (Path(sys.executable).resolve().parent / "data") if getattr(sys, 'frozen', False) else (BASE_DIR / "data")
if not DATA_DIR.exists():
    os.makedirs(DATA_DIR, exist_ok=True)
init_db()

# 정적 파일 경로를 절대 경로로 고정 (404 방지 핵심!)
STATIC_DIR = (BASE_DIR / "nexus-view" / "dist").resolve()
SESSIONS_FILE = DATA_DIR / "sessions.jsonl"
LOCKS_FILE = DATA_DIR / "locks.json"
# 에이전트 간 메시지 채널 파일
MESSAGES_FILE = DATA_DIR / "messages.jsonl"
# 에이전트 간 공유 작업 큐 파일 (JSON 배열 — 업데이트/삭제 지원)
TASKS_FILE = DATA_DIR / "tasks.json"
# 에이전트 간 공유 메모리/지식 베이스 (SQLite — 동시성·검색 안정성 확보)
MEMORY_DB = DATA_DIR / "shared_memory.db"

# 데이터 디렉토리 생성 보장
if not DATA_DIR.exists():
    os.makedirs(DATA_DIR, exist_ok=True)

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
    """요청마다 새 커넥션 생성 (스레드 안전 — ThreadedHTTPServer 대응)"""
    conn = sqlite3.connect(str(MEMORY_DB), timeout=5, check_same_thread=False)
    conn.row_factory = sqlite3.Row
    return conn

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
                updated_at TEXT NOT NULL
            )
        ''')
        conn.execute('CREATE INDEX IF NOT EXISTS idx_memory_author ON memory(author)')
        conn.execute('CREATE INDEX IF NOT EXISTS idx_memory_updated ON memory(updated_at)')

_init_memory_db()
# ─────────────────────────────────────────────────────────────────────────────

print("Static files directory:", STATIC_DIR)
if not STATIC_DIR.exists():
    print("WARNING: Static directory not found!")


class ThreadedHTTPServer(ThreadingMixIn, HTTPServer):
    """멀티 스레드 지원 HTTP 서버 (SSE 등 지속적 연결 동시 처리용)"""
    daemon_threads = True

last_heartbeat_time = time.time()
client_connected_once = False

def monitor_heartbeat():
    global last_heartbeat_time, client_connected_once
    while True:
        time.sleep(2)
        # 5초 이상 하트비트가 끊기면 자폭 (즉각 종료)
        if client_connected_once and (time.time() - last_heartbeat_time > 5):
            print("브라우저 창이 닫혀 하트비트가 끊어졌습니다. 서버를 자동 종료합니다...")
            os._exit(0)

import string
from urllib.parse import urlparse, parse_qs

class SSEHandler(BaseHTTPRequestHandler):
    def do_GET(self):
        parsed_path = urlparse(self.path)
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
            
            while True:
                try:
                    # 새로운 로그가 있는지 확인 (last_id 보다 큰 id 조회)
                    import sqlite3
                    conn = sqlite3.connect(str(DATA_DIR / "hive_mind.db"), timeout=5.0)
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
                    
                    time.sleep(0.5) # 감시 주기
                except (BrokenPipeError, ConnectionResetError):
                    break
                except Exception as e:
                    print(f"SSE DB Stream error: {e}")
                    time.sleep(1)
        elif parsed_path.path == '/api/heartbeat':
            global last_heartbeat_time, client_connected_once
            last_heartbeat_time = time.time()
            client_connected_once = True
            self.send_response(200)
            self.send_header('Access-Control-Allow-Origin', '*')
            self.end_headers()
            self.wfile.write(b"OK")
        elif parsed_path.path == '/api/drives':
            self.send_response(200)
            self.send_header('Content-Type', 'application/json;charset=utf-8')
            self.send_header('Access-Control-Allow-Origin', '*')
            self.end_headers()
            drives = []
            if os.name == 'nt':
                for letter in string.ascii_uppercase:
                    drive = f"{letter}:\\"
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
                import subprocess
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
                import subprocess
                # Claude Code 설치 (전역)
                subprocess.Popen('cmd.exe /k "echo Installing Claude Code... && npm install -g @anthropic-ai/claude-code"', shell=True)
                result = {"status": "success", "message": "Claude Code installation started in a new window."}
            except Exception as e:
                result = {"status": "error", "message": str(e)}
            self.wfile.write(json.dumps(result).encode('utf-8'))
        elif parsed_path.path == '/api/shutdown':
            self.send_response(200)
            self.send_header('Content-Type', 'application/json;charset=utf-8')
            self.send_header('Access-Control-Allow-Origin', '*')
            self.end_headers()
            self.wfile.write(json.dumps({"status": "success", "message": "Server shutting down..."}).encode('utf-8'))
            print("Shutdown requested via API. Exiting in 1 second...")
            import threading
            threading.Timer(1.0, lambda: os._exit(0)).start()
        elif parsed_path.path == '/api/files':
            self.send_response(200)
            self.send_header('Content-Type', 'application/json;charset=utf-8')
            self.send_header('Access-Control-Allow-Origin', '*')
            self.end_headers()
            query = parse_qs(parsed_path.query)
            target_path = query.get('path', [''])[0]
            items = []
            if target_path and os.path.exists(target_path) and os.path.isdir(target_path):
                try:
                    for entry in os.scandir(target_path):
                        if not entry.name.startswith('.'):
                            items.append({
                                "name": entry.name, 
                                "path": entry.path.replace('\\', '/'),
                                "isDir": entry.is_dir()
                            })
                except Exception:
                    pass
            # 폴더가 먼저 오도록 정렬
            items.sort(key=lambda x: (not x['isDir'], x['name'].lower()))
            self.wfile.write(json.dumps(items).encode('utf-8'))
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
                    import shutil
                    # 소스 경로 (설치된 앱의 위치 기준)
                    # .gemini, scripts, GEMINI.md 등을 복사
                    source_base = BASE_DIR.parent # 프로젝트 루트로 가정
                    
                    # .gemini 복사
                    gemini_src = source_base / ".gemini"
                    if gemini_src.exists():
                        shutil.copytree(gemini_src, Path(target_path) / ".gemini", dirs_exist_ok=True)
                    
                    # scripts 복사
                    scripts_src = source_base / "scripts"
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
                        
                    result = {"status": "success", "message": f"Skills installed to {target_path}"}
                except Exception as e:
                    result = {"status": "error", "message": str(e)}
            
            self.wfile.write(json.dumps(result).encode('utf-8'))
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
                        if entry.is_dir() and not entry.name.startswith('.'):
                            dirs.append({"name": entry.name, "path": entry.path.replace('\\', '/')})
                except Exception:
                    pass
            dirs.sort(key=lambda x: x['name'].lower())
            self.wfile.write(json.dumps(dirs).encode('utf-8'))
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
        elif parsed_path.path == '/api/locks':
            self.send_response(200)
            self.send_header('Content-Type', 'application/json;charset=utf-8')
            self.send_header('Access-Control-Allow-Origin', '*')
            self.end_headers()
            if LOCKS_FILE.exists():
                with open(LOCKS_FILE, 'r', encoding='utf-8') as f:
                    locks = json.load(f)
                self.wfile.write(json.dumps(locks).encode('utf-8'))
            else:
                self.wfile.write(json.dumps({}).encode('utf-8'))
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
                    cwd=git_path, capture_output=True, text=True, timeout=5
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
                    import re
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
                    cwd=git_path, capture_output=True, text=True, timeout=5
                )
                commits = []
                for line in result.stdout.strip().splitlines():
                    parts = line.split('\x1f')
                    if len(parts) == 4:
                        commits.append({'hash': parts[0], 'message': parts[1], 'author': parts[2], 'date': parts[3]})
                self.wfile.write(json.dumps(commits, ensure_ascii=False).encode('utf-8'))
            except Exception as e:
                self.wfile.write(json.dumps([]).encode('utf-8'))
        elif parsed_path.path == '/api/memory':
            # 공유 메모리 조회 — ?q=검색어 파라미터로 전문 검색 지원 (SQLite LIKE)
            self.send_response(200)
            self.send_header('Content-Type', 'application/json;charset=utf-8')
            self.send_header('Access-Control-Allow-Origin', '*')
            self.end_headers()
            query = parse_qs(parsed_path.query)
            q = query.get('q', [''])[0].strip()
            try:
                with _memory_conn() as conn:
                    if q:
                        # 키·제목·내용·태그 전문 검색
                        pattern = f'%{q}%'
                        rows = conn.execute(
                            'SELECT * FROM memory WHERE key LIKE ? OR title LIKE ? OR content LIKE ? OR tags LIKE ? ORDER BY updated_at DESC',
                            (pattern, pattern, pattern, pattern)
                        ).fetchall()
                    else:
                        rows = conn.execute('SELECT * FROM memory ORDER BY updated_at DESC').fetchall()
                entries = []
                for row in rows:
                    entry = dict(row)
                    entry['tags'] = json.loads(entry.get('tags', '[]'))
                    entries.append(entry)
                self.wfile.write(json.dumps(entries, ensure_ascii=False).encode('utf-8'))
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
        if parsed_path.path == '/api/launch':
            try:
                content_length = int(self.headers['Content-Length'])
                post_data = self.rfile.read(content_length)
                data = json.loads(post_data.decode('utf-8'))
                
                agent = data.get('agent')
                target_dir = data.get('path', 'C:\\')
                is_yolo = data.get('yolo', False)
                
                import subprocess
                
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
                    pty = pty_sessions[target_slot]
                    # 명령어 끝에 개행 문자가 없으면 추가하여 즉시 실행 유도
                    final_cmd = command if command.endswith('\n') or command.endswith('\r') else command + '\r\n'
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

                now   = time.strftime('%Y-%m-%dT%H:%M:%S')
                entry = {
                    'key':        key,
                    'id':         str(int(time.time() * 1000)),
                    'title':      str(data.get('title', key)).strip()[:300],
                    'content':    content,
                    'tags':       json.dumps(data.get('tags', []), ensure_ascii=False),
                    'author':     str(data.get('author', 'unknown')),
                    'timestamp':  now,
                    'updated_at': now,
                }

                with _memory_conn() as conn:
                    # 기존 항목이면 timestamp(최초)는 유지, updated_at만 갱신
                    existing = conn.execute('SELECT timestamp FROM memory WHERE key=?', (key,)).fetchone()
                    if existing:
                        entry['timestamp'] = existing['timestamp']
                    conn.execute(
                        'INSERT OR REPLACE INTO memory (key,id,title,content,tags,author,timestamp,updated_at) VALUES (?,?,?,?,?,?,?,?)',
                        (entry['key'], entry['id'], entry['title'], entry['content'],
                         entry['tags'], entry['author'], entry['timestamp'], entry['updated_at'])
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
        else:
            self.send_response(404)
            self.end_headers()

    def log_message(self, format, *args):
        # 불필요한 콘솔 로그 제거하여 터미널 깔끔하게 유지
        pass

import asyncio
import websockets
import threading
from winpty import PtyProcess

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

        pty = PtyProcess.spawn('cmd.exe', cwd=cwd, dimensions=(rows, cols))
        
        is_yolo = qs.get('yolo', ['false'])[0].lower() == 'true'

        if agent == 'claude':
            # 클로드는 --dangerously-skip-permissions 플래그 지원 (YOLO)
            yolo_flag = " --dangerously-skip-permissions" if is_yolo else ""
            pty.write(f'claude{yolo_flag}\r\n')
        elif agent == 'gemini':
            # 제미나이는 -y 또는 --yolo 플래그 지원
            yolo_flag = " -y" if is_yolo else ""
            pty.write(f'gemini{yolo_flag}\r\n')

        import re
        match = re.search(r'/pty/slot(\d+)', path)
        if match:
            # UI의 Terminal 1, Terminal 2 와 맞추기 위해 slot + 1 을 ID로 사용
            session_id = str(int(match.group(1)) + 1)
        else:
            session_id = str(id(websocket))
            
        pty_sessions[session_id] = pty

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
                if isinstance(message, str):
                    pty.write(message)
                else:
                    pty.write(message.decode('utf-8'))
            except Exception as e:
                break

    task1 = asyncio.create_task(read_from_pty())
    task2 = asyncio.create_task(read_from_ws())
    
    done, pending = await asyncio.wait([task1, task2], return_when=asyncio.FIRST_COMPLETED)
    for task in pending:
        task.cancel()
    
    try:
        pty.terminate(force=True)
    except:
        pass
    if session_id in pty_sessions:
        del pty_sessions[session_id]

# 포트 설정: 개발(8000/8001), 배포(8005/8006)
if getattr(sys, 'frozen', False):
    HTTP_PORT = 8005
    WS_PORT = 8006
else:
    HTTP_PORT = 8000
    WS_PORT = 8001

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

if __name__ == '__main__':
    print(f"Vibe Coding {__version__}")

    # --- Auto-update check (non-blocking) ---
    if getattr(sys, 'frozen', False):
        from updater import check_and_update
        update_thread = threading.Thread(
            target=check_and_update,
            args=(DATA_DIR,),
            daemon=True,
        )
        update_thread.start()

    threading.Thread(target=start_ws_server, daemon=True).start()
    threading.Thread(target=monitor_heartbeat, daemon=True).start()
    try:
        server = ThreadedHTTPServer(('0.0.0.0', HTTP_PORT), SSEHandler)
        print(f"Nexus View SSE Log Server started on port {HTTP_PORT}")
        threading.Thread(target=server.serve_forever, daemon=True).start()
        
        import webview
        webview.create_window('Nexus View', f"http://localhost:{HTTP_PORT}", width=1400, height=900)
        webview.start()
    except OSError:
        import webview
        webview.create_window('Nexus View', f"http://localhost:{HTTP_PORT}", width=1400, height=900)
        webview.start()
        sys.exit(0)
