"""
FILE: infra/tunnel_daemon.py
DESCRIPTION: 중앙 PG(아픽스 서버)로 가는 SSH 터널을 띄우고 살려두는 데몬.
             `ssh -N -L <local>:127.0.0.1:<remote>`를 자식으로 돌리며, 죽으면 재연결하고
             앱이 비정상 종료해 남은 고아 터널은 다음 부팅에 회수한다.
             아픽스 서버(중앙 대화 PG) 1차 — Task 6~7.

             [WHY Tailscale이 아니라 SSH 터널인가] 아픽스 서버를 세운 목적 자체가 제3자
             서비스 의존을 줄이는 것이다. SSH는 이미 쓰는 수단이라 새 의존이 0이고,
             서버 PG는 listen_addresses=127.0.0.1인 채로 둘 수 있어 공인망 노출이 없다.

             [불변식] 중앙 설정이 없으면 이 데몬은 아무것도 하지 않는다. 터널 실패는
             앱의 실패가 아니다 — 로컬 기능은 전부 그대로 돌아야 한다.

REVISION HISTORY:
- 2026-08-08 Claude: 신규. 좀비 방지(런타임 파일 + 명령줄 검증)와 포트 재사용을 함께 설계.
"""
import json
import os
import socket
import subprocess
import sys
import threading
import time
from pathlib import Path

from infra import proc  # [표준] 콘솔 숨김 래퍼 — 인라인 CREATE_NO_WINDOW 금지

# 재연결 백오프. 서버가 오래 죽어 있어도 로그와 CPU를 낭비하지 않도록 상한을 둔다.
_BACKOFF_START = 5
_BACKOFF_MAX = 300
_HEALTH_INTERVAL = 20          # 터널 생존 확인 주기(초)
_PORT_PROBE_TIMEOUT = 1.5

_stop_event = threading.Event()
_state_lock = threading.Lock()


# ── 런타임 상태 파일 ─────────────────────────────────────────────────────────
# [WHY 파일에 남기는가] 앱이 비정상 종료하면 자식 ssh는 고아로 살아남는다(Windows는
#   부모가 죽어도 자식을 정리하지 않는다). 다음 부팅이 회수하려면 'PID + 무엇이었는지'가
#   디스크에 있어야 한다.
# [과거사고 v3.7.244] 좀비 node PTY가 _MEI 폴더를 잠가 업데이트 후 앱이 아예 안 켜졌다.
#   터널로 같은 사고를 반복하지 않으려면 정리는 선택이 아니라 부팅 필수 단계다.
def _runtime_file(data_dir: Path) -> Path:
    return Path(data_dir) / 'central_tunnel.json'


def _read_state(data_dir: Path) -> dict:
    try:
        return json.loads(_runtime_file(data_dir).read_text(encoding='utf-8'))
    except Exception:
        return {}


def _write_state(data_dir: Path, state: dict) -> None:
    path = _runtime_file(data_dir)
    tmp = path.with_suffix('.json.tmp')
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        tmp.write_text(json.dumps(state, ensure_ascii=False, indent=2), encoding='utf-8')
        os.replace(tmp, path)
    except Exception:
        try:
            tmp.unlink()
        except Exception:
            pass


def _clear_state(data_dir: Path) -> None:
    try:
        _runtime_file(data_dir).unlink()
    except Exception:
        pass


# ── 프로세스 조회 (psutil 없이) ──────────────────────────────────────────────
def _process_cmdline(pid: int) -> str:
    """PID의 명령줄을 반환한다. 없으면 ''.

    [WHY 명령줄까지 보는가] PID는 재사용된다. 런타임 파일의 PID만 믿고 kill하면
      그 사이 그 번호를 물려받은 **무관한 프로세스**를 죽인다. 명령줄에 우리 터널의
      흔적(-L 포워딩 + 대상 호스트)이 있어야만 우리 것으로 인정한다.
    [제약] psutil이 없는 환경이라 플랫폼별 외부 명령에 의존한다. 실패 시 ''를 돌려
      '우리 것이 아님'으로 보수적 판정 — 남의 프로세스를 죽이는 것보다 고아를 남기는 게 낫다.
    """
    try:
        if sys.platform == 'win32':
            res = proc.run(
                ['wmic', 'process', 'where', f'ProcessId={int(pid)}',
                 'get', 'CommandLine', '/FORMAT:LIST'],
                capture_output=True, text=True, encoding='utf-8',
                errors='replace', timeout=5,
            )
            for line in (res.stdout or '').splitlines():
                line = line.strip()
                if line.startswith('CommandLine='):
                    return line[len('CommandLine='):]
            return ''
        res = proc.run(['ps', '-p', str(int(pid)), '-o', 'args='],
                       capture_output=True, text=True, timeout=5)
        return (res.stdout or '').strip()
    except Exception:
        return ''


