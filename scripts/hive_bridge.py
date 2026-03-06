# -*- coding: utf-8 -*-
# ------------------------------------------------------------------------
# 📄 파일명: scripts/hive_bridge.py
# 📝 설명: 에이전트 작업 로그를 하이브 마인드(task_logs.jsonl + hive_mind.db)에 기록합니다.
#          모든 에이전트(Claude, Gemini 등)가 공통 사용하는 로그 브릿지.
#
# 🕒 변경 이력 (History):
# [2026-03-05] - Claude (Phase 1/2 실시간 협업 구현)
#   - _post_message(): messages.jsonl 직접 기록 헬퍼 추가
#   - log_task() 내 하트비트 자동 기록 (Phase 1)
#   - lock_file() / unlock_file() / check_conflict(): 충돌 방지 LOCK 시스템 (Phase 2)
# [2026-02-28] - Claude (배포 버전 경로 버그 수정)
#   - _resolve_log_dir() 함수 추가: CWD 상대경로 → frozen/개발 모드별 절대경로 계산
#   - ".ai_monitor/data" 하드코딩 제거 → 에이전트가 다른 디렉토리에서 호출해도 정상 동작
# ------------------------------------------------------------------------
import sys
import os
import io
from datetime import datetime
import json

# Windows 터미널(CP949 등)에서 이모지/한글 출력 시 UnicodeEncodeError 방지
if sys.stdout.encoding and sys.stdout.encoding.lower() not in ("utf-8", "utf8"):
    try:
        sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8', errors='replace')
        sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding='utf-8', errors='replace')
    except Exception:
        pass

# secure 모듈을 임포트하기 위해 .ai_monitor/src 경로를 sys.path에 추가
sys.path.append(os.path.join(os.path.dirname(__file__), '..', '.ai_monitor', 'src'))
try:
    from secure import mask_sensitive_data
except ImportError:
    def mask_sensitive_data(text): return text

def _resolve_log_dir() -> str:
    """배포(frozen)/개발 모드에 따라 올바른 데이터 디렉토리 경로를 반환합니다.

    - frozen 모드: PyInstaller 번들 exe 내에서 실행 시 %APPDATA%\\VibeCoding 사용
    - 개발 모드 : __file__ 기준 상대 경로 (.ai_monitor/data)
    - install-skills로 복사된 경우: __file__ 기준 경로가 올바른 프로젝트 data 디렉토리를 가리킴

    CWD 의존 상대경로(".ai_monitor/data")는 에이전트가 다른 디렉토리에서 호출할 경우
    잘못된 경로를 가리킬 수 있으므로 절대 경로를 사용합니다.
    """
    if getattr(sys, 'frozen', False):
        # PyInstaller 배포 버전 — 데이터는 APPDATA에 있음
        if os.name == 'nt':
            return os.path.join(os.getenv('APPDATA', ''), "VibeCoding")
        return os.path.join(os.path.expanduser("~"), ".vibe-coding")
    # 개발/설치 모드 — __file__ 기준으로 .ai_monitor/data 절대 경로 계산
    return os.path.normpath(
        os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', '.ai_monitor', 'data')
    )


def log_task(agent_name, task_summary, terminal_id=None):
    """
    하이브 마인드 상황판에 수행한 작업 결과를 로그로 남깁니다.
    이 파일은 프로젝트의 모든 에이전트(Gemini, Claude 등)가 공통으로 사용합니다.

    terminal_id: 터미널 식별자 (T1~T8). None이면 환경변수 TERMINAL_ID 자동 참조.
                 로그에 포함되어 대시보드에서 터미널별 필터링에 사용됨.
    """
    log_dir = _resolve_log_dir()
    if not os.path.exists(log_dir):
        os.makedirs(log_dir)

    log_file = os.path.join(log_dir, "task_logs.jsonl")
    archive_file = os.path.join(log_dir, "task_logs_archive.jsonl")
    MAX_LINES = 50  # 최신 로그 유지 개수 (AI 토큰 최적화)

    # 보안 마스킹 처리 적용 (API Key, 토큰 등 누출 방지)
    safe_summary = mask_sensitive_data(task_summary)

    # 터미널 ID: 인자 > 환경변수 > 기본값 T0 순으로 결정
    _tid = terminal_id or os.environ.get('TERMINAL_ID', 'T0')

    log_entry = {
        "timestamp": datetime.now().isoformat(),
        "agent": agent_name,
        "terminal_id": _tid,
        "task": safe_summary
    }
    
    new_line = json.dumps(log_entry, ensure_ascii=False, indent=None) + "\n"
    
    lines = []
    if os.path.exists(log_file):
        with open(log_file, "r", encoding="utf-8", errors="replace") as f:
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
    
    # SQLite DB (hive_mind.db) 에도 연동하여 바이브 코딩(Vibe Coding) SSE 스트림에 실시간으로 표시
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
    
    # Phase 1: 하트비트 메시지를 messages.jsonl에도 자동 기록
    # → 상대 에이전트가 메시지 탭에서 현재 작업 상황을 실시간 파악 가능
    _post_message(
        from_agent=agent_name,
        to_agent="all",
        msg_type="heartbeat",
        content=f"[작업 진행 중] {safe_summary}",
        log_dir=log_dir,
    )

    print(f"[OK] [{agent_name}] Task logged to Hive: {safe_summary}")


