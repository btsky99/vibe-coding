# ─────────────────────────────────────────────────────────────────────────────
# 📄 파일명: infra/daemons.py
# 📝 설명: 백그라운드 데몬 러너 — 워치독/텔레그램/힐데몬/오케스트레이터/문서 생성/
#          에이전트 동기화/MUX/제텔 동기화·정제/커밋 감시 (server.py 분할 단계 9)
# 🕒 변경 이력:
# [2026-06-10] Claude — server.py main() 내부 중첩 함수 11개 이관 (~500줄)
#   - [제약] 모든 함수는 daemon=True 스레드에서 호출됨 — 블로킹 루프 허용.
#   - [WHY] env(DaemonEnv)는 호출 시점에 server.py 래퍼가 생성 — HTTP_PORT 등이
#     main() 후반에 재바인딩되므로 모듈 import 시점 값 고정을 피한다.
#   - [불변식] subprocess로 띄운 자식은 반드시 env.child_procs에 append —
#     lifecycle.cleanup_child_procs가 이 리스트만 종료 대상으로 삼는다.
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

from infra import runtime


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
        proc = subprocess.Popen(
            [python_exe, str(watchdog_script), "--data-dir", str(env.data_dir)],
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            encoding='utf-8',
            errors='replace',
            creationflags=getattr(subprocess, 'CREATE_NO_WINDOW', 0x08000000)
        )
        env.child_procs.append(proc)

_tg_bridge_launched = [False]
def run_telegram_bridge(env: DaemonEnv) -> None:
    if _tg_bridge_launched[0]:
        return
    _tg_bridge_launched[0] = True
    if not env.scripts_dir:
        return
    tg_script = env.scripts_dir / "telegram_bridge.py"
    env_file = env.project_root / ".env"
    tg_log = env.data_dir / "telegram_bridge.log"
    if not tg_script.exists():
        return
    tg_pid_file = env.data_dir / "telegram_bridge.pid"
    if tg_pid_file.exists():
        try:
            old_pid = int(tg_pid_file.read_text().strip())
            check = subprocess.run(
                ['tasklist', '/FI', f'PID eq {old_pid}', '/NH'],
                capture_output=True, text=True, timeout=5,
                creationflags=0x08000000,
            )
            if str(old_pid) in check.stdout and 'python' in check.stdout.lower():
                print(f"[*] Telegram Bridge 이미 실행 중 (PID={old_pid}) — 스킵")
                return
            else:
                tg_pid_file.unlink(missing_ok=True)
        except Exception:
            tg_pid_file.unlink(missing_ok=True)
    try:
        env_content = env_file.read_text(encoding='utf-8') if env_file.exists() else ""
        has_token = False
        for line in env_content.splitlines():
            stripped = line.strip()
            if stripped.startswith("TELEGRAM_BOT_T") and "=" in stripped:
                token_val = stripped.split("=", 1)[1].strip()
                if token_val:
                    has_token = True
                    break
            elif stripped.startswith("TELEGRAM_BOT_TOKEN="):
                token_val = stripped.split("=", 1)[1].strip()
                if token_val:
                    has_token = True
                    break
        if not has_token:
            return
    except Exception:
        return
    _python_cmds = runtime.python_runner_cmds(env.base_dir, env.project_root)
    if not _python_cmds:
        print("[!] run_telegram_bridge: Python 인터프리터를 찾을 수 없어 Telegram 브릿지 스킵")
        return
    python_exe = _python_cmds[0]
    child_env = os.environ.copy()
    child_env['VIBE_SERVER_PORT'] = str(env.http_port)
    tg_log.parent.mkdir(parents=True, exist_ok=True)
    log_handle = open(tg_log, 'a', encoding='utf-8')
    proc = subprocess.Popen(
        [python_exe, str(tg_script)],
        cwd=str(env.project_root),
        stdout=log_handle,
        stderr=log_handle,
        env=child_env,
        encoding='utf-8',
        errors='replace',
        creationflags=getattr(subprocess, 'CREATE_NO_WINDOW', 0x08000000),
    )
    proc._vibe_log_handle = log_handle
    env.child_procs.append(proc)
    try:
        tg_pid_file.write_text(str(proc.pid))
    except Exception:
        pass
    print(f"[*] Telegram Bridge 자동 시작됨 (PID={proc.pid})")