def _kill(pid: int) -> bool:
    try:
        if sys.platform == 'win32':
            proc.run(['taskkill', '/F', '/PID', str(int(pid))],
                     capture_output=True, timeout=8)
        else:
            os.kill(int(pid), 9)
        return True
    except Exception:
        return False


# ── 터널 식별 / 포트 상태 ────────────────────────────────────────────────────
def _forward_spec(local_port: int, remote_port: int) -> str:
    return f'{local_port}:127.0.0.1:{remote_port}'


def _is_our_tunnel(pid: int, local_port: int, remote_port: int, ssh_host: str) -> bool:
    """이 PID가 정말 '우리가 띄운 그 터널'인지 명령줄로 확인한다."""
    if not pid:
        return False
    cmd = _process_cmdline(pid)
    if not cmd:
        return False
    return _forward_spec(local_port, remote_port) in cmd and ssh_host in cmd


def _port_is_open(port: int, host: str = '127.0.0.1') -> bool:
    """TCP 연결이 되는지만 본다(핸드셰이크 없음)."""
    try:
        with socket.create_connection((host, int(port)), timeout=_PORT_PROBE_TIMEOUT):
            return True
    except Exception:
        return False


def _port_speaks_postgres(port: int, host: str = '127.0.0.1') -> bool:
    """포트 너머가 실제로 PostgreSQL인지 확인한다.

    [WHY 단순 connect로 부족한가] 터널이 죽어도 로컬 리스너가 남아 connect만 성공하는
      상태가 생긴다. 또 그 포트를 전혀 다른 프로그램이 점유했을 수도 있다.
      SSLRequest(8바이트)를 보내면 PG는 'S'/'N' 한 바이트로 답한다 — 인증 이전 단계라
      자격증명 없이 정체를 확인할 수 있는 가장 싼 방법이다.
    """
    try:
        with socket.create_connection((host, int(port)), timeout=_PORT_PROBE_TIMEOUT) as s:
            s.settimeout(_PORT_PROBE_TIMEOUT)
            # length=8, code=80877103 (SSLRequest)
            s.sendall((8).to_bytes(4, 'big') + (80877103).to_bytes(4, 'big'))
            reply = s.recv(1)
            return reply in (b'S', b'N')
    except Exception:
        return False


# ── 설정 ─────────────────────────────────────────────────────────────────────
def get_tunnel_config(config_file=None) -> dict | None:
    """central_db.tunnel 설정을 정규화해 반환. 미설정/불완전하면 None.

    [WHY 터널이 선택적인가] 중앙 PG가 이미 도달 가능한 환경(같은 LAN, 별도 VPN,
      혹은 사람이 손으로 띄운 터널)에서는 이 데몬이 필요 없다. 그때는 central_db만
      설정하고 tunnel은 비워두면 된다 — 데몬은 조용히 잠든다.
    """
    try:
        from src.pg_central import get_central_config
    except Exception:
        return None

    central = get_central_config(config_file)
    if not central:
        return None

    raw = central.get('tunnel')
    if not isinstance(raw, dict):
        return None

    ssh_host = str(raw.get('ssh_host') or '').strip()
    if not ssh_host:
        return None

    return {
        'ssh_host': ssh_host,
        'ssh_user': str(raw.get('ssh_user') or 'root').strip(),
        'key': os.path.expanduser(str(raw.get('key') or '').strip()),
        'remote_port': int(raw.get('remote_port') or 5432),
        # 로컬 포트는 central_db.port를 그대로 쓴다 — 그래야 pg_central이 별도 조회 없이 붙는다.
        'local_port': int(central['port']),
    }