def _post_message(from_agent: str, to_agent: str, msg_type: str, content: str,
                  log_dir: str = None) -> bool:
    """messages.jsonl에 직접 메시지를 기록합니다 (서버 미실행 시 폴백 전용).

    send_message.py와 동일한 JSON 형식을 사용하여 대시보드 메시지 탭에 표시됩니다.
    서버가 실행 중이어도 여기서는 직접 파일 기록 방식만 사용합니다.
    (hive_bridge는 저수준 로깅 계층이므로 HTTP 의존성을 배제함)
    """
    import time as _time
    _dir = log_dir or _resolve_log_dir()
    messages_file = os.path.join(_dir, "messages.jsonl")
    msg = {
        "id": str(int(_time.time() * 1000)),
        "timestamp": datetime.now().strftime("%Y-%m-%dT%H:%M:%S"),
        "from": from_agent,
        "to": to_agent,
        "type": msg_type,
        "content": content,
        "read": False,
    }
    try:
        os.makedirs(_dir, exist_ok=True)
        with open(messages_file, "a", encoding="utf-8") as f:
            f.write(json.dumps(msg, ensure_ascii=False) + "\n")
        return True
    except Exception:
        return False


def lock_file(agent_name: str, file_path: str) -> None:
    """파일 수정 시작 전 LOCK 메시지를 messages.jsonl에 기록합니다 (Phase 2).

    다른 에이전트가 check_conflict()를 호출하면 이 LOCK을 감지하여 충돌을 방지합니다.

    Args:
        agent_name: 잠금을 요청하는 에이전트 이름 (예: "Claude", "Gemini")
        file_path:  수정할 파일 경로
    """
    _post_message(
        from_agent=agent_name,
        to_agent="all",
        msg_type="LOCK",
        content=f"[LOCK] {file_path}",
    )
    print(f"[LOCK] {agent_name} → {file_path}")


def unlock_file(agent_name: str, file_path: str) -> None:
    """파일 수정 완료 후 UNLOCK 메시지를 messages.jsonl에 기록합니다 (Phase 2).

    Args:
        agent_name: 잠금 해제를 요청하는 에이전트 이름
        file_path:  수정 완료한 파일 경로
    """
    _post_message(
        from_agent=agent_name,
        to_agent="all",
        msg_type="UNLOCK",
        content=f"[UNLOCK] {file_path}",
    )
    print(f"[UNLOCK] {agent_name} → {file_path}")


def check_conflict(file_path: str, my_agent: str = "") -> str | None:
    """messages.jsonl 최근 20줄을 검사하여 다른 에이전트의 LOCK 여부를 확인합니다 (Phase 2).

    동작:
    - LOCK 발견 후 같은 파일에 대한 UNLOCK이 없으면 충돌로 판단
    - 자기 자신의 LOCK은 무시 (my_agent 파라미터로 필터)

    Returns:
        충돌하는 에이전트 이름(str) 또는 충돌 없음(None)
    """
    log_dir = _resolve_log_dir()
    messages_file = os.path.join(log_dir, "messages.jsonl")
    if not os.path.exists(messages_file):
        return None

    try:
        with open(messages_file, "r", encoding="utf-8", errors="replace") as f:
            lines = f.readlines()
    except Exception:
        return None

    # 최근 20줄만 검사 (오래된 LOCK은 무시)
    recent = lines[-20:]
    locked_by = None
    for line in recent:
        try:
            entry = json.loads(line.strip())
        except Exception:
            continue
        if entry.get("type") == "LOCK" and file_path in entry.get("content", ""):
            locked_by = entry.get("from", "unknown")
        elif entry.get("type") == "UNLOCK" and file_path in entry.get("content", ""):
            locked_by = None  # UNLOCK 확인 → 충돌 해제

    # 자기 자신의 LOCK은 충돌이 아님
    if locked_by and locked_by == my_agent:
        return None
    return locked_by


if __name__ == "__main__":
    if len(sys.argv) >= 3:
        log_task(sys.argv[1], sys.argv[2])
    else:
        print("Usage: python scripts/hive_bridge.py [agent_name] [task_summary]")
