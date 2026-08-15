# ─────────────────────────────────────────────────────────────────────────────
# 📄 파일명: infra/daemons.py
# 📝 설명: 백그라운드 데몬 러너 — 워치독/리사이클 워처/오케스트레이터/문서 생성/
#          에이전트 동기화/MUX/제텔 동기화·정제/커밋 감시 (server.py 분할 단계 9)
# 🕒 변경 이력:
# [2026-08-14] Claude — 데몬 .py 실행기를 runtime.script_runner_cmd로 통일(설치본에서
#   Python 미설치 PC면 LAN 브리지/워치독이 조용히 안 뜨던 결함) + _spawn_script 실패 로그.
# [2026-08-14] Claude — Discord 대시보드/게이트웨이 러너 2종 삭제(커넥터 전면 철거).
# [2026-08-04] Claude — popen 계열 데몬이 상태판에서 항상 '꺼짐'으로 보이던 오탐 수정
#   (스레드명 단독 판정 → 자식 프로세스 레지스트리 병행).
# [2026-06-10] Claude — server.py main() 내부 중첩 함수 11개 이관 (~500줄)
#   - [제약] 모든 함수는 daemon=True 스레드에서 호출됨 — 블로킹 루프 허용.
#   - [WHY] env(DaemonEnv)는 호출 시점에 server.py 래퍼가 생성 — HTTP_PORT 등이
#     main() 후반에 재바인딩되므로 모듈 import 시점 값 고정을 피한다.
#   - [불변식] subprocess로 띄운 자식은 반드시 env.child_procs에 append —
#     lifecycle.cleanup_child_procs가 이 리스트만 종료 대상으로 삼는다.
# [2026-07-22] Claude — 맥 포팅: config vault_dir 검증을 _config_vault_dir로 통합.
#   Windows 절대경로가 POSIX에서 상대로 풀려 리포 내 정크 vault + FS 이벤트 폭주를
#   유발 → is_absolute() 검증으로 전역 vault 폴백(중복 2곳 흡수).
# ─────────────────────────────────────────────────────────────────────────────
import json
import os
import subprocess
import sys
import threading
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Callable

from infra import proc  # [표준] 콘솔 숨김 subprocess 래퍼 — 인라인 CREATE_NO_WINDOW 금지
from infra import runtime
from infra.project_context import slugify


def _config_vault_dir(config_file: Path, default_vault: Path) -> Path:
    """config.json의 vault_dir이 이 OS에서 유효(절대경로)하면 그 경로, 아니면 default_vault.

    [WHY / 과거사고 2026-07 맥포팅] Windows 세션이 저장한 vault_dir 'D:/vibe-coding/.zettel-vault'는
      POSIX에서 상대경로로 풀려 리포 안에 './D:/vibe-coding/.zettel-vault' 정크 트리를 만들고,
      그게 FS 워처와 맞물려 이벤트 폭주를 일으킨다. vault는 mkdir로 생성되므로 존재 검증(is_dir)이
      아니라 **is_absolute()만** 본다 — 타 OS 절대경로는 POSIX에서 상대로 취급돼 자동 거부되고
      전역 기본 vault로 폴백된다. Windows에서는 'D:/..'가 절대경로라 기존 동작 유지.
    """
    try:
        if config_file.exists():
            cfg = json.loads(config_file.read_text(encoding='utf-8'))
            uv = cfg.get('vault_dir', '')
            if uv and Path(uv).is_absolute():
                return Path(uv)
    except Exception:
        pass
    return default_vault


@dataclass
class DaemonEnv:
    """server.py 전역을 데몬 함수에 전달하는 컨텍스트 — 래퍼가 호출 시점에 생성."""
    base_dir: Path
    project_root: Path
    scripts_dir: Path | None
    data_dir: Path
    global_vault_dir: Path
    config_file: Path
    http_port: int
    child_procs: list
    current_project_root: Callable[[], Path]
    current_project_id: Callable[[], str]


# ── 자식 프로세스 레지스트리 (상태판 running 판정용) ─────────────────────────
# [과거사고 2026-08-04] daemon_status가 running을 threading.enumerate()의 스레드명으로만
#   판정했다. 그런데 popen 계열 데몬(watchdog/lan_bridge/orchestrator)은 자식을
#   띄우고 즉시 return하므로 스레드가 사라진다 → 실측에서 4종이 프로세스는 살아있는데
#   상태판은 전부 "꺼짐"이었다. 안 뜬 줄 알고 엉뚱한 곳을 팠다.
# [불변식] 자식은 여전히 env.child_procs 에도 반드시 들어가야 한다 —
#   lifecycle.cleanup_child_procs 가 그 리스트만 종료 대상으로 삼는다. 레지스트리는
#   '표시용 별도 인덱스'이지 종료 책임을 가져가지 않는다.
# [WHY 제거하지 않음] 죽은 자식은 poll()이 None이 아니게 되므로 항목을 지우지 않아도
#   판정이 정확하다. 재기동 시 같은 키를 덮어쓰면 최신 자식만 남는다.
_DAEMON_CHILDREN: dict = {}
_DAEMON_CHILDREN_LOCK = threading.Lock()


def _track_child(key: str, env: DaemonEnv, child) -> None:
    """자식을 종료 대상(child_procs)과 상태판 레지스트리 양쪽에 등록한다."""
    env.child_procs.append(child)
    with _DAEMON_CHILDREN_LOCK:
        _DAEMON_CHILDREN[key] = child


def _spawn_script(key: str, env: 'DaemonEnv', argv: list):
    """데몬 스크립트 자식을 띄우고 레지스트리에 등록. 실패하면 None + 이유 로그.

    [WHY try] 데몬은 이름 없는 daemon 스레드에서 돌고 호출부에 try가 없다.
      실행기 경로가 틀리면 Popen이 FileNotFoundError로 스레드째 사라지는데,
      frozen(GUI) 모드는 stderr가 어디에도 안 붙어 **아무 흔적도 안 남는다** —
      사용자에겐 "토글을 켰는데 아무 일도 안 일어남"으로만 보인다(2026-08-14 LAN 브리지).
    [불변식] stdout/stderr=PIPE 유지 — 읽는 쪽이 없어도 기존 동작이며, 파이프를
      없애면 자식 출력이 부모 콘솔로 새어 규칙 10(창 노출)과 충돌할 수 있다.
    """
    try:
        child = proc.popen(
            argv, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
            text=True, encoding='utf-8', errors='replace',
        )
    except OSError as e:
        print(f"[!] 데몬 '{key}' 기동 실패 — 실행기={argv[0]!r} ({e})")
        return None
    _track_child(key, env, child)
    return child


def _daemon_child_alive(key: str) -> bool:
    with _DAEMON_CHILDREN_LOCK:
        child = _DAEMON_CHILDREN.get(key)
    if child is None:
        return False
    try:
        return child.poll() is None
    except Exception:
        return False


def run_watchdog(env: DaemonEnv) -> None:
    if not env.scripts_dir:
        return
    watchdog_script = env.scripts_dir / "hive_watchdog.py"
    if watchdog_script.exists():
        # [실행기] script_runner_cmd — frozen이면 앱 EXE 자신. 시스템 Python은 번들
        #   의존성(psycopg 등)이 없어 설치본 PC에서 import 실패로 즉사한다.
        python_exe = runtime.script_runner_cmd(env.base_dir, env.project_root)
        # [지역변수 rename] proc→child: 모듈 proc(콘솔숨김 헬퍼)와 이름 충돌 회피
        child = _spawn_script(
            'watchdog', env,
            [python_exe, str(watchdog_script), "--data-dir", str(env.data_dir)],
        )
        if child is None:
            return


