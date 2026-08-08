#!/usr/bin/env python3
"""
FILE: scripts/apix_push.py
DESCRIPTION: 이 PC 의 상태를 아픽스 콘솔로 밀어 올린다. 5분 주기 실행을 전제한다.

             [🔴 불변식 — 실패해도 로컬에 영향 0]
             서버가 꺼져 있든 토큰이 틀렸든, 이 스크립트는 조용히 끝난다.
             관제는 부가 기능이지 앱의 필수 경로가 아니다. 여기서 예외를 올리면
             호출한 데몬이 죽고, 관제를 붙였다가 오히려 앱을 불안정하게 만든다.

             [WHY 토큰을 config.json 에 두지 않나] config.json 은 git 에 추적된다.
             토큰을 넣으면 커밋 한 번으로 유출된다. 홈 디렉터리(~/.apix/token)에
             두면 저장소와 완전히 분리되고 다른 PC 에 그대로 옮길 수 있다.

             설정:
               ~/.apix/token   또는 환경변수 APIX_TOKEN   (노드별 개별 토큰)
               ~/.apix/url     또는 환경변수 APIX_URL     (기본: 아래 DEFAULT_URL)

REVISION HISTORY:
- 2026-08-08 Claude: 최초 작성 — 하트비트부터.
"""
from __future__ import annotations

import json
import os
import platform
import socket
import sys
import urllib.error
import urllib.request
from pathlib import Path

DEFAULT_URL = 'https://admin.btsky.pe.kr'
TIMEOUT = 8
CONF_DIR = Path.home() / '.apix'


def _read(name: str, env: str, default: str = '') -> str:
    v = os.environ.get(env, '').strip()
    if v:
        return v
    f = CONF_DIR / name
    try:
        return f.read_text(encoding='utf-8').strip()
    except Exception:                                  # noqa: BLE001
        return default


def _app_version() -> str:
    """[제약] 개발 모드와 설치본 모두에서 동작해야 한다. import 대신 파일을 읽는
    이유 — 이 스크립트는 vibe-coding 패키지 밖에서도 단독 실행된다."""
    try:
        p = Path(__file__).resolve().parent.parent / '.ai_monitor' / '_version.py'
        for line in p.read_text(encoding='utf-8').splitlines():
            if line.strip().startswith('__version__'):
                return line.split('=', 1)[1].strip().strip('\'"')
    except Exception:                                  # noqa: BLE001
        pass
    return ''


def _mem_pct() -> float | None:
    """[WHY stdlib 로 직접 재나] psutil 은 이 프로젝트의 정식 의존성이 아니다
    (번들 pgAdmin 안에만 있다). 관제를 붙이자고 노드마다 새 패키지를 깔면
    '다른 PC 에서도 그냥 돈다'는 전제가 깨진다."""
    if sys.platform == 'win32':
        import ctypes

        class MEMSTAT(ctypes.Structure):
            _fields_ = [('dwLength', ctypes.c_ulong), ('dwMemoryLoad', ctypes.c_ulong),
                        ('ullTotalPhys', ctypes.c_ulonglong), ('ullAvailPhys', ctypes.c_ulonglong),
                        ('ullTotalPageFile', ctypes.c_ulonglong), ('ullAvailPageFile', ctypes.c_ulonglong),
                        ('ullTotalVirtual', ctypes.c_ulonglong), ('ullAvailVirtual', ctypes.c_ulonglong),
                        ('ullAvailExtendedVirtual', ctypes.c_ulonglong)]

        m = MEMSTAT()
        m.dwLength = ctypes.sizeof(MEMSTAT)
        if ctypes.windll.kernel32.GlobalMemoryStatusEx(ctypes.byref(m)):
            return float(m.dwMemoryLoad)
        return None
    try:
        info = {}
        with open('/proc/meminfo', encoding='utf-8') as f:
            for line in f:
                k, _, v = line.partition(':')
                info[k.strip()] = int(v.split()[0])
        total, avail = info['MemTotal'], info['MemAvailable']
        return round((total - avail) / total * 100, 1)
    except Exception:                                  # noqa: BLE001
        return None


