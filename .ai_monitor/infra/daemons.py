# ─────────────────────────────────────────────────────────────────────────────
# 📄 파일명: infra/daemons.py
# 📝 설명: 백그라운드 데몬 러너 — 워치독/Discord 대시보드/오케스트레이터/문서 생성/
#          에이전트 동기화/MUX/제텔 동기화·정제/커밋 감시 (server.py 분할 단계 9)
# 🕒 변경 이력:
# [2026-08-04] Codex — 저장된 Bot Token과 T1 채널만으로 사용량 대시보드 자동 기동.
# [2026-08-04] Codex — Discord T1~Tn을 활성 프로젝트 하나가 아닌 slot_projects에 바인딩.
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


def run_watchdog(env: DaemonEnv) -> None:
    if not env.scripts_dir:
        return
    watchdog_script = env.scripts_dir / "hive_watchdog.py"
    if watchdog_script.exists():
        _python_cmds = runtime.python_runner_cmds(env.base_dir, env.project_root)
        if not _python_cmds:
            print("[!] run_watchdog: Python 인터프리터를 찾을 수 없어 워치독 스킵")
            return
        python_exe = _python_cmds[0]
        # [지역변수 rename] proc→child: 모듈 proc(콘솔숨김 헬퍼)와 이름 충돌 회피
        child = proc.popen(
            [python_exe, str(watchdog_script), "--data-dir", str(env.data_dir)],
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            encoding='utf-8',
            errors='replace',
        )
        env.child_procs.append(child)