def run_lan_bridge(env: DaemonEnv) -> None:
    """LAN 브리지(lan_bridge.py) 별도 프로세스 기동 — config lan_bridge_enabled=True일 때만.

    [WHY 기본 꺼짐] 브리지는 0.0.0.0을 노출하므로 사용자가 명시적으로 켤 때만 뜬다.
    [과거사고 2026-08-14] 설치본에서 "브리지 켜기 → 재시작"을 해도 안 뜨던 결함.
      옛 코드가 python_runner_cmds()[0]을 실행기로 썼는데, 그 함수는 frozen에서
      앱 EXE를 후보에서 **제외**하므로 Python 미설치 PC는 폴백 'python'이 나가
      Popen이 죽었다. 그런데 Python이 깔린 PC(개발 PC)에서는 우연히 떠서
      "개발에선 되는데 설치본에선 안 됨"으로 보였다 → script_runner_cmd로 교체.
    [불변식] Popen 자식은 child_procs.append — cleanup_child_procs가 이 리스트만 종료.
    """
    try:
        cfg = json.loads(env.config_file.read_text(encoding='utf-8')) if env.config_file.exists() else {}
    except (json.JSONDecodeError, OSError):
        cfg = {}
    if not cfg.get('lan_bridge_enabled', False):
        return
    bridge_script = env.base_dir / 'lan_bridge.py'
    if not bridge_script.exists():
        print(f"[!] run_lan_bridge: 브리지 스크립트 없음 — {bridge_script}")
        return
    runner = runtime.script_runner_cmd(env.base_dir, env.project_root)
    _spawn_script(
        'lan_bridge', env,
        [runner, str(bridge_script), "--data-dir", str(env.data_dir)],
    )


# Codex를 '사용 중'으로 볼 시간 창 — 이 시간 안에 히스토리가 갱신됐으면 워처를 띄운다.
# [WHY 10분] Codex 한 턴의 생각/응답 간격보다 충분히 길어야 대화 중간에 워처가 죽지 않는다.
_CODEX_ACTIVE_WINDOW_SEC = 10 * 60
_CODEX_SUPERVISOR_INTERVAL_SEC = 60


def _codex_last_activity(codex_home: Path) -> float:
    """Codex 홈에서 가장 최근 변경 시각(epoch). 없으면 0.

    [WHY 프로세스 목록이 아니라 파일 mtime] 프로세스 스캔은 60초마다 전체 프로세스를 훑어야 해
      감시 비용이 감시 대상만큼 커진다. 히스토리 파일 stat 2번이면 충분하고, Codex가 실제로
      기록을 남길 때만 워처가 할 일이 생기므로 신호로도 정확하다.
    """
    latest = 0.0
    for p in (codex_home / 'history.jsonl', codex_home / 'sessions'):
        try:
            latest = max(latest, p.stat().st_mtime)
        except OSError:
            pass
    return latest


def run_codex_pg_watcher(env: DaemonEnv) -> None:
    """[온디맨드] Codex를 쓸 때만 워처를 띄우고, 안 쓰면 내려서 CPU/메모리를 회수한다.

    [WHY 2026-08-01] 기존에는 부팅 시 무조건 띄워 5초 주기로 히스토리를 폴링했다. Codex를
      쓰지 않는 PC에서도 하루 17,280회를 돌아 CPU 15,140초(4.2시간)를 소비했다 — 실측 기준
      server.py 다음으로 큰 CPU 소비자였다. 저사양 PC에서는 이 고정 비용이 그대로 압박이 된다.
    [무손실 근거] 워처는 codex_pg_watcher_state.json 의 `seen` 집합(최근 5000키)을 재로딩하므로
      죽였다 살려도 이미 기록한 항목을 건너뛴다. 중단 중 쌓인 항목은 재기동 후 따라잡는다.
      이 상태 파일이 사라지면 무손실 보장이 깨지므로 워처의 state 저장을 제거하지 말 것.
    [불변식] 자식은 반드시 env.child_procs 에 append — cleanup_child_procs가 이 리스트만 종료한다.
      내려보낼 때는 리스트에서도 제거해야 종료 시 죽은 핸들을 kill하려다 예외가 나지 않는다.
    """
    if not env.scripts_dir:
        return
    watcher_script = env.scripts_dir / "codex_pg_watcher.py"
    if not watcher_script.exists():
        return
    # [실행기] frozen이면 앱 EXE 자신 — 이 워처는 psycopg(번들 전용)를 import한다.
    python_exe = runtime.script_runner_cmd(env.base_dir, env.project_root)
    codex_home = Path(os.environ.get('CODEX_HOME') or Path.home() / '.codex')
    child = None

    while True:
        try:
            active = (time.time() - _codex_last_activity(codex_home)) < _CODEX_ACTIVE_WINDOW_SEC
            if child is not None and child.poll() is not None:
                child = None                      # 스스로 죽은 경우 정리 후 재기동 대상으로
            if active and child is None:
                child = proc.popen(
                    [python_exe, str(watcher_script), "--interval", "5"],
                    cwd=str(env.project_root),
                    stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                    encoding='utf-8', errors='replace',
                )
                _track_child('codex_watcher', env, child)
                print("[*] Codex 활동 감지 — pg_logs 워처 시작")
            elif not active and child is not None:
                try:
                    child.terminate()
                except OSError:
                    pass
                if child in env.child_procs:
                    env.child_procs.remove(child)
                child = None
                print("[*] Codex 유휴 — pg_logs 워처 종료 (활동 시 자동 재시작)")
        except Exception as e:
            print(f"[!] codex 워처 감독 오류(무시하고 계속): {e}")
        time.sleep(_CODEX_SUPERVISOR_INTERVAL_SEC)

def run_orchestrator_daemon(env: DaemonEnv) -> None:
    # 하이브 오케스트레이터 데몬 — assigned_to='all' 태스크를
    # 살아있는 에이전트로 자동 재배정. wiki_generator 등 'all' 발행자가
    # 만든 태스크가 영원히 적체되는 것을 방지한다.
    if not env.scripts_dir:
        return
    orch_script = env.scripts_dir / "orchestrator.py"
    if orch_script.exists():
        pid_file = env.data_dir / "orchestrator.pid"
        def _pid_is_alive(pid: int) -> bool:
            try:
                result = proc.run(['tasklist', '/FI', f'PID eq {pid}', '/FO', 'CSV', '/NH'], capture_output=True, text=True, encoding='utf-8', errors='replace', timeout=5)
                return result.returncode == 0 and f'"{pid}"' in result.stdout
            except Exception:
                return False
        try:
            existing_pid = int(pid_file.read_text(encoding='utf-8').strip())
        except Exception:
            existing_pid = 0
        if existing_pid and _pid_is_alive(existing_pid):
            print(f"[*] Orchestrator daemon already running (PID={existing_pid})")
            return

        _python_cmds = runtime.python_runner_cmds(env.base_dir, env.project_root)
        if not _python_cmds:
            print("[!] run_orchestrator_daemon: Python 인터프리터를 찾을 수 없어 오케스트레이터 스킵")
            return
        python_exe = _python_cmds[0]
        # [지역변수 rename] proc→child: 모듈 proc(콘솔숨김 헬퍼)와 이름 충돌 회피.
        # [필수] 중첩 _pid_is_alive가 proc.run(모듈)을 참조 — outer proc 지역화 시
        #   free variable 조기참조 NameError. child로 rename해 모듈 proc 노출 유지.
        child = proc.popen(
            [python_exe, str(orch_script), "--daemon", "--interval", "60"],
            cwd=str(env.project_root),
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            encoding='utf-8',
            errors='replace',
        )
        _track_child('orchestrator', env, child)
        print("[*] 하이브 오케스트레이터 데몬(orchestrator) 자동 시작됨")

        try:
            pid_file.write_text(str(child.pid), encoding='utf-8')
        except Exception:
            pass

