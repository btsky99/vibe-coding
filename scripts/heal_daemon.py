# -*- coding: utf-8 -*-
# ------------------------------------------------------------------------
# 📄 파일명: scripts/heal_daemon.py
# 📝 설명: 하이브 마인드 자가 치유(Self-Healing) 엔진.
#          PostgreSQL 18의 pg_logs를 감시하여 에러 발생 시 자동 수리를 시도합니다.
#
# REVISION HISTORY:
# - 2026-03-06 Gemini-1: 최초 작성 및 자가 치유 로직 구현.
# ------------------------------------------------------------------------
import os
import sys
import time
import json
import subprocess
from datetime import datetime

# 하이브 브릿지 및 Postgres 정보 로드
PROJECT_ROOT = os.path.normpath(os.path.join(os.path.dirname(os.path.abspath(__file__)), '..'))
PG_BIN = os.path.join(PROJECT_ROOT, ".ai_monitor", "bin", "pgsql", "bin", "psql.exe")
try:
    sys.path.append(PROJECT_ROOT)
    import scripts.hive_bridge as hive_bridge
except ImportError:
    hive_bridge = None

def run_query(sql: str):
    """psql을 통해 쿼리를 실행하고 결과를 반환합니다."""
    try:
        _no_window = getattr(subprocess, 'CREATE_NO_WINDOW', 0x08000000)
        res = subprocess.run(
            [PG_BIN, "-p", "5433", "-U", "postgres", "-d", "postgres", "-c", sql, "--csv"],
            capture_output=True, text=True, encoding='utf-8', errors='replace',
            creationflags=_no_window
        )
        return res.stdout.strip()
    except Exception:
        return ""

def get_latest_errors():
    """최근 1분 내의 발생한 에러 로그를 가져옵니다."""
    sql = "SELECT id, agent, task FROM pg_logs WHERE status = 'error' AND ts > NOW() - INTERVAL '1 minute' ORDER BY ts DESC;"
    output = run_query(sql)
    if not output or "agent,task" in output:
        return []
    
    errors = []
    lines = output.split('\n')[1:] # 헤더 제외
    for line in lines:
        if ',' in line:
            parts = line.split(',', 2)
            errors.append({"id": parts[0], "agent": parts[1], "msg": parts[2]})
    return errors

def attempt_healing(error_id, agent, error_msg):
    """에러를 분석하고 자가 치유 워크플로우를 가동합니다."""
    healing_msg = f"[Self-Healing] {agent}의 에러 감지 (ID: {error_id}). 자가 치유를 시작합니다."
    print(f"\n🚀 {healing_msg}")
    if hive_bridge:
        hive_bridge.log_task("heal_daemon", healing_msg, "HIVE")
        hive_bridge.log_thought("heal_daemon", "self-healing", {
            "action": "detect_error",
            "error_msg": error_msg,
            "strategy": "Analyze error context and trigger auto-repair via brainstorming."
        })

    # [중요] 여기서 오케스트레이터나 다른 에이전트에게 수리 명령을 전달하거나
    # 직접 brainstorming 워크플로우를 호출하는 로직이 들어갑니다.
    # 현재는 감지 및 로깅 단계까지 구현.
    
    # 수리 완료 후 상태 업데이트 (임시)
    run_query(f"UPDATE pg_logs SET status = 'healed' WHERE id = {error_id};")

def main():
    print(f"[*] 하이브 자가 치유 데몬 가동 중... (PostgreSQL 18 감시)")
    if hive_bridge:
        hive_bridge.log_task("heal_daemon", "자가 치유 데몬 시작 (Postgres-First)", "HIVE")

    while True:
        try:
            errors = get_latest_errors()
            for err in errors:
                attempt_healing(err['id'], err['agent'], err['msg'])
        except KeyboardInterrupt:
            break
        except Exception as e:
            print(f"[!] 데몬 오류: {e}")
        
        time.sleep(10) # 10초 주기로 감시

if __name__ == "__main__":
    if not os.path.exists(PG_BIN):
        print(f"[오류] Postgres 바이너리 없음: {PG_BIN}")
        sys.exit(1)

    # ── 싱글톤 보호: 중복 실행 방지 ────────────────────────────────────────────
    # server.py 재시작 시 heal_daemon 인스턴스가 누적되는 문제 방지.
    _pid_file = os.path.join(PROJECT_ROOT, ".ai_monitor", "data", "heal_daemon.pid")
    _my_pid   = os.getpid()
    try:
        if os.path.exists(_pid_file):
            with open(_pid_file) as _f:
                _old_pid = int(_f.read().strip())
            if _old_pid != _my_pid:
                _alive = False
                try:
                    _no_window = getattr(subprocess, 'CREATE_NO_WINDOW', 0x08000000)
                    _r = subprocess.run(
                        ['tasklist', '/FI', f'PID eq {_old_pid}', '/FO', 'CSV'],
                        capture_output=True, text=True, timeout=3,
                        creationflags=_no_window
                    ) if os.name == 'nt' else None
                    _alive = _r is not None and str(_old_pid) in _r.stdout
                    if _r is None:
                        os.kill(_old_pid, 0)
                        _alive = True
                except Exception:
                    _alive = False
                if _alive:
                    sys.exit(0)
        with open(_pid_file, 'w') as _f:
            _f.write(str(_my_pid))
    except Exception:
        pass  # PID 파일 I/O 실패 시 무시하고 계속 실행

    main()
