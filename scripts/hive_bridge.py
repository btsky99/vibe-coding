# -*- coding: utf-8 -*-
# ------------------------------------------------------------------------
# 📄 파일명: scripts/hive_bridge.py
# 📝 설명: 에이전트 작업 로그를 하이브 마인드(task_logs.jsonl + hive_mind.db)에 기록합니다.
#          모든 에이전트(Claude, Gemini 등)가 공통 사용하는 로그 브릿지.
#
# 🕒 변경 이력 (History):
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


def log_task(agent_name, task_summary):
    """
    하이브 마인드 상황판에 수행한 작업 결과를 로그로 남깁니다.
    이 파일은 프로젝트의 모든 에이전트(Gemini, Claude 등)가 공통으로 사용합니다.
    """
    log_dir = _resolve_log_dir()
    if not os.path.exists(log_dir):
        os.makedirs(log_dir)
    
    log_file = os.path.join(log_dir, "task_logs.jsonl")
    archive_file = os.path.join(log_dir, "task_logs_archive.jsonl")
    MAX_LINES = 50  # 최신 로그 유지 개수 (AI 토큰 최적화)
    
    # 보안 마스킹 처리 적용 (API Key, 토큰 등 누출 방지)
    safe_summary = mask_sensitive_data(task_summary)
    
    log_entry = {
        "timestamp": datetime.now().isoformat(),
        "agent": agent_name,
        "task": safe_summary
    }
    
    new_line = json.dumps(log_entry, ensure_ascii=False, indent=None) + "\n"
    
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
    
    print(f"[OK] [{agent_name}] Task logged to Hive: {safe_summary}")

if __name__ == "__main__":
    if len(sys.argv) >= 3:
        log_task(sys.argv[1], sys.argv[2])
    else:
        print("Usage: python scripts/hive_bridge.py [agent_name] [task_summary]")