def run_doc_generators_daemon(env: DaemonEnv) -> None:
    # PROJECT_MAP.md / HIVEMIND.md 자동 갱신 데몬.
    # 시동 시 즉시 1회 + 이후 30분마다 갱신.
    # 원인: 두 자동 생성기가 시동 시퀀스에서 빠져있어 17일/15일째 stale.
    if not env.scripts_dir:
        return
    pm_script = env.scripts_dir / "generate_project_map.py"
    hv_script = env.scripts_dir / "generate_hivemind_doc.py"
    _python_cmds = runtime.python_runner_cmds(env.base_dir, env.project_root)
    if not _python_cmds:
        print("[!] run_doc_generators_daemon: Python 인터프리터를 찾을 수 없어 스킵")
        return
    python_exe = _python_cmds[0]
    interval_sec = 30 * 60  # 30분 주기

    while True:
        # PROJECT_MAP.md 갱신
        if pm_script.exists():
            try:
                proc.run(
                    [python_exe, str(pm_script)],
                    cwd=str(env.project_root),
                    timeout=120,
                    capture_output=True,
                )
                print("[*] PROJECT_MAP.md 자동 갱신 완료")
            except Exception as e:
                print(f"[!] PROJECT_MAP.md 갱신 실패: {e}")

        # HIVEMIND.md 갱신
        if hv_script.exists():
            try:
                proc.run(
                    [python_exe, str(hv_script)],
                    cwd=str(env.project_root),
                    timeout=120,
                    capture_output=True,
                )
                print("[*] HIVEMIND.md 자동 갱신 완료")
            except Exception as e:
                print(f"[!] HIVEMIND.md 갱신 실패: {e}")

        time.sleep(interval_sec)

def agent_sync_daemon(agent_status: dict, agent_status_lock: threading.Lock) -> None:
    # [WHY] 함수 내부 import — infra 패키지가 src 패키지를 모듈 레벨에서 물면
    # 단독 import(테스트/도구) 시 sys.path 준비 전에 ImportError가 나기 쉬움
    from src.pg_store import list_agent_status, record_heartbeat
    while True:
        try:
            time.sleep(60)
            now_ts = time.time()
            with agent_status_lock:
                snapshot = dict(agent_status)
            for agent_name, info in snapshot.items():
                status = info.get('status', 'idle')
                if status in ('active', 'running', 'working'):
                    try:
                        record_heartbeat(agent_name, status=status,
                                         current_task=info.get('task'))
                    except Exception:
                        pass
            try:
                db_rows = list_agent_status()
                with agent_status_lock:
                    for row in db_rows:
                        aid = row.get('agent_id', '')
                        if not aid:
                            continue
                        if aid not in agent_status:
                            try:
                                from datetime import datetime as _dt
                                lb = _dt.fromisoformat(row.get('last_beat', '')).timestamp()
                            except Exception:
                                lb = now_ts - 600
                            age = now_ts - lb
                            agent_status[aid] = {
                                'status': 'offline' if age > 300 else row.get('status', 'idle'),
                                'task': row.get('current_task'),
                                'last_seen': lb,
                                'beat_count': row.get('beat_count', 0),
                            }
                    for aid, info in agent_status.items():
                        last = info.get('last_seen', 0)
                        if now_ts - last > 300 and info.get('status') not in ('offline',):
                            agent_status[aid]['status'] = 'offline'
            except Exception:
                pass
        except Exception:
            pass

# ── 위키 동기화 데몬 (코드 주석 → wiki/ → 검색 인덱스 → 구글 드라이브) ──────
def run_wiki_sync(env: DaemonEnv) -> None:
    """LLM 위키 파이프라인을 주기적으로 돌린다.

    코드 주석을 고치면 백과사전이 따라오고, 백과사전이 바뀌면 회상이 따라온다.
    이 데몬이 없으면 사람이 매번 `python scripts/wiki_build.py` 를 쳐야 하고,
    그러면 안 치게 되고, 창고는 다시 낡는다 — 자동화의 유일한 이유가 그것이다.

    [WHY 10분인가] 코드 주석은 커밋 단위로 바뀌지 초 단위로 바뀌지 않는다. 반면
      wiki_build 는 소스 155개를 전부 읽는다. 짧게 잡으면 이득 없이 디스크만 긁는다.
    [🔴 규칙 10] 전부 같은 프로세스 안의 함수 호출이다 — 서브프로세스를 띄우지 않으므로
      콘솔 창이 생기지 않는다. 여기서 subprocess 로 바꾸면 10분마다 창이 뜬다.
    [불변식] 순서 고정: build → index → mirror. 인덱스를 먼저 만들면 방금 바뀐 페이지가
      아니라 직전 내용이 색인되고, 미러를 먼저 하면 낡은 페이지가 다른 PC 로 퍼진다.
    """
    import time as _time
    try:
        from src import wiki_index
    except Exception as exc:
        print(f'[wiki_sync] 모듈 로드 실패 — 데몬 중단: {exc}')
        return

    wiki_root = env.current_project_root() / 'wiki'
    build_script = (env.scripts_dir or (env.base_dir / 'scripts')) / 'wiki_build.py'
    print(f'[*] 위키 동기화 데몬 시작됨 — wiki={wiki_root}, 600초 주기')

    while True:
        try:
            root = env.current_project_root() / 'wiki'   # 라이브 프로젝트 전환 추종
            proj_id = env.current_project_id()
            if root.is_dir():
                # 1) 코드 주석 → 페이지. 모듈로 직접 부른다(무창).
                if build_script.exists():
                    try:
                        import importlib.util as _ilu
                        _spec = _ilu.spec_from_file_location('wiki_build', str(build_script))
                        _mod = _ilu.module_from_spec(_spec)
                        _spec.loader.exec_module(_mod)
                        _mod.build()
                    except Exception as be:
                        print(f'[wiki_sync] 페이지 합성 건너뜀: {be}')
                # 2) 페이지 → 검색 인덱스
                stat = wiki_index.sync(root, proj_id)
                if stat.get('created') or stat.get('updated') or stat.get('archived'):
                    print(f"[wiki_sync] 인덱스 갱신 — 신규 {stat['created']} / "
                          f"변경 {stat['updated']} / 정리 {stat['archived']}")
                # 3) 구글 드라이브 허브 미러 (드라이브가 없으면 조용히 건너뜀)
                res = wiki_index.mirror_to_hub(root, env.current_project_root().name)
                if res.get('status') == 'ok' and res.get('written'):
                    print(f"[wiki_sync] 드라이브 미러 {res['written']}건 → {res['hub']}")
        except Exception as exc:
            print(f'[wiki_sync] 오류(계속 진행): {exc}')
        _time.sleep(600)