def run_codex_pg_watcher(env: DaemonEnv) -> None:
    if not env.scripts_dir:
        return
    watcher_script = env.scripts_dir / "codex_pg_watcher.py"
    if watcher_script.exists():
        _python_cmds = runtime.python_runner_cmds(env.base_dir, env.project_root)
        if not _python_cmds:
            print("[!] run_codex_pg_watcher: Python interpreter not found")
            return
        python_exe = _python_cmds[0]
        proc = subprocess.Popen(
            [python_exe, str(watcher_script), "--interval", "5"],
            cwd=str(env.project_root),
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            encoding='utf-8',
            errors='replace',
            creationflags=getattr(subprocess, 'CREATE_NO_WINDOW', 0x08000000),
        )
        env.child_procs.append(proc)
        print("[*] Codex pg_logs watcher started")

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
                result = subprocess.run(['tasklist', '/FI', f'PID eq {pid}', '/FO', 'CSV', '/NH'], capture_output=True, text=True, encoding='utf-8', errors='replace', timeout=5, creationflags=getattr(subprocess, 'CREATE_NO_WINDOW', 0x08000000))
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
        proc = subprocess.Popen(
            [python_exe, str(orch_script), "--daemon", "--interval", "60"],
            cwd=str(env.project_root),
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            encoding='utf-8',
            errors='replace',
            creationflags=getattr(subprocess, 'CREATE_NO_WINDOW', 0x08000000),
        )
        env.child_procs.append(proc)
        print("[*] 하이브 오케스트레이터 데몬(orchestrator) 자동 시작됨")

        try:
            pid_file.write_text(str(proc.pid), encoding='utf-8')
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
                subprocess.run(
                    [python_exe, str(pm_script)],
                    cwd=str(env.project_root),
                    timeout=120,
                    capture_output=True,
                    creationflags=getattr(subprocess, 'CREATE_NO_WINDOW', 0x08000000),
                )
                print("[*] PROJECT_MAP.md 자동 갱신 완료")
            except Exception as e:
                print(f"[!] PROJECT_MAP.md 갱신 실패: {e}")

        # HIVEMIND.md 갱신
        if hv_script.exists():
            try:
                subprocess.run(
                    [python_exe, str(hv_script)],
                    cwd=str(env.project_root),
                    timeout=120,
                    capture_output=True,
                    creationflags=getattr(subprocess, 'CREATE_NO_WINDOW', 0x08000000),
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

        # config.json에서 사용자 지정 vault 경로 읽기 (없으면 전역 기본값)
        _vault = env.global_vault_dir
        try:
            if env.config_file.exists():
                _cfg = json.loads(env.config_file.read_text(encoding='utf-8'))
                _user_vault = _cfg.get('vault_dir', '')
                if _user_vault:
                    _vault = Path(_user_vault)
        except Exception:
            pass
        _vault.mkdir(parents=True, exist_ok=True)

        # 기존 .zettel-vault 마이그레이션 (최초 1회)
        import shutil as _shutil
        _old_vault = env.current_project_root() / '.zettel-vault'
        if _old_vault.exists() and not (_vault / '_migrated').exists():
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
                            bidirectional=True, include_archived=True)
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
        _no_window = getattr(subprocess, 'CREATE_NO_WINDOW', 0x08000000)
        # 마지막으로 처리한 커밋 해시
        _last_hash = None
        try:
            r = subprocess.run(
                ['git', 'rev-parse', 'HEAD'],
                cwd=str(env.project_root), capture_output=True, text=True,
                timeout=5, creationflags=_no_window,
            )
            if r.returncode == 0:
                _last_hash = r.stdout.strip()
        except Exception:
            pass

        while True:
            try:
                time.sleep(60)
                r = subprocess.run(
                    ['git', 'rev-parse', 'HEAD'],
                    cwd=str(env.project_root), capture_output=True, text=True,
                    timeout=5, creationflags=_no_window,
                )
                if r.returncode != 0:
                    continue
                current_hash = r.stdout.strip()
                if current_hash == _last_hash:
                    continue

                # 새 커밋 감지 — 커밋 메시지 + 변경 파일 조회
                r2 = subprocess.run(
                    ['git', 'log', '-1', '--pretty=format:%B', current_hash],
                    cwd=str(env.project_root), capture_output=True, text=True,
                    timeout=5, encoding='utf-8', errors='replace',
                    creationflags=_no_window,
                )
                commit_msg = r2.stdout.strip() if r2.returncode == 0 else ''

                r3 = subprocess.run(
                    ['git', 'diff-tree', '--no-commit-id', '--name-only', '-r', current_hash],
                    cwd=str(env.project_root), capture_output=True, text=True,
                    timeout=5, encoding='utf-8', errors='replace',
                    creationflags=_no_window,
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
    텔레그램 /auto on의 명시적 옵트인 후에만. 루프 자체는 항상 돌지만
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


def start_all_daemons(env: DaemonEnv, agent_status: dict,
                      agent_status_lock: threading.Lock) -> None:
    """부팅 4단계 — 백그라운드 데몬 스레드 10종을 일괄 기동.

    server.py main()이 run_* 래퍼를 개별 정의/기동하던 것을 한 곳으로 이관(R18).
    [불변식] env는 caller가 HTTP_PORT 확정 후 생성해 주입 — DaemonEnv late-binding
      계약 유지(모듈 import 시점 포트 고정 금지). agent_sync_daemon만 env가 아닌
      (agent_status, lock) 시그니처라 별도 처리.
    [제약] name= 값은 기존 server.py 스레드명을 verbatim 보존 — 로그/디버깅 추적성
      및 PTY-Watchdog 등 다른 스레드명과의 관례 일관성. run_watchdog/
      run_telegram_bridge는 원래 name 미지정이라 그대로 둔다.
    """
    def _t(target, args, name=None):
        threading.Thread(target=target, args=args, name=name, daemon=True).start()

    _t(run_watchdog, (env,))
    _t(run_telegram_bridge, (env,))
    _t(run_codex_pg_watcher, (env,), 'CodexPGWatcher')
    _t(run_orchestrator_daemon, (env,), 'OrchestratorDaemon')
    _t(run_doc_generators_daemon, (env,), 'DocGeneratorsDaemon')
    _t(agent_sync_daemon, (agent_status, agent_status_lock), 'AgentSyncDaemon')
    _t(run_zettel_sync, (env,), 'ZettelSync')
    _t(run_zettel_refine, (env,), 'ZettelRefine')
    _t(run_commit_watcher, (env,), 'CommitWatcher')
    _t(run_embedding_backfill, (env,), 'EmbedBackfill')
    _t(run_heartbeat, (env,), 'Heartbeat')

