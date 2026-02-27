# ------------------------------------------------------------------------
# 📄 파일명: server.py
# 🗺️ 메인 프로젝트 맵: PROJECT_MAP.md
# 📝 설명: 하이브 마인드(Gemini & Claude)의 중앙 통제 서버.
#          에이전트 간의 통신 중계, 상태 모니터링, 데이터 영속성을 관리합니다.
#
# 🕒 변경 이력 (History):
# [2026-02-26] - Gemini (하이브 에볼루션 v5.0)
#   - 사고 과정 시각화(Thought Trace)를 위한 SSE 엔진 및 로그 캡처 로직 추가.
#   - Vector DB 연동을 위한 API 엔드포인트 기초 설계.
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
from pathlib import Path

# BASE_DIR: 개발 모드에선 server.py 위치, 배포(frozen) 모드에선 PyInstaller 임시 압축 해제 폴더(sys._MEIPASS)
# 이 상수는 winpty DLL 경로 등 초기화 코드보다 반드시 먼저 정의되어야 함
if getattr(sys, 'frozen', False):
    BASE_DIR = Path(sys._MEIPASS)
else:
    BASE_DIR = Path(__file__).resolve().parent

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
    """
    log_path = Path(__file__).parent / 'data' / 'task_logs.jsonl'
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
        if any(x in path for x in ['.git', '.ai_monitor/data', '__pycache__', '.ruff_cache', '.ico', '.png', '.jpg', '.tmp', 'node_modules', 'dist', 'build']):
            return
        
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
    # 윈도우 배포 버전: %APPDATA%\VibeCoding 폴더 사용 (권한 문제 해결)
    if os.name == 'nt':
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
if getattr(sys, 'frozen', False):
    PROJECT_ROOT = Path(sys.executable).resolve().parent
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
    """요청마다 새 커넥션 생성 (스레드 안전 — ThreadedHTTPServer 대응)"""
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

def migrate_sqlite_to_vector():
    """기존 SQLite의 공유 메모리 항목 중 벡터 DB에 누락된 데이터를 마이그레이션합니다."""
    print("[Migration] SQLite -> Vector DB 초기 동기화 시작...")
    try:
        scripts_dir = str(SCRIPTS_DIR)
        if scripts_dir not in sys.path:
            sys.path.insert(0, scripts_dir)
        from vector_memory import VectorMemory
        vm = VectorMemory()
        
        # 벡터 DB에 이미 있는 ID 목록 가져오기 (중복 마이그레이션 방지)
        existing_vecs = vm.collection.get()
        existing_ids = set(existing_vecs.get('ids', []))
        
        with _memory_conn() as conn:
            rows = conn.execute('SELECT * FROM memory').fetchall()
            count = 0
            for row in rows:
                if row['key'] not in existing_ids:
                    vm.add_memory(
                        key=row['key'],
                        content=f"{row['title']}\n{row['content']}",
                        metadata={
                            "author": row['author'],
                            "project": row['project'],
                            "tags": row['tags'],
                            "updated_at": row['updated_at']
                        }
                    )
                    count += 1
            if count > 0:
                print(f"[Migration] {count}개의 항목이 벡터 DB로 성공적으로 복사되었습니다.")
            else:
                print("[Migration] 이미 모든 데이터가 동기화되어 있습니다.")
    except Exception as e:
        print(f"[Migration] 오류 발생: {e}")

_init_memory_db()
migrate_sqlite_to_vector()
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
        with _memory_conn() as conn:
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
        
        # ── Vector DB (ChromaDB) 동기화 추가 ──────────────────────────────
        try:
            scripts_dir = str(SCRIPTS_DIR)
            if scripts_dir not in sys.path:
                sys.path.insert(0, scripts_dir)
            from vector_memory import VectorMemory
            vm = VectorMemory()
            vm.add_memory(
                key=key,
                content=f"{title}\n{content}",
                metadata={
                    "author": author,
                    "project": proj,
                    "tags": ",".join(tags),
                    "updated_at": now
                }
            )
        except Exception as ve:
            print(f"[MemoryWatcher] Vector DB 동기화 실패: {ve}")

        print(f"[MemoryWatcher] 동기화 완료: {key} (프로젝트: {proj}, 임베딩: {'✓' if emb else '✗'})")

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

# ── MCP 설정 파일 경로 헬퍼 ──────────────────────────────────────────────────
def _mcp_config_path(tool: str, scope: str) -> Path:
    """
    도구(tool)와 범위(scope)에 따른 MCP 설정 파일 경로를 반환합니다.
    - claude / global  → ~/.claude/settings.json
    - claude / project → {프로젝트루트}/.claude/settings.local.json
    - gemini / global  → ~/.gemini/settings.json
    - gemini / project → {프로젝트루트}/.gemini/settings.json
    """
    home = Path.home()
    project_root = BASE_DIR.parent  # .ai_monitor의 부모 = 프로젝트 루트
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
                while True:
                    time.sleep(15)
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
                # 연결 유지를 위한 하트비트 루프
                while True:
                    time.sleep(15)
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
            
            while True:
                try:
                    # 새로운 로그가 있는지 확인 (last_id 보다 큰 id 조회)
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
                            
                            # 연결 상태 확인하며 전송
                            self.connection.settimeout(1.0)
                            self.wfile.write(f"data: {json.dumps(out_row, ensure_ascii=False)}\n\n".encode('utf-8'))
                            self.wfile.flush()
                        last_id = new_rows[-1]['id']
                    
                    time.sleep(1.0) # 감시 주기를 0.5s에서 1.0s로 늘려 리소스 절약
                except (BrokenPipeError, ConnectionResetError, TimeoutError):
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
                res = subprocess.run(['powershell', '-Command', ps_cmd], capture_output=True, text=True, encoding='utf-8')
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
        elif parsed_path.path == '/api/shutdown':
            self.send_response(200)
            self.send_header('Content-Type', 'application/json;charset=utf-8')
            self.send_header('Access-Control-Allow-Origin', '*')
            self.end_headers()
            self.wfile.write(json.dumps({"status": "success", "message": "Server shutting down..."}).encode('utf-8'))
            print("Shutdown requested via API. Exiting in 1 second...")
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
                        
                    result = {"status": "success", "message": f"Skills installed to {target_path}"}
                except Exception as e:
                    result = {"status": "error", "message": str(e)}
            
            self.wfile.write(json.dumps(result).encode('utf-8'))
        elif parsed_path.path == '/api/hive/skill-analysis':
            self.send_response(200)
            self.send_header('Content-Type', 'application/json;charset=utf-8')
            self.send_header('Access-Control-Allow-Origin', '*')
            self.end_headers()
            analysis_file = DATA_DIR / "skill_analysis.json"
            analysis_data = {"proposals": []}
            if analysis_file.exists():
                try:
                    with open(analysis_file, 'r', encoding='utf-8') as f:
                        analysis_data = json.load(f)
                except: pass
            self.wfile.write(json.dumps(analysis_data, ensure_ascii=False).encode('utf-8'))
        elif parsed_path.path == '/api/hive/health/repair':
            self.send_response(200)
            self.send_header('Content-Type', 'application/json;charset=utf-8')
            self.send_header('Access-Control-Allow-Origin', '*')
            self.end_headers()
            try:
                watchdog_script = SCRIPTS_DIR / "hive_watchdog.py"
                result_proc = subprocess.run(
                    [sys.executable, str(watchdog_script), "--check"],
                    capture_output=True, text=True, encoding='utf-8'
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
                    self.wfile.write(json.dumps(data).encode('utf-8'))
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

        elif parsed_path.path == '/api/apply-update':
            self.send_response(200)
            self.send_header('Content-Type', 'application/json;charset=utf-8')
            self.send_header('Access-Control-Allow-Origin', '*')
            self.end_headers()
            
            update_file = DATA_DIR / "update_ready.json"
            if not update_file.exists():
                self.wfile.write(json.dumps({"success": False, "error": "No update ready"}).encode('utf-8'))
                return
                
            try:
                with open(update_file, "r", encoding="utf-8") as f:
                    data = json.load(f)
                
                exe_path = data.get("exe_path")
                if not exe_path or not os.path.exists(exe_path):
                    self.wfile.write(json.dumps({"success": False, "error": "New executable not found"}).encode('utf-8'))
                    return
                
                self.wfile.write(json.dumps({"success": True}).encode('utf-8'))
                
                # Delete update_ready.json so it won't prompt again
                try:
                    update_file.unlink()
                except OSError:
                    pass
                
                # Import updater and apply update in background to not block response
                from updater import apply_update_from_temp
                threading.Thread(target=apply_update_from_temp, args=(Path(exe_path),), daemon=True).start()
                
            except Exception as e:
                self.wfile.write(json.dumps({"success": False, "error": str(e)}).encode('utf-8'))

        elif parsed_path.path == '/api/copy-path':
            self.send_response(200)
            self.send_header('Content-Type', 'application/json;charset=utf-8')
            self.send_header('Access-Control-Allow-Origin', '*')
            self.end_headers()
            query = parse_qs(parsed_path.query)
            target_path = query.get('path', [''])[0]
            try:
                # Windows 클립보드에 경로 복사
                if os.name == 'nt':
                    subprocess.run(['powershell', '-Command', f'Set-Clipboard -Value "{target_path}"'], check=True, encoding='utf-8')
                self.wfile.write(json.dumps({"status": "success", "message": "Path copied to clipboard"}).encode('utf-8'))
            except Exception as e:
                self.wfile.write(json.dumps({"status": "error", "message": str(e)}).encode('utf-8'))
        
        elif parsed_path.path == '/api/file-op':
            # 파일 복사/이동/삭제/생성 등 운영체제 수준 작업
            self.send_response(200)
            self.send_header('Content-Type', 'application/json;charset=utf-8')
            self.send_header('Access-Control-Allow-Origin', '*')
            self.end_headers()
            try:
                data = json.loads(self.rfile.read(int(self.headers['Content-Length'])).decode('utf-8'))
                op = data.get('op')
                src = data.get('src')
                dest = data.get('dest')
                path = data.get('path')
                
                if op == 'copy':
                    if os.path.isdir(src): shutil.copytree(src, dest, dirs_exist_ok=True)
                    else: shutil.copy2(src, dest)
                elif op == 'delete':
                    if os.path.isdir(src):
                        shutil.rmtree(src)
                    else:
                        os.remove(src)
                elif op == 'create_file':
                    # 빈 파일 생성
                    if not os.path.exists(path):
                        with open(path, 'w', encoding='utf-8') as f:
                            f.write("")
                elif op == 'create_dir':
                    # 폴더 생성
                    os.makedirs(path, exist_ok=True)
                
                self.wfile.write(json.dumps({"status": "success"}).encode('utf-8'))
            except Exception as e:
                self.wfile.write(json.dumps({"status": "error", "message": str(e)}).encode('utf-8'))

        elif parsed_path.path == '/api/save-file':
            # 파일 내용 저장
            self.send_response(200)
            self.send_header('Content-Type', 'application/json;charset=utf-8')
            self.send_header('Access-Control-Allow-Origin', '*')
            self.end_headers()
            try:
                data = json.loads(self.rfile.read(int(self.headers['Content-Length'])).decode('utf-8'))
                target_path = data.get('path')
                content = data.get('content', '')
                
                if not target_path:
                    self.wfile.write(json.dumps({"status": "error", "message": "Path is required"}).encode('utf-8'))
                    return
                
                # 디렉토리가 없으면 생성
                os.makedirs(os.path.dirname(target_path), exist_ok=True)
                
                with open(target_path, 'w', encoding='utf-8') as f:
                    f.write(content)
                
                self.wfile.write(json.dumps({"status": "success"}).encode('utf-8'))
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
                    conn_h = sqlite3.connect(str(DATA_DIR / 'hive_mind.db'), timeout=5, check_same_thread=False)
                    conn_h.row_factory = sqlite3.Row
                    for row in conn_h.execute(
                        "SELECT agent, MAX(ts_start) as last_seen FROM session_logs "
                        "WHERE agent IN ('claude','gemini') GROUP BY agent"
                    ).fetchall():
                        agent_last_seen[row['agent']] = row['last_seen']
                    conn_h.close()
                except Exception:
                    pass

                # 에이전트 상태 (active / idle / unknown)
                now_dt = datetime.now()
                agent_status = {}
                for agent, seen in agent_last_seen.items():
                    if seen is None:
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
                orch_log = DATA_DIR / 'orchestrator_log.jsonl'
                recent_actions: list = []
                if orch_log.exists():
                    for line in reversed(orch_log.read_text(encoding='utf-8').strip().splitlines()[-20:]):
                        try:
                            recent_actions.append(json.loads(line))
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

        elif parsed_path.path == '/api/vector/list':
            # 벡터 DB 전체 항목 목록 반환
            # ChromaDB에 저장된 모든 메모리를 id, content, metadata와 함께 반환합니다.
            self.send_response(200)
            self.send_header('Content-Type', 'application/json;charset=utf-8')
            self.send_header('Access-Control-Allow-Origin', '*')
            self.end_headers()
            try:
                # scripts/ 경로를 sys.path에 추가하여 vector_memory 모듈 로드
                scripts_dir = str(SCRIPTS_DIR)
                if scripts_dir not in sys.path:
                    sys.path.insert(0, scripts_dir)
                from vector_memory import VectorMemory
                vm = VectorMemory()
                raw = vm.collection.get()
                items = []
                for i, doc_id in enumerate(raw.get('ids', [])):
                    items.append({
                        'id': doc_id,
                        'content': raw['documents'][i] if raw.get('documents') else '',
                        'metadata': raw['metadatas'][i] if raw.get('metadatas') else {},
                    })
                self.wfile.write(json.dumps({'items': items}, ensure_ascii=False).encode('utf-8'))
            except ImportError:
                self.wfile.write(json.dumps({
                    'items': [], 'error': 'chromadb 미설치 — pip install chromadb'
                }, ensure_ascii=False).encode('utf-8'))
            except Exception as e:
                self.wfile.write(json.dumps({'items': [], 'error': str(e)}, ensure_ascii=False).encode('utf-8'))
        elif parsed_path.path == '/api/hive/health':
            # 하이브 시스템 건강 상태 진단
            # hive_health.json(워치독 엔진 상태) + 파일 존재 여부 실시간 검사를 병합하여 반환
            self.send_response(200)
            self.send_header('Content-Type', 'application/json;charset=utf-8')
            self.send_header('Access-Control-Allow-Origin', '*')
            self.end_headers()

            def check_exists(p): return Path(p).exists()

            # hive_health.json에서 워치독 엔진 상태(DB, 에이전트, 복구 횟수) 로드
            engine_data = {}
            health_file = DATA_DIR / "hive_health.json"
            if health_file.exists():
                try:
                    with open(health_file, 'r', encoding='utf-8') as f:
                        engine_data = json.load(f)
                except: pass

            # 파일 존재 여부 실시간 검사 결과와 병합
            health = {
                **engine_data,
                "constitution": {
                    "rules_md": check_exists(PROJECT_ROOT / "RULES.md"),
                    "gemini_md": check_exists(PROJECT_ROOT / "GEMINI.md"),
                    "claude_md": check_exists(PROJECT_ROOT / "CLAUDE.md"),
                    "project_map": check_exists(PROJECT_ROOT / "PROJECT_MAP.md")
                },
                "skills": {
                    "master": check_exists(PROJECT_ROOT / ".gemini/skills/master/SKILL.md"),
                    "brainstorm": check_exists(PROJECT_ROOT / ".gemini/skills/brainstorming/SKILL.md"),
                    "memory_script": check_exists(SCRIPTS_DIR / "memory.py")
                },
                "agents": {
                    "claude_config": check_exists(PROJECT_ROOT / ".claude/commands/vibe-master.md"),
                    "gemini_config": check_exists(PROJECT_ROOT / ".gemini/settings.json")
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
            # Claude: 프로젝트별 설치 — PROJECT_ROOT/.claude/commands/vibe-master.md 존재 여부로 판단
            claude_cmd_dir = PROJECT_ROOT / '.claude' / 'commands'
            claude_installed = (claude_cmd_dir / 'vibe-master.md').exists()
            claude_skills = [f.stem.replace('vibe-', '') for f in claude_cmd_dir.glob('vibe-*.md')] if claude_installed else []
            # Gemini: 현재 프로젝트 .gemini/skills/master 존재 여부로 판단
            gemini_skills_dir = PROJECT_ROOT / '.gemini' / 'skills'
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
                    
                    # Vector DB (ChromaDB) 동기화
                    try:
                        scripts_dir = str(SCRIPTS_DIR)
                        if scripts_dir not in sys.path:
                            sys.path.insert(0, scripts_dir)
                        from vector_memory import VectorMemory
                        vm = VectorMemory()
                        vm.add_memory(
                            key=key,
                            content=f"{title}\n{content}",
                            metadata={
                                "author": agent,
                                "project": PROJECT_ID,
                                "tags": ",".join(tags),
                                "updated_at": data['timestamp']
                            }
                        )
                    except Exception as ve:
                        print(f"🧠 [Thought→Vector] 저장 실패: {ve}")

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

        if parsed_path.path == '/api/agents/heartbeat':
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
                    pty = pty_sessions[target_slot]
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

                for pty in pty_sessions.values():
                    try:
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

                # ── Vector DB (ChromaDB) 동기화 추가 ──────────────────────────────
                try:
                    scripts_dir = str(SCRIPTS_DIR)
                    if scripts_dir not in sys.path:
                        sys.path.insert(0, scripts_dir)
                    from vector_memory import VectorMemory
                    vm = VectorMemory()
                    vm.add_memory(
                        key=key,
                        content=f"{title}\n{content}",
                        metadata={
                            "author": entry['author'],
                            "project": project,
                            "tags": ",".join(data.get('tags', [])),
                            "updated_at": now
                        }
                    )
                except Exception as ve:
                    print(f"[API] Vector DB 동기화 실패: {ve}")

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
                
                # ── Vector DB (ChromaDB) 삭제 추가 ───────────────────────────────
                try:
                    scripts_dir = str(SCRIPTS_DIR)
                    if scripts_dir not in sys.path:
                        sys.path.insert(0, scripts_dir)
                    from vector_memory import VectorMemory
                    vm = VectorMemory()
                    vm.delete_memory(key)
                except Exception as ve:
                    print(f"[API] Vector DB 삭제 실패: {ve}")

                self.wfile.write(json.dumps({'status': 'success'}, ensure_ascii=False).encode('utf-8'))
            except Exception as e:
                self.wfile.write(json.dumps({'status': 'error', 'message': str(e)}).encode('utf-8'))
        elif parsed_path.path == '/api/vector/search':
            # 벡터 DB 시맨틱 검색 — 쿼리 텍스트와 의미적으로 유사한 메모리를 찾아 반환합니다.
            # body: { "query": "검색어", "n": 5 }
            self.send_response(200)
            self.send_header('Content-Type', 'application/json;charset=utf-8')
            self.send_header('Access-Control-Allow-Origin', '*')
            self.end_headers()
            try:
                content_length = int(self.headers.get('Content-Length', 0))
                body = json.loads(self.rfile.read(content_length).decode('utf-8'))
                query = str(body.get('query', '')).strip()
                n = int(body.get('n', 5))
                if not query:
                    self.wfile.write(json.dumps({'results': [], 'error': '쿼리가 비어있습니다'}, ensure_ascii=False).encode('utf-8'))
                    return
                # scripts/ 경로를 sys.path에 추가하여 vector_memory 모듈 로드
                scripts_dir = str(SCRIPTS_DIR)
                if scripts_dir not in sys.path:
                    sys.path.insert(0, scripts_dir)
                from vector_memory import VectorMemory
                vm = VectorMemory()
                results = vm.search(query, n_results=n)
                self.wfile.write(json.dumps({'results': results}, ensure_ascii=False).encode('utf-8'))
            except ImportError:
                self.wfile.write(json.dumps({
                    'results': [], 'error': 'chromadb 미설치 — pip install chromadb'
                }, ensure_ascii=False).encode('utf-8'))
            except Exception as e:
                self.wfile.write(json.dumps({'results': [], 'error': str(e)}, ensure_ascii=False).encode('utf-8'))
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

                if tool == 'claude':
                    # 내장 스킬 소스 경로: exe 기준 BASE_DIR/../skills/claude/ 또는 개발 환경
                    import shutil as _shutil
                    skills_src = BASE_DIR / 'skills' / 'claude'
                    if not skills_src.exists():
                        skills_src = PROJECT_ROOT / 'skills' / 'claude'
                    if not skills_src.exists():
                        raise Exception('내장 스킬 파일을 찾을 수 없습니다 (skills/claude/)')
                    cmd_dir = PROJECT_ROOT / '.claude' / 'commands'
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
                    # 빌드 버전: BASE_DIR(sys._MEIPASS)에 내장된 스킬을 PROJECT_ROOT에 복사
                    # 개발 버전: PROJECT_ROOT/.gemini/skills/ 가 이미 존재하므로 소스=대상
                    import shutil as _shutil
                    gemini_skills_src = BASE_DIR / '.gemini' / 'skills'
                    if not gemini_skills_src.exists():
                        gemini_skills_src = PROJECT_ROOT / '.gemini' / 'skills'
                    if not gemini_skills_src.exists():
                        raise Exception('내장 Gemini 스킬을 찾을 수 없습니다 (.gemini/skills/)')
                    target_dir = PROJECT_ROOT / '.gemini' / 'skills'
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
                import shutil

                if tool == 'claude':
                    # 프로젝트별 설치 경로에서 제거
                    cmd_dir = PROJECT_ROOT / '.claude' / 'commands'
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

        if agent == 'claude':
            # 클로드는 --dangerously-skip-permissions 플래그 지원 (YOLO)
            yolo_flag = " --dangerously-skip-permissions" if is_yolo else ""
            pty.write(f'claude{yolo_flag}\r\n')
        elif agent == 'gemini':
            # 제미나이는 -y 또는 --yolo 플래그 지원
            yolo_flag = " -y" if is_yolo else ""
            pty.write(f'gemini{yolo_flag}\r\n')

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
WS_PORT = _find_free_port(9572)

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
    def run_watchdog():
        watchdog_script = SCRIPTS_DIR / "hive_watchdog.py"
        if watchdog_script.exists():
            subprocess.Popen([sys.executable, str(watchdog_script)])
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
        os._exit(0)  # 창 닫히면 즉시 프로세스 종료
    except Exception as e:
        print(f"[!] GUI Error: {e}")
        open_app_window(f"http://localhost:{HTTP_PORT}")
        while True: time.sleep(10)