# ── 제텔카스텐 Vault 동기화 데몬 (DB ↔ Obsidian 60초 주기) ────────────
def run_zettel_sync(env: DaemonEnv) -> None:
    """PostgreSQL zettel_notes ↔ Obsidian vault 양방향 동기화 데몬.
    [v3.7.179] 서버 시작 시 자동 실행 — 이전에는 수동 실행만 가능했음."""
    try:
        _sync_dir = env.scripts_dir or (env.base_dir / 'scripts')
        _sync_script = _sync_dir / 'zettel_sync.py'
        if not _sync_script.exists():
            return
        # zettel_sync 모듈 직접 import하여 스레드 내에서 실행 (subprocess 대신)
        import importlib.util as _ilu
        _spec = _ilu.spec_from_file_location('zettel_sync', str(_sync_script))
        _mod = _ilu.module_from_spec(_spec)
        _spec.loader.exec_module(_mod)

        # config.json에서 사용자 지정 vault 경로 읽기 (없거나 타 OS 절대경로면 전역 기본값)
        _vault = _config_vault_dir(env.config_file, env.global_vault_dir)
        _vault.mkdir(parents=True, exist_ok=True)

        # 기존 .zettel-vault 마이그레이션 (최초 1회)
        # [과거사고] 2026-07-19: config vault_dir이 레거시 .zettel-vault와 동일 경로로
        #   설정된 환경에서 copytree(old, vault)가 디렉토리를 자기 자신에 복사 →
        #   Obsidian이 파일을 잡고 있어 WinError 32 → line 360 마커가 안 찍혀
        #   매 데몬 시작마다 재시도(server.log 67회 폭주). 두 경로가 같으면(=이미 활성
        #   vault면) 마이그레이션할 게 없으므로 건너뛴다.
        import shutil as _shutil
        _old_vault = env.current_project_root() / '.zettel-vault'
        try:
            _same_path = _old_vault.resolve() == _vault.resolve()
        except Exception:
            _same_path = str(_old_vault) == str(_vault)
        if _old_vault.exists() and not _same_path and not (_vault / '_migrated').exists():
            try:
                _shutil.copytree(str(_old_vault), str(_vault), dirs_exist_ok=True)
                (_vault / '_migrated').touch()
                print(f'[zettel_sync] 기존 vault 마이그레이션 완료: {_old_vault} -> {_vault}')
            except Exception as _me:
                print(f'[zettel_sync] 마이그레이션 오류 (무시): {_me}')

        # 현재 활성 project_id. Phase 2 이후 zettel_notes.project_id는 폴더명이 아니라
        # 경로 slug(D--vibe-coding)를 표준으로 사용한다. 폴더명을 쓰면 Obsidian export가
        # 구형 project_id(vibe-coding) 49건만 내보내고 최신 지식 대부분을 누락한다.
        _proj_id = env.current_project_id()

        # [자가 복구] 이스케이프 폭주의 잔해를 부팅 시 1회 걷어낸다.
        #   [WHY] 새 버전의 크기 가드는 '더 나빠지지 않게' 할 뿐, 구버전에서 이미 부푼
        #     볼트(실측 3.2GB)를 되돌리지 못한다. 사용자가 복구 스크립트를 손으로 돌릴 것을
        #     기대할 수 없고, 방치하면 동기화가 매 사이클 그 데이터를 읽어 CPU를 태운다.
        #   [비용] 정상 환경에서는 SQL 1회 + stat() 몇 번 — 오염이 없으면 즉시 끝난다.
        #   [제약] 여기서 예외가 새면 동기화 데몬 전체가 죽는다. 복구는 부가 기능이므로
        #     실패해도 동기화는 계속되어야 한다 → 반드시 감싼다.
        try:
            _fix_spec = _ilu.spec_from_file_location(
                'fix_corrupted_titles', str(_sync_script.parent / 'fix_corrupted_titles.py'))
            _fix_mod = _ilu.module_from_spec(_fix_spec)
            _fix_spec.loader.exec_module(_fix_mod)
            _rep = _fix_mod.auto_repair()
            if _rep['db_fixed'] or _rep['files_deleted'] or _rep['files_fixed']:
                print(f'[zettel_sync] 🔧 폭주 잔해 자동 정리 — DB {_rep["db_fixed"]}건, '
                      f'파일 수정 {_rep["files_fixed"]}건, 삭제 {_rep["files_deleted"]}건 '
                      f'({_rep["freed_mb"]}MB 회수)')
        except Exception as _re:
            print(f'[zettel_sync] 자동 정리 건너뜀 (무시): {_re}')

        print(f'[*] 제텔카스텐 Vault 동기화 데몬 시작됨 — vault={_vault}, project_id={_proj_id}, 60초 단방향')

        # [라이브 전환 추종] 매 사이클 현재 vault/project_id를 재해석 — 무재시작 프로젝트 전환 시
        #   서버 DB 커넥션이 새 프로젝트로 바뀌므로 이 루프의 스코프도 함께 따라가야 한다
        #   (옛 스코프로 새 DB를 정리하면 노트 오삭제 위험). env.current_project_id는 라이브 콜러블.
        def _resolve_current():
            _v = _config_vault_dir(env.config_file, env.global_vault_dir)
            return _v, env.current_project_id()

        # Google Drive vault — 자동 탐지 + config.json 오버라이드
        # PC마다 드라이브 레터(I:/G:/H:…)와 언어(내 드라이브/My Drive)가 달라
        # 고정 경로를 쓰면 다른 PC에서 동작하지 않는다.
        _VAULT_MARKER = Path('obsidian') / 'hive-zettel'
        _DRIVE_ROOTS = ('내 드라이브', 'My Drive')

        def _detect_gdrive_vault():
            """드라이브 레터 A~Z를 스캔해 GDrive vault를 자동 탐지한다."""
            import string as _string
            for _letter in _string.ascii_uppercase:
                _root = Path(f'{_letter}:/')
                if not _root.exists():
                    continue
                for _label in _DRIVE_ROOTS:
                    _candidate = _root / _label / _VAULT_MARKER
                    if _candidate.exists():
                        return _candidate
            return None

        def _bidirectional_enabled() -> bool:
            """볼트 → DB 되읽기를 켤지. 기본 **꺼짐**(단방향 PG→Vault).

            [WHY 기본을 껐나] 되읽기 경로에서만 사고가 3건 났다 —
              핑퐁(c7a42f2, CPU 47%) / 이스케이프 누적(f500109, 제목 115MB) /
              그 잔해로 인한 폭주(c93061f, CPU 93%). 그런데 실측하면 얻은 게 없다:
              author='obsidian' 노트가 **0건**이고(사람이 볼트에서 만든 노트가 없다),
              회상 경로는 전부 PG(pg_vector_search)라 볼트 .md를 읽어 쓰는 코드가 없다.
              얻는 것 0, 사고 3건 — 그래서 기본값을 뒤집었다.
            [불변식] 단방향이면 볼트는 순수 파생물이 된다. 깨지면 지우고 재생성하면 되고,
              폭주가 DB로 돌아올 경로 자체가 사라진다.
            [되켜기] 크로스-PC 지식 흡수가 필요하면 config.json에
              "zettel_bidirectional": true. 다만 중앙 PG(아픽스 서버)로 가면 이 경로는
              통째로 불필요해진다 — 파일 병합 대신 INSERT 하나가 곧 공유다.
            """
            try:
                if env.config_file.exists():
                    _cfg = json.loads(env.config_file.read_text(encoding='utf-8'))
                    return bool(_cfg.get('zettel_bidirectional', False))
            except Exception:
                pass
            return False

        def _get_gdrive_vault():
            # 1순위: config.json 명시 설정 (사용자 오버라이드)
            try:
                if env.config_file.exists():
                    _cfg = json.loads(env.config_file.read_text(encoding='utf-8'))
                    _gd = _cfg.get('gdrive_vault_path', '')
                    if _gd:
                        return Path(_gd)
            except Exception:
                pass
            # 2순위: 자동 탐지
            return _detect_gdrive_vault()

        def _sync_with_gdrive():
            _last_vault = None
            while True:
                try:
                    _gdrive_vault = _get_gdrive_vault()
                    if _gdrive_vault and _gdrive_vault.exists():
                        if _last_vault != _gdrive_vault:
                            print(f'[zettel_sync] Google Drive vault 감지됨: {_gdrive_vault}')
                            _last_vault = _gdrive_vault
                        # [크로스-PC 양방향] GDrive 허브 ↔ 이 프로젝트 PG. 순서: 흡수 → 반영 → push.
                        #   1) GDrive(다른 PC가 올린 '이 프로젝트' 노트) → PG 흡수. project_id 스코프라
                        #      다른 프로젝트 노트는 흡수 안 함(격리 유지) — GDrive엔 통합 열람으로만 남음.
                        #   2) PG → 로컬 vault. include_archived=True로 아카이브 상태까지 반영(부활 방지).
                        #   3) 로컬 vault → GDrive push. _is_gdrive_worthy로 커밋덤프/세션요약 노이즈 제외.
                        #   [핑퐁 안전] import_from_vault의 mtime + _same_note_payload 가드가 동일내용
                        #      재쓰기/재흡수를 막아 수렴. 로컬 60초 루프와 include_archived=True로 일치시켜
                        #      _보관 파일을 두고 두 루프가 다투지 않게 한다(watch_and_sync 호출부 참조).
                        if _bidirectional_enabled():
                            _mod.import_from_vault(_gdrive_vault, project_id=_proj_id)
                        _mod.export_to_vault(_vault, project_id=_proj_id,
                                             include_archived=True)
                        _mod.mirror_vault(
                            _vault, _gdrive_vault,
                            note_filter=lambda p: _mod._is_gdrive_worthy(p, _vault),
                        )
                    else:
                        if _last_vault is not None:
                            print('[zettel_sync] Google Drive vault 사라짐 — 동기화 일시 중단')
                            _last_vault = None
                except Exception as _ge:
                    print(f'[zettel_sync] Google Drive 동기화 오류: {_ge}')
                time.sleep(120)
        threading.Thread(target=_sync_with_gdrive, daemon=True,
                         name='ZettelGDrive').start()
        # include_archived=True — GDrive 루프와 아카이브 표현을 일치시켜 _보관 파일 핑퐁 제거.
        _mod.watch_and_sync(_vault, project_id=_proj_id, interval=60,
                            bidirectional=_bidirectional_enabled(),
                            include_archived=True,
                            resolve=_resolve_current)
    except Exception as e:
        print(f"[!] 제텔카스텐 동기화 데몬 오류: {e}")

