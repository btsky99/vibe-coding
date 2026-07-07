# ────────────────────────────────────────────────────────────────────────────
# 📄 파일명: src/pg_base.py
# 📝 설명: PostgreSQL 연결 인프라 — 경로 결정, psycopg2 커넥션/풀, 쿼리 실행 프리미티브
#          (pg_store.py 분할 1/6 — 모든 pg_* 도메인 모듈이 의존하는 최하층)
# 🕒 변경 이력:
# [2026-06-10] Claude — pg_store.py(2492줄) 분할로 신설 (1500줄 규칙 준수)
#   - [불변식] 이 모듈은 src.pg_* 를 모듈 레벨에서 import 하지 않는다 (순환 방지).
#     query_rows/execute의 ensure_schema 호출만 함수 내부 지연 import.
#   - [WHY] PG_DB는 set_project_db()가 런타임에 재바인딩하는 가변 전역 —
#     다른 모듈에서 `from src.pg_base import PG_DB`로 값 복사 금지(스테일 값 위험).
#     반드시 query_rows/execute 등 함수를 통해 간접 접근한다.
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


def set_pg_port(port) -> None:
    """server.py ensure_postgres_running()에서 호출 — 동적 폴백으로 확정된 실제 PG 포트를
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
    """
    global PG_PORT, _pg_conn
    new_port = str(port)
    if new_port == PG_PORT:
        return
    PG_PORT = new_port
    if _pg_conn is not None:
        try:
            _pg_conn.close()
        except Exception:
            pass
        _pg_conn = None
    with _pool_lock:
        for _conn, _db in _pool:
            try:
                _conn.close()
            except Exception:
                pass
        _pool.clear()

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
    """psycopg2 커넥션을 반환합니다. 끊겼으면 재연결합니다.
    주의: 반드시 _pg_conn_lock 안에서 호출할 것."""
    global _pg_conn, _HAS_PSYCOPG2
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
        conn = psycopg2.connect(
            host='127.0.0.1',
            port=int(PG_PORT),
            user=PG_USER,
            dbname=PG_DB,
            options='-c lc_messages=C',
            connect_timeout=5,
        )
        conn.autocommit = True
        _pg_conn = conn
    except UnicodeDecodeError:
        print("[pg_store] psycopg2 UnicodeDecodeError — CP949 에러 메시지 감지. subprocess 폴백 사용.")
        _HAS_PSYCOPG2 = False
        _pg_conn = None
        return None
    except Exception as e:
        print(f"[pg_store] psycopg2 연결 실패: {e}")
        _pg_conn = None
        return None
    return _pg_conn


# ── 다중 DB 커넥션 풀 (서버 측 고빈도 쿼리용) ───────────────────────────────
# [2026-04-21 단계 8a] server.py L208~252에서 이관. 위의 단일 `_pg_conn`은
# 모듈 내부 CRUD(단일 프로젝트 DB)용이고, 아래 풀은 server.py가 여러 DB
# (postgres / 프로젝트 DB 등)에 접속하는 고빈도 API 핸들러 전용이다.
_pool: list = []                  # (conn, db) 튜플 리스트
_pool_lock = threading.Lock()
_POOL_MAX = 5


def get_pool_conn(db: str = "postgres"):
    """풀에서 커넥션을 꺼내거나, 풀이 비었으면 새로 생성하여 반환.

    같은 db 이름의 커넥션만 재사용. 다른 db의 커넥션은 풀에 그대로 둠.
    연결이 끊어졌으면(OperationalError) 버리고 새로 생성.
    """
    import psycopg2
    with _pool_lock:
        for i, (conn, conn_db) in enumerate(_pool):
            if conn_db == db:
                _pool.pop(i)
                try:
                    conn.cursor().execute("SELECT 1")
                    return conn
                except (psycopg2.OperationalError, psycopg2.InterfaceError):
                    try:
                        conn.close()
                    except Exception:
                        pass
                    break
    conn = psycopg2.connect(host='127.0.0.1', port=int(PG_PORT), user='postgres', dbname=db)
    conn.autocommit = True
    return conn


def return_pool_conn(conn, db: str = "postgres") -> None:
    """사용 완료된 커넥션을 풀에 반환. 풀이 가득 차면 연결을 닫고 폐기."""
    with _pool_lock:
        if len(_pool) < _POOL_MAX:
            _pool.append((conn, db))
        else:
            try:
                conn.close()
            except Exception:
                pass


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
    # [WHY] global 선언 — 분할 전 코드는 선언 없이 except에서 _pg_conn = None을
    # 대입해 로컬 변수만 만들었고(리셋 무효), 죽은 커넥션이 _get_pg_conn의
    # SELECT 1 프로브로만 회복되고 있었다. 분할하며 근본 수정.
    global _pg_conn
    # [WHY] 지연 import — pg_schema가 pg_base를 모듈 레벨에서 import 하므로
    # 역방향은 함수 내부에서만 (순환 import 방지)
    from src.pg_schema import ensure_schema
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
            # 커넥션 에러 시 다음 호출에서 재연결하도록 리셋
            with _pg_conn_lock:
                _pg_conn = None
            return []
    # psycopg2 미설치 시 psql.exe 폴백
    ok, output = _run_psql(sql, csv_output=True, timeout=timeout)
    if not ok or not output.strip():
        return []
    return list(csv.DictReader(io.StringIO(output)))


def execute(sql: str, timeout: int = 15) -> bool:
    global _pg_conn  # query_rows와 동일한 리셋 무효 버그 수정
    from src.pg_schema import ensure_schema  # 순환 import 방지 지연 import
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
                    import time as _t
                    _t.sleep(0.05 * (attempt + 1))
                    continue
                print(f"[pg_store] execute 오류 (psycopg2): {e}")
                with _pg_conn_lock:
                    _pg_conn = None
                return False
    ok, _ = _run_psql(sql, csv_output=False, timeout=timeout)
    return ok

def execute_raw(sql: str, timeout: int = 15) -> bool:
    global _pg_conn  # query_rows와 동일한 리셋 무효 버그 수정
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
                _pg_conn = None
                break
        # psycopg2 실패 시 psql.exe 폴백 시도
    ok, _ = _run_psql(sql, csv_output=False, timeout=timeout)
    return ok