# ── 고아 회수 ────────────────────────────────────────────────────────────────
def cleanup_orphan_tunnel(data_dir: Path, cfg: dict | None = None) -> int:
    """부팅 시 1회 — 이전 실행이 남긴 고아 터널을 회수한다. 회수한 개수를 반환.

    [🔴 자기 것만 죽인다] pty_process.kill_orphan_pty_servers와 같은 원칙이다.
      명령줄이 우리 포워딩 규격과 일치할 때만 kill한다. 다른 인스턴스/사용자의 ssh를
      죽이면 그쪽 작업이 통째로 끊긴다(v3.7.122에서 실제로 겪은 사고 유형).
    [WHY 살아있는데도 죽이나] 이 함수는 '재사용'을 판단하지 않는다. 재사용 여부는
      ensure_tunnel이 포트 상태로 결정하고, 여기서는 **상태 파일에 적힌 이전 PID**만
      다룬다. 부팅 시점에 그 PID가 살아있다면 그것은 지난 세션의 잔재다.
    """
    state = _read_state(data_dir)
    pid = int(state.get('pid') or 0)
    if not pid:
        return 0

    local_port = int(state.get('local_port') or 0)
    remote_port = int(state.get('remote_port') or 0)
    ssh_host = str(state.get('ssh_host') or '')

    if not _is_our_tunnel(pid, local_port, remote_port, ssh_host):
        # 이미 죽었거나 PID가 재사용됐다 — 파일만 정리하고 아무도 건드리지 않는다.
        _clear_state(data_dir)
        return 0

    ok = _kill(pid)
    print(f'[tunnel] 고아 터널 회수 pid={pid} port={local_port} → {"ok" if ok else "실패"}')
    _clear_state(data_dir)
    return 1 if ok else 0


# ── 기동 ─────────────────────────────────────────────────────────────────────
def _build_ssh_cmd(cfg: dict) -> list:
    """[제약] BatchMode=yes — 비밀번호 프롬프트가 뜨면 데몬이 영원히 멈춘다(윈도우 모드라
        입력할 콘솔도 없다). 키 인증만 허용한다.
       [제약] ExitOnForwardFailure=yes — 포워딩이 실패했는데 ssh가 살아있으면 '터널이 있다'고
        착각하게 된다. 실패하면 즉시 죽어야 재연결 루프가 알아챈다.
       [제약] ServerAliveInterval — 절전/네트워크 단절로 죽은 소켓을 감지하는 유일한 수단.
        없으면 ssh가 established인 채로 영원히 매달린다(pg_base가 같은 이유로 keepalive를 건다).
    """
    cmd = ['ssh', '-N',
           '-o', 'BatchMode=yes',
           '-o', 'ExitOnForwardFailure=yes',
           '-o', 'StrictHostKeyChecking=accept-new',
           '-o', 'ServerAliveInterval=30',
           '-o', 'ServerAliveCountMax=3',
           '-L', _forward_spec(cfg['local_port'], cfg['remote_port'])]
    if cfg.get('key'):
        cmd += ['-i', cfg['key']]
    cmd.append(f"{cfg['ssh_user']}@{cfg['ssh_host']}")
    return cmd


