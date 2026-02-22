import sys
import os
from datetime import datetime

def log_task(agent_name, task_summary):
    """
    하이브 마인드 상황판에 수행된 작업 결과를 로그로 남깁니다.
    이 파일은 프로젝트의 모든 에이전트(Gemini, Claude 등)가 공통으로 사용합니다.
    """
    log_dir = ".ai_monitor/data"
    if not os.path.exists(log_dir):
        os.makedirs(log_dir)
    
    log_file = os.path.join(log_dir, "task_logs.jsonl")
    
    log_entry = {
        "timestamp": datetime.now().isoformat(),
        "agent": agent_name,
        "task": task_summary
    }
    
    with open(log_file, "a", encoding="utf-8") as f:
        import json
        f.write(json.dumps(log_entry, ensure_ascii=False) + "\n")
    
    print(f"[OK] [{agent_name}] Task logged to Hive: {task_summary}")

if __name__ == "__main__":
    if len(sys.argv) >= 3:
        log_task(sys.argv[1], sys.argv[2])
    else:
        print("Usage: python scripts/hive_bridge.py [agent_name] [task_summary]")
