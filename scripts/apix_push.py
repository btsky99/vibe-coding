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
               ~/.apix/cursor.json — 마지막으로 **서버가 받아준** 지점 (자동 생성)

REVISION HISTORY:
- 2026-08-09 Claude: Task 14 — 태스크·커밋·체크포인트·사고 증분 전송 + 커서 배선.
- 2026-08-08 Claude: 최초 작성 — 하트비트부터.
"""
from __future__ import annotations

import json
import os
import platform
import re
import socket
import sys
import urllib.error
import urllib.request
from pathlib import Path

# [WHY apex 인가] `admin` 은 계획상 은퇴 대상(→ apex 301)이다. 301 을 만나면 urllib 은
#   기본적으로 POST 를 GET 으로 바꿔 따라가므로, 인제스트가 **본문 없이** 재요청되어
#   조용히 사라진다. 영구 주소로 직접 쏘고, 그래도 3xx 가 오면 아래 _NoRedirect 가
#   에러로 바꿔 로그에 드러나게 한다.
DEFAULT_URL = 'https://btsky.pe.kr'
TIMEOUT = 8
CONF_DIR = Path.home() / '.apix'
CURSOR_PATH = CONF_DIR / 'cursor.json'

# 서버(collector/app.py)의 MAX_BODY 는 256KB, nginx client_max_body_size 도 256k.
# 그 아래로 잘라 보낸다 — 넘으면 413 이고, 413 은 재시도해도 영원히 413 이다.
CHUNK_BYTES = 200 * 1024


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
    이유 — 이 스크립트는 vibe-coding 패키지 밖에서도 단독 실행된다.

    [🔴 후보를 여러 개 보는 이유 — 두 레이아웃의 상대 경로가 다르다]
      개발:   <repo>/scripts/apix_push.py       → <repo>/.ai_monitor/_version.py
      설치본: _internal/scripts/apix_push.py    → _internal/_version.py
      (.ai_monitor 패키지가 _internal 루트로 펼쳐지므로 중간 폴더가 사라진다)
      개발 경로만 보던 초판은 설치본에서 조용히 ''를 돌려줬고, 그 값이 관제 하트비트의
      app_version 으로 올라갔다. 2026-08-11 na2js 진단 때 '이 노드가 새 코드를 쓰는가'를
      원격에서 판정할 수 없어 막힌 지점이 정확히 여기다 — 버전이 안 보이면 노드가
      침묵할 때 '설정 문제'와 '구버전 문제'를 가를 수 없다.
    [제약] 실패해도 ''를 돌려준다 — 버전을 못 읽는 것이 하트비트 전체를 막으면 안 된다.
    """
    here = Path(__file__).resolve().parent
    for p in (here.parent / '.ai_monitor' / '_version.py',   # 개발 레이아웃
              here.parent / '_version.py',                   # 설치본(_internal) 레이아웃
              here / '_version.py'):
        try:
            for line in p.read_text(encoding='utf-8').splitlines():
                if line.strip().startswith('__version__'):
                    return line.split('=', 1)[1].strip().strip('\'"')
        except Exception:                              # noqa: BLE001
            continue
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


