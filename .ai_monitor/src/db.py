# ------------------------------------------------------------------------
# 📄 파일명: db.py
# 📂 메인 문서 링크: docs/README.md
# 🔗 개별 상세 문서: docs/db.py.md
# 📝 설명: 하이브 마인드의 데이터 저장소를 관리하는 SQLite 데이터베이스 모듈.
#          다중 에이전트 동시 접근을 처리하기 위해 WAL(Write-Ahead Logging) 모드를 사용합니다.
# ------------------------------------------------------------------------

import sqlite3
import json
import os
import sys
from pathlib import Path
from datetime import datetime
import time

def _find_project_root() -> Path:
    """현재 실행 위치에서 위로 올라가며 프로젝트 루트를 탐색합니다."""
    # 1. 환경 변수 확인 (가장 확실함)
    if os.getenv('VIBE_PROJECT_ROOT'):
        return Path(os.getenv('VIBE_PROJECT_ROOT'))
    
    # 2. 실행 위치 또는 소스 파일 위치 기준 탐색
    start_path = Path(sys.executable).resolve().parent if getattr(sys, 'frozen', False) else Path(__file__).resolve().parent.parent.parent
    markers = ['.git', 'CLAUDE.md', 'GEMINI.md']
    for p in [start_path, *start_path.parents]:
        if any((p / m).exists() for m in markers):
            return p
    return start_path

PROJECT_ROOT = _find_project_root()

# 데이터 디렉토리 설정 (server.py와 로직 동기화)
if getattr(sys, 'frozen', False):
    # [수정] 배포 버전에서도 프로젝트 로컬 데이터를 우선 사용
    _local_data = PROJECT_ROOT / ".ai_monitor" / "data"
    if _local_data.exists():
        DATA_DIR = _local_data
    elif os.name == 'nt':
        DATA_DIR = Path(os.getenv('APPDATA', '')) / "VibeCoding"
    else:
        DATA_DIR = Path.home() / ".vibe-coding"
else:
    # 개발 모드: 소스 폴더 내의 data 사용
    DATA_DIR = Path(__file__).resolve().parent.parent / "data"

if not DATA_DIR.exists():
    try:
        os.makedirs(DATA_DIR, exist_ok=True)
    except:
        # 권한 문제 시 APPDATA로 폴백
        if os.name == 'nt':
            DATA_DIR = Path(os.getenv('APPDATA', '')) / "VibeCoding"
            os.makedirs(DATA_DIR, exist_ok=True)

DB_FILE = DATA_DIR / "hive_mind.db"

def get_connection():
    """데이터베이스 커넥션을 반환하고 WAL 모드를 활성화합니다."""
    # timeout: 락(lock) 발생 시 최대 대기 시간
    conn = sqlite3.connect(str(DB_FILE), timeout=10.0, check_same_thread=False)
    conn.row_factory = sqlite3.Row  # 결과를 딕셔너리처럼 접근 가능하게 설정
    
    # 동시성 성능 극대화 (Write-Ahead Logging)
    conn.execute("PRAGMA journal_mode=WAL")
    # 동기화 수준 조정 (안전성 약간 낮추고 속도 대폭 향상)
    conn.execute("PRAGMA synchronous=NORMAL")
    return conn

def init_db():
    """데이터베이스 테이블을 초기화합니다."""
    if not DATA_DIR.exists():
        os.makedirs(DATA_DIR, exist_ok=True)
        
    conn = get_connection()
    try:
        # 1. 세션/작업 로그 테이블 (기존 sessions.jsonl / task_logs.jsonl 대체)
        conn.execute('''
            CREATE TABLE IF NOT EXISTS session_logs (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                session_id TEXT NOT NULL,
                terminal_id TEXT,
                project TEXT,
                agent TEXT,
                trigger_msg TEXT,
                status TEXT,
                commit_hash TEXT,
                files_changed TEXT,  -- JSON Array
                ts_start DATETIME DEFAULT CURRENT_TIMESTAMP,
                ts_end DATETIME
            )
        ''')
        
        # 2. 에이전트 간 메시지 테이블 (기존 messages.jsonl 대체)
        conn.execute('''
            CREATE TABLE IF NOT EXISTS messages (
                id TEXT PRIMARY KEY,
                msg_from TEXT NOT NULL,
                msg_to TEXT NOT NULL,
                msg_type TEXT NOT NULL,
                content TEXT NOT NULL,
                is_read BOOLEAN DEFAULT 0,
                timestamp DATETIME DEFAULT CURRENT_TIMESTAMP
            )
        ''')
        
        # 3. 파일 락(Lock) 테이블 (기존 locks.json 대체)
        conn.execute('''
            CREATE TABLE IF NOT EXISTS file_locks (
                file_path TEXT PRIMARY KEY,
                agent TEXT NOT NULL,
                locked_at DATETIME DEFAULT CURRENT_TIMESTAMP
            )
        ''')
        
        # 인덱스 생성 (조회 성능 최적화)
        conn.execute("CREATE INDEX IF NOT EXISTS idx_session_id ON session_logs(session_id)")
        conn.execute("CREATE INDEX IF NOT EXISTS idx_msg_timestamp ON messages(timestamp DESC)")
        conn.execute("CREATE INDEX IF NOT EXISTS idx_msg_to ON messages(msg_to)")
        
        conn.commit()
    finally:
        conn.close()

if __name__ == "__main__":
    print(f"Initializing Hive Mind Database at: {DB_FILE}")
    init_db()
    print("[OK] Database initialized successfully with WAL mode.")
