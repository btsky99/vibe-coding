import os
import sys
import json
import uuid
import datetime
from pathlib import Path
from filelock import FileLock
from secure import parse_secure_payload, mask_sensitive_data

# 환경 설정 (현재 스크립트가 위치한 src 폴더의 부모 폴더 .ai_monitor 로 변경)
AI_MONITOR_DIR = Path(__file__).resolve().parent.parent
DATA_DIR = AI_MONITOR_DIR / "data"
CONFIG_FILE = AI_MONITOR_DIR / "config.json"
SESSIONS_FILE = DATA_DIR / "sessions.jsonl"
LOCK_FILE = DATA_DIR / "sessions.lock"

DATA_DIR.mkdir(parents=True, exist_ok=True)

def load_config() -> dict:
    try:
        with open(CONFIG_FILE, "r", encoding="utf-8") as f:
            return json.load(f)
    except FileNotFoundError:
        return {"max_log_mb": 10, "projects": {}}
    except Exception as e:
        print(f"Error loading config: {e}", file=sys.stderr)
        return {"max_log_mb": 10, "projects": {}}

def rotate_log_if_needed(max_mb: int):
    """지정된 MB를 초과하면 로그 파일을 로테이션(백업)합니다."""
    if not SESSIONS_FILE.exists():
        return
    
    size_mb = SESSIONS_FILE.stat().st_size / (1024 * 1024)
    if size_mb > max_mb:
        timestamp = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
        backup_file = DATA_DIR / f"sessions_{timestamp}.jsonl.bak"
        try:
            os.rename(SESSIONS_FILE, backup_file)
        except Exception as e:
            print(f"Failed to rotate log: {e}", file=sys.stderr)

def append_session_log(record: dict):
    """dict 데이터를 sessions.jsonl에 추가(append)합니다."""
    lock = FileLock(LOCK_FILE, timeout=5)
    try:
        with lock:
            with open(SESSIONS_FILE, "a", encoding="utf-8") as f:
                f.write(json.dumps(record, ensure_ascii=False) + "\n")
    except Exception as e:
        print(f"Error appending session log: {e}", file=sys.stderr)

def log_start(terminal_id: str, project: str, project_path: str, agent: str, skill: str, trigger: str) -> str:
    """새로운 작업 세션을 시작하고 session_id를 반환합니다."""
    config = load_config()
    rotate_log_if_needed(config.get("max_log_mb", 10))
    
    session_id = f"{uuid.uuid4().hex[:8]}_{terminal_id}"
    now = datetime.datetime.now().isoformat()
    
    record = {
        "session_id": session_id,
        "terminal_id": terminal_id,
        "ts_start": now,
        "project": project,
        "agent": agent,
        "trigger": mask_sensitive_data(trigger),
        "status": "running"
    }
    
    append_session_log(record)
    return session_id

def log_phase(session_id: str, phase_name: str, status: str, detail: str):
    """특정 세션의 단계를 업데이트합니다."""
    # Append-only 방식이므로, 해당 phase의 상태를 새 로그로 남깁니다.
    record = {
        "session_id": session_id,
        "terminal_id": session_id.split("_")[-1] if "_" in session_id else "UNKNOWN",
        "project": "phase",
        "agent": "system",
        "trigger": f"[{phase_name}] {mask_sensitive_data(detail)}",
        "status": status,
        "ts_start": datetime.datetime.now().isoformat()
    }
    append_session_log(record)

def log_end(session_id: str, status: str, commit: str = "", files_changed: list = None):
    """작업 세션을 종료 처리합니다."""
    if files_changed is None:
        files_changed = []
    
    record = {
        "session_id": session_id,
        "terminal_id": session_id.split("_")[-1] if "_" in session_id else "UNKNOWN",
        "project": "end",
        "agent": "system",
        "trigger": f"Session completed. Files changed: {len(files_changed)}",
        "status": status,
        "commit": commit,
        "files_changed": files_changed,
        "ts_start": datetime.datetime.now().isoformat()
    }
    append_session_log(record)

# CLI로 직접 실행 시 명령줄 대응 (안전성을 위해 Base64 페이로드 모드 지원)
if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("Usage: python logger.py <command> [args...]")
        sys.exit(1)
        
    command = sys.argv[1]
    
    # 예: python logger.py payload <base64_json_string>
    if command == "payload" and len(sys.argv) == 3:
        try:
            payload_data = parse_secure_payload(sys.argv[2])
            cmd = payload_data.get("command")
            
            if cmd == "start":
                sid = log_start(
                    payload_data.get("terminal_id", "TERM_UNKNOWN"),
                    payload_data.get("project", "unknown"),
                    payload_data.get("project_path", ""),
                    payload_data.get("agent", "unknown"),
                    payload_data.get("skill", "unknown"),
                    payload_data.get("trigger", "")
                )
                print(f"SESSION_ID={sid}")
                
            elif cmd == "phase":
                log_phase(
                    payload_data.get("session_id"),
                    payload_data.get("phase_name"),
                    payload_data.get("status"),
                    payload_data.get("detail", "")
                )
                print("Phase logged.")
                
            elif cmd == "end":
                log_end(
                    payload_data.get("session_id"),
                    payload_data.get("status"),
                    payload_data.get("commit", ""),
                    payload_data.get("files_changed", [])
                )
                print("End logged.")
                
        except Exception as e:
            print(f"Payload Error: {e}", file=sys.stderr)
            sys.exit(1)
            
    else:
        print("Direct command line args not fully implemented. Use payload mode for security.")
