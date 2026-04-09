# ────────────────────────────────────────────────────────────────────────────
# 📄 파일명: src/pg_store.py
# 📝 설명: PostgreSQL 저장소 — session_logs, skill_chain, 오피스 프로필 등 관리
# 🕒 변경 이력:
# [2026-04-09] Claude — 오피스 프로필 중앙화 (localStorage → PostgreSQL SSOT)
#   - office_profiles, office_profile_state 테이블 추가
#   - LISTEN/NOTIFY 'office_profiles_changed' 채널로 창 간 실시간 동기화
#   - seed/list/get/upsert/delete/get_active/set_active 헬퍼 함수 추가
# [2026-03-11] Claude — frozen(EXE) 모드 PG_BIN 경로 수정
#   - 기존: PROJECT_ROOT / '.ai_monitor' / 'bin' / 'pgsql' (개발 경로 하드코딩)
#   - 수정: frozen 모드 → Path(sys.executable).parent / "pgsql" / "bin" / "psql.exe"
#           개발 모드 → 기존 경로 유지
# ────────────────────────────────────────────────────────────────────────────
import csv
import io
import json
import os
import subprocess
import sys
import threading
import time
from pathlib import Path

from src.file_store import (
    ensure_legacy_store,
    load_memory_entries,
    load_session_logs,
    load_skill_chain_rows,
)


# ── PostgreSQL 바이너리 경로 — frozen(EXE) / 개발 모드 분기 ───────────────────
# frozen 모드: installer가 {app}\pgsql\ 에 설치한 바이너리 사용
# 개발 모드:   소스 트리 내 .ai_monitor/bin/pgsql/ 사용
if getattr(sys, 'frozen', False):
    # EXE 빌드: 설치 디렉토리 기준 (installer가 {app}\pgsql\ 에 배치)
    _PG_DIR = Path(sys.executable).resolve().parent / 'pgsql'
    PROJECT_ROOT = Path(sys.executable).resolve().parent
    if os.name == 'nt':
        DATA_DIR = Path(os.getenv('APPDATA', '')) / 'VibeCoding'
    else:
        DATA_DIR = Path.home() / '.vibe-coding'
else:
    # 개발 모드: 소스 트리 경로
    _PG_DIR = Path(__file__).resolve().parents[2] / '.ai_monitor' / 'bin' / 'pgsql'
    PROJECT_ROOT = Path(__file__).resolve().parents[2]
    DATA_DIR = PROJECT_ROOT / '.ai_monitor' / 'data'
PG_BIN = _PG_DIR / 'bin' / 'psql.exe'
PG_PORT = os.environ.get('VIBE_PG_PORT', '5433')
PG_USER = 'postgres'
def _resolve_project_db() -> str:
    """프로젝트별 DB 이름을 자동 결정한다.

    server.py의 _init_project_db()와 동일한 변환 로직을 사용하여
    CLI 도구(hive_hook.py, memory.py 등)도 서버와 같은 DB에 접속한다.

    우선순위:
    1. 환경변수 VIBE_PG_DB (server.py가 실행 시 설정)
    2. PROJECT_ROOT 기반 자동 생성 (server.py PROJECT_ID 변환 로직과 동일)
    3. 폴백: 'postgres'

    변환 예: D:\\vibe-coding → D--vibe-coding → d__vibe_coding → vibe_d__vibe_coding
    """
    # 1. 환경변수 — server.py가 이미 설정한 경우
    env_db = os.environ.get('VIBE_PG_DB', '').strip()
    if env_db:
        return env_db

    # 2. PROJECT_ROOT 기반 — server.py의 PROJECT_ID 생성 로직 재현
    try:
        # server.py와 동일: \\→/ , :제거, /→-- , 선행 - 제거
        proj_raw = str(PROJECT_ROOT).replace('\\', '/').replace(':', '').replace('/', '--')
        project_id = proj_raw.lstrip('-') or 'default'
        # _init_project_db()와 동일: 소문자, -→_, 영숫자+_ 만 허용
        safe_id = project_id.lower().replace('-', '_').replace(' ', '_')
        safe_id = ''.join(c for c in safe_id if c.isalnum() or c == '_')
        db_name = f"vibe_{safe_id}"[:63]
        if db_name and db_name != "vibe_":
            return db_name
    except Exception:
        pass

    return 'postgres'


PG_DB = _resolve_project_db()  # CLI/훅에서도 서버와 동일한 프로젝트 DB 자동 사용


def set_project_db(db_name: str):
    """server.py의 _init_project_db()에서 호출하여 프로젝트별 DB 이름을 설정합니다.

    [2026-03-22] 단일 PG + 프로젝트별 DB 분리 지원.
    기존 커넥션은 폐기하여 새 DB로 재연결되도록 합니다.
    """
    global PG_DB, _pg_conn
    PG_DB = db_name
    # 기존 커넥션 폐기 (새 DB로 재연결 유도)
    if _pg_conn is not None:
        try:
            _pg_conn.close()
        except Exception:
            pass
        _pg_conn = None

# ── psycopg2 직접 연결 (psql.exe subprocess 대비 ~50x 빠름) ─────────────────
# psycopg2-binary가 설치되어 있으면 직접 연결, 없으면 psql.exe subprocess 폴백
try:
    import psycopg2
    import psycopg2.extras
    _HAS_PSYCOPG2 = True
except ImportError:
    _HAS_PSYCOPG2 = False

_pg_conn = None
_pg_conn_lock = threading.Lock()


def _get_pg_conn():
    """psycopg2 커넥션을 반환합니다. 끊겼으면 재연결합니다."""
    global _pg_conn, _HAS_PSYCOPG2  # [2026-03-30 Claude] _HAS_PSYCOPG2도 global 선언 — 폴백 전환 버그 수정
    if _pg_conn is not None:
        try:
            with _pg_conn.cursor() as cur:
                cur.execute("SELECT 1")
            return _pg_conn
        except Exception:
            try:
                _pg_conn.close()
            except Exception:
                pass
            _pg_conn = None
    try:
        _pg_conn = psycopg2.connect(
            host='127.0.0.1',
            port=int(PG_PORT),
            user=PG_USER,
            dbname=PG_DB,
            options='-c lc_messages=C',  # 에러 메시지 영문 강제 (CP949 디코딩 방지)
        )
        _pg_conn.autocommit = True
    except UnicodeDecodeError:
        # PostgreSQL이 CP949/EUC-KR 에러 메시지를 반환할 때 psycopg2가 UTF-8 디코딩 실패
        # lc_messages=C 옵션이 적용되기 전에 연결 자체가 실패하는 경우 (DB 없음 등)
        # → psql subprocess 폴백으로 전환
        print("[pg_store] psycopg2 UnicodeDecodeError — CP949 에러 메시지 감지. subprocess 폴백 사용.")
        _HAS_PSYCOPG2 = False
        _pg_conn = None
        return None
    return _pg_conn


_SCHEMA_LOCK = threading.Lock()
_SCHEMA_READY = False
_MIGRATION_DONE = False


def _now_iso() -> str:
    return time.strftime('%Y-%m-%dT%H:%M:%S')


def _sql_text(value) -> str:
    if value is None:
        return 'NULL'
    return "'" + str(value).replace("'", "''") + "'"


def _sql_json(value) -> str:
    return _sql_text(json.dumps(value, ensure_ascii=False)) + '::jsonb'


def _parse_json_text(value, default):
    if value in (None, ''):
        return default
    if isinstance(value, (dict, list)):
        return value
    try:
        return json.loads(value)
    except Exception:
        return default


def _run_psql(sql: str, csv_output: bool = False, timeout: int = 15) -> tuple[bool, str]:
    if not PG_BIN.exists():
        return False, 'psql.exe not found'
    no_window = getattr(subprocess, 'CREATE_NO_WINDOW', 0x08000000)
    env = {**os.environ, 'PGCLIENTENCODING': 'UTF8'}
    cmd = [
        str(PG_BIN), '-X', '-q', '-v', 'ON_ERROR_STOP=1',
        '-p', PG_PORT, '-U', PG_USER, '-d', PG_DB,
    ]
    if csv_output:
        cmd.append('--csv')
    try:
        result = subprocess.run(
            cmd,
            input=sql,
            capture_output=True,
            text=True,
            encoding='utf-8',
            errors='replace',
            timeout=timeout,
            creationflags=no_window,
            env=env,
        )
        if result.returncode != 0:
            return False, (result.stderr or result.stdout).strip()
        return True, result.stdout.strip()
    except Exception as exc:
        return False, str(exc)