def _tunnel_identity() -> dict:
    """이 PC 의 역터널 이름·포트. 역터널 노드가 아니면 빈 dict.

    [WHY 이 값을 하트비트에 싣는가] 관제(하트비트)와 접속(역터널)은 별개 계통이라
      상태판이 "이 하트비트가 어느 ssh 별칭의 것인가"를 맞출 키가 없었다. 라벨은
      사람이 자유롭게 적는 값이라(`개발 PC (Windows)`) ssh 별칭(`cipher`)과 안 맞는다.
      역터널 포트는 **양쪽이 같은 값을 아는 유일한 식별자**다 — 관리하는 쪽 ssh config 의
      `Port` 와 노드 쪽 `-R <포트>:localhost:22` 가 같은 숫자다.
    [제약] Setup-RemoteNode.ps1 이 만든 래퍼(`tunnel-<이름>.cmd`)에서 읽는다. 그 스크립트가
      래퍼 형식을 바꾸면 여기도 같이 고쳐야 한다 — 어긋나면 조용히 빈 값이 되고,
      증상은 상태판의 '생존 미확인'뿐이라 원인이 드러나지 않는다.

    [🔴 래퍼가 둘 이상이면 이름을 고르지 않는다 — 진단이 두 번 오염된 지점]
      옛 구현은 `sorted(glob(...))` 의 **첫 파일**을 말없이 채택했다. 알파벳 순이라
      다른 PC 것을 복사해 온 래퍼가 남아 있으면 그쪽이 이긴다(`cipher` < `na2js`).
      그 결과 na2js 가 자기를 'cipher/22001' 이라고 보고했고, 상태판·진단이 두 번
      엉뚱한 PC 를 가리켰다(2026-08-11). **틀린 식별자는 없는 것보다 나쁘다** —
      없으면 '모른다'로 보이지만, 틀리면 '안다'고 믿고 엉뚱한 곳을 파게 된다.
      그래서 모호하면 이름·포트를 비우고 후보 목록만 실어 보낸다. 화면이 충돌을
      볼 수 있어야 사람이 지울 래퍼를 고를 수 있다.
    """
    base = os.environ.get('LOCALAPPDATA') or ''
    roots = [Path(base) / 'vibe-remote'] if base else []
    roots.append(Path.home() / '.vibe-remote')      # 맥/리눅스 노드

    found: list[dict] = []
    seen: set[str] = set()
    for root in roots:
        try:
            for f in sorted(root.glob('tunnel-*.cmd')):
                text = f.read_text(encoding='utf-8', errors='replace')
                m = re.search(r'-R\s+(\d+):', text)
                if not m:
                    continue
                name = f.stem[len('tunnel-'):]
                if name in seen:
                    continue    # 두 루트에 같은 이름 — 같은 노드의 중복이지 충돌이 아니다
                seen.add(name)
                found.append({'node_name': name, 'tunnel_port': int(m.group(1))})
        except OSError:
            continue

    if len(found) == 1:
        return found[0]
    if not found:
        return {}
    return {'tunnel_conflict': found}


def payload() -> dict:
    d = {
        'host': socket.gethostname(),
        'platform': f'{platform.system()} {platform.release()}',
        'app_version': _app_version(),
        'projects': _projects(),
    }
    d.update(_tunnel_identity())
    d.update(_resources())
    return d


class _NoRedirect(urllib.request.HTTPRedirectHandler):
    """[🔴 왜 리다이렉트를 막나] 기본 동작은 301/302 를 만나면 POST 를 GET 으로 바꿔
    따라간다. 그러면 본문(태스크·이벤트)이 통째로 버려진 채 요청이 '성공'할 수도 있고,
    실패해도 원인이 'http_404'로만 보여 도메인 이전 때문이라는 걸 알 수 없다.
    따라가지 않으면 urllib 이 HTTPError 를 올려 `http_301` 로 정확히 남는다."""

    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


_OPENER = urllib.request.build_opener(_NoRedirect)


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
        with _OPENER.open(req, timeout=TIMEOUT) as r:
            return (200 <= r.status < 300), f'http_{r.status}'
    except urllib.error.HTTPError as e:
        return False, f'http_{e.code}'
    except Exception as e:                             # noqa: BLE001
        return False, type(e).__name__


# ── 커서 (Task 14) ──────────────────────────────────────────────────────────
# [🔴 불변식] 커서는 **서버가 202 로 받아준 지점**만 기록한다. 조회 직후에 전진시키면,
#   전송이 실패한 구간이 영영 다시 조회되지 않아 그 사이의 태스크·사고가 사라진다.
#   반대로 실패 시 다시 보내는 중복은 서버가 흡수한다 —
#   태스크는 (node_id, external_id) UPSERT, 이벤트는 dedup_key ON CONFLICT DO NOTHING.
#   즉 이 방향의 오차는 '중복'(무해)이고, 반대 방향은 '유실'(복구 불가)이다.

def _load_cursor() -> dict:
    try:
        d = json.loads(CURSOR_PATH.read_text(encoding='utf-8'))
        return d if isinstance(d, dict) else {}
    except Exception:                                  # noqa: BLE001
        return {}


def _save_cursor(data: dict) -> None:
    """[제약] 5분마다 덮어쓴다 — 쓰다가 죽으면 커서가 깨져 전량 재전송이 된다.
    임시 파일 + os.replace 로 원자 교체한다(같은 볼륨이라 replace 가 원자적)."""
    try:
        CONF_DIR.mkdir(parents=True, exist_ok=True)
        tmp = CURSOR_PATH.with_suffix('.tmp')
        tmp.write_text(json.dumps(data, ensure_ascii=False, indent=1), encoding='utf-8')
        os.replace(tmp, CURSOR_PATH)
    except Exception:                                  # noqa: BLE001
        pass


