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

def read_all_sessions() -> dict:
    """sessions.jsonl의 모든 줄을 읽어 session_id를 키로 하는 dict 반환"""
    sessions = {}
    if not SESSIONS_FILE.exists():
        return sessions
    
    with open(SESSIONS_FILE, "r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                record = json.loads(line)
                sid = record.get("session_id")
                if sid:
                    sessions[sid] = record
            except json.JSONDecodeError:
                continue
    return sessions

def write_all_sessions(sessions: dict):
    """dict 데이터를 sessions.jsonl에 덮어씁니다."""
    with open(SESSIONS_FILE, "w", encoding="utf-8") as f:
        for sid, record in sessions.items():
            f.write(json.dumps(record, ensure_ascii=False) + "\n")

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
        "ts_end": "",
        "project": project,
        "project_path": project_path,
        "agent": agent,
        "skill": skill,
        "trigger": mask_sensitive_data(trigger),
        "status": "running",
        "duration_sec": 0,
        "commit": "",
        "files_changed": [],
        "phases": []
    }
    
    lock = FileLock(LOCK_FILE, timeout=5)
    try:
        with lock:
            sessions = read_all_sessions()
            sessions[session_id] = record
            write_all_sessions(sessions)
    except Exception as e:
        print(f"Error in log_start: {e}", file=sys.stderr)
        
    return session_id

def log_phase(session_id: str, phase_name: str, status: str, detail: str):
    """특정 세션의 단계를 업데이트합니다."""
    lock = FileLock(LOCK_FILE, timeout=5)
    try:
        with lock:
            sessions = read_all_sessions()
            if session_id in sessions:
                phase_record = {
                    "name": phase_name,
                    "status": status,
                    "detail": mask_sensitive_data(detail),
                    "ts": datetime.datetime.now().isoformat()
                }
                sessions[session_id]["phases"].append(phase_record)
                write_all_sessions(sessions)
            else:
                print(f"Session {session_id} not found.", file=sys.stderr)
    except Exception as e:
        print(f"Error in log_phase: {e}", file=sys.stderr)

def log_end(session_id: str, status: str, commit: str = "", files_changed: list = None):
    """작업 세션을 종료 처리합니다."""
    if files_changed is None:
        files_changed = []
        
    lock = FileLock(LOCK_FILE, timeout=5)
    try:
        with lock:
            sessions = read_all_sessions()
            if session_id in sessions:
                record = sessions[session_id]
                now = datetime.datetime.now()
                try:
                    start_time = datetime.datetime.fromisoformat(record["ts_start"])
                    duration = int((now - start_time).total_seconds())
                except ValueError:
                    duration = 0
                
                record["ts_end"] = now.isoformat()
                record["status"] = status
                record["duration_sec"] = duration
                record["commit"] = commit
                record["files_changed"] = files_changed
                
                write_all_sessions(sessions)
            else:
                print(f"Session {session_id} not found.", file=sys.stderr)
    except Exception as e:
        print(f"Error in log_end: {e}", file=sys.stderr)

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
