"""
FILE: scripts/lock_manager.py
DESCRIPTION: 에이전트 간 파일 수정 충돌을 방지하기 위한 파일 잠금(Lock) 관리 도구.
             특정 파일을 수정하기 전 'acquire'를 호출하여 잠금을 획득하고, 완료 후 'release'함.

REVISION HISTORY:
- 2026-03-06 Gemini: 최초 작성. JSON 기반 실시간 잠금 메커니즘 구현.
"""

import os
import json
import sys
import time
from datetime import datetime
from pathlib import Path

# 데이터 디렉토리 설정
DATA_DIR = Path(__file__).parent.parent / ".ai_monitor" / "data"
LOCK_FILE = DATA_DIR / "locks.json"

def _get_agent():
    return os.getenv('HIVE_AGENT', 'unknown')

def _load_locks():
    if not LOCK_FILE.exists():
        return {}
    try:
        with open(LOCK_FILE, 'r', encoding='utf-8') as f:
            return json.load(f)
    except Exception:
        return {}

def _save_locks(locks):
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    with open(LOCK_FILE, 'w', encoding='utf-8') as f:
        json.dump(locks, f, ensure_ascii=False, indent=2)

def acquire(file_path):
    """파일에 대한 잠금 획득 시도"""
    abs_path = str(Path(file_path).absolute())
    locks = _load_locks()
    agent = _get_agent()
    
    if abs_path in locks:
        owner = locks[abs_path].get('agent', 'unknown')
        if owner != agent:
            print(f"❌ [Fail] 파일이 이미 잠겨 있습니다: {file_path} (소유자: {owner})")
            return False
    
    locks[abs_path] = {
        "agent": agent,
        "locked_at": datetime.now().isoformat(),
        "pid": os.getpid()
    }
    _save_locks(locks)
    print(f"🔒 [Locked] {file_path} (에이전트: {agent})")
    return True

def release(file_path):
    """파일에 대한 잠금 해제"""
    abs_path = str(Path(file_path).absolute())
    locks = _load_locks()
    agent = _get_agent()
    
    if abs_path in locks:
        if locks[abs_path].get('agent') == agent:
            del locks[abs_path]
            _save_locks(locks)
            print(f"🔓 [Released] {file_path}")
            return True
        else:
            print(f"⚠️ [Warning] 잠금 소유자가 아닙니다. 해제 불가: {file_path}")
            return False
    return True

def status():
    """현재 모든 잠금 상태 출력"""
    locks = _load_locks()
    if not locks:
        print("현재 잠긴 파일이 없습니다.")
        return
    
    print("\n--- [Active File Locks] ---")
    for path, info in locks.items():
        print(f"📍 {os.path.relpath(path)} | 에이전트: {info['agent']} | 일시: {info['locked_at']}")
    print("---------------------------\n")

if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("사용법: python lock_manager.py [acquire|release|status] <file_path>")
        sys.exit(1)
    
    cmd = sys.argv[1]
    if cmd == "status":
        status()
    elif len(sys.argv) >= 3:
        target = sys.argv[2]
        if cmd == "acquire":
            if not acquire(target): sys.exit(1)
        elif cmd == "release":
            release(target)
    else:
        print("파일 경로를 입력하세요.")
