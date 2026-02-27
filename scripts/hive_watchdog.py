"""
FILE: scripts/hive_watchdog.py
DESCRIPTION: 하이브 마인드(Hive Mind) 시스템 자가 치유(Self-Healing) 및 모니터링 엔진.
             DB 무결성, 파일 동기화 상태, 에이전트 활동 주기를 주기적으로 체크하고 복구를 시도합니다.
REVISION HISTORY:
- 2026-02-28 Claude: --data-dir 인자 추가 — 설치 버전에서 DATA_DIR 하드코딩 오류 수정.
- 2026-02-26 Gemini-1: 초기 생성. DB 체크, 메모리 동기화(memory.py) 연동 기능 구현.
- 2026-02-26 Claude: 오탐 개선 — 에이전트 비활성 임계값 1h→8h, memory_sync_ok 갱신 버그 수정.
"""

import os
import sys
import time
import json
import sqlite3
import subprocess
import urllib.request
import urllib.error
from datetime import datetime, timedelta
from pathlib import Path

# Windows 터미널(CP949 등)에서 이모지/한글 출력 시 UnicodeEncodeError 방지
if sys.stdout.encoding and sys.stdout.encoding.lower() not in ("utf-8", "utf8"):
    try:
        import io
        sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8', errors='replace')
        sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding='utf-8', errors='replace')
    except Exception:
        pass

# 프로젝트 루트 및 데이터 경로 설정
# --data-dir 인자가 있으면 해당 경로 사용 (설치 버전에서 server.py가 실제 DATA_DIR 전달)
# 없으면 __file__ 기준 상대 경로 (개발 모드)
def _resolve_data_dir() -> Path:
    for i, arg in enumerate(sys.argv[1:], 1):
        if arg == "--data-dir" and i < len(sys.argv):
            return Path(sys.argv[i + 1])
    return Path(__file__).resolve().parent.parent / ".ai_monitor" / "data"

PROJECT_ROOT = Path(__file__).resolve().parent.parent
DATA_DIR = _resolve_data_dir()
LOG_FILE = DATA_DIR / "task_logs.jsonl"
DB_FILE = DATA_DIR / "hive_mind.db"
MEMORY_DB = DATA_DIR / "shared_memory.db"

# 기본 HTTP 포트 (server.py와 동일하게 9571 선호)
HTTP_PORT = 9571