def _ensure_pg_running() -> bool:
    # psycopg2로 빠른 연결 확인 (subprocess 대비 ~100ms 절약)
    if _HAS_PSYCOPG2:
        try:
            with _pg_conn_lock:
                _get_pg_conn()
            return True
        except Exception:
            pass  # 연결 실패 → pg_manager로 시작 시도
    ok, _ = _run_psql('SELECT 1;', timeout=2)
    if ok:
        return True
    pg_manager = PROJECT_ROOT / 'scripts' / 'pg_manager.py'
    if not pg_manager.exists():
        return False
    no_window = getattr(subprocess, 'CREATE_NO_WINDOW', 0x08000000)
    try:
        subprocess.Popen(
            ['python', str(pg_manager), 'start'],
            cwd=str(PROJECT_ROOT),
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            creationflags=no_window,
        )
    except Exception:
        return False
    for _ in range(10):
        time.sleep(0.5)
        ok, _ = _run_psql('SELECT 1;', timeout=2)
        if ok:
            return True
    return False


def query_rows(sql: str, timeout: int = 15) -> list[dict]:
    if not ensure_schema():
        return []
    if _HAS_PSYCOPG2:
        try:
            # [2026-03-30 Claude] 락 범위 최소화 — 커넥션 획득만 락으로 보호
            # 기존: 쿼리 실행 + fetchall() 전체를 락 안에서 수행 → 다른 DB 호출 전부 블로킹
            # 변경: 커넥션 획득 후 즉시 락 해제 → 쿼리는 락 밖에서 실행
            # autocommit=True이므로 커넥션 객체를 락 밖에서 사용해도 트랜잭션 충돌 없음
            with _pg_conn_lock:
                conn = _get_pg_conn()
            if conn is None:
                return []
            with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
                cur.execute(sql)
                return [dict(row) for row in cur.fetchall()]
        except Exception as e:
            print(f"[pg_store] query_rows 오류 (psycopg2): {e}")
            return []
    # psycopg2 미설치 시 psql.exe 폴백
    ok, output = _run_psql(sql, csv_output=True, timeout=timeout)
    if not ok or not output.strip():
        return []
    return list(csv.DictReader(io.StringIO(output)))


def execute(sql: str, timeout: int = 15) -> bool:
    if not ensure_schema():
        return False
    if _HAS_PSYCOPG2:
        # 최대 2회 재시도 — "tuple concurrently updated" 등 일시적 충돌 대비
        for attempt in range(3):
            try:
                # [2026-03-30 Claude] 락 범위 최소화 — 커넥션 획득만 락으로 보호
                with _pg_conn_lock:
                    conn = _get_pg_conn()
                if conn is None:
                    return False
                with conn.cursor() as cur:
                    cur.execute(sql)
                return True
            except Exception as e:
                err_msg = str(e)
                if 'tuple concurrently updated' in err_msg and attempt < 2:
                    import time
                    time.sleep(0.05 * (attempt + 1))  # 50~100ms 대기 후 재시도
                    continue
                print(f"[pg_store] execute 오류 (psycopg2): {e}")
                return False
    ok, _ = _run_psql(sql, csv_output=False, timeout=timeout)
    return ok


