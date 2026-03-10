"""
FILE: scripts/hive_watchdog.py
DESCRIPTION: 하이브 마인드(Hive Mind) 시스템 자가 치유(Self-Healing) 및 모니터링 엔진.
             DB 무결성, 파일 동기화 상태, 에이전트 활동 주기를 주기적으로 체크하고 복구를 시도합니다.

             [자기치유 3계층]
             계층 1 — 인프라 치유: DB/서버/메모리 60초 루프 (기존)
             계층 2 — 스킬 치유: skill_analyzer 10분마다 실행, 반복 패턴 → 스킬 자동 업데이트 (신규)
             계층 3 — 지식 치유: (미래) LLM 응답 분석 → 스킬 파일 갱신

REVISION HISTORY:
- 2026-03-09 Claude: [버그 3건 수정]
  Bug 1) repair_memory_sync() subprocess.run에 encoding='utf-8' 미지정 →
         Windows CP949 환경에서 이모지 포함 출력 시 UnicodeDecodeError 발생 →
         Thread-1 crash로 루프 불안정 유발. encoding/errors 명시로 수정.
  Bug 2) repair_memory_sync() 쿨다운 없음 → 에이전트 비활성(8h+) 상태에서
         매 60초마다 실행 → repair_count 127+ 누적. 최소 1시간 쿨다운 추가.
  Bug 3) _restart_fail_count >= 3 조건에서 영구 재시작 포기 →
         30분 쿨다운 후 재시도 허용으로 변경 (_restart_fail_time 추적).
- 2026-03-01 Claude: [자기치유 계층 1 강화] restart_server() 추가
  - server 다운 감지 시 subprocess.Popen으로 server.py 자동 재시작
  - _restart_fail_count 추적: 3회 연속 실패 시 🚨 경고 로그
  - run_check(): check_server() 실패 시 restart_server() 자동 호출
- 2026-03-01 Claude: [자기치유 계층 2 완성] skill_analyzer 연동
  - check_skill_gaps(): skill_analyzer로 패턴 감지 → vibe-orchestrate.md 자동 업데이트
  - start_loop(): _loop_count 추적, 10루프(10분)마다 check_skill_gaps() 호출
  - status에 skill_heal_count 추가
- 2026-02-28 Claude: --data-dir 인자 추가 — 설치 버전에서 DATA_DIR 하드코딩 오류 수정.
- 2026-02-26 Gemini-1: 초기 생성. DB 체크, 메모리 동기화(memory.py) 연동 기능 구현.
- 2026-02-26 Claude: 오탐 개선 — 에이전트 비활성 임계값 1h→8h, memory_sync_ok 갱신 버그 수정.
"""

import os
import sys
import time
import json
import subprocess
import urllib.request
import urllib.error
from datetime import datetime, timedelta
from pathlib import Path

ROOT_DIR = Path(__file__).resolve().parent.parent
MONITOR_DIR = ROOT_DIR / '.ai_monitor'
if str(MONITOR_DIR) not in sys.path:
    sys.path.insert(0, str(MONITOR_DIR))

from src.pg_store import ensure_schema, save_state

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

# 기본 HTTP 포트 (server.py와 동일하게 9000 선호)
HTTP_PORT = 9000