def run_lan_bridge(env: DaemonEnv) -> None:
    """LAN 브리지(lan_bridge.py) 별도 프로세스 기동 — config lan_bridge_enabled=True일 때만.

    [WHY 기본 꺼짐] 브리지는 0.0.0.0을 노출하므로 사용자가 명시적으로 켤 때만 뜬다.
    [frozen 함정] sys.executable은 frozen 모드에서 앱EXE라 스크립트 실행 불가 →
      python_runner_cmds가 개발/EXE 모드별 실제 인터프리터를 해석(watchdog과 동일 패턴).
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
        return
    _python_cmds = runtime.python_runner_cmds(env.base_dir, env.project_root)
    if not _python_cmds:
        print("[!] run_lan_bridge: Python 인터프리터를 찾을 수 없어 LAN 브리지 스킵")
        return
    # [지역변수 rename] proc→child: 모듈 proc(콘솔숨김 헬퍼)와 이름 충돌 회피
    child = proc.popen(
        [_python_cmds[0], str(bridge_script), "--data-dir", str(env.data_dir)],
        stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True,
        encoding='utf-8', errors='replace',
    )
    env.child_procs.append(child)


def run_discord_dashboard(env: DaemonEnv) -> None:
    """Webhook 또는 UI에 저장된 공용 Bot으로 Discord 사용량 대시보드를 기동한다."""
    webhook = os.environ.get('DISCORD_WEBHOOK_URL', '').strip()
    child_env = os.environ.copy()
    try:
        from api.discord_config_api import load_config
        config = load_config(env.data_dir / 'discord_secrets.dat')
        channels = config.get('channels') or {}
        # T1을 기본 상태 채널로 사용하고, T1이 비었으면 첫 등록 채널을 사용한다.
        dashboard_channel = channels.get('T1') or next(iter(channels.values()), '')
        if config.get('token') and dashboard_channel:
            child_env['DISCORD_BOT_TOKEN'] = config['token']
            child_env['DISCORD_DASHBOARD_CHANNEL_ID'] = dashboard_channel
    except Exception as error:
        print(f'[!] Discord dashboard 설정 로드 실패: {type(error).__name__}')
    has_bot_target = (child_env.get('DISCORD_BOT_TOKEN', '').strip()
                      and child_env.get('DISCORD_DASHBOARD_CHANNEL_ID', '').strip())
    if (not webhook and not has_bot_target) or not env.scripts_dir:
        return
    script = env.scripts_dir / 'discord_dashboard.py'
    runners = runtime.python_runner_cmds(env.base_dir, env.project_root)
    if not script.exists() or not runners:
        return
    log_path = env.data_dir / 'discord_dashboard.log'
    log_path.parent.mkdir(parents=True, exist_ok=True)
    log_handle = open(log_path, 'a', encoding='utf-8')
    child = proc.popen(
        [runners[0], str(script), '--server', f'http://127.0.0.1:{env.http_port}',
         '--project-root', str(env.project_root), '--project-id', env.current_project_id()],
        cwd=str(env.project_root), stdout=log_handle, stderr=log_handle,
        env=child_env,
        encoding='utf-8', errors='replace',
    )
    child._vibe_log_handle = log_handle
    env.child_procs.append(child)


def run_discord_gateway(env: DaemonEnv) -> None:
    """공용 봇 토큰 하나로 현재 PC의 모든 터미널 binding을 처리한다.

    UI v2 설정이 있으면 그 값이 정본이며 Gateway를 한 개만 띄운다. 환경변수 계약은
    UI 설정이 없는 기존 사용자의 하위 호환을 위해 유지한다.
    """
    if not env.scripts_dir:
        return
    config = {}
    try:
        from api.discord_config_api import load_config
        config = load_config(env.data_dir / 'discord_secrets.dat')
        if env.config_file.exists():
            app_config = json.loads(env.config_file.read_text(encoding='utf-8'))
            config['slot_projects'] = app_config.get('slot_projects') or {}
    except Exception as error:
        print(f'[!] Discord UI 설정 로드 실패: {type(error).__name__}')
    child_env = os.environ.copy()
    if config.get('token'):
        channels = config.get('channels') or {}
        child_env['DISCORD_BOT_TOKEN'] = config['token']
        child_env['VIBE_NODE_ID'] = config['node_id']
        child_env['DISCORD_GUILD_IDS'] = ','.join(config['guild_ids'])
        child_env['DISCORD_USER_IDS'] = ','.join(config['user_ids'])
        child_env['DISCORD_CHANNEL_IDS'] = ','.join(channels.values())
        child_env['DISCORD_CHANNEL_BINDINGS'] = json.dumps(
            _discord_channel_bindings(config, env.current_project_id())
        )
    required = ('DISCORD_BOT_TOKEN', 'DISCORD_GUILD_IDS', 'DISCORD_CHANNEL_IDS', 'DISCORD_USER_IDS')
    has_bindings = (child_env.get('DISCORD_CHANNEL_BINDINGS', '').strip()
                    or child_env.get('DISCORD_GROUP_BINDINGS', '').strip())
    if not all(child_env.get(key, '').strip() for key in required) or not has_bindings:
        return
    script = env.scripts_dir / 'discord_gateway.py'
    runners = runtime.python_runner_cmds(env.base_dir, env.project_root)
    if not script.exists() or not runners:
        return
    log_path = env.data_dir / 'discord_gateway.log'
    log_handle = open(log_path, 'a', encoding='utf-8')
    child_env.pop('DISCORD_TERMINAL_ID', None)
    child_env['VIBE_SERVER_URL'] = f'http://127.0.0.1:{env.http_port}'
    child_env['VIBE_PROJECT_ID'] = env.current_project_id()
    child = proc.popen(
        [runners[0], str(script)], cwd=str(env.project_root),
        stdout=log_handle, stderr=log_handle, env=child_env,
        encoding='utf-8', errors='replace',
    )
    child._vibe_log_handle = log_handle
    env.child_procs.append(child)


def _discord_channel_bindings(config: dict, fallback_project_id: str) -> dict:
    """Bind Discord terminal IDs to the persisted per-slot projects.

    ``slot_projects`` is zero-based while external terminal IDs are one-based.
    Falling back is intentional for old configurations that predate per-slot
    project persistence.
    """
    channels = config.get('channels') or {}
    slot_projects = config.get('slot_projects') or {}
    bindings = {}
    for terminal, channel in channels.items():
        terminal_id = str(terminal).upper()
        project_id = fallback_project_id
        if terminal_id.startswith('T') and terminal_id[1:].isdigit():
            slot_index = int(terminal_id[1:]) - 1
            path = slot_projects.get(str(slot_index), slot_projects.get(slot_index, ''))
            if isinstance(path, str) and path.strip():
                project_id = slugify(Path(path.strip()))
        bindings[str(channel)] = {
            'node_id': config['node_id'],
            'terminal_id': terminal_id,
            'project_id': project_id,
        }
    return bindings


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
    _python_cmds = runtime.python_runner_cmds(env.base_dir, env.project_root)
    if not _python_cmds:
        print("[!] run_codex_pg_watcher: Python interpreter not found")
        return
    python_exe = _python_cmds[0]
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
                env.child_procs.append(child)
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
        env.child_procs.append(child)
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
        print(f'[*] 제텔카스텐 Vault 동기화 데몬 시작됨 — vault={_vault}, project_id={_proj_id}, 60초 양방향')

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
                            bidirectional=True, include_archived=True,
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
                        # 빈 텍스트도 placeholder로 임베딩 — 스킵하면 매 주기 재선택(무한 루프)
                        text = (row.get('text') or '').strip() or '(빈 내용)'
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
DAEMON_TOGGLES: dict = {
    'watchdog':      {'label': '하이브 워치독 (프로세스 감시)', 'thread': 'Watchdog'},
    'discord_dashboard': {'label': 'Discord 읽기 전용 대시보드', 'thread': 'DiscordDashboard'},
    'discord_gateway': {'label': 'Discord 양방향 Gateway', 'thread': 'DiscordGateway'},
    'codex_watcher': {'label': 'Codex PG 워처 (온디맨드 — Codex 쓸 때만 자동 기동)',
                      'thread': 'CodexPGWatcher'},
    'orchestrator':  {'label': '오케스트레이터 데몬', 'thread': 'OrchestratorDaemon'},
    'doc_generators': {'label': 'PROJECT_MAP/HIVEMIND 자동 갱신 (30분 주기)', 'thread': 'DocGeneratorsDaemon'},
    'agent_sync':    {'label': '에이전트 상태 동기화', 'thread': 'AgentSyncDaemon'},
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
    [제약] running은 스레드 존재 여부일 뿐 '일하는 중'이 아니다 — embed_backfill/heartbeat는
      대부분 sleep 상태로 살아있다.
    """
    off = _disabled_daemons(config_file)
    env_off = {k.strip() for k in os.environ.get('VIBE_DISABLE_DAEMONS', '').split(',') if k.strip()}
    alive = {t.name for t in threading.enumerate()}
    return [
        {
            'key': key,
            'label': meta['label'],
            'enabled': key not in off,
            'running': meta['thread'] in alive,
            # env: 환경변수로 끈 것은 config를 고쳐도 안 켜진다 → UI에서 토글을 잠근다.
            'source': 'env' if key in env_off else 'config',
        }
        for key, meta in DAEMON_TOGGLES.items()
    ]


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
    _t('discord_dashboard', run_discord_dashboard, (env,))
    _t('discord_gateway', run_discord_gateway, (env,))
    _t('codex_watcher', run_codex_pg_watcher, (env,))
    _t('orchestrator', run_orchestrator_daemon, (env,))
    _t('doc_generators', run_doc_generators_daemon, (env,))
    _t('agent_sync', agent_sync_daemon, (agent_status, agent_status_lock))
    _t('zettel_sync', run_zettel_sync, (env,))
    _t('zettel_refine', run_zettel_refine, (env,))
    _t('commit_watcher', run_commit_watcher, (env,))
    _t('embed_backfill', run_embedding_backfill, (env,))
    _t('heartbeat', run_heartbeat, (env,))
    _t('lan_bridge', run_lan_bridge, (env,))

    # [WHY 로그] 데몬이 안 뜬 이유가 로그에 없으면 비활성 원인을 추적할 방법이 없다.
    #   설정으로 끈 것과 버그로 안 뜬 것을 구분하는 유일한 단서다.
    if skipped:
        print(f"[*] 데몬 {len(skipped)}종 비활성(config daemons/VIBE_DISABLE_DAEMONS): "
              f"{', '.join(sorted(skipped))}")
    unknown = off - set(DAEMON_TOGGLES)
    if unknown:
        print(f"[!] 알 수 없는 데몬 키 무시됨: {', '.join(sorted(unknown))} "
              f"(가능한 키: {', '.join(sorted(DAEMON_TOGGLES))})")

