import sqlite3
import json
import time
from datetime import datetime
from src.db import get_connection, init_db

def _ensure_tables():
    """테이블이 존재하는지 확인하고 없으면 초기화합니다."""
    conn = get_connection()
    try:
        cursor = conn.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='session_logs'")
        if not cursor.fetchone():
            print("[DB] session_logs 테이블이 없어 초기화를 시도합니다.")
            init_db()
    except Exception as e:
        print(f"[DB-ERR] 테이블 확인 실패: {e}")
    finally:
        conn.close()

def insert_log(session_id, terminal_id, agent, trigger_msg, project="hive", status="running"):
    """작업 로그를 삽입합니다. 실패 시 에러를 던지지 않고 로그만 남깁니다."""
    try:
        _ensure_tables()
        conn = get_connection()
        try:
            conn.execute('''
                INSERT INTO session_logs (session_id, terminal_id, project, agent, trigger_msg, status)
                VALUES (?, ?, ?, ?, ?, ?)
            ''', (session_id, terminal_id, project, agent, trigger_msg, status))
            conn.commit()
        finally:
            conn.close()
    except Exception as e:
        print(f"[DB-ERR] insert_log 실패 (무시됨): {e}")

def get_recent_logs(limit=50):
    """최근 로그를 가져옵니다."""
    try:
        _ensure_tables()
        conn = get_connection()
        try:
            cursor = conn.execute('''
                SELECT * FROM session_logs
                ORDER BY id DESC LIMIT ?
            ''', (limit,))
            rows = [dict(row) for row in cursor.fetchall()]
            return rows[::-1] 
        finally:
            conn.close()
    except Exception as e:
        print(f"[DB-ERR] get_recent_logs 실패: {e}")
        return []

def send_message(msg_id, from_agent, to_agent, msg_type, content):
    """메시지를 삽입합니다. ID 중복 시 재시도 로직을 포함합니다."""
    try:
        _ensure_tables()
        conn = get_connection()
        try:
            # 중복 ID 방지를 위한 루프 (최대 3회)
            for attempt in range(3):
                try:
                    current_id = msg_id if attempt == 0 else f"{msg_id}_{int(time.time() % 1000)}"
                    conn.execute('''
                        INSERT INTO messages (id, msg_from, msg_to, msg_type, content)
                        VALUES (?, ?, ?, ?, ?)
                    ''', (current_id, from_agent, to_agent, msg_type, content))
                    conn.commit()
                    return True
                except sqlite3.IntegrityError:
                    if attempt == 2: raise
                    time.sleep(0.01)
                    continue
        finally:
            conn.close()
    except Exception as e:
        print(f"[DB-ERR] send_message 실패 (무시됨): {e}")
        return False

def get_messages(limit=50):
    """최근 메시지를 가져옵니다."""
    try:
        _ensure_tables()
        conn = get_connection()
        try:
            cursor = conn.execute('''
                SELECT * FROM messages
                ORDER BY timestamp DESC LIMIT ?
            ''', (limit,))
            return [dict(row) for row in cursor.fetchall()]
        finally:
            conn.close()
    except Exception as e:
        print(f"[DB-ERR] get_messages 실패: {e}")
        return []
