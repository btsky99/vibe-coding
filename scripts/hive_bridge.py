import sys
import os
from datetime import datetime
import json

# secure 모듈을 임포트하기 위해 .ai_monitor/src 경로를 sys.path에 추가
sys.path.append(os.path.join(os.path.dirname(__file__), '..', '.ai_monitor', 'src'))
try:
    from secure import mask_sensitive_data
except ImportError:
    def mask_sensitive_data(text): return text

def log_task(agent_name, task_summary):
    """
    하이브 마인드 상황판에 수행된 작업 결과를 로그로 남깁니다.
    이 파일은 프로젝트의 모든 에이전트(Gemini, Claude 등)가 공통으로 사용합니다.
    """
    log_dir = ".ai_monitor/data"
    if not os.path.exists(log_dir):
        os.makedirs(log_dir)
    
    log_file = os.path.join(log_dir, "task_logs.jsonl")
    archive_file = os.path.join(log_dir, "task_logs_archive.jsonl")
    MAX_LINES = 50  # 최신 로그 유지 갯수 (AI 토큰 최적화)
    
    # 보안 마스킹 처리 적용 (API Key, 토큰 등 숨김)
    safe_summary = mask_sensitive_data(task_summary)
    
    log_entry = {
        "timestamp": datetime.now().isoformat(),
        "agent": agent_name,
        "task": safe_summary
    }
    
    new_line = json.dumps(log_entry, ensure_ascii=False) + "\n"
    
    lines = []
    if os.path.exists(log_file):
        with open(log_file, "r", encoding="utf-8") as f:
            lines = f.readlines()
            
    lines.append(new_line)
    
    # MAX_LINES 초과 시 오래된 로그는 아카이브 파일로 이동
    if len(lines) > MAX_LINES:
        excess = len(lines) - MAX_LINES
        with open(archive_file, "a", encoding="utf-8") as af:
            af.writelines(lines[:excess])
        lines = lines[excess:]
        
    with open(log_file, "w", encoding="utf-8") as f:
        f.writelines(lines)
    
    # SQLite DB (session_logs) 에도 연동하여 웹 대시보드(Nexus View) SSE 스트림에 실시간으로 표시
    try:
        aimon_path = os.path.abspath(os.path.join(os.path.dirname(__file__), '..', '.ai_monitor'))
        sys.path.append(aimon_path)
        from src.db_helper import insert_log
        insert_log(
            session_id=f"hive_{datetime.now().strftime('%H%M%S')}",
            terminal_id="HIVE_BRIDGE",
            agent=agent_name,
            trigger_msg=safe_summary,
            project="hive",
            status="success"
        )
    except ImportError as e:
        print(f"Warning: Failed to import db_helper for SQLite logging: {e}")
    except Exception as e:
        print(f"Warning: Failed to insert log to SQLite DB: {e}")
    
    print(f"[OK] [{agent_name}] Task logged to Hive: {safe_summary}")

if __name__ == "__main__":
    if len(sys.argv) >= 3:
        log_task(sys.argv[1], sys.argv[2])
    else:
        print("Usage: python scripts/hive_bridge.py [agent_name] [task_summary]")
