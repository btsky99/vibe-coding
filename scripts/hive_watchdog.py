"""
FILE: scripts/hive_watchdog.py
DESCRIPTION: 하이브 마인드(Hive Mind) 시스템 자가 치유(Self-Healing) 및 모니터링 엔진.
             DB 무결성, 파일 동기화 상태, 에이전트 활동 주기를 주기적으로 체크하고 복구를 시도합니다.

             [자기치유 3계층]
             계층 1 — 인프라 치유: DB/서버/메모리 60초 루프 (기존)
             계층 2 — 스킬 치유: skill_analyzer 10분마다 실행, 반복 패턴 → 스킬 자동 업데이트 (신규)
             계층 3 — 지식 치유: (미래) LLM 응답 분석 → 스킬 파일 갱신

REVISION HISTORY:
- 2026-08-16 Claude: [🔴 "껐는데 자꾸 살아난다" 사고] 이 워치독이 범인이었다.
  ① restart_server() 가 띄우는 server.py 의 __main__ 은 HTTP 서버가 아니라 **GUI 앱 전체**다
     (server.py:2159 → main() → app_boot.run_gui_app → webview.create_window).
     "서버만 되살린다"는 기존 주석은 사실과 다르다 — 창까지 되살아난다.
  ② check_server() 가 9000~9005 만 두드렸는데 실제 포트는 (프로젝트×환경) 해시 슬롯
     9000/9002/9004/9006/9008 이다. 9006·9008 인스턴스는 살아 있어도 항상 '죽음' 판정.
  ③ 워치독은 앱의 자식인데 앱이 강제종료되면 cleanup_child_procs 가 안 돌아 **고아로
     생존**한다. 고아가 앱을 되살리고 그 앱이 또 워치독을 낳고 죽으며 자기증식했다
     (실측: 죽은 부모 PID 3개 + orchestrator 3벌 동시 생존).
  수정 = 감시자를 없애지 않고 '사람이 끈 것'만 가려낸다:
  - --port / --parent-pid 주입 (오판 제거)
  - infra.shutdown_marker 표식이 있으면 복구 포기 + 스스로 종료
  - 부모가 살아있으면 재시작 금지, 재시작 성공 시 스스로 종료(세대 누적 차단)
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

from infra import proc  # [표준] 콘솔 숨김 subprocess 래퍼 (경로삽입 후라야 import 가능)
from infra import shutdown_marker  # 사람이 끈 종료인지 판정 — 되살릴지 말지의 유일한 근거
from src.pg_store import ensure_schema, save_state, cleanup_expired_memory

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


def _resolve_int_arg(name: str) -> int:
    """--<name> <정수> 를 읽는다. 없거나 깨졌으면 0.

    [WHY argparse 를 안 쓰나] 이 스크립트는 `--check` 를 위치 인자처럼 쓰는 기존 호출부와
      `--data-dir` 만 넘기는 구버전 호출부가 함께 살아 있다. argparse 로 바꾸면 그쪽이
      전부 에러로 죽는다 — 인자 파서 교체는 이 사고의 범위가 아니다.
    """
    for i, arg in enumerate(sys.argv[1:], 1):
        if arg == f"--{name}" and i < len(sys.argv) - 1:
            try:
                return int(sys.argv[i + 1])
            except ValueError:
                return 0
    return 0


PROJECT_ROOT = Path(__file__).resolve().parent.parent
DATA_DIR = _resolve_data_dir()
LOG_FILE = DATA_DIR / "task_logs.jsonl"

# 기본 HTTP 포트 (server.py와 동일하게 9000 선호)
HTTP_PORT = 9000

# [사고 2026-08-16] 앱이 알려준 '진짜' 포트/부모 PID. 0 이면 구버전 호출(미주입)이라
#   아래 폴백 스캔으로 돈다. 주입되면 오판이 사라져 불필요한 재기동 자체가 없어진다.
INSTANCE_PORT = _resolve_int_arg("port")
PARENT_PID = _resolve_int_arg("parent-pid")

# 1회성 진단 모드. [불변식] 이 모드에서는 어떤 경로로도 앱을 띄우지 않는다(should_restart 참조).
CHECK_MODE = "--check" in sys.argv

# 이 워치독 프로세스가 태어난 시각 — 표식 유효성 판정 기준(shutdown_marker.was_intentional).
#   나보다 먼저 찍힌 표식은 이전 세대의 것이라 나와 무관하다.
STARTED_AT = time.time()

# 싱글톤 자물쇠. [제약] PROJECT_ROOT 기준 — DATA_DIR 기준이 아니다. 설치본은 두 경로가
#   갈리는데, 이 파일을 쓰는 쪽(__main__ 하단)과 지우는 쪽이 다른 경로를 보면 자물쇠가
#   영원히 안 풀려 다음 앱의 워치독이 조용히 즉사한다 — 한 상수로 묶어 어긋남을 막는다.
WATCHDOG_PID_FILE = PROJECT_ROOT / ".ai_monitor" / "data" / "watchdog.pid"


def _pid_alive(pid: int) -> bool:
    """PID 생존 확인. 0 이면 '모름'이라 False(=판정 근거로 쓰지 않음)."""
    if pid <= 0:
        return False
    try:
        if os.name == 'nt':
            r = proc.run(['tasklist', '/FI', f'PID eq {pid}', '/FO', 'CSV', '/NH'],
                         capture_output=True, text=True,
                         encoding='utf-8', errors='replace', timeout=5)
            return r.returncode == 0 and f'"{pid}"' in r.stdout
        os.kill(pid, 0)
        return True
    except Exception:
        return False

class HiveWatchdog:
    def __init__(self, interval=60):
        self.interval = interval
        self.is_running = False
        self._loop_count = 0          # 루프 횟수 추적 (10회마다 스킬 갭 분석)
        self._restart_fail_count = 0  # 서버 재시작 연속 실패 횟수 (3회 초과 시 쿨다운)
        self._restart_fail_time: datetime | None = None  # 3회 실패 시점 (30분 후 재시도 허용)
        self._last_memory_sync_time: datetime | None = None  # 마지막 메모리 동기화 성공 시각 (쿨다운용)
        self._last_inactive_log_time: datetime | None = None  # "장시간 활동 없음" 로그 스팸 방지 (1시간 쿨다운)
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

    def _probe(self, port: int, timeout: float) -> bool:
        try:
            with urllib.request.urlopen(
                    f"http://localhost:{port}/api/heartbeat", timeout=timeout) as resp:
                return resp.status == 200
        except Exception:
            return False

    def check_server(self):
        """중앙 제어 서버(server.py)가 살아있는지 HTTP 하트비트 체크.

        [🔴 사고 2026-08-16] 예전 폴백 목록은 9000~9005/8005/8000 이었다. 그런데 실제
          HTTP 포트는 (프로젝트×환경) 해시로 9000·9002·9004·9006·9008 중 하나로 정해진다
          (infra/instance_lock.py:_server_port_slot_base). 9006·9008 에 떨어진 인스턴스는
          **살아 있어도 매번 '응답 없음'** 이 되어 60초마다 앱이 재기동됐다. 실측:
          D:\\vibe-coding 설치본(frozen) 슬롯 = 9008 — 옛 목록에 아예 없다.
        [불변식] --port 가 주입되면 그 포트만 본다. 남의 인스턴스 포트를 긁어 '내 서버가
          살아있다'고 오판하면 진짜 죽었을 때 복구를 안 하게 되므로, 스캔은 포트를
          모를 때(구버전 호출)만 쓰는 폴백이다.
        """
        if INSTANCE_PORT:
            ok = self._probe(INSTANCE_PORT, 3)
            if not ok:
                self._add_log(f"⚠️ 중앙 제어 서버(server.py) 응답 없음 (포트 {INSTANCE_PORT})")
            self.status["server_ok"] = ok
            return ok

        # 폴백(포트 미주입) — 서버 대역 9000-9009 전체 + 레거시 8005/8000.
        for p in [HTTP_PORT] + [q for q in range(9000, 9010) if q != HTTP_PORT] + [8005, 8000]:
            if self._probe(p, 2):
                self.status["server_ok"] = True
                return True

        self._add_log("⚠️ 중앙 제어 서버(server.py) 응답 없음")
        self.status["server_ok"] = False
        return False

    def should_restart(self) -> bool:
        """앱을 되살려도 되는 상황인지 판정한다. 이 판정이 이번 사고의 핵심이다.

        [🔴 --check 는 절대 재시작 금지] --check 는 UI 의 '헬스체크/복구' 버튼
          (/api/hive/health/repair)이 부르는 **1회성 진단**이다. 진단이 앱을 띄우면
          사용자는 버튼 하나에 창이 하나 더 뜨는 걸 보게 된다. 게다가 --check 는
          --port 미주입이라 포트 스캔으로 도는데, 9006·9008 슬롯 인스턴스는 옛 목록에서
          늘 '죽음'으로 나왔으므로 **버튼을 누를 때마다 앱이 하나씩 더 떴다**.
          진단은 관측만 한다 — 복구는 상주 루프의 몫이다.

        [무엇을 가르는가] '사람이 껐다' 와 '죽어서 꺼졌다'.
          자동 복구 자체는 필요하다(진짜 크래시는 되살려야 한다). 없애야 하는 것은
          **사장이 끈 것을 되살리는 행위** 하나뿐이다.

        [가르는 근거 — 코드 도달 여부]
          사람이 창을 닫으면 webview.start() 가 리턴하고 app_boot 의 정리 블록이 실행되며
          거기서 shutdown_marker.mark() 가 표식을 남긴다. taskkill·크래시·WebView2 사망은
          그 줄에 **도달할 수 없다**. 즉 표식의 존재는 사람의 의사를 위조 불가능하게
          증명한다. 시간 간격·종료 코드 같은 추측성 신호를 쓰지 않는 이유가 이것이다.
          오판의 방향도 안전하다 — 표식을 놓치면 '한 번 더 되살아남'(회복 가능)이고,
          없는 표식이 생기는 경우는 구조적으로 없다.

        [부모 생존 검사] 앱이 살아있는데 HTTP 만 아직 안 뜬 부팅 구간을 '죽음'으로 보면
          두 번째 인스턴스가 떠서 락에 걸리고, 그 과정에서 기존 창을 포커스한다 —
          사용자 눈엔 "창이 자꾸 튀어나옴". 부모가 살아있으면 기다린다.
        """
        if CHECK_MODE:
            self._add_log("🔍 진단(--check) 모드 — 관측만 하고 재시작하지 않습니다")
            return False

        if _pid_alive(PARENT_PID):
            self._add_log(f"⏸️ 앱(PID {PARENT_PID})은 살아 있음 — 부팅 중으로 보고 재시작 보류")
            return False

        intent = shutdown_marker.was_intentional(DATA_DIR, STARTED_AT)
        if intent:
            self._add_log(
                f"🛑 사람이 끈 종료({intent.get('reason', '?')} @ {intent.get('at', '?')}) "
                f"— 되살리지 않고 워치독도 함께 내려갑니다"
            )
            self.is_running = False   # start_loop 탈출 → 자기 종료
            return False
        return True

    def restart_server(self):
        """server.py가 다운되었을 때 자동으로 재시작한다.

        [🔴 이건 '서버 재시작'이 아니라 '앱 재시작'이다 — 2026-08-16 정정]
          server.py 를 인자 없이 실행하면 __main__ → main() → app_boot.run_gui_app 로
          내려가 **PyWebView 창까지 새로 뜬다**. 아래 옛 주석의 "서버만"은 사실이 아니었고,
          그 오해 때문에 "누가 앱을 띄우는지" 를 오래 못 찾았다. 호출 전에 반드시
          should_restart() 로 사람의 종료 의사를 확인할 것.

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
            # [번쩍임 방지] proc.popen이 CREATE_NO_WINDOW를 자동 주입 — 미설정 시 서버 재시작마다
            #   가시 콘솔 창이 생성되어 무한 창 생성 버그 발생.
            proc.popen(
                [sys.executable, str(server_py)],
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                close_fds=True,
            )
            # 3초 대기 후 실제로 응답하는지 확인
            time.sleep(3)
            if self.check_server():
                self._add_log("✅ server.py 자동 재시작 성공 — 새 인스턴스에 인계하고 종료합니다")
                self._restart_fail_count = 0
                self.status["restart_count"] = self.status.get("restart_count", 0) + 1
                # [세대 누적 차단 / 실측 2026-08-16] 새로 뜬 앱은 자기 워치독·오케스트레이터를
                #   새로 낳는다. 옛 워치독이 계속 살면 세대마다 감시자가 쌓인다 — 실제로
                #   orchestrator 가 3벌(죽은 부모 3개) 동시 생존 중이었다. 임무를 넘겼으면
                #   내려간다. 이 인스턴스의 --parent-pid 도 이미 죽은 값이라 더 감시할 대상이 없다.
                self.is_running = False
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

        [데이터 소스 우선순위]
        1. PostgreSQL pg_logs 테이블 (Postgres-First 정책)
        2. task_logs.jsonl 파일 (폴백 — PG 미연결 시)

        [근본 원인 수정] 2026-03-17 Claude
        - 기존: task_logs.jsonl만 확인 → PG로 로깅 이전 후 파일이 갱신되지 않아
          영구적으로 "8h+ 활동 없음" 오탐 발생 (마지막 파일 기록: 2026-03-01)
        - 수정: pg_logs에서 최신 created_at 조회 → 실시간 활동 반영

        [스팸 억제]
        - "장시간 활동 없음" 경고를 매 60초 → 1시간 1회로 제한
        - 헬스체크 UI에 반복 경고가 20줄 모두 채워지는 문제 해소
        """
        last_time = None

        # 1차: PostgreSQL pg_logs에서 최신 활동 시각 조회
        try:
            from src.pg_store import query_rows as _qr
            rows = _qr("SELECT MAX(created_at) AS last_active FROM pg_logs LIMIT 1;")
            if rows and rows[0].get('last_active'):
                val = rows[0]['last_active']
                # psycopg2는 datetime 객체 반환, psql CSV는 문자열 반환
                if isinstance(val, datetime):
                    last_time = val.replace(tzinfo=None)  # naive datetime으로 통일
                else:
                    last_time = datetime.fromisoformat(str(val).replace('+00:00', '').replace('Z', ''))
        except Exception:
            pass  # PG 미연결 시 파일 폴백

        # 2차 폴백: task_logs.jsonl 파일
        if last_time is None and LOG_FILE.exists():
            try:
                with open(LOG_FILE, "r", encoding="utf-8") as f:
                    lines = f.readlines()
                if lines:
                    last_line = json.loads(lines[-1])
                    last_time = datetime.fromisoformat(last_line["timestamp"])
            except Exception as e:
                self._add_log(f"⚠️ 로그 파일 파싱 실패: {e}")

        if last_time is None:
            self.status["agent_active"] = False
            return False

        if datetime.now() - last_time < timedelta(hours=8):
            self.status["agent_active"] = True
            return True
        else:
            # 스팸 억제: 1시간에 1회만 경고 로그 출력
            now = datetime.now()
            if (self._last_inactive_log_time is None or
                    (now - self._last_inactive_log_time).total_seconds() > 3600):
                self._add_log("⚠️ 장시간(8h+) 에이전트 활동 없음")
                self._last_inactive_log_time = now
            self.status["agent_active"] = False
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

            healed = False

            # 계층 2a: 사용자 지시 패턴 → vibe-orchestrate.md
            if proposals:
                applied = analyzer.apply_knowledge_to_skill(proposals)
                if applied:
                    count = len(proposals)
                    self._add_log(f"✅ [계층2a] {count}개 지시 패턴 스킬에 반영")
                    healed = True

            # 계층 2b: 에러 패턴 → 해당 스킬 파일 자동 업데이트
            # (기존에 빌드 에러, 포트 충돌 등이 감지 안 되던 근본 원인 수정)
            logs = analyzer.get_logs()
            error_patterns = analyzer.extract_error_patterns(logs)
            if error_patterns:
                updated = analyzer.apply_error_fixes_to_skills(error_patterns)
                if updated > 0:
                    self._add_log(f"✅ [계층2b] {len(error_patterns)}개 에러 패턴 → {updated}개 스킬 업데이트")
                    healed = True

            if healed:
                self.status["skill_heal_count"] = self.status.get("skill_heal_count", 0) + 1
                self.status["repair_count"] += 1
                return True
            else:
                self._add_log("ℹ️ 신규 패턴 없음 — 스킬 최신 상태")
            return False

        except ImportError:
            self._add_log("⚠️ skill_analyzer.py 로드 실패 — scripts/ 경로 확인 필요")
            return False
        except Exception as e:
            self._add_log(f"❌ 스킬 갭 분석 오류: {e}")
            return False

    def check_skill_gaps_llm(self):
        """계층 3 자기치유: LLM이 실패 로그를 분석하여 스킬 개선안을 도출합니다.

        [동작 순서]
        1. task_logs.jsonl에서 최근 실패/에러 로그 20건 추출
        2. Gemini API로 근본 원인 분석 요청 (GOOGLE_API_KEY 필요)
        3. 분석 결과를 vibe-orchestrate.md의 자기치유 섹션에 반영
        4. API 키 없으면 조용히 스킵 (계층2만 동작)

        [호출 시점]
        start_loop()에서 50루프(=약 50분)마다 자동 호출.
        """
        api_key = os.environ.get('GOOGLE_API_KEY') or os.environ.get('GEMINI_API_KEY')
        if not api_key:
            return False  # API 키 없으면 스킵

        self._add_log("🧠 [계층3] LLM 기반 스킬 분석 중...")
        try:
            # 1. 실패 로그 수집
            if not LOG_FILE.exists():
                return False
            error_logs = []
            with open(LOG_FILE, "r", encoding="utf-8") as f:
                for line in f:
                    try:
                        entry = json.loads(line)
                        status = entry.get("status", "")
                        task = entry.get("task", "")
                        if status in ("error", "fail", "failed") or "오류" in task or "실패" in task:
                            error_logs.append(task[:200])
                    except Exception:
                        continue
            error_logs = error_logs[-20:]  # 최근 20건
            if len(error_logs) < 3:
                self._add_log("ℹ️ [계층3] 실패 로그 3건 미만 — 분석 불필요")
                return False

            # 2. Antigravity API 호출
            prompt = (
                "다음은 AI 에이전트 시스템의 최근 실패/에러 로그 목록입니다. "
                "반복되는 근본 원인을 3개 이내로 분석하고, 각각에 대해 "
                "에이전트가 다음에 같은 실수를 반복하지 않도록 하는 구체적인 지침을 "
                "한 줄씩 작성해주세요. 형식: '- [원인]: [지침]'\n\n"
                + "\n".join(f"- {log}" for log in error_logs)
            )
            req_body = json.dumps({
                "contents": [{"parts": [{"text": prompt}]}],
                "generationConfig": {"maxOutputTokens": 500, "temperature": 0.3}
            }).encode("utf-8")

            url = f"https://generativelanguage.googleapis.com/v1beta/models/gemini-2.0-flash:generateContent?key={api_key}"
            req = urllib.request.Request(url, data=req_body, headers={"Content-Type": "application/json"})
            with urllib.request.urlopen(req, timeout=15) as resp:
                result = json.loads(resp.read().decode("utf-8"))

            # 3. 응답 파싱
            text = result.get("candidates", [{}])[0].get("content", {}).get("parts", [{}])[0].get("text", "")
            if not text.strip():
                self._add_log("⚠️ [계층3] LLM 응답 비어있음")
                return False

            # 4. vibe-orchestrate.md에 반영
            skill_file = PROJECT_ROOT / ".claude" / "commands" / "vibe-orchestrate.md"
            if not skill_file.exists():
                return False

            MARKER = "## 🤖 계층3 LLM 분석 결과"
            now = datetime.now().strftime("%Y-%m-%d %H:%M")
            section = f"\n\n---\n\n{MARKER} (자동 업데이트: {now})\n\n"
            section += "> 워치독 계층3이 Antigravity API로 실패 로그를 분석한 결과입니다.\n\n"
            section += text.strip() + "\n"

            content = skill_file.read_text(encoding="utf-8")
            if MARKER in content:
                idx = content.find(f"\n\n---\n\n{MARKER}")
                if idx != -1:
                    content = content[:idx]
            content += section
            skill_file.write_text(content, encoding="utf-8")

            self._add_log(f"✅ [계층3] LLM 분석 완료 — vibe-orchestrate.md 업데이트됨")
            self.status["skill_heal_count"] = self.status.get("skill_heal_count", 0) + 1
            return True

        except urllib.error.URLError as e:
            self._add_log(f"⚠️ [계층3] API 호출 실패: {e}")
            return False
        except Exception as e:
            self._add_log(f"❌ [계층3] LLM 분석 오류: {e}")
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
            # [번쩍임 방지] 워치독(백그라운드)에서 proc.run이 CREATE_NO_WINDOW 자동 주입.
            proc.run(
                [sys.executable, str(memory_script), "sync"],
                capture_output=True, text=True, check=True,
                # encoding 명시: Windows CP949 환경에서 이모지 포함 출력 시
                # UnicodeDecodeError → Thread-1 crash 방지 (Bug 1 수정)
                encoding='utf-8', errors='replace',
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
            # [🔴 게이트 / 사고 2026-08-16] 재시작 앞에 '사람이 껐나' 를 반드시 먼저 묻는다.
            #   이 한 줄이 "사장이 끄면 꺼진 채로 있는다"의 전부다. 게이트를 지나가는 경우는
            #   '부모도 죽었고 사람의 종료 표식도 없다' = 진짜 사고뿐이므로 자동 복구는 보존된다.
            if self._restart_fail_count < 3 and self.should_restart():
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
        
        # 만료된 메모리 항목 자동 정리 (TTL 만료 정책)
        try:
            cleanup_expired_memory()
        except Exception:
            pass

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
        self._add_log("🚀 하이브 워치독 엔진 가동 시작 (계층 1 인프라 + 계층 2 스킬 + 계층 3 LLM 치유)")
        # 서버 초기화 대기: Flask가 포트를 열기 전에 첫 체크를 실행하면
        # "서버 다운" 오탐이 발생하여 불필요한 재시작 시도로 중복 서버 인스턴스가 생성됨.
        # 15초 대기 후 첫 체크 실행 — server.py 기동 완료에 충분한 시간.
        time.sleep(15)
        while self.is_running:
            try:
                self.run_check()
                self._loop_count += 1

                # 10루프(약 10분)마다 계층2 스킬 갭 분석 실행
                if self._loop_count % 10 == 0:
                    self.check_skill_gaps()

                # 50루프(약 50분)마다 계층3 LLM 기반 분석 실행
                if self._loop_count % 50 == 0:
                    self.check_skill_gaps_llm()

            except Exception as e:
                self._add_log(f"❌ 루프 실행 에러: {e}")
            # [즉시 탈출] run_check 안에서 is_running 이 내려갔으면(사람이 끔 / 인계 완료)
            #   60초를 더 자지 않는다 — 그 사이 다음 판정이 끼어들 여지를 없앤다.
            if not self.is_running:
                break
            time.sleep(self.interval)
        self._add_log("👋 워치독 종료")
        try:
            WATCHDOG_PID_FILE.unlink()   # 싱글톤 자물쇠 반납 — 다음 앱의 워치독이 뜰 수 있게
        except OSError:
            pass

if __name__ == "__main__":
    # ── 싱글톤 보호: 이미 실행 중인 워치독 인스턴스가 있으면 즉시 종료 ──────────────────
    # server.py가 재시작할 때마다 새 인스턴스를 spawn하여 누적되는 문제 방지.
    # --check 모드(1회 점검)는 싱글톤 체크 없이 항상 실행 허용.
    _is_check_mode = len(sys.argv) > 1 and sys.argv[1] == "--check"
    if not _is_check_mode:
        _pid_file = WATCHDOG_PID_FILE   # [불변식] 종료 시 지우는 경로와 동일해야 함
        _my_pid   = os.getpid()
        try:
            if _pid_file.exists():
                _old_pid = int(_pid_file.read_text().strip())
                if _old_pid != _my_pid and _pid_alive(_old_pid):
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