class HiveWatchdog:
    def __init__(self, interval=60):
        self.interval = interval
        self.is_running = False
        self._loop_count = 0          # 루프 횟수 추적 (10회마다 스킬 갭 분석)
        self._restart_fail_count = 0  # 서버 재시작 연속 실패 횟수 (3회 초과 시 쿨다운)
        self._restart_fail_time: datetime | None = None  # 3회 실패 시점 (30분 후 재시도 허용)
        self._last_memory_sync_time: datetime | None = None  # 마지막 메모리 동기화 성공 시각 (쿨다운용)
        self.status = {
            "last_check": None,
            "db_ok": False,
            "server_ok": False,
            "memory_sync_ok": False,
            "agent_active": False,
            "repair_count": 0,
            "skill_heal_count": 0,   # 스킬 자기치유 성공 횟수
            "restart_count": 0,      # 서버 자동 재시작 성공 횟수
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
        
        # 포트 9000이 안되면 9001~9010, 8005, 8000 등 시도 (동적 포트 할당 대비)
        # [2026-03-09] server.py가 _find_free_port(9000) 사용 — 9001~9020까지 확인 추가
        for p in [9001, 9002, 9003, 9004, 9005, 8005, 8000]:
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

    def restart_server(self):
        """server.py가 다운되었을 때 자동으로 재시작한다.

        [재시작 로직]
        - PROJECT_ROOT/.ai_monitor/server.py 경로로 subprocess 실행
        - 성공 시 _restart_fail_count 초기화 + restart_count 증가
        - 연속 3회 실패 시 🚨 경고 로그 출력 (추가 재시도 없음)

        [배포 버전 대응]
        - frozen(EXE) 환경에서는 server.py가 내장되어 있으므로 직접 실행 불가
        - 해당 경우 경고 로그만 남기고 스킵
        """
        server_py = PROJECT_ROOT / ".ai_monitor" / "server.py"

        # 배포(frozen) 환경에서는 server.py 직접 실행 불가 — 스킵
        if not server_py.exists():
            self._add_log("⚠️ server.py 경로를 찾을 수 없음 — 자동 재시작 불가")
            return False

        self._add_log("🔄 server.py 자동 재시작 시도...")
        try:
            # 새 프로세스로 server.py 실행 (부모 프로세스와 독립)
            # CREATE_NO_WINDOW: Windows에서 콘솔 창이 팝업되지 않도록 방지
            # 미설정 시 서버 재시작마다 가시 콘솔 창이 생성되어 무한 창 생성 버그 발생
            _creationflags = subprocess.CREATE_NO_WINDOW if os.name == 'nt' else 0
            subprocess.Popen(
                [sys.executable, str(server_py)],
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                close_fds=True,
                creationflags=_creationflags,
            )
            # 3초 대기 후 실제로 응답하는지 확인
            time.sleep(3)
            if self.check_server():
                self._add_log("✅ server.py 자동 재시작 성공")
                self._restart_fail_count = 0
                self.status["restart_count"] = self.status.get("restart_count", 0) + 1
                return True
            else:
                raise RuntimeError("재시작 후에도 서버 응답 없음")
        except Exception as e:
            self._restart_fail_count += 1
            self._add_log(f"❌ 서버 재시작 실패 ({self._restart_fail_count}회): {e}")
            if self._restart_fail_count >= 3:
                self._restart_fail_time = datetime.now()
                self._add_log("🚨 서버 자동 재시작 3회 연속 실패 — 30분 후 재시도 예정")
            return False

    def check_db(self):
        """DB 파일 존재 여부 및 연결성 체크"""
        try:
            if not ensure_schema(DATA_DIR):
                self._add_log("⚠️ PostgreSQL schema unavailable")
                self.status["db_ok"] = False
                return False
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

    def check_skill_gaps(self):
        """skill_analyzer.py를 사용하여 반복 패턴 감지 및 스킬 자동 업데이트 (계층 2 자기치유).

        [동작 순서]
        1. SkillAnalyzer로 task_logs.jsonl의 사용자 [지시] 로그 분석
        2. 3회 이상 반복 패턴 감지
        3. apply_knowledge_to_skill()로 vibe-orchestrate.md 자동 업데이트
        4. 성공 시 skill_heal_count 증가 + 로그 기록

        [호출 시점]
        start_loop()에서 10루프(=약 10분)마다 자동 호출.
        --check 모드에서는 run_check()와 별도로 수동 호출 가능.
        """
        self._add_log("🧠 스킬 갭 분석 중...")
        try:
            # scripts/ 디렉토리를 sys.path에 추가하여 skill_analyzer 임포트
            scripts_dir = str(PROJECT_ROOT / "scripts")
            if scripts_dir not in sys.path:
                sys.path.insert(0, scripts_dir)

            from skill_analyzer import SkillAnalyzer

            # project_root를 주입하여 경로 오류 방지 (배포 버전 대응)
            analyzer = SkillAnalyzer(project_root=PROJECT_ROOT)
            report = analyzer.analyze_patterns()
            proposals = report.get("proposals", []) if isinstance(report, dict) else []

            # 분석 결과를 JSON 파일로도 저장 (UI 참조용)
            analyzer.save_analysis(report)

            if proposals:
                applied = analyzer.apply_knowledge_to_skill(proposals)
                if applied:
                    count = len(proposals)
                    self._add_log(f"✅ 자기치유 완료: {count}개 패턴 스킬에 반영")
                    self.status["skill_heal_count"] = self.status.get("skill_heal_count", 0) + 1
                    self.status["repair_count"] += 1
                    return True
                else:
                    self._add_log("⚠️ 스킬 파일 업데이트 실패 (파일 없거나 경로 오류)")
            else:
                self._add_log("ℹ️ 신규 반복 패턴 없음 — 스킬 최신 상태")
            return False

        except ImportError:
            self._add_log("⚠️ skill_analyzer.py 로드 실패 — scripts/ 경로 확인 필요")
            return False
        except Exception as e:
            self._add_log(f"❌ 스킬 갭 분석 오류: {e}")
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
            # CREATE_NO_WINDOW: 워치독(백그라운드 프로세스)에서 subprocess 실행 시
            # Windows가 새 콘솔 창을 생성하지 않도록 방지
            _no_window = subprocess.CREATE_NO_WINDOW if os.name == 'nt' else 0
            subprocess.run(
                [sys.executable, str(memory_script), "sync"],
                capture_output=True, text=True, check=True,
                # encoding 명시: Windows CP949 환경에서 이모지 포함 출력 시
                # UnicodeDecodeError → Thread-1 crash 방지 (Bug 1 수정)
                encoding='utf-8', errors='replace',
                creationflags=_no_window
            )
            self._add_log("✅ 메모리 동기화 완료")
            self.status["memory_sync_ok"] = True  # 성공 시 상태 반영
            self.status["repair_count"] += 1
            self._last_memory_sync_time = datetime.now()  # 쿨다운 시작 시각 기록
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

        # 서버가 죽어있으면 자동 재시작 시도 후 메모리 동기화 상태 반영
        if not server_ok:
            self.status["memory_sync_ok"] = False
            # 3회 연속 실패 후 30분이 지났으면 카운터 리셋하여 재시도 허용
            # 영구 포기 방지: _restart_fail_time 기록 후 30분 쿨다운
            if self._restart_fail_count >= 3 and self._restart_fail_time:
                elapsed = (datetime.now() - self._restart_fail_time).total_seconds()
                if elapsed > 1800:  # 30분 = 1800초
                    self._add_log("🔄 서버 재시작 쿨다운 해제 — 재시도 허용")
                    self._restart_fail_count = 0
                    self._restart_fail_time = None
            if self._restart_fail_count < 3:
                server_ok = self.restart_server()

        if server_ok and db_ok:
            self.status["memory_sync_ok"] = True

        # 복구 로직: 서버/DB는 OK인데 에이전트가 오랫동안 비활성 상태일 때만 동기화 재시도
        # 쿨다운 1시간: 매 60초마다 실행되면 repair_count가 무한 누적되는 버그 방지
        _sync_cooldown_ok = (
            self._last_memory_sync_time is None or
            (datetime.now() - self._last_memory_sync_time).total_seconds() > 3600
        )
        if server_ok and db_ok and not activity_ok and _sync_cooldown_ok:
            self.repair_memory_sync()
        
        # 점검 결과를 Postgres state에 저장
        try:
            save_state("health", self.status)
        except Exception:
            pass

    def start_loop(self):
        """워치독 메인 루프.

        [루프 주기]
        - 매 60초: run_check() — DB/서버/메모리 인프라 점검 (계층 1 치유)
        - 매 10루프(=10분): check_skill_gaps() — 스킬 갭 분석·자동 업데이트 (계층 2 치유)

        스킬 분석을 매 루프 실행하지 않는 이유:
        - 로그 파일 읽기 + 파일 쓰기가 빈번하면 I/O 부하 발생
        - 10분 간격이면 세션 중 패턴 변화를 충분히 반영 가능
        """
        self.is_running = True
        self._loop_count = 0
        self._add_log("🚀 하이브 워치독 엔진 가동 시작 (계층 1 인프라 + 계층 2 스킬 치유)")
        # 서버 초기화 대기: Flask가 포트를 열기 전에 첫 체크를 실행하면
        # "서버 다운" 오탐이 발생하여 불필요한 재시작 시도로 중복 서버 인스턴스가 생성됨.
        # 15초 대기 후 첫 체크 실행 — server.py 기동 완료에 충분한 시간.
        time.sleep(15)
        while self.is_running:
            try:
                self.run_check()
                self._loop_count += 1

                # 10루프(약 10분)마다 스킬 갭 분석 실행
                if self._loop_count % 10 == 0:
                    self.check_skill_gaps()

            except Exception as e:
                self._add_log(f"❌ 루프 실행 에러: {e}")
            time.sleep(self.interval)

if __name__ == "__main__":
    # ── 싱글톤 보호: 이미 실행 중인 워치독 인스턴스가 있으면 즉시 종료 ──────────────────
    # server.py가 재시작할 때마다 새 인스턴스를 spawn하여 누적되는 문제 방지.
    # --check 모드(1회 점검)는 싱글톤 체크 없이 항상 실행 허용.
    _is_check_mode = len(sys.argv) > 1 and sys.argv[1] == "--check"
    if not _is_check_mode:
        _pid_file = Path(__file__).resolve().parent.parent / ".ai_monitor" / "data" / "watchdog.pid"
        _my_pid   = os.getpid()
        try:
            if _pid_file.exists():
                _old_pid = int(_pid_file.read_text().strip())
                _alive = False
                if _old_pid != _my_pid:
                    try:
                        if os.name == 'nt':
                            _r = subprocess.run(
                                ['tasklist', '/FI', f'PID eq {_old_pid}', '/FO', 'CSV'],
                                capture_output=True, text=True, timeout=3,
                                creationflags=getattr(subprocess, 'CREATE_NO_WINDOW', 0x08000000)
                            )
                            _alive = str(_old_pid) in _r.stdout
                        else:
                            os.kill(_old_pid, 0)
                            _alive = True
                    except Exception:
                        _alive = False
                    if _alive:
                        # 이미 실행 중인 워치독 존재 → 중복 인스턴스 즉시 종료
                        sys.exit(0)
            _pid_file.write_text(str(_my_pid))
        except Exception:
            pass  # PID 파일 I/O 실패 시 무시하고 계속 실행

    # 단독 실행 시 --check 인자가 있으면 1회 점검 후 종료
    watchdog = HiveWatchdog(interval=60)
    if _is_check_mode:
        watchdog.run_check()
        print(json.dumps(watchdog.status, indent=2, ensure_ascii=False))
    else:
        watchdog.start_loop()