def ensure_schema(data_dir: Path | None = None) -> bool:
    global _SCHEMA_READY, _MIGRATION_DONE
    if _SCHEMA_READY:
        return True
    with _SCHEMA_LOCK:
        if _SCHEMA_READY:
            return True
        if not _ensure_pg_running():
            return False
        schema_sql = """
        CREATE EXTENSION IF NOT EXISTS pg_trgm;

        CREATE TABLE IF NOT EXISTS pg_logs (
            id BIGSERIAL PRIMARY KEY,
            ts TIMESTAMPTZ DEFAULT NOW(),
            created_at TIMESTAMPTZ DEFAULT NOW(),
            agent TEXT NOT NULL DEFAULT 'unknown',
            terminal_id TEXT DEFAULT '',
            task TEXT NOT NULL DEFAULT '',
            status TEXT DEFAULT 'success',
            project_id TEXT DEFAULT '',
            metadata JSONB DEFAULT '{}'::jsonb
        );
        CREATE INDEX IF NOT EXISTS idx_pg_logs_project_id ON pg_logs (project_id);
        CREATE INDEX IF NOT EXISTS idx_pg_logs_ts ON pg_logs (ts DESC);
        CREATE TABLE IF NOT EXISTS pg_messages (
            id BIGSERIAL PRIMARY KEY,
            ts TIMESTAMPTZ DEFAULT NOW(),
            from_agent TEXT DEFAULT '',
            to_agent TEXT DEFAULT '',
            msg_type TEXT DEFAULT 'info',
            content TEXT DEFAULT '',
            is_read BOOLEAN DEFAULT FALSE,
            channel TEXT DEFAULT 'general',
            metadata JSONB DEFAULT '{}'::jsonb,
            terminal_id TEXT DEFAULT ''
        );
        CREATE INDEX IF NOT EXISTS idx_pg_messages_unread
            ON pg_messages (to_agent, is_read, ts DESC);

        CREATE TABLE IF NOT EXISTS hive_memory (
            key TEXT PRIMARY KEY,
            title TEXT NOT NULL DEFAULT '',
            content TEXT NOT NULL DEFAULT '',
            tags JSONB NOT NULL DEFAULT '[]'::jsonb,
            author TEXT NOT NULL DEFAULT 'unknown',
            project TEXT NOT NULL DEFAULT '',
            created_at TEXT NOT NULL DEFAULT '',
            updated_at TEXT NOT NULL DEFAULT '',
            expires_at TEXT DEFAULT NULL
        );
        CREATE INDEX IF NOT EXISTS idx_hive_memory_updated ON hive_memory (updated_at DESC);
        CREATE INDEX IF NOT EXISTS idx_hive_memory_project ON hive_memory (project);

        CREATE TABLE IF NOT EXISTS hive_sessions (
            id BIGSERIAL PRIMARY KEY,
            legacy_source TEXT,
            legacy_id BIGINT,
            session_id TEXT NOT NULL,
            terminal_id TEXT DEFAULT '',
            project TEXT DEFAULT '',
            agent TEXT DEFAULT '',
            trigger_msg TEXT DEFAULT '',
            status TEXT DEFAULT '',
            commit_hash TEXT DEFAULT '',
            files_changed JSONB NOT NULL DEFAULT '[]'::jsonb,
            ts_start TEXT NOT NULL DEFAULT '',
            ts_end TEXT DEFAULT ''
        );
        CREATE UNIQUE INDEX IF NOT EXISTS idx_hive_sessions_legacy
            ON hive_sessions (legacy_source, legacy_id)
            WHERE legacy_source IS NOT NULL AND legacy_id IS NOT NULL;
        CREATE INDEX IF NOT EXISTS idx_hive_sessions_start ON hive_sessions (ts_start DESC);

        CREATE TABLE IF NOT EXISTS hive_tasks (
            id TEXT PRIMARY KEY,
            timestamp TEXT NOT NULL DEFAULT '',
            updated_at TEXT NOT NULL DEFAULT '',
            title TEXT NOT NULL DEFAULT '',
            description TEXT NOT NULL DEFAULT '',
            status TEXT NOT NULL DEFAULT 'pending',
            assigned_to TEXT NOT NULL DEFAULT 'all',
            priority TEXT NOT NULL DEFAULT 'medium',
            created_by TEXT NOT NULL DEFAULT 'user',
            kanban_status TEXT NOT NULL DEFAULT 'todo',
            role TEXT NOT NULL DEFAULT '',
            claimed_by TEXT NOT NULL DEFAULT '',
            tags JSONB NOT NULL DEFAULT '[]'::jsonb,
            extra JSONB NOT NULL DEFAULT '{}'::jsonb,
            project_id TEXT NOT NULL DEFAULT ''
        );
        CREATE INDEX IF NOT EXISTS idx_hive_tasks_updated ON hive_tasks (updated_at DESC);
        CREATE INDEX IF NOT EXISTS idx_hive_tasks_assigned ON hive_tasks (assigned_to, status);
        CREATE INDEX IF NOT EXISTS idx_hive_tasks_project ON hive_tasks (project_id);

        CREATE TABLE IF NOT EXISTS hive_state (
            state_key TEXT PRIMARY KEY,
            payload JSONB NOT NULL DEFAULT '{}'::jsonb,
            updated_at TEXT NOT NULL DEFAULT ''
        );

        CREATE TABLE IF NOT EXISTS hive_skill_chains (
            id BIGSERIAL PRIMARY KEY,
            legacy_id BIGINT,
            session_id TEXT NOT NULL,
            terminal_id INTEGER NOT NULL DEFAULT 0,
            agent TEXT DEFAULT '',
            request TEXT DEFAULT '',
            skill_num INTEGER DEFAULT 0,
            skill_name TEXT DEFAULT '',
            step_order INTEGER NOT NULL DEFAULT 0,
            status TEXT NOT NULL DEFAULT 'pending',
            summary TEXT DEFAULT '',
            started_at TEXT NOT NULL DEFAULT '',
            updated_at TEXT NOT NULL DEFAULT ''
        );
        CREATE UNIQUE INDEX IF NOT EXISTS idx_hive_skill_chains_legacy
            ON hive_skill_chains (legacy_id)
            WHERE legacy_id IS NOT NULL;
        CREATE INDEX IF NOT EXISTS idx_hive_skill_chains_terminal
            ON hive_skill_chains (terminal_id, session_id, step_order);
        CREATE UNIQUE INDEX IF NOT EXISTS idx_hive_skill_chains_legacy_id
            ON hive_skill_chains (legacy_id)
            WHERE legacy_id IS NOT NULL;
        """
        if not execute_raw(schema_sql, timeout=30):
            return False
        execute_raw("ALTER TABLE pg_logs ADD COLUMN IF NOT EXISTS ts TIMESTAMPTZ DEFAULT NOW();")
        execute_raw("ALTER TABLE pg_logs ADD COLUMN IF NOT EXISTS created_at TIMESTAMPTZ DEFAULT NOW();")
        execute_raw("ALTER TABLE pg_logs ADD COLUMN IF NOT EXISTS agent TEXT NOT NULL DEFAULT 'unknown';")
        execute_raw("ALTER TABLE pg_logs ADD COLUMN IF NOT EXISTS terminal_id TEXT DEFAULT '';")
        execute_raw("ALTER TABLE pg_logs ADD COLUMN IF NOT EXISTS task TEXT NOT NULL DEFAULT '';")
        execute_raw("ALTER TABLE pg_logs ADD COLUMN IF NOT EXISTS status TEXT DEFAULT 'success';")
        execute_raw("ALTER TABLE pg_logs ADD COLUMN IF NOT EXISTS project_id TEXT DEFAULT '';")
        execute_raw("ALTER TABLE pg_logs ADD COLUMN IF NOT EXISTS metadata JSONB DEFAULT '{}'::jsonb;")
        execute_raw("UPDATE pg_logs SET created_at = COALESCE(created_at, ts, NOW()) WHERE created_at IS NULL;")
        execute_raw("UPDATE pg_logs SET ts = COALESCE(ts, created_at, NOW()) WHERE ts IS NULL;")
        execute_raw("CREATE INDEX IF NOT EXISTS idx_pg_logs_project_id ON pg_logs (project_id);")
        execute_raw("CREATE INDEX IF NOT EXISTS idx_pg_logs_ts ON pg_logs (ts DESC);")
        execute_raw("CREATE INDEX IF NOT EXISTS idx_pg_logs_created_at ON pg_logs (created_at DESC);")
        execute_raw("ALTER TABLE pg_messages ADD COLUMN IF NOT EXISTS ts TIMESTAMPTZ DEFAULT NOW();")
        execute_raw("ALTER TABLE pg_messages ADD COLUMN IF NOT EXISTS from_agent TEXT DEFAULT '';")
        execute_raw("ALTER TABLE pg_messages ADD COLUMN IF NOT EXISTS to_agent TEXT DEFAULT '';")
        execute_raw("ALTER TABLE pg_messages ADD COLUMN IF NOT EXISTS msg_type TEXT DEFAULT 'info';")
        execute_raw("ALTER TABLE pg_messages ADD COLUMN IF NOT EXISTS content TEXT DEFAULT '';")
        execute_raw("ALTER TABLE pg_messages ADD COLUMN IF NOT EXISTS is_read BOOLEAN DEFAULT FALSE;")
        execute_raw("ALTER TABLE pg_messages ADD COLUMN IF NOT EXISTS channel TEXT DEFAULT 'general';")
        execute_raw("ALTER TABLE pg_messages ADD COLUMN IF NOT EXISTS metadata JSONB DEFAULT '{}'::jsonb;")
        execute_raw("ALTER TABLE pg_messages ADD COLUMN IF NOT EXISTS terminal_id TEXT DEFAULT '';")
        execute_raw("CREATE INDEX IF NOT EXISTS idx_pg_messages_unread ON pg_messages (to_agent, is_read, ts DESC);")
        # 기존 테이블에 project_id 컬럼 없으면 추가 (마이그레이션)
        execute_raw("ALTER TABLE hive_tasks ADD COLUMN IF NOT EXISTS project_id TEXT NOT NULL DEFAULT '';")
        execute_raw("CREATE INDEX IF NOT EXISTS idx_hive_tasks_project ON hive_tasks (project_id);")
        # 기존 hive_memory 테이블에 expires_at 컬럼 없으면 추가 (TTL 만료 정책)
        execute_raw("ALTER TABLE hive_memory ADD COLUMN IF NOT EXISTS expires_at TEXT DEFAULT NULL;")

        # [2026-03-29] 하이브 메모리 실시간 채팅 통합 — LISTEN/NOTIFY 트리거
        # hive_memory에 INSERT/UPDATE 시 'hive_realtime' 채널로 NOTIFY 발생
        # 그룹챗 브릿지와 대시보드가 LISTEN으로 실시간 수신
        execute_raw("""
            CREATE OR REPLACE FUNCTION notify_hive_realtime()
            RETURNS TRIGGER AS $$
            BEGIN
                PERFORM pg_notify('hive_realtime',
                    json_build_object(
                        'key', NEW.key,
                        'title', NEW.title,
                        'content', NEW.content,
                        'tags', NEW.tags,
                        'author', NEW.author,
                        'updated_at', NEW.updated_at
                    )::text
                );
                RETURN NEW;
            END;
            $$ LANGUAGE plpgsql;
        """)
        execute_raw("""
            DO $$
            BEGIN
                IF NOT EXISTS (SELECT 1 FROM pg_trigger WHERE tgname = 'trg_hive_realtime') THEN
                    CREATE TRIGGER trg_hive_realtime
                    AFTER INSERT OR UPDATE ON hive_memory
                    FOR EACH ROW EXECUTE FUNCTION notify_hive_realtime();
                END IF;
            END;
            $$;
        """)

        # ── [2026-03-30] Paperclip 스타일 오케스트레이션 전환 ──────────────
        # Task 1: hive_tasks 확장 — 계층 구조 + 원자적 체크아웃 + 결과 기록
        execute_raw("ALTER TABLE hive_tasks ADD COLUMN IF NOT EXISTS parent_id TEXT DEFAULT NULL;")
        execute_raw("ALTER TABLE hive_tasks ADD COLUMN IF NOT EXISTS checkout_by TEXT DEFAULT NULL;")
        execute_raw("ALTER TABLE hive_tasks ADD COLUMN IF NOT EXISTS checkout_at TIMESTAMPTZ DEFAULT NULL;")
        execute_raw("ALTER TABLE hive_tasks ADD COLUMN IF NOT EXISTS result TEXT DEFAULT '';")
        execute_raw("CREATE INDEX IF NOT EXISTS idx_hive_tasks_parent ON hive_tasks (parent_id);")
        execute_raw("CREATE INDEX IF NOT EXISTS idx_hive_tasks_checkout ON hive_tasks (checkout_by);")

        # Task 2: 태스크 코멘트 — 에이전트 간 비동기 통신 (그룹 채팅 대체)
        execute_raw("""
            CREATE TABLE IF NOT EXISTS task_comments (
                id SERIAL PRIMARY KEY,
                task_id TEXT NOT NULL,
                author TEXT NOT NULL DEFAULT '',
                content TEXT NOT NULL DEFAULT '',
                created_at TIMESTAMPTZ NOT NULL DEFAULT now()
            );
        """)
        execute_raw("CREATE INDEX IF NOT EXISTS idx_task_comments_task ON task_comments (task_id, created_at);")

        # Task 3: 에이전트 하트비트 상태 — 자율 실행 모니터링
        execute_raw("""
            CREATE TABLE IF NOT EXISTS agent_heartbeats (
                agent_id TEXT PRIMARY KEY,
                status TEXT NOT NULL DEFAULT 'offline',
                last_beat TIMESTAMPTZ DEFAULT now(),
                current_task TEXT DEFAULT NULL,
                beat_count INT NOT NULL DEFAULT 0,
                config JSONB NOT NULL DEFAULT '{}'::jsonb
            );
        """)

        # Task 4: NOTIFY 트리거 — 태스크 할당 시 에이전트 자동 깨우기
        execute_raw("""
            CREATE OR REPLACE FUNCTION notify_task_assigned()
            RETURNS TRIGGER AS $$
            BEGIN
                IF NEW.assigned_to IS DISTINCT FROM OLD.assigned_to
                   AND NEW.assigned_to IS NOT NULL
                   AND NEW.assigned_to != '' THEN
                    PERFORM pg_notify('task_assigned',
                        json_build_object(
                            'task_id', NEW.id,
                            'agent', NEW.assigned_to,
                            'title', NEW.title,
                            'priority', NEW.priority
                        )::text
                    );
                END IF;
                RETURN NEW;
            END;
            $$ LANGUAGE plpgsql;
        """)
        execute_raw("""
            DO $$
            BEGIN
                IF NOT EXISTS (SELECT 1 FROM pg_trigger WHERE tgname = 'trg_task_assigned') THEN
                    CREATE TRIGGER trg_task_assigned
                    AFTER UPDATE ON hive_tasks
                    FOR EACH ROW EXECUTE FUNCTION notify_task_assigned();
                END IF;
            END;
            $$;
        """)

        # ── [2026-04-05] Hive Zettelkasten — 카파시 + 루만 메모 시스템 ──────
        # 원자 노트 테이블: 하나의 노트 = 하나의 아이디어
        execute_raw("""
            CREATE TABLE IF NOT EXISTS zettel_notes (
                id TEXT PRIMARY KEY,
                title TEXT NOT NULL,
                content TEXT NOT NULL DEFAULT '',
                note_type TEXT NOT NULL DEFAULT 'fleeting',
                author TEXT NOT NULL DEFAULT 'unknown',
                project TEXT NOT NULL DEFAULT '',
                tags JSONB NOT NULL DEFAULT '[]'::jsonb,
                source_ref TEXT DEFAULT '',
                access_count INT NOT NULL DEFAULT 0,
                created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
                updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
                last_rescued_at TIMESTAMPTZ,
                archived BOOLEAN NOT NULL DEFAULT FALSE
            );
        """)
        execute_raw("CREATE INDEX IF NOT EXISTS idx_zettel_notes_type ON zettel_notes (note_type);")
        execute_raw("CREATE INDEX IF NOT EXISTS idx_zettel_notes_author ON zettel_notes (author);")
        execute_raw("CREATE INDEX IF NOT EXISTS idx_zettel_notes_project ON zettel_notes (project);")
        execute_raw("CREATE INDEX IF NOT EXISTS idx_zettel_notes_updated ON zettel_notes (updated_at DESC);")
        execute_raw("CREATE INDEX IF NOT EXISTS idx_zettel_notes_rescued ON zettel_notes (last_rescued_at DESC NULLS LAST);")
        execute_raw("CREATE INDEX IF NOT EXISTS idx_zettel_notes_archived ON zettel_notes (archived, updated_at DESC);")

        # 백링크 테이블: 노트 간 양방향 연결
        execute_raw("""
            CREATE TABLE IF NOT EXISTS zettel_links (
                id SERIAL PRIMARY KEY,
                source_id TEXT NOT NULL REFERENCES zettel_notes(id) ON DELETE CASCADE,
                target_id TEXT NOT NULL REFERENCES zettel_notes(id) ON DELETE CASCADE,
                link_type TEXT NOT NULL DEFAULT 'relates_to',
                created_by TEXT NOT NULL DEFAULT 'system',
                created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
                UNIQUE(source_id, target_id, link_type)
            );
        """)
        execute_raw("CREATE INDEX IF NOT EXISTS idx_zettel_links_source ON zettel_links (source_id);")
        execute_raw("CREATE INDEX IF NOT EXISTS idx_zettel_links_target ON zettel_links (target_id);")

        # NOTIFY 트리거 — 노트 변경 시 실시간 알림
        execute_raw("""
            CREATE OR REPLACE FUNCTION notify_zettel_change()
            RETURNS TRIGGER AS $$
            BEGIN
                PERFORM pg_notify('zettel_change',
                    json_build_object(
                        'id', NEW.id,
                        'title', NEW.title,
                        'note_type', NEW.note_type,
                        'author', NEW.author,
                        'updated_at', NEW.updated_at
                    )::text
                );
                RETURN NEW;
            END;
            $$ LANGUAGE plpgsql;
        """)
        execute_raw("""
            DO $$
            BEGIN
                IF NOT EXISTS (SELECT 1 FROM pg_trigger WHERE tgname = 'trg_zettel_change') THEN
                    CREATE TRIGGER trg_zettel_change
                    AFTER INSERT OR UPDATE ON zettel_notes
                    FOR EACH ROW EXECUTE FUNCTION notify_zettel_change();
                END IF;
            END;
            $$;
        """)

        # ── [2026-04-09] 클래식/오피스 워커 네임스페이스 분리 ──
        # hive_tasks, agent_heartbeats에 source/namespace 컬럼을 추가해
        # 두 모드의 실행 상태가 섞이지 않도록 한다.
        execute_raw("ALTER TABLE hive_tasks ADD COLUMN IF NOT EXISTS source TEXT NOT NULL DEFAULT 'classic';")
        execute_raw("CREATE INDEX IF NOT EXISTS idx_hive_tasks_source ON hive_tasks (source, status);")
        execute_raw("ALTER TABLE agent_heartbeats ADD COLUMN IF NOT EXISTS namespace TEXT NOT NULL DEFAULT 'classic';")
        execute_raw("CREATE INDEX IF NOT EXISTS idx_agent_heartbeats_ns ON agent_heartbeats (namespace);")

        # ── [2026-04-09] 오피스 프로필 중앙화 — localStorage → PostgreSQL SSOT ──
        # 창(pywebview/QWebEngine)이 여러 개라 localStorage를 공유할 수 없고
        # 브라우저별 영구 저장 정책이 달라 데이터 유실이 발생하므로
        # 서버 단일 진실의 원천(SSOT)으로 프로필을 이동한다.
        execute_raw("""
            CREATE TABLE IF NOT EXISTS office_profiles (
                id TEXT PRIMARY KEY,
                name TEXT NOT NULL DEFAULT '',
                data JSONB NOT NULL DEFAULT '{}'::jsonb,
                is_default BOOLEAN NOT NULL DEFAULT FALSE,
                created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
                updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
            );
        """)
        execute_raw("CREATE INDEX IF NOT EXISTS idx_office_profiles_updated ON office_profiles (updated_at DESC);")

        # 활성 프로필 포인터 — 싱글톤 레코드 (id=1 고정)
        execute_raw("""
            CREATE TABLE IF NOT EXISTS office_profile_state (
                id INT PRIMARY KEY DEFAULT 1,
                active_profile_id TEXT NOT NULL DEFAULT 'default',
                updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
                CONSTRAINT office_profile_state_singleton CHECK (id = 1)
            );
        """)
        execute_raw("INSERT INTO office_profile_state (id, active_profile_id) VALUES (1, 'default') ON CONFLICT (id) DO NOTHING;")

        # NOTIFY 트리거 — 프로필 변경 시 'office_profiles_changed' 채널로 알림
        # 모든 창(메인/오피스)의 SSE 구독자가 즉시 반영
        execute_raw("""
            CREATE OR REPLACE FUNCTION notify_office_profiles_changed()
            RETURNS TRIGGER AS $$
            DECLARE
                payload TEXT;
            BEGIN
                IF TG_OP = 'DELETE' THEN
                    payload := json_build_object('op', 'delete', 'id', OLD.id)::text;
                ELSE
                    payload := json_build_object('op', TG_OP, 'id', NEW.id)::text;
                END IF;
                PERFORM pg_notify('office_profiles_changed', payload);
                RETURN COALESCE(NEW, OLD);
            END;
            $$ LANGUAGE plpgsql;
        """)
        execute_raw("""
            DO $$
            BEGIN
                IF NOT EXISTS (SELECT 1 FROM pg_trigger WHERE tgname = 'trg_office_profiles_changed') THEN
                    CREATE TRIGGER trg_office_profiles_changed
                    AFTER INSERT OR UPDATE OR DELETE ON office_profiles
                    FOR EACH ROW EXECUTE FUNCTION notify_office_profiles_changed();
                END IF;
                IF NOT EXISTS (SELECT 1 FROM pg_trigger WHERE tgname = 'trg_office_profile_state_changed') THEN
                    CREATE TRIGGER trg_office_profile_state_changed
                    AFTER UPDATE ON office_profile_state
                    FOR EACH ROW EXECUTE PROCEDURE notify_office_profiles_changed();
                END IF;
            END;
            $$;
        """)

        _SCHEMA_READY = True
        if not _MIGRATION_DONE:
            # DB에 마이그레이션 완료 플래그 확인 — 프로세스 재시작 시 재실행 방지
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