class HiveWatchdog:
    def __init__(self, interval=60):
        self.interval = interval
        self.is_running = False
        self.status = {
            "last_check": None,
            "db_ok": False,
            "server_ok": False,
            "memory_sync_ok": False,
            "agent_active": False,
            "repair_count": 0,
            "logs": []
        }

    def _add_log(self, msg):
        timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        log_entry = f"[{timestamp}] {msg}"
        print(log_entry)
        self.status["logs"].append(log_entry)
        if len(self.status["logs"]) > 20:
            self.status["logs"].pop(0)

    def check_server(self):
        """중앙 제어 서버(server.py)가 살아있는지 HTTP 하트비트 체크"""
        try:
            url = f"http://localhost:{HTTP_PORT}/api/heartbeat"
            with urllib.request.urlopen(url, timeout=3) as resp:
                if resp.status == 200:
                    self.status["server_ok"] = True
                    return True
        except Exception:
            pass
        
        # 포트 9571이 안되면 8005나 8000 등 다른 포트 시도 (서버가 포트 충돌로 밀려났을 경우 대비)
        for p in [8005, 8000]:
            try:
                url = f"http://localhost:{p}/api/heartbeat"
                with urllib.request.urlopen(url, timeout=2) as resp:
                    if resp.status == 200:
                        self.status["server_ok"] = True
                        return True
            except Exception:
                continue

        self._add_log("⚠️ 중앙 제어 서버(server.py) 응답 없음")
        self.status["server_ok"] = False
        return False

    def check_db(self):
        """DB 파일 존재 여부 및 연결성 체크"""
        try:
            if not DB_FILE.exists() or not MEMORY_DB.exists():
                self._add_log("⚠️ DB 파일 누락 감지")
                return False
            
            conn = sqlite3.connect(str(MEMORY_DB), timeout=2)
            conn.execute("SELECT count(*) FROM memory")
            conn.close()
            self.status["db_ok"] = True
            return True
        except Exception as e:
            self._add_log(f"❌ DB 체크 실패: {e}")
            self.status["db_ok"] = False
            return False

    def check_agent_activity(self):
        """최근 에이전트 활동 로그 확인 (8시간 이내 활동 여부)

        임계값을 8시간으로 설정한 이유:
        - 에이전트는 사용자 요청이 있을 때만 활동하므로 짧은 유휴 상태는 정상임
        - 1시간 임계값은 오탐(false alarm)을 과다 발생시켜 불필요한 복구 루프 유발
        """
        if not LOG_FILE.exists():
            self.status["agent_active"] = False
            return False

        try:
            with open(LOG_FILE, "r", encoding="utf-8") as f:
                lines = f.readlines()
                if not lines:
                    return False

                last_line = json.loads(lines[-1])
                last_time = datetime.fromisoformat(last_line["timestamp"])

                if datetime.now() - last_time < timedelta(hours=8):
                    self.status["agent_active"] = True
                    return True
                else:
                    self._add_log("⚠️ 장시간(8h+) 에이전트 활동 없음")
                    self.status["agent_active"] = False
                    return False
        except Exception as e:
            self._add_log(f"⚠️ 로그 분석 실패: {e}")
            return False

    def repair_memory_sync(self):
        """memory.py를 호출하여 에이전트 간 메모리 강제 동기화.

        성공 시 memory_sync_ok를 True로 갱신한다.
        기존에는 repair_count만 증가하고 상태 플래그를 업데이트하지 않아
        동기화 성공 후에도 UI에 항상 빨간불이 표시되는 버그가 있었음.
        """
        self._add_log("🔧 메모리 동기화 복구 시도 중...")
        try:
            memory_script = PROJECT_ROOT / "scripts" / "memory.py"
            subprocess.run(
                [sys.executable, str(memory_script), "sync"],
                capture_output=True, text=True, check=True
            )
            self._add_log("✅ 메모리 동기화 완료")
            self.status["memory_sync_ok"] = True  # 성공 시 상태 반영
            self.status["repair_count"] += 1
            return True
        except Exception as e:
            self._add_log(f"❌ 동기화 복구 실패: {e}")
            self.status["memory_sync_ok"] = False
            return False

    def run_check(self):
        """전체 점검 및 자동 복구 실행.

        복구 조건:
        - 서버가 정상이 아닐 경우 로그에 기록
        - DB가 정상인데 에이전트 활동이 8시간 이상 없는 경우에만 메모리 동기화 복구 실행
        - DB 자체가 정상이면 기본적으로 memory_sync_ok = True로 간주
        """
        self.status["last_check"] = datetime.now().isoformat()

        server_ok = self.check_server()
        db_ok = self.check_db()
        activity_ok = self.check_agent_activity()

        # 서버가 죽어있으면 메모리 동기화도 안 되므로 상태 반영
        if not server_ok:
            self.status["memory_sync_ok"] = False
        elif db_ok:
            self.status["memory_sync_ok"] = True

        # 복구 로직: 서버/DB는 OK인데 에이전트가 오랫동안 비활성 상태일 때만 동기화 재시도
        if server_ok and db_ok and not activity_ok:
            self.repair_memory_sync()
        
        # 점검 결과를 파일로 저장 (서버/UI에서 읽기 위함)
        health_file = DATA_DIR / "hive_health.json"
        with open(health_file, "w", encoding="utf-8") as f:
            json.dump(self.status, f, indent=2, ensure_ascii=False)

    def start_loop(self):
        self.is_running = True
        self._add_log("🚀 하이브 워치독 엔진 가동 시작")
        while self.is_running:
            try:
                self.run_check()
            except Exception as e:
                self._add_log(f"❌ 루프 실행 에러: {e}")
            time.sleep(self.interval)

if __name__ == "__main__":
    # 단독 실행 시 --check 인자가 있으면 1회 점검 후 종료
    watchdog = HiveWatchdog(interval=60)
    if len(sys.argv) > 1 and sys.argv[1] == "--check":
        watchdog.run_check()
        print(json.dumps(watchdog.status, indent=2, ensure_ascii=False))
    else:
        watchdog.start_loop()