# ── fleeting 노트 자동 정제 데몬 (10분 주기) ──────────────────────────
def run_zettel_refine(env: DaemonEnv) -> None:
    """24시간 이상 된 fleeting 노트를 자동으로 permanent로 승격.
    [v3.7.179] 수동 refine_note() 없이도 지식이 자동 정제됨."""
    try:
        time.sleep(120)  # 서버 안정화 대기 (2분)
        sys.path.insert(0, str(env.base_dir))
        from src.zettelkasten import list_notes, refine_note, auto_link
        from src.pg_store import ensure_schema
        while True:
            try:
                ensure_schema()
                notes = list_notes(note_type='fleeting', limit=100)
                from datetime import datetime, timezone, timedelta
                now = datetime.now(timezone.utc)
                cutoff = now - timedelta(hours=24)
                promoted = 0
                for n in notes:
                    # [2026-06-21] 휘발성 자동노트(세션 요약/머지 커밋 등)는 영구 승격 금지.
                    # [근본사고] refine이 fleeting 전부를 24h 후 permanent로 끌어올려, 세션요약 수백 개가
                    #   영구지식(옵시디언 그래프)을 점령하던 문제. LLM 작업기억은 PG에만 남기고(fleeting 유지),
                    #   사람용 옵시디언 영구지식엔 진짜 지식만 올라가도록 분리한다. [[project_installed_empty_panels]]
                    _title = str(n.get('title', '') or '')
                    if n.get('source_ref') == 'session-summary' \
                            or _title.startswith('세션 요약') \
                            or _title.startswith('Merge '):
                        continue
                    # created가 문자열이면 파싱
                    created = n.get('created_at') or n.get('created', '')
                    if isinstance(created, str):
                        try:
                            created = datetime.fromisoformat(created.replace('Z', '+00:00'))
                        except Exception:
                            continue
                    if hasattr(created, 'tzinfo') and created.tzinfo is None:
                        created = created.replace(tzinfo=timezone.utc)
                    if created < cutoff:
                        nid = n.get('id') or n.get('zettel_id', '')
                        if nid:
                            refine_note(nid, new_type='permanent')
                            auto_link(nid, content=n.get('content', ''),
                                     tags=n.get('tags', []), created_by='system')
                            promoted += 1
                if promoted:
                    print(f"[zettel_refine] {promoted}개 fleeting 노트 → permanent 승격 완료")
            except Exception as e:
                print(f"[!] 제텔 자동 정제 오류: {e}")
            time.sleep(600)  # 10분 주기
    except Exception as e:
        print(f"[!] 제텔 자동 정제 데몬 시작 실패: {e}")

# ── git 커밋 감지 → 제텔카스텐 자동 캡처 데몬 (60초 폴링) ──────────────
def run_commit_watcher(env: DaemonEnv) -> None:
    """새 git 커밋을 폴링하여 zettel_capture.capture_commit() 자동 호출.
    [v3.7.179] git hook 없이도 커밋 노트가 자동 생성됨."""
    try:
        time.sleep(60)  # 서버 안정화 대기
        # 마지막으로 처리한 커밋 해시
        _last_hash = None
        try:
            r = proc.run(
                ['git', 'rev-parse', 'HEAD'],
                cwd=str(env.project_root), capture_output=True, text=True,
                timeout=5,
            )
            if r.returncode == 0:
                _last_hash = r.stdout.strip()
        except Exception:
            pass

        while True:
            try:
                time.sleep(60)
                r = proc.run(
                    ['git', 'rev-parse', 'HEAD'],
                    cwd=str(env.project_root), capture_output=True, text=True,
                    timeout=5,
                )
                if r.returncode != 0:
                    continue
                current_hash = r.stdout.strip()
                if current_hash == _last_hash:
                    continue

                # 새 커밋 감지 — 커밋 메시지 + 변경 파일 조회
                r2 = proc.run(
                    ['git', 'log', '-1', '--pretty=format:%B', current_hash],
                    cwd=str(env.project_root), capture_output=True, text=True,
                    timeout=5, encoding='utf-8', errors='replace',
                )
                commit_msg = r2.stdout.strip() if r2.returncode == 0 else ''

                r3 = proc.run(
                    ['git', 'diff-tree', '--no-commit-id', '--name-only', '-r', current_hash],
                    cwd=str(env.project_root), capture_output=True, text=True,
                    timeout=5, encoding='utf-8', errors='replace',
                )
                files = [f for f in r3.stdout.strip().split('\n') if f] if r3.returncode == 0 else []

                if commit_msg and 'auto-bump version' not in commit_msg:
                    try:
                        _cap_dir = env.scripts_dir or (env.base_dir.parent / 'scripts')
                        _cap_script = _cap_dir / 'zettel_capture.py'
                        if _cap_script.exists():
                            import importlib.util as _ilu2
                            _spec2 = _ilu2.spec_from_file_location('zettel_capture', str(_cap_script))
                            _mod2 = _ilu2.module_from_spec(_spec2)
                            _spec2.loader.exec_module(_mod2)
                            _mod2.capture_commit(commit_msg, files=files, agent='system')
                            # [T6] 커밋마다 파일 지도 스냅샷 갱신 편승 — 현재 프로젝트 루트 대상.
                            #   실패해도 커밋 캡처 자체는 이미 성공했으므로 무시(try 내부 격리 불필요).
                            try:
                                _mod2.capture_project_map(root=str(env.project_root),
                                                          agent='system')
                            except Exception as _me:
                                print(f"[commit_watcher] 파일 지도 갱신 오류(무시): {_me}")
                    except Exception as e:
                        print(f"[commit_watcher] 캡처 오류: {e}")

                _last_hash = current_hash
            except Exception as e:
                print(f"[commit_watcher] 폴링 오류: {e}")
    except Exception as e:
        print(f"[!] 커밋 감시 데몬 시작 실패: {e}")