def execute_raw(sql: str, timeout: int = 15) -> bool:
    if _HAS_PSYCOPG2:
        # 최대 2회 재시도 — "tuple concurrently updated" 등 일시적 충돌 대비
        for attempt in range(3):
            try:
                with _pg_conn_lock:
                    conn = _get_pg_conn()
                    with conn.cursor() as cur:
                        cur.execute(sql)
                    return True
            except Exception as e:
                err_msg = str(e)
                if 'tuple concurrently updated' in err_msg and attempt < 2:
                    import time
                    time.sleep(0.05 * (attempt + 1))  # 50~100ms 대기 후 재시도
                    continue
                print(f"[pg_store] execute_raw 오류 (psycopg2): {e}")
                break
        # psycopg2 실패 시 psql.exe 폴백 시도
    ok, _ = _run_psql(sql, csv_output=False, timeout=timeout)
    return ok


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
    rows = load_memory_entries(data_dir)
    for row in rows:
        set_memory(
            key=row.get('key', ''),
            content=row.get('content', ''),
            title=row.get('title', '') or row.get('key', ''),
            tags=_parse_json_text(row.get('tags'), []),
            author=row.get('author', 'unknown'),
            project=row.get('project', ''),
            created_at=row.get('created_at') or row.get('updated_at') or '',
            updated_at=row.get('updated_at') or row.get('created_at') or '',
        )