def ensure_tunnel(data_dir: Path, cfg: dict):
    """터널이 필요하면 띄우고, 이미 통하면 그대로 둔다. Popen 또는 None.

    [🔴 PC당 1개 공유] 로컬 포트에서 PostgreSQL이 응답하면 **누가 띄웠든** 목적은 달성된
      것이므로 새로 띄우지 않는다. 개발본과 설치본이 동시에 도는 환경(멀티 인스턴스)에서
      각자 터널을 띄우면 뒤에 온 쪽이 포트 충돌로 조용히 실패한다 — 그 상태가 제일 나쁘다
      ('설정은 했는데 왜 안 되지'). 포트를 공유 자원으로 보는 편이 단순하고 안전하다.
    """
    if _port_speaks_postgres(cfg['local_port']):
        return None

    if _port_is_open(cfg['local_port']):
        # 포트는 열려 있는데 PG가 아니다 — 남의 프로그램이다. 절대 죽이지 않는다.
        print(f"[tunnel] 로컬 포트 {cfg['local_port']}를 다른 프로그램이 쓰고 있다 — "
              f"central_db.port를 비어 있는 값으로 바꿔야 한다")
        return None

    cmd = _build_ssh_cmd(cfg)
    try:
        p = proc.popen(cmd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    except Exception as exc:
        print(f'[tunnel] ssh 기동 실패: {exc}')
        return None

    with _state_lock:
        _write_state(data_dir, {
            'pid': p.pid,
            'local_port': cfg['local_port'],
            'remote_port': cfg['remote_port'],
            'ssh_host': cfg['ssh_host'],
            'started_at': time.time(),
        })

    # 포워딩이 실제로 열릴 때까지 잠깐 기다린다(ExitOnForwardFailure 덕에 실패는 즉사로 나타난다).
    for _ in range(20):
        if p.poll() is not None:
            print('[tunnel] ssh가 즉시 종료됨 — 키/permitopen/호스트 설정 확인 필요')
            _clear_state(data_dir)
            return None
        if _port_speaks_postgres(cfg['local_port']):
            print(f"[tunnel] 연결됨 pid={p.pid} 127.0.0.1:{cfg['local_port']} "
                  f"→ {cfg['ssh_host']}:{cfg['remote_port']}")
            return p
        time.sleep(0.5)

    print('[tunnel] 포워딩이 열리지 않았다 — 회수')
    _kill(p.pid)
    _clear_state(data_dir)
    return None


def stop_tunnel(data_dir: Path) -> None:
    """앱 종료 경로에서 호출 — 우리가 띄운 터널을 정리한다.

    [제약] 정상 종료에서만 불린다. 비정상 종료는 다음 부팅의 cleanup_orphan_tunnel이 맡는다.
    """
    _stop_event.set()
    state = _read_state(data_dir)
    pid = int(state.get('pid') or 0)
    if pid and _is_our_tunnel(pid, int(state.get('local_port') or 0),
                              int(state.get('remote_port') or 0),
                              str(state.get('ssh_host') or '')):
        _kill(pid)
    _clear_state(data_dir)


# ── 데몬 루프 ────────────────────────────────────────────────────────────────
def run_tunnel_daemon(env) -> None:
    """중앙 터널 유지 루프. start_all_daemons에서 스레드로 기동한다.

    [불변식] 설정이 없으면 즉시 반환한다 — 중앙을 쓰지 않는 사용자에게 스레드조차 남기지 않는다.
    [제약] 이 함수는 예외를 밖으로 내보내지 않는다. 데몬 스레드에서 터지면 앱 전체가
      아니라 이 기능만 죽어야 한다.
    """
    try:
        data_dir = Path(getattr(env, 'data_dir', None) or Path.cwd())
        config_file = getattr(env, 'config_file', None)

        cfg = get_tunnel_config(config_file)
        if not cfg:
            return   # 중앙 미설정 또는 터널 불필요 — 조용히 잠든다

        cleanup_orphan_tunnel(data_dir, cfg)

        backoff = _BACKOFF_START
        child = None
        while not _stop_event.is_set():
            try:
                # 설정은 매 순회 다시 읽는다 — 사용자가 껐다면 즉시 물러나야 한다.
                cfg = get_tunnel_config(config_file)
                if not cfg:
                    if child is not None:
                        stop_tunnel(data_dir)
                        child = None
                    return

                if child is not None and child.poll() is not None:
                    print('[tunnel] ssh 종료 감지 — 재연결')
                    child = None

                if not _port_speaks_postgres(cfg['local_port']):
                    child = ensure_tunnel(data_dir, cfg)
                    if child is None and not _port_speaks_postgres(cfg['local_port']):
                        # 실패 — 백오프. 서버가 꺼져 있는 것은 정상 상태이므로 조용히 기다린다.
                        _stop_event.wait(backoff)
                        backoff = min(backoff * 2, _BACKOFF_MAX)
                        continue

                backoff = _BACKOFF_START
                _stop_event.wait(_HEALTH_INTERVAL)
            except Exception as exc:
                print(f'[tunnel] 루프 오류(무시): {exc}')
                _stop_event.wait(backoff)
                backoff = min(backoff * 2, _BACKOFF_MAX)
    except Exception as exc:
        print(f'[tunnel] 데몬 시작 실패(무시): {exc}')