# ── 임베딩 백필 데몬 (60초 주기) — 자가 치유 2.0 ④ ─────────────────────
def run_embedding_backfill(env: DaemonEnv) -> None:
    """embedding IS NULL 행(zettel/메모리/경험)을 주기적으로 임베딩 채움.

    [WHY] 쓰기 경로(훅/CLI)는 단명 프로세스라 모델 로드(수 초~수십 초) 불가 —
    warm 모델을 가진 서버가 사후 60초 내 채우는 구조. INSERT 측 수정 불필요.
    [제약] 모델 첫 호출이 ~100MB 다운로드를 트리거할 수 있음 — 데몬 스레드라 OK,
    동기 경로(API 핸들러)에서는 절대 첫 로드를 트리거하지 말 것.
    """
    try:
        time.sleep(90)  # 서버 안정화 + PG 기동 대기
        sys.path.insert(0, str(env.base_dir))
        from infra.embed_service import embed_floats
        from src.pg_store import ensure_schema
        from src.pg_vector_search import (
            _TABLES, ensure_vector_schema, pending_embedding_rows, upsert_embedding,
        )
        if not ensure_schema() or not ensure_vector_schema():
            print("[embed_backfill] vector 비활성 — 백필 데몬 종료 (ILIKE 회상 유지)")
            return
        if embed_floats('워밍업') is None:
            print("[embed_backfill] 임베딩 모델 사용 불가 — 백필 데몬 종료")
            return
        # _TABLES가 단일 진실 — 테이블 추가(예: incident_ledger) 시 자동 포함
        tables = tuple(_TABLES)
        while True:
            try:
                done = 0
                for table in tables:
                    for row in pending_embedding_rows(table, limit=50):
                        # [🔴 2026-08-14] 예전엔 빈 텍스트를 '(빈 내용)'으로 채웠다(재선택
                        #   무한 루프 회피). 그런데 그 placeholder 벡터가 아무 질의와도
                        #   중간 매칭돼 회상 노이즈가 됐고, 빈 행을 NULL로 비우는
                        #   scripts/reembed_all.py와 60초마다 왕복했다. 이제 빈 행은
                        #   pending_embedding_rows가 아예 안 골라준다 — 여기 continue는
                        #   그 계약이 깨졌을 때를 위한 이중 안전망이다(placeholder 부활 금지).
                        text = (row.get('text') or '').strip()
                        if not text:
                            continue
                        vec = embed_floats(text)
                        if vec and upsert_embedding(table, row['pk'], vec):
                            done += 1
                if done:
                    print(f"[embed_backfill] 임베딩 {done}건 채움")
            except Exception as e:
                print(f"[embed_backfill] 주기 오류: {e}")
            time.sleep(60)
    except Exception as e:
        print(f"[!] 임베딩 백필 데몬 시작 실패: {e}")


def run_heartbeat(env: DaemonEnv) -> None:
    """자율 클로드 심장 박동 데몬 — 본체는 infra/heartbeat_daemon.py.

    [WHY] 기본 꺼짐(hive_state 'heartbeat'.enabled=False) — 자율 실행은 반드시
    자율 실행의 명시적 옵트인 후에만. 루프 자체는 항상 돌지만
    enabled=False면 30초 재확인만 반복(무비용).
    [제약] frozen(EXE) 모드는 실행 대상이 앱 자신의 소스가 아니라 사용자 프로젝트 —
    current_project_root() late-binding으로 프로젝트 전환을 따라간다.
    """
    try:
        time.sleep(60)  # 서버 안정화 + PG 기동 대기 (embed_backfill과 동일 관례)
        sys.path.insert(0, str(env.base_dir))
        from infra.heartbeat_daemon import run_loop
        run_loop(env.current_project_root, env.data_dir, env.current_project_id)
    except Exception as e:
        print(f"[!] heartbeat 데몬 시작 실패: {e}")


# ── 데몬 토글 레지스트리 ──────────────────────────────────────────────────
# [WHY 2026-08-01] 실측: 상시 데몬 6종이 ~211MB + CPU를 점유하는데 토글은 lan_bridge 하나뿐이라
#   안 쓰는 기능도 무조건 떴다. Codex를 안 쓰는 PC에서 codex_pg_watcher가 CPU 15,140초(4.2시간),
# [불변식] 기본값은 전부 True — 토글 도입이 기존 동작을 바꾸면 안 된다. 끄는 것은 사용자 선택이며,
#   기본값을 False로 바꾸려면 그 기능이 죽는다는 것을 사용자가 알고 결정해야 한다.
# [설정] config.json  {"daemons": {"codex_watcher": false}}
#        또는 환경변수  VIBE_DISABLE_DAEMONS="codex_watcher"  (테스트/1회성)
# [제약] lan_bridge는 run_lan_bridge 내부에도 자체 게이트(lan_bridge_enabled)가 있다 —
#   이중 게이트지만 어느 쪽이든 OFF면 안 뜨므로 안전하다. 내부 게이트를 지우지 말 것.
# [불변식] 'thread' 값은 실제 기동 스레드명과 반드시 일치 — daemon_status()가 이 이름으로
#   threading.enumerate()를 조회해 "실행 중" 배지를 만든다. 이름이 어긋나면 UI는 살아있는
#   데몬을 죽었다고 표시한다. start_all_daemons가 이 값을 name=으로 그대로 쓰므로
#   레지스트리가 유일한 원천이다(호출부에 스레드명 재작성 금지).
# [제약] 스레드명만으로는 부족하다 — popen 후 즉시 return하는 데몬은 스레드가 사라진다.
#   daemon_status는 _daemon_child_alive()로 자식 프로세스도 함께 본다(위 과거사고 참조).
DAEMON_TOGGLES: dict = {
    'watchdog':      {'label': '하이브 워치독 (프로세스 감시)', 'thread': 'Watchdog'},
    'recycle_watcher': {'label': '컨텍스트 리사이클 자동 발동 (85% 초과 시)',
                        'thread': 'RecycleWatcher'},
    'codex_watcher': {'label': 'Codex PG 워처 (온디맨드 — Codex 쓸 때만 자동 기동)',
                      'thread': 'CodexPGWatcher'},
    'orchestrator':  {'label': '오케스트레이터 데몬', 'thread': 'OrchestratorDaemon'},
    'doc_generators': {'label': 'PROJECT_MAP/HIVEMIND 자동 갱신 (30분 주기)', 'thread': 'DocGeneratorsDaemon'},
    'agent_sync':    {'label': '에이전트 상태 동기화', 'thread': 'AgentSyncDaemon'},
    'wiki_sync':     {'label': '위키 동기화 (주석→백과사전→검색→드라이브, 10분)',
                      'thread': 'WikiSync'},
    'zettel_sync':   {'label': '제텔카스텐 동기화', 'thread': 'ZettelSync'},
    'zettel_refine': {'label': '제텔카스텐 정제', 'thread': 'ZettelRefine'},
    'commit_watcher': {'label': '커밋 감시', 'thread': 'CommitWatcher'},
    'embed_backfill': {'label': '임베딩 백필 (회상 v2 검색 품질)', 'thread': 'EmbedBackfill'},
    'heartbeat':     {'label': '자율 클로드 하트비트', 'thread': 'Heartbeat'},
    'lan_bridge':    {'label': 'LAN 브리지 (별도 토글 lan_bridge_enabled도 필요)', 'thread': 'LanBridge'},
}