def _migrate_sessions(data_dir: Path) -> None:
    rows = list(reversed(load_session_logs(data_dir)))
    for row in rows:
        upsert_session_log(
            session_id=row.get('session_id', ''),
            terminal_id=row.get('terminal_id', ''),
            project=row.get('project', ''),
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
    save_state(state_key, payload)


def _migrate_skill_chains(data_dir: Path) -> None:
    rows = load_skill_chain_rows(data_dir)
    for row in rows:
        upsert_skill_chain_row(row, legacy_id=row.get('id'))


def list_memory(q: str = '', top_k: int = 20, project: str = '', show_all: bool = False) -> list[dict]:
    filters = []
    if project and not show_all:
        # 현재 프로젝트 + 글로벌(__global__) 항목 모두 반환 (크로스 프로젝트 지식 공유)
        filters.append(f"(project = {_sql_text(project)} OR project = '__global__')")
    # 만료된 항목 제외 (expires_at이 NULL이거나 현재 시각 이후인 것만)
    filters.append(f"(expires_at IS NULL OR expires_at > {_sql_text(_now_iso())})")
    where_sql = f"WHERE {' AND '.join(filters)}" if filters else ''
    if q:
        q_sql = _sql_text(q)
        query = f"""
        SELECT key, title, content, author, project, created_at, updated_at, tags::text AS tags
        FROM hive_memory
        {where_sql} {'AND' if where_sql else 'WHERE'}
            (
                LOWER(key) LIKE LOWER('%' || {q_sql} || '%')
                OR LOWER(title) LIKE LOWER('%' || {q_sql} || '%')
                OR LOWER(content) LIKE LOWER('%' || {q_sql} || '%')
                OR tags::text LIKE '%' || {q_sql} || '%'
            )
        ORDER BY updated_at DESC
        LIMIT {int(top_k)};
        """
    else:
        query = f"""
        SELECT key, title, content, author, project, created_at, updated_at, tags::text AS tags
        FROM hive_memory
        {where_sql}
        ORDER BY updated_at DESC
        LIMIT {int(top_k)};
        """
    rows = query_rows(query)
    for row in rows:
        row['tags'] = _parse_json_text(row.get('tags'), [])
    return rows


def get_memory(key: str) -> dict | None:
    rows = query_rows(
        f"SELECT key, title, content, author, project, created_at, updated_at, tags::text AS tags "
        f"FROM hive_memory WHERE key = {_sql_text(key)} LIMIT 1;"
    )
    if not rows:
        return None
    row = rows[0]
    row['tags'] = _parse_json_text(row.get('tags'), [])
    return row


def set_memory(
    key: str,
    content: str,
    title: str = '',
    tags: list | None = None,
    author: str = 'unknown',
    project: str = '',
    created_at: str = '',
    updated_at: str = '',
    ttl_days: int | None = None,
) -> dict | None:
    if not key or content is None:
        return None
    existing = get_memory(key)
    created_value = existing.get('created_at', '') if existing else (created_at or updated_at or _now_iso())
    updated_value = updated_at or _now_iso()
    title_value = title or key
    # TTL 만료 시각 계산 — ttl_days 지정 시 updated_at + N일
    expires_value = None
    if ttl_days and ttl_days > 0:
        import datetime as _dt
        expires_value = (_dt.datetime.fromisoformat(updated_value) + _dt.timedelta(days=ttl_days)).isoformat()
    execute(
        f"""
        INSERT INTO hive_memory (key, title, content, tags, author, project, created_at, updated_at, expires_at)
        VALUES (
            {_sql_text(key)},
            {_sql_text(title_value)},
            {_sql_text(content)},
            {_sql_json(tags or [])},
            {_sql_text(author)},
            {_sql_text(project)},
            {_sql_text(created_value)},
            {_sql_text(updated_value)},
            {_sql_text(expires_value)}
        )
        ON CONFLICT (key) DO UPDATE SET
            title = EXCLUDED.title,
            content = EXCLUDED.content,
            tags = EXCLUDED.tags,
            author = EXCLUDED.author,
            project = EXCLUDED.project,
            updated_at = EXCLUDED.updated_at,
            expires_at = EXCLUDED.expires_at;
        """
    )
    return get_memory(key)


def delete_memory(key: str) -> bool:
    return execute(f"DELETE FROM hive_memory WHERE key = {_sql_text(key)};")


def cleanup_expired_memory() -> int:
    """expires_at이 현재 시각보다 이전인 메모리 항목을 삭제합니다.
    워치독 루프 또는 서버 기동 시 호출하여 오래된 데이터를 자동 정리합니다.
    반환값: 삭제된 행 수 (파싱 실패 시 0)
    """
    ok, output = _run_psql(
        f"DELETE FROM hive_memory WHERE expires_at IS NOT NULL AND expires_at < {_sql_text(_now_iso())};",
        timeout=10
    )
    return 0  # psql은 DELETE 행 수를 직접 반환하지 않아 0 리턴 (동작은 수행됨)


def upsert_session_log(
    session_id: str,
    terminal_id: str = '',
    project: str = '',
    agent: str = '',
    trigger_msg: str = '',
    status: str = '',
    commit_hash: str = '',
    files_changed: list | None = None,
    ts_start: str = '',
    ts_end: str = '',
    legacy_source: str | None = None,
    legacy_id: int | None = None,
) -> bool:
    if legacy_source and legacy_id is not None:
        # SELECT-first: partial unique index와 ON CONFLICT 호환 문제 회피
        existing = query_rows(
            f"SELECT id FROM hive_sessions WHERE legacy_source = {_sql_text(legacy_source)} "
            f"AND legacy_id = {legacy_id} LIMIT 1;"
        )
        if existing:
            return True  # 이미 존재하면 스킵 (레거시 마이그레이션 중복 방지)
        return execute(
            f"""
            INSERT INTO hive_sessions
                (legacy_source, legacy_id, session_id, terminal_id, project, agent, trigger_msg,
                 status, commit_hash, files_changed, ts_start, ts_end)
            VALUES (
                {_sql_text(legacy_source)}, {legacy_id}, {_sql_text(session_id)}, {_sql_text(terminal_id)},
                {_sql_text(project)}, {_sql_text(agent)}, {_sql_text(trigger_msg)}, {_sql_text(status)},
                {_sql_text(commit_hash)}, {_sql_json(files_changed or [])}, {_sql_text(ts_start or _now_iso())},
                {_sql_text(ts_end or '')}
            );
            """
        )
    return execute(
        f"""
        INSERT INTO hive_sessions
            (session_id, terminal_id, project, agent, trigger_msg, status, commit_hash, files_changed, ts_start, ts_end)
        VALUES (
            {_sql_text(session_id)}, {_sql_text(terminal_id)}, {_sql_text(project)}, {_sql_text(agent)},
            {_sql_text(trigger_msg)}, {_sql_text(status)}, {_sql_text(commit_hash)},
            {_sql_json(files_changed or [])}, {_sql_text(ts_start or _now_iso())}, {_sql_text(ts_end or '')}
        );
        """
    )


def list_session_logs(limit: int = 200) -> list[dict]:
    rows = query_rows(
        f"""
        SELECT id, session_id, terminal_id, project, agent, trigger_msg, status, commit_hash,
               files_changed::text AS files_changed, ts_start, ts_end
        FROM hive_sessions
        ORDER BY ts_start DESC, id DESC
        LIMIT {int(limit)};
        """
    )
    for row in rows:
        row['files_changed'] = _parse_json_text(row.get('files_changed'), [])
    return rows


def get_agent_last_seen(agent_names: list[str] | None = None) -> dict[str, str | None]:
    agent_names = agent_names or []
    result = {name: None for name in agent_names}
    rows = query_rows(
        "SELECT LOWER(agent) AS agent_name, MAX(ts_start) AS last_seen "
        "FROM hive_sessions GROUP BY LOWER(agent) ORDER BY last_seen DESC;"
    )
    for row in rows:
        agent_name = row.get('agent_name', '')
        for wanted in agent_names:
            if wanted in agent_name and result.get(wanted) is None:
                result[wanted] = row.get('last_seen')
    return result


def save_task(task: dict, project_id: str = '') -> dict | None:
    task_id = str(task.get('id', '')).strip()
    if not task_id:
        return None
    # task dict 안에 project_id가 있으면 우선 사용, 없으면 파라미터 사용
    _proj_id = str(task.get('project_id', '') or project_id)
    payload = {
        'timestamp': str(task.get('timestamp', '') or task.get('created_at', '') or _now_iso()),
        'updated_at': str(task.get('updated_at', '') or _now_iso()),
        'title': str(task.get('title', '')),
        'description': str(task.get('description', '')),
        'status': str(task.get('status', 'pending')),
        'assigned_to': str(task.get('assigned_to', 'all')),
        'priority': str(task.get('priority', 'medium')),
        'created_by': str(task.get('created_by', 'user')),
        'kanban_status': str(task.get('kanban_status', 'todo')),
        'role': str(task.get('role', '')),
        'claimed_by': str(task.get('claimed_by', '')),
        'tags': task.get('tags', []),
        'project_id': _proj_id,
    }
    extra = {
        k: v for k, v in task.items()
        if k not in {'id', 'timestamp', 'updated_at', 'title', 'description', 'status', 'assigned_to',
                     'priority', 'created_by', 'kanban_status', 'role', 'claimed_by', 'tags', 'project_id'}
    }
    execute(
        f"""
        INSERT INTO hive_tasks
            (id, timestamp, updated_at, title, description, status, assigned_to, priority,
             created_by, kanban_status, role, claimed_by, tags, extra, project_id)
        VALUES (
            {_sql_text(task_id)}, {_sql_text(payload['timestamp'])}, {_sql_text(payload['updated_at'])},
            {_sql_text(payload['title'])}, {_sql_text(payload['description'])}, {_sql_text(payload['status'])},
            {_sql_text(payload['assigned_to'])}, {_sql_text(payload['priority'])}, {_sql_text(payload['created_by'])},
            {_sql_text(payload['kanban_status'])}, {_sql_text(payload['role'])}, {_sql_text(payload['claimed_by'])},
            {_sql_json(payload['tags'] if isinstance(payload['tags'], list) else [])}, {_sql_json(extra)},
            {_sql_text(_proj_id)}
        )
        ON CONFLICT (id) DO UPDATE SET
            timestamp = EXCLUDED.timestamp,
            updated_at = EXCLUDED.updated_at,
            title = EXCLUDED.title,
            description = EXCLUDED.description,
            status = EXCLUDED.status,
            assigned_to = EXCLUDED.assigned_to,
            priority = EXCLUDED.priority,
            created_by = EXCLUDED.created_by,
            kanban_status = EXCLUDED.kanban_status,
            role = EXCLUDED.role,
            claimed_by = EXCLUDED.claimed_by,
            tags = EXCLUDED.tags,
            extra = EXCLUDED.extra,
            project_id = EXCLUDED.project_id;
        """
    )
    return get_task(task_id)


def list_tasks(project_id: str = None) -> list[dict]:
    # project_id 지정 시 해당 프로젝트 태스크만 반환 (project_id='' 구버전 데이터도 포함)
    # project_id 미지정(None) 시 전체 반환 (하위 호환)
    if project_id:
        where = f"WHERE project_id = {_sql_text(project_id)} OR project_id = ''"
    else:
        where = ""
    rows = query_rows(
        f"""
        SELECT id, timestamp, updated_at, title, description, status, assigned_to, priority,
               created_by, kanban_status, role, claimed_by, tags::text AS tags, extra::text AS extra,
               project_id
        FROM hive_tasks
        {where}
        ORDER BY updated_at DESC, timestamp DESC, id DESC;
        """
    )
    result = []
    for row in rows:
        task = {k: row.get(k) for k in (
            'id', 'timestamp', 'updated_at', 'title', 'description', 'status', 'assigned_to',
            'priority', 'created_by', 'kanban_status', 'role', 'claimed_by', 'project_id'
        )}
        task['tags'] = _parse_json_text(row.get('tags'), [])
        task.update(_parse_json_text(row.get('extra'), {}))
        result.append(task)
    return result


def get_task(task_id: str) -> dict | None:
    """단건 태스크 조회 — WHERE id = 로 직접 조회 (O(1), 기존 list_tasks 전체 스캔 제거)"""
    rows = query_rows(
        f"""
        SELECT id, timestamp, updated_at, title, description, status, assigned_to, priority,
               created_by, kanban_status, role, claimed_by, tags::text AS tags, extra::text AS extra,
               project_id
        FROM hive_tasks
        WHERE id = {_sql_text(task_id)}
        LIMIT 1;
        """
    )
    if not rows:
        return None
    row = rows[0]
    task = {k: row.get(k) for k in (
        'id', 'timestamp', 'updated_at', 'title', 'description', 'status', 'assigned_to',
        'priority', 'created_by', 'kanban_status', 'role', 'claimed_by', 'project_id'
    )}
    task['tags'] = _parse_json_text(row.get('tags'), [])
    task.update(_parse_json_text(row.get('extra'), {}))
    return task


_task_update_lock = threading.Lock()

def update_task(task_id: str, updates: dict) -> dict | None:
    # READ-MODIFY-WRITE 전체를 락으로 보호하여 concurrent update 방지
    with _task_update_lock:
        existing = get_task(task_id)
        if not existing:
            return None
        merged = {**existing, **updates}
        merged['id'] = task_id
        merged['updated_at'] = str(updates.get('updated_at', _now_iso()))
        if 'tags' in merged and isinstance(merged['tags'], str):
            merged['tags'] = [tag.strip() for tag in merged['tags'].split(',') if tag.strip()]
        return save_task(merged)


def delete_task(task_id: str) -> bool:
    return execute(f"DELETE FROM hive_tasks WHERE id = {_sql_text(task_id)};")


def bulk_update_tasks(assigned_to: str, statuses: list[str], new_status: str) -> int:
    if not statuses:
        return 0
    execute(
        f"""
        UPDATE hive_tasks
        SET status = {_sql_text(new_status)}, updated_at = {_sql_text(_now_iso())}
        WHERE assigned_to = {_sql_text(assigned_to)}
          AND status IN ({', '.join(_sql_text(status) for status in statuses)});
        """
    )
    return len([task for task in list_tasks() if task.get('assigned_to') == assigned_to and task.get('status') == new_status])


def save_state(state_key: str, payload: dict) -> bool:
    return execute(
        f"""
        INSERT INTO hive_state (state_key, payload, updated_at)
        VALUES ({_sql_text(state_key)}, {_sql_json(payload)}, {_sql_text(_now_iso())})
        ON CONFLICT (state_key) DO UPDATE SET
            payload = EXCLUDED.payload,
            updated_at = EXCLUDED.updated_at;
        """
    )


def load_state(state_key: str, default=None):
    rows = query_rows(
        f"SELECT payload::text AS payload FROM hive_state WHERE state_key = {_sql_text(state_key)} LIMIT 1;"
    )
    if not rows:
        return default
    return _parse_json_text(rows[0].get('payload'), default)


def upsert_skill_chain_row(row: dict, legacy_id: int | None = None) -> bool:
    if legacy_id is not None:
        # 기존 레코드 존재 여부 먼저 확인 (ON CONFLICT + partial unique index 호환 문제 회피)
        existing = query_rows(f"SELECT id FROM hive_skill_chains WHERE legacy_id = {int(legacy_id)} LIMIT 1;")
        if existing:
            return True  # 이미 존재하면 스킵 (레거시 마이그레이션 중복 방지)
        return execute(
            f"""
            INSERT INTO hive_skill_chains
                (legacy_id, session_id, terminal_id, agent, request, skill_num, skill_name,
                 step_order, status, summary, started_at, updated_at)
            VALUES (
                {legacy_id}, {_sql_text(row.get('session_id', ''))}, {int(row.get('terminal_id', 0) or 0)},
                {_sql_text(row.get('agent', ''))}, {_sql_text(row.get('request', ''))},
                {int(row.get('skill_num', 0) or 0)}, {_sql_text(row.get('skill_name', ''))},
                {int(row.get('step_order', 0) or 0)}, {_sql_text(row.get('status', 'pending'))},
                {_sql_text(row.get('summary', ''))}, {_sql_text(row.get('started_at', ''))},
                {_sql_text(row.get('updated_at', ''))}
            );
            """
        )
    return execute(
        f"""
        INSERT INTO hive_skill_chains
            (session_id, terminal_id, agent, request, skill_num, skill_name, step_order, status, summary, started_at, updated_at)
        VALUES (
            {_sql_text(row.get('session_id', ''))}, {int(row.get('terminal_id', 0) or 0)},
            {_sql_text(row.get('agent', ''))}, {_sql_text(row.get('request', ''))},
            {int(row.get('skill_num', 0) or 0)}, {_sql_text(row.get('skill_name', ''))},
            {int(row.get('step_order', 0) or 0)}, {_sql_text(row.get('status', 'pending'))},
            {_sql_text(row.get('summary', ''))}, {_sql_text(row.get('started_at', ''))},
            {_sql_text(row.get('updated_at', ''))}
        );
        """
    )


def list_skill_chain_rows() -> list[dict]:
    return query_rows(
        """
        SELECT id, session_id, terminal_id, agent, request, skill_num, skill_name,
               step_order, status, summary, started_at, updated_at
        FROM hive_skill_chains
        ORDER BY updated_at DESC, id DESC;
        """
    )


# ── 실시간 채팅 (hive_memory 기반) ────────────────────────────────────────────
# 채팅 메시지를 hive_memory에 저장 (tag: ["chat"])
# key 형식: chat:{timestamp}:{sender}
# LISTEN/NOTIFY 트리거가 자동으로 'hive_realtime' 채널에 알림

def send_chat(sender: str, content: str, project: str = '') -> dict | None:
    """실시간 채팅 메시지 전송 — hive_memory에 저장 + NOTIFY 자동 발생."""
    import time as _t
    key = f"chat:{_t.strftime('%Y%m%d-%H%M%S')}:{sender}:{id(_t)}"
    return set_memory(
        key=key,
        title=f"[{sender}] {content[:50]}",
        content=content[:2000],
        tags=["chat"],
        author=sender,
        project=project,
        ttl_days=7,  # 채팅 메시지는 7일 후 자동 삭제
    )


def get_chat_history(limit: int = 20) -> list[dict]:
    """최근 채팅 메시지 조회 (오래된 순)."""
    rows = query_rows(
        f"""
        SELECT key, content, author, updated_at
        FROM hive_memory
        WHERE tags @> '["chat"]'::jsonb
        ORDER BY updated_at DESC
        LIMIT {limit};
        """
    )
    # 오래된 순으로 뒤집기
    messages = []
    for row in reversed(rows):
        messages.append({
            "sender": row.get("author", ""),
            "content": row.get("content", ""),
            "ts": row.get("updated_at", ""),
        })
    return messages


def get_chat_context(limit: int = 10) -> str:
    """에이전트용 채팅 컨텍스트 프롬프트 생성."""
    messages = get_chat_history(limit)
    if not messages:
        return "(대화 없음)"
    return "\n".join(f"[{m['sender']}] {m['content']}" for m in messages)


# ── Paperclip 스타일 오케스트레이션 ──────────────────────────────────────────
# [2026-03-30] 그룹 채팅 대체 — 원자적 체크아웃 + 태스크 코멘트 + 에이전트 하트비트

def atomic_checkout(agent_id: str, task_id: str) -> dict | None:
    """원자적 태스크 체크아웃 — 이미 체크아웃된 태스크는 None 반환.

    SELECT ... FOR UPDATE SKIP LOCKED 패턴으로 동시 접근 시 하나만 성공.
    """
    conn = _get_pg_conn()
    if not conn:
        return None
    try:
        with conn.cursor() as cur:
            # 트랜잭션 내에서 잠금 획득 시도
            cur.execute(
                "SELECT id, title, description, assigned_to, status, priority "
                "FROM hive_tasks WHERE id = %s "
                "AND (checkout_by IS NULL OR checkout_by = '') "
                "FOR UPDATE SKIP LOCKED;",
                (task_id,)
            )
            row = cur.fetchone()
            if not row:
                return None  # 이미 체크아웃됨 또는 존재하지 않음
            # 체크아웃 마킹
            cur.execute(
                "UPDATE hive_tasks SET checkout_by = %s, checkout_at = now(), "
                "kanban_status = 'working', status = 'in_progress', "
                "updated_at = %s WHERE id = %s;",
                (agent_id, _now_iso(), task_id)
            )
            conn.commit()
            cols = ('id', 'title', 'description', 'assigned_to', 'status', 'priority')
            return dict(zip(cols, row))
    except Exception as e:
        conn.rollback()
        print(f"[pg_store] atomic_checkout 실패: {e}")
        return None


def release_checkout(task_id: str, new_status: str = 'done', result: str = '') -> bool:
    """체크아웃 해제 — 작업 완료 또는 실패 시 호출."""
    return execute(
        f"UPDATE hive_tasks SET checkout_by = NULL, checkout_at = NULL, "
        f"status = {_sql_text(new_status)}, kanban_status = {_sql_text(new_status)}, "
        f"result = {_sql_text(result)}, updated_at = {_sql_text(_now_iso())} "
        f"WHERE id = {_sql_text(task_id)};"
    )


def find_tasks_for_agent(agent_id: str, project_id: str = '') -> list[dict]:
    """에이전트에게 할당된 미처리 태스크 조회 (체크아웃 안 된 것만)."""
    where_parts = [
        f"assigned_to = {_sql_text(agent_id)}",
        "(checkout_by IS NULL OR checkout_by = '')",
        "status NOT IN ('done', 'cancelled', 'blocked')"
    ]
    if project_id:
        where_parts.append(f"(project_id = {_sql_text(project_id)} OR project_id = '')")
    where = " AND ".join(where_parts)
    return query_rows(
        f"SELECT id, title, description, priority, status, kanban_status "
        f"FROM hive_tasks WHERE {where} "
        f"ORDER BY CASE priority WHEN 'critical' THEN 0 WHEN 'high' THEN 1 "
        f"WHEN 'medium' THEN 2 ELSE 3 END, updated_at ASC;"
    )


# ── 태스크 코멘트 CRUD ──────────────────────────────────────────────────────

def add_task_comment(task_id: str, author: str, content: str) -> bool:
    """태스크에 코멘트 추가 — 에이전트 간 비동기 통신 채널."""
    return execute(
        f"INSERT INTO task_comments (task_id, author, content) "
        f"VALUES ({_sql_text(task_id)}, {_sql_text(author)}, {_sql_text(content)});"
    )


def list_task_comments(task_id: str, limit: int = 50) -> list[dict]:
    """태스크의 코멘트 목록 조회 (오래된 순)."""
    return query_rows(
        f"SELECT id, task_id, author, content, "
        f"to_char(created_at, 'YYYY-MM-DD\"T\"HH24:MI:SS') AS created_at "
        f"FROM task_comments WHERE task_id = {_sql_text(task_id)} "
        f"ORDER BY created_at ASC LIMIT {int(limit)};"
    )


# ── 에이전트 하트비트 ────────────────────────────────────────────────────────

def record_heartbeat(agent_id: str, status: str = 'idle',
                     current_task: str = None) -> bool:
    """에이전트 하트비트 기록 — 상태 갱신 + 카운터 증가."""
    task_val = _sql_text(current_task) if current_task else 'NULL'
    return execute(
        f"INSERT INTO agent_heartbeats (agent_id, status, last_beat, current_task, beat_count) "
        f"VALUES ({_sql_text(agent_id)}, {_sql_text(status)}, now(), {task_val}, 1) "
        f"ON CONFLICT (agent_id) DO UPDATE SET "
        f"status = {_sql_text(status)}, last_beat = now(), "
        f"current_task = {task_val}, "
        f"beat_count = agent_heartbeats.beat_count + 1;"
    )


def list_agent_status() -> list[dict]:
    """전체 에이전트 하트비트 상태 조회."""
    return query_rows(
        "SELECT agent_id, status, "
        "to_char(last_beat, 'YYYY-MM-DD\"T\"HH24:MI:SS') AS last_beat, "
        "current_task, beat_count, config::text AS config "
        "FROM agent_heartbeats ORDER BY agent_id;"
    )


def trigger_agent(agent_id: str) -> bool:
    """에이전트에게 NOTIFY 전송 — 수동 하트비트 트리거."""
    conn = _get_pg_conn()
    if not conn:
        return False
    try:
        import json as _json
        payload = _json.dumps({'agent': agent_id, 'trigger': 'manual'})
        with conn.cursor() as cur:
            cur.execute(f"NOTIFY task_assigned, '{payload}';")
        conn.commit()
        return True
    except Exception as e:
        print(f"[pg_store] trigger_agent 실패: {e}")
        return False


# ── pg_logs 활동 기록 ────────────────────────────────────────────────────────

def insert_pg_log(agent: str, task: str = '', status: str = 'success',
                  terminal_id: str = '', project_id: str = '',
                  metadata: dict | None = None) -> bool:
    """에이전트 활동을 pg_logs 테이블에 기록한다.

    서버 API 호출, heartbeat 갱신, 태스크 상태 변경 등
    모든 에이전트 활동의 영구 로그를 남긴다.
    """
    import json as _json
    meta_json = _json.dumps(metadata or {}, ensure_ascii=False)
    return execute(
        f"INSERT INTO pg_logs (agent, task, status, terminal_id, project_id, metadata) "
        f"VALUES ({_sql_text(agent)}, {_sql_text(task)}, {_sql_text(status)}, "
        f"{_sql_text(terminal_id)}, {_sql_text(project_id)}, "
        f"{_sql_text(meta_json)}::jsonb);"
    )


# ── 오피스 프로필 CRUD ──────────────────────────────────────────────────────
#
# 메인 창(pywebview)과 오피스 창(QWebEngineView)은 서로 다른 브라우저 엔진이라
# localStorage가 공유되지 않는다. 프로필은 서버 DB에서만 관리한다.

# 기본 프로필 시드 스키마 버전 — 이 값을 올리면 재시드 시 기본 프로필의 모델/역할이
# 자동 업그레이드된다. 사용자가 생성한 커스텀 프로필은 절대 건드리지 않는다.
_OFFICE_PROFILE_SCHEMA_VERSION = 2  # v2: Gemini 3.1 / GPT-5.3-Codex 최신 모델 반영

# 기본 프로필 씨드 — 경영진(대표) + 코딩 부서. useWorkspaceProfiles.ts의 DEFAULT_PROFILE과 동일
_DEFAULT_OFFICE_PROFILE = {
    "id": "default",
    "name": "코딩 회사",
    "isDefault": True,
    "schemaVersion": _OFFICE_PROFILE_SCHEMA_VERSION,
    "createdAt": "2026-04-08T00:00:00.000Z",
    "departments": [
        {
            "id": "dept-exec",
            "name": "경영진",
            "color": "#fbbf24",
            "icon": "crown",
            "agents": [
                {"id": "ceo", "name": "대표 (지휘자)", "role": "ceo",
                 "cli": "claude", "model": "claude-opus-4-6",
                 "skills": ["orchestrate", "brainstorm", "write-plan"],
                 "avatar": "crown", "yolo": True, "order": 0},
            ],
        },
        {
            "id": "dept-coding",
            "name": "코딩 부서",
            "color": "#22d3ee",
            "icon": "code-2",
            "agents": [
                {"id": "a1", "name": "기획자",     "role": "planner",   "cli": "claude", "model": "claude-opus-4-6",   "skills": ["brainstorm", "write-plan"], "avatar": "clipboard-list", "yolo": True, "order": 0},
                {"id": "a2", "name": "아키텍트",   "role": "architect", "cli": "claude", "model": "claude-opus-4-6",   "skills": ["brainstorm"],               "avatar": "blocks",         "yolo": True, "order": 1},
                {"id": "a3", "name": "프론트엔드", "role": "frontend",  "cli": "gemini", "model": "gemini-3.1-pro",       "skills": ["code"],                     "avatar": "monitor",        "yolo": True, "order": 2},
                {"id": "a4", "name": "백엔드",     "role": "backend",   "cli": "claude", "model": "claude-sonnet-4-6",    "skills": ["code"],                     "avatar": "server",         "yolo": True, "order": 3},
                {"id": "a5", "name": "풀스택",     "role": "fullstack", "cli": "gemini", "model": "gemini-3.1-flash",     "skills": ["code"],                     "avatar": "layers",         "yolo": True, "order": 4},
                {"id": "a6", "name": "코드 리뷰어","role": "reviewer",  "cli": "claude", "model": "claude-opus-4-6",      "skills": ["code-review"],              "avatar": "search-check",   "yolo": True, "order": 5},
                {"id": "a7", "name": "QA 테스터",  "role": "qa",        "cli": "codex",  "model": "gpt-5.3-codex-spark",  "skills": ["tdd"],                      "avatar": "test-tubes",     "yolo": True, "order": 6},
                {"id": "a8", "name": "보안 담당",  "role": "security",  "cli": "claude", "model": "claude-opus-4-6",      "skills": ["security"],                 "avatar": "shield",         "yolo": True, "order": 7},
                {"id": "a9", "name": "DevOps",     "role": "devops",    "cli": "codex",  "model": "gpt-5.3-codex",        "skills": ["release"],                  "avatar": "wrench",         "yolo": True, "order": 8},
            ],
        },
    ],
}


def seed_default_office_profile() -> bool:
    """기본 프로필을 시드 또는 업그레이드한다.

    - 최초 실행: 'default' 프로필을 그대로 INSERT.
    - 재실행: 'default' 프로필의 schemaVersion이 현재 버전보다 낮으면 data를 덮어쓴다.
              사용자가 생성한 다른 프로필은 절대 건드리지 않는다.
              'default' 프로필을 사용자가 직접 수정했더라도, 기본 시드는 진실의 원천이
              바뀐 경우(예: 구버전 모델 → 최신 모델) 자동 최신화되는 편이 안전하다.
    """
    import json as _json
    data_json = _json.dumps(_DEFAULT_OFFICE_PROFILE, ensure_ascii=False)

    # 현재 저장된 'default' 프로필의 schemaVersion 확인
    rows = query_rows(
        "SELECT (data->>'schemaVersion')::int AS v FROM office_profiles WHERE id = 'default';"
    )
    if not rows:
        # 최초 시드
        return execute(
            f"INSERT INTO office_profiles (id, name, data, is_default) "
            f"VALUES ('default', {_sql_text(_DEFAULT_OFFICE_PROFILE['name'])}, "
            f"{_sql_text(data_json)}::jsonb, TRUE) "
            f"ON CONFLICT (id) DO NOTHING;"
        )

    current_version = rows[0].get('v') or 0
    if current_version < _OFFICE_PROFILE_SCHEMA_VERSION:
        # 기본 프로필 데이터 업그레이드 (모델명 등 최신화)
        print(f"[pg_store] 기본 오피스 프로필 업그레이드: v{current_version} → v{_OFFICE_PROFILE_SCHEMA_VERSION}")
        return execute(
            f"UPDATE office_profiles SET "
            f"data = {_sql_text(data_json)}::jsonb, "
            f"name = {_sql_text(_DEFAULT_OFFICE_PROFILE['name'])}, "
            f"updated_at = NOW() "
            f"WHERE id = 'default';"
        )
    return True


def list_office_profiles() -> list[dict]:
    """전체 오피스 프로필 목록 + 활성 프로필 ID 반환.

    반환 형식: [{"id", "name", "data", "is_default", "created_at", "updated_at"}, ...]
    data 필드는 JSON 문자열이 아닌 파싱된 dict이다.
    """
    import json as _json
    rows = query_rows(
        "SELECT id, name, data::text AS data, is_default, "
        "to_char(created_at, 'YYYY-MM-DD\"T\"HH24:MI:SS') AS created_at, "
        "to_char(updated_at, 'YYYY-MM-DD\"T\"HH24:MI:SS') AS updated_at "
        "FROM office_profiles ORDER BY is_default DESC, created_at ASC;"
    )
    for r in rows:
        try:
            r['data'] = _json.loads(r.get('data') or '{}')
        except Exception:
            r['data'] = {}
    return rows


def get_office_profile(profile_id: str) -> dict | None:
    """단일 프로필 조회."""
    import json as _json
    rows = query_rows(
        f"SELECT id, name, data::text AS data, is_default, "
        f"to_char(created_at, 'YYYY-MM-DD\"T\"HH24:MI:SS') AS created_at, "
        f"to_char(updated_at, 'YYYY-MM-DD\"T\"HH24:MI:SS') AS updated_at "
        f"FROM office_profiles WHERE id = {_sql_text(profile_id)} LIMIT 1;"
    )
    if not rows:
        return None
    r = rows[0]
    try:
        r['data'] = _json.loads(r.get('data') or '{}')
    except Exception:
        r['data'] = {}
    return r


def upsert_office_profile(profile_id: str, name: str, data: dict,
                           is_default: bool = False) -> bool:
    """프로필 생성 또는 전체 대체. data는 departments를 포함한 전체 JSON."""
    import json as _json
    data_json = _json.dumps(data, ensure_ascii=False)
    return execute(
        f"INSERT INTO office_profiles (id, name, data, is_default, updated_at) "
        f"VALUES ({_sql_text(profile_id)}, {_sql_text(name)}, "
        f"{_sql_text(data_json)}::jsonb, {'TRUE' if is_default else 'FALSE'}, NOW()) "
        f"ON CONFLICT (id) DO UPDATE SET "
        f"name = EXCLUDED.name, data = EXCLUDED.data, updated_at = NOW();"
    )


def delete_office_profile(profile_id: str) -> bool:
    """프로필 삭제. 기본 프로필은 삭제 불가 (is_default=TRUE 제외)."""
    return execute(
        f"DELETE FROM office_profiles "
        f"WHERE id = {_sql_text(profile_id)} AND is_default = FALSE;"
    )


def get_active_office_profile_id() -> str:
    """현재 활성 프로필 ID."""
    rows = query_rows("SELECT active_profile_id FROM office_profile_state WHERE id = 1 LIMIT 1;")
    if rows:
        return rows[0].get('active_profile_id') or 'default'
    return 'default'


def set_active_office_profile(profile_id: str) -> bool:
    """활성 프로필 변경 — 싱글톤 레코드 업데이트."""
    return execute(
        f"UPDATE office_profile_state SET active_profile_id = {_sql_text(profile_id)}, "
        f"updated_at = NOW() WHERE id = 1;"
    )
