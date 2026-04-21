"""
FILE: infra/postgres_runtime.py
DESCRIPTION: 내장 PostgreSQL 18 기동/초기화 런타임. 배포(frozen) 모드에서
             pgsql 바이너리가 동봉되어 있을 때 자동 initdb → pg_ctl start →
             포트 점유 회피 → 스키마 확장 초기화까지의 기동 체인을 담당한다.

             프로젝트별 DB 이름 규칙(vibe_{project_id})에 따라 CREATE DATABASE
             수행 + pg_store 모듈로 DB 이름 전파까지 포함.

REVISION HISTORY:
- 2026-04-21 Claude: server.py L230~536 분리 (단계 8b)
                     PG_PORT 글로벌 mutation은 start_server 반환값으로 전환해
                     caller가 명시적으로 갱신하도록 한다.
"""
from __future__ import annotations

import os
import re
import socket
import subprocess
import time
from pathlib import Path
from typing import Callable


# ── 공용 배치 스키마 SQL ────────────────────────────────────────────────────
# 기동 성능 최적화: 13개 CREATE 문을 1개 psql 실행으로 묶음 (~5초 단축).
BOOTSTRAP_SCHEMA_SQL = """
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
"""

PROJECT_DB_EXTENSIONS_SQL = """
    CREATE EXTENSION IF NOT EXISTS vector;
    CREATE EXTENSION IF NOT EXISTS pg_trgm;
    CREATE EXTENSION IF NOT EXISTS fuzzystrmatch;
"""


# ── PG 기동 ─────────────────────────────────────────────────────────────────
def start_server(pg_ctl_bin: Path, initdb_bin: Path, pg_data_dir: Path, pg_port: int) -> int:
    """pgdata가 없으면 initdb → pg_ctl start까지 수행.

    포트 점유 시 빈 포트를 자동 탐색하여 postgresql.conf를 갱신한다.
    반환: 실제 사용 중인 포트. caller가 server.py 글로벌을 갱신해야 한다.
    pg_ctl_bin이 없으면(개발/미설치) pg_port를 그대로 반환한다.
    """
    if not pg_ctl_bin.exists():
        print(f"[PG] pg_ctl.exe 없음 → PG 자동시작 스킵 ({pg_ctl_bin})")
        return pg_port

    _no_window = getattr(subprocess, 'CREATE_NO_WINDOW', 0x08000000)
    pg_log = pg_data_dir.parent / "pgsql.log"

    # 1) initdb — pgdata 없으면 최초 DB 클러스터 생성
    if not pg_data_dir.exists():
        print(f"[PG] pgdata 없음 → initdb 실행: {pg_data_dir}")
        pg_data_dir.mkdir(parents=True, exist_ok=True)
        try:
            res = subprocess.run(
                [str(initdb_bin), "-D", str(pg_data_dir),
                 "-U", "postgres", "-E", "UTF8", "--no-locale"],
                capture_output=True, text=True, encoding='utf-8', errors='replace',
                creationflags=_no_window
            )
            if res.returncode != 0:
                print(f"[PG] initdb 오류:\n{res.stderr}")
                return pg_port
            print(f"[PG] initdb 완료")

            pg_conf = pg_data_dir / "postgresql.conf"
            if pg_conf.exists():
                conf_text = pg_conf.read_text(encoding='utf-8')
                conf_text = conf_text.replace("#listen_addresses = 'localhost'", "listen_addresses = 'localhost'")
                conf_text = conf_text.replace("#port = 5432", f"port = {pg_port}")
                conf_text = conf_text.replace("port = 5432", f"port = {pg_port}")
                pg_conf.write_text(conf_text, encoding='utf-8')
                print(f"[PG] postgresql.conf 포트 {pg_port} 설정 완료")
        except Exception as e:
            print(f"[PG] initdb 예외: {e}")
            return pg_port

    # 2) 실행 여부 확인 — pg_ctl status
    try:
        status_res = subprocess.run(
            [str(pg_ctl_bin), "status", "-D", str(pg_data_dir)],
            capture_output=True, text=True, encoding='utf-8', errors='replace',
            creationflags=_no_window
        )
        if "server is running" in status_res.stdout:
            print("[PG] 이미 실행 중")
            return pg_port
    except Exception as e:
        print(f"[PG ERROR] pg_ctl status 확인: {e}")

    # 2-1) 포트 점유 확인 — 외부 프로세스가 점유 중이면 빈 포트 자동 탐색
    try:
        _pg_test = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        _pg_result = _pg_test.connect_ex(('127.0.0.1', pg_port))
        _pg_test.close()
        if _pg_result == 0:
            print(f"[PG] 포트 {pg_port}이 이미 사용 중 (외부 프로세스) → 빈 포트 탐색")
            _found_port = False
            for _try_port in range(pg_port + 1, pg_port + 20):
                _s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
                _r = _s.connect_ex(('127.0.0.1', _try_port))
                _s.close()
                if _r != 0:
                    pg_port = _try_port
                    print(f"[PG] 빈 포트 발견: {pg_port}")
                    pg_conf = pg_data_dir / "postgresql.conf"
                    if pg_conf.exists():
                        conf_text = pg_conf.read_text(encoding='utf-8')
                        if re.search(r'^\s*port\s*=', conf_text, flags=re.MULTILINE):
                            conf_text = re.sub(r'^\s*port\s*=\s*\d+', f'port = {pg_port}', conf_text, flags=re.MULTILINE)
                        elif re.search(r'^\s*#\s*port\s*=', conf_text, flags=re.MULTILINE):
                            conf_text = re.sub(r'^\s*#\s*port\s*=\s*\d+', f'port = {pg_port}', conf_text, flags=re.MULTILINE)
                        else:
                            conf_text += f'\nport = {pg_port}\n'
                        pg_conf.write_text(conf_text, encoding='utf-8')
                    os.environ['VIBE_PG_PORT'] = str(pg_port)
                    _found_port = True
                    break
            if not _found_port:
                print(f"[PG ERROR] 포트 {pg_port-19}~{pg_port} 범위에서 빈 포트를 찾지 못함")
                return pg_port
    except Exception:
        pass

    # 3) pg_ctl start (Windows 전용 PIPE 상속 버그 회피 — DEVNULL 사용)
    print(f"[PG] PostgreSQL 시작 중 (port={pg_port})...")
    try:
        subprocess.run(
            [str(pg_ctl_bin), "start", "-D", str(pg_data_dir),
             "-l", str(pg_log), "-o", f"-p {pg_port}"],
            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
            creationflags=_no_window, timeout=15
        )
        # ready 폴링 (최대 5초)
        _pg_ready = False
        for _i in range(50):
            time.sleep(0.1)
            try:
                _chk = subprocess.run(
                    [str(pg_ctl_bin), "status", "-D", str(pg_data_dir)],
                    capture_output=True, text=True, encoding='utf-8', errors='replace',
                    creationflags=_no_window, timeout=1
                )
                if "server is running" in _chk.stdout:
                    _pg_ready = True
                    break
            except Exception:
                pass
        print(f"[PG] PostgreSQL 시작 완료 ({(_i+1)*100}ms 소요)")
    except subprocess.TimeoutExpired:
        print(f"[PG] pg_ctl start 타임아웃 (pgdata 락 충돌 가능) → 기존 PG 인스턴스 재사용 시도")
        for _fallback_port in [5433, 5434, 5435, 5432]:
            try:
                _s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
                _r = _s.connect_ex(('127.0.0.1', _fallback_port))
                _s.close()
                if _r == 0:
                    pg_port = _fallback_port
                    os.environ['VIBE_PG_PORT'] = str(pg_port)
                    print(f"[PG] 기존 PG 인스턴스 발견 (port={pg_port}) → 재사용")
                    break
            except Exception:
                continue
        else:
            print("[PG ERROR] 실행 중인 PostgreSQL을 찾지 못함")

    return pg_port