def _disabled_daemons(config_file: Path) -> set:
    """끄기로 지정된 데몬 키 집합. 설정 파싱 실패는 '아무것도 끄지 않음'으로 흡수한다.

    [WHY 실패 시 ON] 설정이 깨졌을 때 데몬이 조용히 안 뜨면 원인 추적이 매우 어렵다.
      기능이 도는 쪽이 안전한 실패 방향.
    [WHY env가 아니라 Path] HTTP 핸들러(daemons_api)는 main() 로컬인 _daemon_env()에
      접근할 수 없다. 필요한 것이 config_file 하나뿐이라 DaemonEnv 의존을 끊었다.
    """
    off = set()
    raw = os.environ.get('VIBE_DISABLE_DAEMONS', '')
    off |= {k.strip() for k in raw.split(',') if k.strip()}
    try:
        cfg = json.loads(config_file.read_text(encoding='utf-8')) if config_file.exists() else {}
        toggles = cfg.get('daemons', {})
        if isinstance(toggles, dict):
            off |= {k for k, v in toggles.items() if v is False}
    except (json.JSONDecodeError, OSError):
        pass
    return off


def daemon_status(config_file: Path) -> list:
    """UI용 데몬 목록 — [{key, label, enabled, running, source}]. 순서는 레지스트리 정의 순.

    [WHY running과 enabled를 따로]  토글은 다음 부팅부터 적용된다(스레드를 런타임에 죽이면
      subprocess 자식과 PG 커넥션이 고아가 되므로 재기동 방식이 안전). enabled=False인데
      running=True면 UI가 "재시작 후 적용"을 정확히 안내할 수 있다 — 이 두 값을 합치면
      사용자는 껐는데 왜 여전히 CPU를 먹는지 알 방법이 없다.
    [제약] running은 존재 여부일 뿐 '일하는 중'이 아니다 — embed_backfill/heartbeat는
      대부분 sleep 상태로 살아있다.
    [WHY 두 가지를 OR] 데몬은 두 형태가 섞여 있다. 루프를 도는 것은 스레드가 살아있고,
      외부 스크립트를 popen하는 것은 스레드가 죽고 자식만 남는다. 한쪽만 보면 반드시
      한 부류를 통째로 오판한다(2026-08-04 사고: popen 계열 4종이 전부 '꺼짐'으로 표시).
    [알려진 구멍] run_orchestrator_daemon은 이전 인스턴스가 남긴 PID가 살아있으면
      자식을 띄우지 않고 return한다 — 이 경로는 여기서 알 수 없어 running=False로 보인다.
      PID 파일 기반 판정은 tasklist 호출이라 UI 폴링 주기에 넣기엔 비싸서 의도적으로 뺐다.
    """
    off = _disabled_daemons(config_file)
    env_off = {k.strip() for k in os.environ.get('VIBE_DISABLE_DAEMONS', '').split(',') if k.strip()}
    alive = {t.name for t in threading.enumerate()}
    return [
        {
            'key': key,
            'label': meta['label'],
            'enabled': key not in off,
            'running': meta['thread'] in alive or _daemon_child_alive(key),
            # env: 환경변수로 끈 것은 config를 고쳐도 안 켜진다 → UI에서 토글을 잠근다.
            'source': 'env' if key in env_off else 'config',
        }
        for key, meta in DAEMON_TOGGLES.items()
    ]


def plan_terminal_recycles(terminals: dict, autos: set,
                           threshold: float) -> tuple[list, list]:
    """터미널별 계측 → (처형 대상, 남길 기록). 부작용 없는 순수 판정.

    반환: ([(terminal_id, cli, pct), ...], [(note_key, message), ...])

    [WHY 순수 함수로 분리] 바로 이 판정이 2026-08-09·08-14 두 번 사고를 냈다
      (T1 고정 폴백 → 전 슬롯 팬아웃). 무한 루프 안에 있으면 테스트가 불가능해
      회귀를 못 막는다. 루프는 이 함수의 결과를 집행하기만 한다.
    [불변식] 대상은 자기 세션이 결속된 터미널뿐 — CLI 전역 계측은 쓰지 않는다.
    """
    targets, notes = [], []
    for terminal_id in sorted(terminals):
        m = terminals[terminal_id] or {}
        cli = str(m.get('cli') or '')
        if cli not in autos:
            continue
        if not m.get('available'):
            if m.get('reason') in ('unbound_session', 'ambiguous_codex_sessions'):
                # [WHY 로그] 이 슬롯은 자동 리사이클이 영영 안 걸린다. 조용히
                #   넘기면 '자동이 도는 줄 알았는데 0회'가 된다.
                notes.append((f'unbound:{terminal_id}',
                              f"[리사이클] {terminal_id} {cli} 계측 불가"
                              f"({m.get('reason')}) — 자동 대상 제외, 수동만 가능"))
            continue
        pct = float(m.get('percentage') or 0)
        if pct < threshold:
            continue
        if m.get('stale'):
            # [WHY 차단] 마지막 쓰기가 STALE_AFTER_SEC보다 오래됐다 = 그 슬롯의
            #   '진행 중 대화'가 아니다. 화석을 근거로 죽이면 새 세션은 첫 응답
            #   전에 또 죽고, 그래서 usage가 영영 0이라 계측은 계속 화석을
            #   가리킨다 — 자기영속 루프가 된다(2026-08-14 실측).
            age_h = (m.get('session_age_sec') or 0) / 3600
            notes.append((f'stale:{terminal_id}',
                          f"[리사이클] {terminal_id} {cli} {pct}% 임계 초과 — "
                          f"세션이 {age_h:.1f}시간째 정지(화석), 건너뜀"))
            continue
        targets.append((terminal_id, cli, pct))
    return targets, notes


