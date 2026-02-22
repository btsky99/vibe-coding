import sqlite3
import json
from datetime import datetime
from src.db import get_connection

def insert_log(session_id, terminal_id, agent, trigger_msg, project="hive", status="running"):
    conn = get_connection()
    try:
        conn.execute('''
            INSERT INTO session_logs (session_id, terminal_id, project, agent, trigger_msg, status)
            VALUES (?, ?, ?, ?, ?, ?)
        ''', (session_id, terminal_id, project, agent, trigger_msg, status))
        conn.commit()
    finally:
        conn.close()

def get_recent_logs(limit=50):
    conn = get_connection()
    try:
        cursor = conn.execute('''
            SELECT * FROM session_logs
            ORDER BY id DESC LIMIT ?
        ''', (limit,))
        
        # 결과를 dict 리스트로 변환하고 시간순(과거->최신)으로 뒤집음
        rows = [dict(row) for row in cursor.fetchall()]
        return rows[::-1] 
    finally:
        conn.close()

def send_message(msg_id, from_agent, to_agent, msg_type, content):
    conn = get_connection()
    try:
        conn.execute('''
            INSERT INTO messages (id, msg_from, msg_to, msg_type, content)
            VALUES (?, ?, ?, ?, ?)
        ''', (msg_id, from_agent, to_agent, msg_type, content))
        conn.commit()
    finally:
        conn.close()

def get_messages(limit=50):
    conn = get_connection()
    try:
        cursor = conn.execute('''
            SELECT * FROM messages
            ORDER BY timestamp DESC LIMIT ?
        ''', (limit,))
        return [dict(row) for row in cursor.fetchall()]
    finally:
        conn.close()
