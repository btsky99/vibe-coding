import time
import threading
import psycopg2
import json
import sys
import os
from pathlib import Path

# 프로젝트 루트를 sys.path에 추가
ROOT = Path(__file__).resolve().parent.parent
sys.path.append(str(ROOT))
sys.path.append(str(ROOT / ".ai_monitor"))

# AI_MONITOR 내부 src 임포트를 위해 추가
os.environ["PYTHONPATH"] = str(ROOT) + ";" + str(ROOT / ".ai_monitor")

from src.db_helper import insert_log

def listener():
    print("👂 Listener: Starting...")
    conn = psycopg2.connect(host="localhost", port=5433, user="postgres", database="postgres")
    conn.set_isolation_level(psycopg2.extensions.ISOLATION_LEVEL_AUTOCOMMIT)
    cursor = conn.cursor()
    cursor.execute("LISTEN hive_log_channel;")
    
    start_time = time.time()
    while time.time() - start_time < 10:
        import select
        if select.select([conn], [], [], 1) == ([], [], []):
            continue
        else:
            conn.poll()
            while conn.notifies:
                notify = conn.notifies.pop(0)
                data = json.loads(notify.payload)
                print(f"🔥 Received NOTIFY: {data['agent']} -> {data['message']}")
    
    conn.close()
    print("👂 Listener: Stopped.")

if __name__ == "__main__":
    print("🚀 Testing PostgreSQL Logging & Notify...")
    
    # 1. 리스너 실행 (별도 스레드)
    t = threading.Thread(target=listener)
    t.start()
    
    time.sleep(1)
    
    # 2. 로그 삽입
    print("📢 Sending test log via insert_log()...")
    insert_log(
        session_id="test_session_123",
        terminal_id="TERM_1",
        agent="test_agent",
        trigger_msg="Hello PostgreSQL Hive Logic!",
        project="test_proj",
        status="running"
    )
    
    t.join()
    print("✅ Test Finished.")