def run_recycle_watcher(env: DaemonEnv) -> None:
    """컨텍스트 임계치 초과 시 세션 리사이클을 자동 발동한다(Phase 6).

    [WHY 서버 API 경유] 판정(GUARD)을 여기 복제하지 않는다 — 사용자 입력 중 여부,
      리사이클 진행 중 여부, 플래핑 가드가 전부 서버 쪽 plan_recycle에 있고,
      데몬이 자체 판단하면 두 벌이 어긋나 '사람이 타이핑 중인데 죽이는' 최악의
      실패 모드가 열린다. 데몬은 계측과 호출만 담당한다.
    [P0 계측] antigravity는 계측 원천이 폐기 경로라 자동 대상에서 제외됨 —
      AUTO_TRIGGER_CLIS가 유일 원천이므로 여기서 별도 분기하지 않는다.
    [🔴 과거사고 2026-08-09] terminal_id를 안 실어 보냈다. 서버가 'T1'로 폴백해
      codex가 임계를 넘어도 죽는 건 claude가 돌던 T1이었다("T1만 계속 크래시").
      계측은 CLI 단위인데 처형은 터미널 단위 — 그 사이를 잇는 매핑이 통째로
      빠져 있었다.
    [🔴 과거사고 2026-08-14] 위 수정이 'T1 고정'을 '전부 처형'으로 바꿨다.
      agent==cli인 running 슬롯을 모두 대상으로 삼아, 세션 하나가 임계를 넘으면
      무관한 옆 슬롯까지 같이 죽었다(T1·T2 동시 처형). 게다가 계측 원천이 어제
      끝난 세션의 화석(85.3%, 16시간 정지)이라 60초마다 영구 반복됐다.
      → 이제 CLI 전역 계측을 아예 안 본다. 서버가 세션 파일을 슬롯에 결속해
      내려주는 status['terminals']만 쓰고, 화석(stale)은 건너뛴다.
    """
    import urllib.error
    import urllib.request

    base = f'http://127.0.0.1:{env.http_port}'
    interval = 60.0
    # [WHY 재출력 억제] 옛 코드는 같은 사유를 60초마다 찍어 로그를 덮었다(실측:
    #   하룻밤 수백 줄). 그렇다고 침묵시키면 화석이 영구히 남아도 아무도 모른다
    #   — 사유가 바뀌거나 30분이 지날 때만 다시 찍는다.
    notes: dict[str, tuple[str, float]] = {}
    NOTE_REPEAT_SEC = 1800.0

    def _note(key: str, msg: str) -> None:
        prev = notes.get(key)
        now = time.time()
        if prev and prev[0] == msg and (now - prev[1]) < NOTE_REPEAT_SEC:
            return
        notes[key] = (msg, now)
        print(msg)

    def _post(path: str, payload: dict) -> dict | None:
        try:
            req = urllib.request.Request(
                base + path, method='POST',
                data=json.dumps(payload).encode('utf-8'),
                headers={'Content-Type': 'application/json'})
            with urllib.request.urlopen(req, timeout=90) as resp:
                return json.loads(resp.read().decode('utf-8'))
        except (urllib.error.URLError, OSError, ValueError):
            return None

    time.sleep(45)  # 서버 라우트와 PG 스키마가 준비될 여유
    while True:
        try:
            status = None
            try:
                with urllib.request.urlopen(
                        f'{base}/api/session/recycle/status', timeout=10) as resp:
                    status = json.loads(resp.read().decode('utf-8'))
            except (urllib.error.URLError, OSError, ValueError):
                status = None

            if status:
                threshold = float(status.get('threshold') or 85.0)
                project_id = env.current_project_id()
                targets, notes_out = plan_terminal_recycles(
                    status.get('terminals') or {},
                    set(status.get('auto_trigger_clis') or []), threshold)
                for key, msg in notes_out:
                    _note(key, msg)
                for terminal_id, cli, pct in targets:
                    res = _post('/api/session/recycle',
                                {'trigger': 'auto', 'cli': cli,
                                 'terminal_id': terminal_id,
                                 'project_id': project_id})
                    if res and res.get('ok'):
                        print(f"[리사이클] {terminal_id} {cli} {pct}% "
                              f"→ 세션 교체 완료 (재정박 {res.get('reanchor_chars')}자)")
                    elif res and res.get('reason') not in (
                            'below_threshold', 'user_active', 'flap_guard',
                            'already_running', 'no_measurement'):
                        # 정상적인 '지금은 아님' 사유는 로그를 더럽히지 않는다.
                        _note(f'hold:{terminal_id}',
                              f"[리사이클] {terminal_id} {cli} 보류 — "
                              f"{res.get('reason')}")
        except Exception as exc:
            print(f'[리사이클 워처] 순회 오류: {exc}')
        time.sleep(interval)


def start_all_daemons(env: DaemonEnv, agent_status: dict,
                      agent_status_lock: threading.Lock) -> None:
    """부팅 4단계 — 백그라운드 데몬 스레드 10종을 일괄 기동.

    server.py main()이 run_* 래퍼를 개별 정의/기동하던 것을 한 곳으로 이관(R18).
    [불변식] env는 caller가 HTTP_PORT 확정 후 생성해 주입 — DaemonEnv late-binding
      계약 유지(모듈 import 시점 포트 고정 금지). agent_sync_daemon만 env가 아닌
      (agent_status, lock) 시그니처라 별도 처리.
    [제약] 스레드명은 DAEMON_TOGGLES['thread']가 유일 원천 — 기존 server.py 이름을
      그대로 옮겨왔고(로그 추적성), watchdog의 무명 스레드를 이름 있는 스레드로
      승격했다(daemon_status의 실행 중 판정에 이름이 필요). 스레드명에 의존하는
      외부 코드는 없음을 확인하고 바꿨다.
    """
    off = _disabled_daemons(env.config_file)
    skipped = []

    def _t(key, target, args):
        """토글 OFF면 스레드를 아예 만들지 않는다(기동 후 내부에서 return하면 스레드가 남음)."""
        if key in off:
            skipped.append(key)
            return
        threading.Thread(target=target, args=args,
                         name=DAEMON_TOGGLES[key]['thread'], daemon=True).start()

    _t('watchdog', run_watchdog, (env,))
    _t('codex_watcher', run_codex_pg_watcher, (env,))
    _t('orchestrator', run_orchestrator_daemon, (env,))
    _t('doc_generators', run_doc_generators_daemon, (env,))
    _t('agent_sync', agent_sync_daemon, (agent_status, agent_status_lock))
    _t('wiki_sync', run_wiki_sync, (env,))
    _t('zettel_sync', run_zettel_sync, (env,))
    _t('zettel_refine', run_zettel_refine, (env,))
    _t('commit_watcher', run_commit_watcher, (env,))
    _t('embed_backfill', run_embedding_backfill, (env,))
    _t('heartbeat', run_heartbeat, (env,))
    _t('lan_bridge', run_lan_bridge, (env,))
    _t('recycle_watcher', run_recycle_watcher, (env,))

    # [WHY 로그] 데몬이 안 뜬 이유가 로그에 없으면 비활성 원인을 추적할 방법이 없다.
    #   설정으로 끈 것과 버그로 안 뜬 것을 구분하는 유일한 단서다.
    if skipped:
        print(f"[*] 데몬 {len(skipped)}종 비활성(config daemons/VIBE_DISABLE_DAEMONS): "
              f"{', '.join(sorted(skipped))}")
    unknown = off - set(DAEMON_TOGGLES)
    if unknown:
        print(f"[!] 알 수 없는 데몬 키 무시됨: {', '.join(sorted(unknown))} "
              f"(가능한 키: {', '.join(sorted(DAEMON_TOGGLES))})")