def _batches(items: list) -> list[list]:
    """직렬화 크기 기준으로 나눈다 — 건수 기준으로 자르면 사고 본문(최대 4000자)이
    섞였을 때 같은 건수라도 크기가 10배씩 차이 나 413 을 못 막는다."""
    out: list[list] = []
    cur: list = []
    size = 0
    for it in items:
        n = len(json.dumps(it, ensure_ascii=False).encode('utf-8')) + 1
        if cur and size + n > CHUNK_BYTES:
            out.append(cur)
            cur, size = [], 0
        cur.append(it)
        size += n
    if cur:
        out.append(cur)
    return out


def _post_all(kind: str, key: str, items: list) -> bool:
    """전부 성공해야 True. 일부만 들어간 채 True 를 주면 커서가 전진해 나머지가 유실된다."""
    for chunk in _batches(items):
        ok, why = post(kind, {key: chunk})
        if not ok:
            print(f'[apix] {kind} 전송 실패 ({why}) — 커서 유지, 다음 주기 재시도')
            return False
    return True


def push_work() -> str:
    """프로젝트별 증분(태스크·커밋·체크포인트·사고)을 콘솔로 올린다.

    [WHY 프로젝트마다 따로 쏘나] 한 요청에 몰면 (a) 20개 프로젝트 부트스트랩이 256KB
      상한을 넘고, (b) 한 프로젝트의 실패가 전체 커서를 묶어 멀쩡한 프로젝트까지
      같은 데이터를 계속 재전송한다. 프로젝트는 서로 독립이므로 실패도 독립이어야 한다.
    [WHY 세 이벤트를 한 요청에 합치나] 커밋·체크포인트·사고는 커서가 각각이지만
      전송 실패의 원인(서버 다운·토큰 만료)은 공통이다. 나눠 쏘면 요청만 3배가 된다.
      한 요청이 성공하면 세 커서를 함께 전진시킨다.
    """
    sys.path.insert(0, str(Path(__file__).resolve().parent))
    try:
        import apix_sources as src
        projects = src.discover()
    except Exception as e:                             # noqa: BLE001
        return f'수집 불가({type(e).__name__})'

    cursor = _load_cursor()
    n_task = n_event = n_fail = 0
    dirty = False

    for proj in projects:
        c = dict(cursor.get(proj['key']) or {})

        try:
            tasks, t_next = src.tasks(proj, c.get('tasks', ''))
        except Exception:                              # noqa: BLE001
            tasks, t_next = [], ''
        if tasks:
            if _post_all('tasks', 'tasks', tasks):
                c['tasks'] = t_next
                n_task += len(tasks)
                dirty = True
            else:
                n_fail += 1

        try:
            commits, sha = src.commit_events(proj, c.get('commit', ''))
            ckpts, ck = src.checkpoint_events(proj, c.get('ckpt', ''))
            incidents, iid = src.incident_events(proj, c.get('incident', 0))
        except Exception:                              # noqa: BLE001
            commits = ckpts = incidents = []
            sha, ck, iid = c.get('commit', ''), c.get('ckpt', ''), c.get('incident', 0)

        events = commits + ckpts + incidents
        if events:
            if _post_all('events', 'events', events):
                c.update({'commit': sha, 'ckpt': ck, 'incident': iid})
                n_event += len(events)
                dirty = True
            else:
                n_fail += 1

        if c:
            cursor[proj['key']] = c

    if dirty:
        _save_cursor(cursor)
    return f'프로젝트 {len(projects)} · 태스크 {n_task} · 이벤트 {n_event} · 실패 {n_fail}'


def main() -> int:
    ok, why = post('heartbeat', payload())
    # [WHY 실패해도 0 을 반환하나] 스케줄러가 실패를 재시도·경보로 확대하면
    #   서버가 잠깐 꺼진 것만으로 로컬에 소음이 쌓인다. 결과는 한 줄로만 남긴다.
    print(f'[apix] heartbeat {"ok" if ok else "skip"} ({why})')

    # [WHY 하트비트 성공을 전제로 하나] 작업 수집은 로컬 PG 접속 4회 + git 호출 수십 회다.
    #   토큰이 없거나 서버가 죽은 노드에서 그 비용을 5분마다 태우는 건 순손실이고,
    #   하트비트가 그 판정을 이미 끝냈다. 서버가 돌아오면 커서 덕에 밀린 만큼 따라잡는다.
    if ok:
        print(f'[apix] work {push_work()}')
    return 0


if __name__ == '__main__':
    sys.exit(main())