def _cpu_pct() -> float | None:
    """두 번 샘플링해 그 사이의 사용률을 낸다.

    [제약] 0.5초 블로킹한다. 5분 주기 실행이라 무시할 만한 비용이지만,
      이 함수를 UI 경로에서 부르면 안 된다.
    """
    try:
        if sys.platform == 'win32':
            import ctypes
            import time

            class FT(ctypes.Structure):
                _fields_ = [('lo', ctypes.c_ulong), ('hi', ctypes.c_ulong)]

            def snap():
                idle, kern, user = FT(), FT(), FT()
                ctypes.windll.kernel32.GetSystemTimes(
                    ctypes.byref(idle), ctypes.byref(kern), ctypes.byref(user))
                q = lambda f: (f.hi << 32) | f.lo          # noqa: E731
                # [함정] kernel 시간에는 idle 이 **포함**돼 있다. 빼지 않으면
                #   사용률이 항상 낮게 나와 '한가한 PC'로 보인다.
                return q(idle), q(kern) + q(user)

            i0, t0 = snap()
            time.sleep(0.5)
            i1, t1 = snap()
            dt, di = t1 - t0, i1 - i0
            return round((dt - di) / dt * 100, 1) if dt > 0 else None

        import time

        def snap():
            with open('/proc/stat', encoding='utf-8') as f:
                v = [int(x) for x in f.readline().split()[1:]]
            return v[3], sum(v)                            # idle, total

        i0, t0 = snap()
        time.sleep(0.5)
        i1, t1 = snap()
        dt, di = t1 - t0, i1 - i0
        return round((dt - di) / dt * 100, 1) if dt > 0 else None
    except Exception:                                      # noqa: BLE001
        return None


def _resources() -> dict:
    """[불변식] 못 잰 값은 **넣지 않는다**. 0 으로 채우면 화면이 '한가한 PC'라고
    거짓말한다 — 값 없음과 값 0 은 다른 사건이다."""
    import shutil

    out: dict = {}
    cpu = _cpu_pct()
    if cpu is not None:
        out['cpu_pct'] = cpu
    mem = _mem_pct()
    if mem is not None:
        out['mem_pct'] = mem
    try:
        du = shutil.disk_usage(os.path.abspath(os.sep))
        out['disk_pct'] = round(du.used / du.total * 100, 1)
    except Exception:                                      # noqa: BLE001
        pass
    return out


def _projects() -> list[str]:
    try:
        p = Path(__file__).resolve().parent.parent / '.ai_monitor' / 'config.json'
        cfg = json.loads(p.read_text(encoding='utf-8'))
        return [str(x) for x in (cfg.get('projects') or [])][:20]
    except Exception:                                  # noqa: BLE001
        return []


def payload() -> dict:
    d = {
        'host': socket.gethostname(),
        'platform': f'{platform.system()} {platform.release()}',
        'app_version': _app_version(),
        'projects': _projects(),
    }
    d.update(_resources())
    return d


def post(kind: str, body: dict) -> tuple[bool, str]:
    token = _read('token', 'APIX_TOKEN')
    if not token:
        return False, 'no_token'
    url = (_read('url', 'APIX_URL', DEFAULT_URL)).rstrip('/') + f'/ingest/{kind}'

    data = json.dumps(body, ensure_ascii=False).encode('utf-8')
    req = urllib.request.Request(url, data=data, method='POST', headers={
        'Authorization': f'Bearer {token}',
        'Content-Type': 'application/json; charset=utf-8',
    })
    try:
        with urllib.request.urlopen(req, timeout=TIMEOUT) as r:
            return (200 <= r.status < 300), f'http_{r.status}'
    except urllib.error.HTTPError as e:
        return False, f'http_{e.code}'
    except Exception as e:                             # noqa: BLE001
        return False, type(e).__name__


def main() -> int:
    ok, why = post('heartbeat', payload())
    # [WHY 실패해도 0 을 반환하나] 스케줄러가 실패를 재시도·경보로 확대하면
    #   서버가 잠깐 꺼진 것만으로 로컬에 소음이 쌓인다. 결과는 한 줄로만 남긴다.
    print(f'[apix] heartbeat {"ok" if ok else "skip"} ({why})')
    return 0


if __name__ == '__main__':
    sys.exit(main())