# ── 프로젝트 DB 생성 ────────────────────────────────────────────────────────
def create_project_db(
    project_id: str,
    run_sql_fn: Callable,
    set_pg_store_db_fn: Callable | None = None,
) -> str:
    """프로젝트별 DB 생성 + pg_store 모듈 전파.

    반환: 생성/확인된 DB 이름. 실패 시 'postgres'(폴백)을 반환한다.
    run_sql_fn(sql, params=None, db=None): caller의 run_pg_sql 주입.
    set_pg_store_db_fn(db_name): pg_store.set_project_db 주입 (optional).
    """
    safe_id = project_id.lower().replace('-', '_').replace(' ', '_')
    safe_id = ''.join(c for c in safe_id if c.isalnum() or c == '_')
    db_name = f"vibe_{safe_id}"[:63]
    if not db_name or db_name == "vibe_":
        db_name = "vibe_default"

    try:
        result = run_sql_fn(
            "SELECT 1 FROM pg_database WHERE datname = %s;",
            (db_name,), db="postgres"
        )
        if not result or not result.strip():
            run_sql_fn(f'CREATE DATABASE "{db_name}";', db="postgres")
            print(f"[PG] 프로젝트 DB 생성 완료: {db_name}")
        else:
            print(f"[PG] 프로젝트 DB 확인: {db_name} (이미 존재)")

        print(f"[PG] PG_PROJECT_DB = {db_name}")

        if set_pg_store_db_fn is not None:
            try:
                set_pg_store_db_fn(db_name)
            except Exception as e:
                print(f"[PG] pg_store.set_project_db 전파 실패 (무시): {e}")

        os.environ['VIBE_PG_DB'] = db_name
        run_sql_fn(PROJECT_DB_EXTENSIONS_SQL, db=db_name)
        return db_name

    except Exception as e:
        print(f"[PG] 프로젝트 DB 생성 실패 (postgres DB 폴백): {e}")
        return "postgres"
