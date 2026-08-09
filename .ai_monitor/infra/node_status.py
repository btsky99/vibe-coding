"""
FILE: infra/node_status.py
DESCRIPTION: 원격 노드의 두 가지 사실을 아픽스 서버에서 한 번에 조회 + CLI(claude/codex) 설치 점검.
  ① 살아 있는가 — 하트비트(관제 PG apix_nodes.last_seen_at). 노드가 HTTPS로 올려보낸 신호.
  ② 조종할 수 있는가 — 역터널(서버 루프백 LISTEN). 내가 그 노드에 ssh로 들어갈 수 있는 통로.
  상태판 창과 tui.py가 이 값을 쓴다.

[🔴 ①과 ②를 한 값으로 합치지 말 것 — 이 파일의 존재 이유]
  둘은 서로 **다른 질문**에 답한다. 합쳐서 "온라인/오프라인" 하나로 그리면 장애 원인을
  구분할 수 없게 된다.

    하트비트 O + 터널 X → 노드는 멀쩡한데 조종만 불가. 할 일 = 터널 재기동.
    하트비트 X + 터널 O → 터널만 살고 앱이 죽음.       할 일 = 앱 재시작.

  두 경우의 조치가 정반대인데 화면이 똑같이 '오프라인'이면 매번 헛발질한다.
  ([[feedback_observability_first]] — 값 없음과 값 낡음을 같은 색으로 그리지 않는다.)

[WHY 관제 데이터는 하트비트가 정본인가]
  계획서(ai_monitor_plan.md) 설계 고정 사항: **관제 전송은 HTTPS 인제스트**, 터널을 쓰지
  않는다. 터널은 노드마다 상주 데몬 + 좀비 정리가 필요해 약한 노드에서 먼저 무너진다.
  따라서 '살아 있는가'의 정본은 언제나 하트비트다. 터널은 조종 가능 여부일 뿐이다.

[WHY 제3자 메시 VPN을 쓰지 않는가]
  아픽스 서버를 세운 목적 자체가 제3자 서비스 의존을 만들지 않는 것이다. 노드 생존은
  내 서버가 받은 하트비트로, 접속 통로는 내 서버의 역터널로 판정한다 — 둘 다 내 것이다.

[제약] 이 조회는 서버로의 SSH 왕복(1~수 초)이다. 로컬 명령이 아니므로 짧은 주기 폴링에
  올리지 말 것. 상태판은 사용자가 열었을 때/새로고침할 때만 부른다.

[제약] CLI 설치 점검은 노드마다 별도 SSH 왕복이라 더 느리다. 폴링에 절대 넣지 않는다 —
  사용자가 명시적으로 "점검" 했을 때만 실행하고 결과는 caller가 캐시한다.

REVISION HISTORY:
- 2026-08-02 Claude: 최초 작성 — 상태판 독립 창의 원격 노드 섹션.
- 2026-08-09 Claude: 제3자 메시 VPN 전면 폐기. 생존=하트비트 / 접속=역터널로 **분리** 조회.
                     (초판은 둘을 역터널 하나로 합쳤다가 설계 고정 사항 위반으로 되돌림.)
"""
from __future__ import annotations

import base64
import os
import re
import shutil
import socket
import sys

from infra import proc  # [표준] 콘솔 숨김 subprocess 래퍼 — 인라인 CREATE_NO_WINDOW 금지

# 아픽스 서버 ssh 별칭 후보. 순서대로 시도하고 처음 성공한 것을 기억한다.
# [WHY 하나로 못 박지 않는가] Register-RemoteNode.ps1은 'vibe-vps'를 써 넣지만, 그 스크립트가
#   생기기 전에 손으로 설정한 PC는 'apix'/'vps'/'vibe-seoul'을 쓴다. 하나만 보면 그런 PC에서
#   모든 노드가 영구 '알 수 없음'이 되고, 원인이 화면에 드러나지 않는다.
# [제약] 후보를 늘리면 최초 1회에 실패 타임아웃이 누적된다 — 자주 쓰는 것부터 앞에 둔다.
VPS_ALIAS_CANDIDATES = ('vibe-vps', 'apix', 'vps', 'vibe-seoul')
VPS_ALIAS = VPS_ALIAS_CANDIDATES[0]

# 성공한 별칭 기억. [제약] 프로세스 수명 동안만 — config가 바뀌면 재시작해야 반영된다.
_resolved_alias: str | None = None

# 역터널에 배정하는 포트 대역. 이 범위 밖 LISTEN은 노드 터널이 아니다
# (서버에는 nginx·hbbs 등 무관한 리스너가 여럿 있다).
_TUNNEL_PORT_MIN = 22000
_TUNNEL_PORT_MAX = 22099

# 하트비트가 이보다 오래되면 죽은 것으로 본다. 노드는 5분 주기로 보낸다(계획서 Task 12)
# → 3주기를 놓쳐야 사망 판정. 한 번 실패에 빨간불이 뜨면 사람이 경보를 무시하게 된다.
STALE_AFTER_SEC = 900

_LISTEN_RE = re.compile(r'(?:127\.0\.0\.1|\[::1\]):(\d+)')

# 관제 PG는 서버 루프백에만 열려 있다. 이 조회는 **서버 안에서** 실행된다(ssh 원격 명령).
# [WHY -tA 인가 — -F 를 안 쓴다] 비정렬 모드(-A)의 기본 구분자가 이미 '|' 다. -F'|' 를 쓰면
#   따옴표가 ssh→sh→su→psql 4겹을 통과하며 깨진다. 기본값에 기대면 그 문제가 사라진다.
#
# [WHY 식별자를 4개나 끌어오는가] 하트비트와 ssh config 를 이어붙일 공용 키가 원래 없었다.
#   label 은 사람이 자유롭게 적고('개발 PC (Windows)'), node_id 는 관제가 붙이고,
#   ssh 별칭은 관리하는 쪽이 정한다. 그래서 맞을 수 있는 후보를 전부 가져와 순서대로 댄다.
#   tunnel_port 가 유일하게 **양쪽이 같은 값을 아는** 정확한 키다(apix_push._tunnel_identity).
# [제약] 마지막 컬럼(나이)의 위치가 고정이다 — 파서가 뒤에서부터 읽는다. 컬럼을 추가하려면
#   나이 앞에 넣을 것.
_HB_SQL = ("SELECT coalesce(payload->>'tunnel_port',''), "
           "coalesce(payload->>'node_name',''), "
           "coalesce(payload->>'host',''), "
           "node_id, lower(label), "
           "EXTRACT(EPOCH FROM (now() - n.last_seen_at))::int "
           "FROM apix_nodes n LEFT JOIN LATERAL ("
           "  SELECT payload FROM apix_heartbeats h WHERE h.node_id = n.node_id"
           "   ORDER BY h.received_at DESC LIMIT 1) p ON true "
           "WHERE NOT n.revoked AND n.last_seen_at IS NOT NULL")

_HB_SQL_B64 = base64.b64encode(_HB_SQL.encode('utf-8')).decode('ascii')

# [WHY 구분자를 출력에 심는가] ss와 psql 출력을 한 SSH 왕복에 합쳐 받는다. 왕복을 둘로
#   나누면 상태판 열 때마다 접속이 2회라 체감이 두 배로 느려진다.
# [🔴 마커를 '#'로 시작하지 말 것] 원격 셸이 주석으로 먹어 `echo #X`가 빈 줄만 찍는다.
#   2026-08-09 실측: 그래서 출력이 통째로 비어 모든 노드가 조용히 '판정 불가'가 됐다.
#   ss/psql은 정상 동작 중이었으므로 원인이 전혀 드러나지 않는 형태였다.
_MARK_TUNNEL = '@@TUNNELS@@'
_MARK_HB = '@@HEARTBEATS@@'

_REMOTE_CMD = (
    f"echo '{_MARK_TUNNEL}'; ss -ltn 2>/dev/null; "
    f"echo '{_MARK_HB}'; "
    # [🔴 비밀번호를 쓰지 않는다] apix 계정은 scram 인증이라 DSN(비밀번호 포함)을 명령줄에
    #   올려야 하는데, 그러면 서버 프로세스 목록에 비밀번호가 잠시 뜬다. 대신 유닉스 소켓
    #   peer 인증으로 postgres 로 붙는다 — 비밀번호가 어디에도 등장하지 않는다.
    #   (자격증명을 흘린 전례: project_apix_central_db 사고 ①)
    # [🔴 SQL 을 base64 로 넘기는 이유] 이 문자열은 ssh→sh→su→psql 4겹을 통과한다.
    #   SQL 안의 작은따옴표(payload->>'host')가 su -c '...' 를 그대로 끊어버린다
    #   (2026-08-09 실측: 관제 DB 조회가 통째로 실패했는데 증상은 '읽음 False' 뿐이었다).
    #   base64 는 따옴표를 만들지 않으므로 인용 계층이 몇 겹이든 안전하다.
    # 실패해도 조용히 넘어가 '하트비트 알 수 없음'이 되게 둔다 — 터널 정보까지 잃으면 안 된다.
    f"echo {_HB_SQL_B64} | base64 -d | "
    "su postgres -c 'psql -p 5433 -d apix -tA -f -' 2>/dev/null; "
    # [🔴 반드시 0으로 끝낼 것] 마지막 psql이 실패하면 그 종료코드가 ssh의 반환값이 되어
    #   '서버 접속 실패'로 오판된다(2026-08-09 실측). 접속 성공 여부는 종료코드가 아니라
    #   아래 마커가 출력에 있는지로 판정한다 — 그래야 관제 DB만 죽은 상황과 구분된다.
    "true"
)


def _ssh_available() -> bool:
    return shutil.which('ssh') is not None


def _probe_once(alias: str, timeout: int) -> dict | None:
    """한 별칭으로 시도. 접속 자체가 안 되면 None(다음 후보로 넘어가라는 뜻)."""
    try:
        res = proc.run(
            ['ssh', '-o', f'ConnectTimeout={max(3, timeout - 5)}', '-o', 'BatchMode=yes',
             '-o', 'StrictHostKeyChecking=accept-new', alias, _REMOTE_CMD],
            capture_output=True, text=True, encoding='utf-8', errors='replace',
            timeout=timeout,
        )
    except Exception as e:
        return {'ok': False, 'error': str(e)}
    # 종료코드가 아니라 마커로 판정한다(_REMOTE_CMD 주석 참조).
    if _MARK_TUNNEL not in (res.stdout or ''):
        return {'ok': False,
                'error': (res.stderr or '').strip()[:200] or f'{alias} 접속 실패'}
    return {'ok': True, 'out': res.stdout or ''}


def server_probe(vps_alias: str = '', timeout: int = 15) -> dict:
    """아픽스 서버에 한 번 물어 역터널 + 하트비트를 함께 가져온다.

    vps_alias를 비우면 VPS_ALIAS_CANDIDATES를 순서대로 시도하고 성공한 것을 기억한다.

    반환: {
      'available': bool,              # 서버에 물어보는 데 성공했나
      'error': str,
      'tunnel_ports': set[int],       # 지금 살아 있는 역터널 포트
      'heartbeats': dict[str, int],   # 소문자 라벨 → 마지막 하트비트 나이(초)
      'heartbeat_available': bool,    # 관제 PG를 읽었나(psql 없거나 DB 다운이면 False)
    }

    [불변식] available=False는 '내가 서버에 못 물었다'는 뜻이지 '노드가 전부 죽었다'가
      아니다. 호출부는 이 둘을 같은 색으로 그리면 안 된다.
    """
    global _resolved_alias
    empty = {'available': False, 'error': '', 'tunnel_ports': set(),
             'heartbeats': {}, 'heartbeat_available': False, 'alias': ''}
    if not _ssh_available():
        return {**empty, 'error': 'ssh 실행파일 없음'}

    if vps_alias:
        candidates = (vps_alias,)
    elif _resolved_alias:
        candidates = (_resolved_alias,)
    else:
        candidates = VPS_ALIAS_CANDIDATES

    last_err = ''
    hit = None
    for alias in candidates:
        r = _probe_once(alias, timeout)
        if r and r.get('ok'):
            hit, _resolved_alias = r, alias
            break
        last_err = (r or {}).get('error') or last_err

    if hit is None:
        # 기억해둔 별칭이 죽었을 수 있다 → 다음 호출에서 전체 후보를 다시 훑게 만든다.
        _resolved_alias = None
        return {**empty, 'error': last_err or '아픽스 서버 접속 실패'}

    out = hit['out']
    tunnel_txt, _, hb_txt = out.partition(_MARK_HB)
    tunnel_txt = tunnel_txt.split(_MARK_TUNNEL, 1)[-1]

    ports = set()
    for line in tunnel_txt.splitlines():
        for m in _LISTEN_RE.finditer(line):
            p = int(m.group(1))
            if _TUNNEL_PORT_MIN <= p <= _TUNNEL_PORT_MAX:
                ports.add(p)

    # 이름 계열 키 → 나이, 터널포트 → 나이. 두 사전을 따로 둔다(포트가 우선순위 최상).
    beats: dict[str, int] = {}
    beats_by_port: dict[int, int] = {}
    for line in hb_txt.splitlines():
        cols = [c.strip() for c in line.strip().split('|')]
        if len(cols) < 6:
            continue
        try:
            age = int(cols[-1])
        except ValueError:
            continue
        tunnel_port, node_name, host, node_id, label = cols[0], cols[1], cols[2], cols[3], cols[4]
        if tunnel_port.isdigit():
            beats_by_port[int(tunnel_port)] = age
        for key in (node_name, host, node_id, label):
            k = key.strip().lower()
            if k:
                beats.setdefault(k, age)
                # node_id 는 'pc-yjscom' 형태라 접두사를 벗긴 값도 후보로 둔다.
                if '-' in k:
                    beats.setdefault(k.split('-', 1)[1], age)

    return {'available': True, 'error': '', 'tunnel_ports': ports,
            'heartbeats': beats, 'heartbeats_by_port': beats_by_port,
            'heartbeat_available': bool(hb_txt.strip()),
            'alias': _resolved_alias or ''}


def _labels_of(host: dict) -> list[str]:
    """이 ssh config 항목에 대응할 수 있는 관제 라벨 후보(소문자).

    [제약] 관제 라벨(apix_nodes.label)과 ssh 별칭은 사람이 따로 정한 이름이라 항상
      같지는 않다. 별칭 전체 + HostName 까지 후보로 넣어 하나라도 맞으면 채택한다.
      끝내 못 맞추면 None(알 수 없음)이지 오프라인이 아니다.
    """
    cands = [str(host.get('alias') or '')] + list(host.get('aliases') or [])
    cands.append(str(host.get('hostName') or ''))
    return [c.strip().lower() for c in cands if c and c.strip()]


def heartbeat_age(probe: dict, host: dict) -> int | None:
    """이 노드의 마지막 하트비트 나이(초). 판정 불가면 None.

    [불변식] 역터널 포트 매칭이 최우선이다 — 유일하게 양쪽이 같은 값을 아는 키라
      오탐이 없다. 이름 계열은 사람이 붙인 값이라 두 노드가 같은 이름을 가질 수 있고,
      그러면 남의 하트비트를 자기 것으로 읽는다. 포트가 있으면 이름은 보지 않는다.
    """
    if not probe.get('heartbeat_available'):
        return None
    port = int(host.get('port') or 0)
    by_port = probe.get('heartbeats_by_port') or {}
    if port and port in by_port:
        return by_port[port]

    beats = probe.get('heartbeats') or {}
    for key in _labels_of(host):
        if key in beats:
            return beats[key]
    return None


def is_alive(probe: dict, host: dict) -> bool | None:
    """살아 있는가 — 하트비트 기준. 판정 불가면 None(오프라인 아님)."""
    age = heartbeat_age(probe, host)
    return None if age is None else age <= STALE_AFTER_SEC


def is_reachable(probe: dict, host: dict) -> bool | None:
    """조종할 수 있는가 — 역터널 기준. 판정 불가면 None.

    [불변식] ProxyJump가 없는 항목(서버 자신, LAN 직결 등)은 역터널 개념이 없으므로
      None이다. 여기서 False를 주면 멀쩡한 노드가 '연결 끊김'으로 표시된다.
    """
    if not probe.get('available'):
        return None
    port = int(host.get('port') or 0)
    if not port or not (host.get('proxyJump') or ''):
        return None
    return port in (probe.get('tunnel_ports') or set())


def check_remote_clis(alias: str, timeout: int = 12) -> dict:
    """원격 노드에 claude/codex가 설치돼 있는지 SSH 1회 왕복으로 확인한다.

    [제약] 폴링 금지 — 호출부가 사용자 액션에만 부른다(모듈 헤더 참조).
    [WHY BatchMode] 비밀번호 프롬프트가 뜨면 무인 호출이 통째로 매달린다. 키 인증만 허용하고
      실패는 즉시 에러로 받는다.
    [WHY command -v] `where`(윈도우)와 `which`(POSIX)가 갈리는데 원격 OS를 모른다.
      셸 빌트인 command -v는 POSIX 셸이면 동작하고, 윈도우 OpenSSH 기본 셸이 cmd면
      실패하므로 그때는 where로 한 번 더 시도한다.
    """
    if not _ssh_available():
        return {'ok': False, 'error': 'ssh 실행파일 없음', 'claude': None, 'codex': None}

    probe = 'command -v claude || where claude; command -v codex || where codex'
    try:
        res = proc.run(
            ['ssh', '-o', f'ConnectTimeout={max(3, timeout - 4)}', '-o', 'BatchMode=yes',
             '-o', 'StrictHostKeyChecking=accept-new', alias, probe],
            capture_output=True, text=True, encoding='utf-8', errors='replace',
            timeout=timeout,
        )
    except Exception as e:
        return {'ok': False, 'error': str(e), 'claude': None, 'codex': None}

    err = (res.stderr or '').lower()
    if 'timed out' in err or 'could not resolve' in err or 'connection refused' in err:
        return {'ok': False, 'error': (res.stderr or '').strip()[:200] or '접속 실패',
                'claude': None, 'codex': None}

    # [WHY stdout만 보는가] command -v / where는 **찾았을 때만** 경로를 stdout에 쓴다.
    #   못 찾으면 종료코드만 1이거나 stderr로 메시지가 간다. 그래서 stdout 라인에
    #   이름이 등장하는지만 보면 오탐 없이 설치 여부가 갈린다(stderr를 섞으면
    #   "INFO: 'claude'에 대한 파일을 찾지 못했습니다" 같은 문구가 설치됨으로 오판된다).
    lines = [ln.strip().lower() for ln in (res.stdout or '').splitlines() if ln.strip()]
    return {
        'ok': True,
        'error': '',
        'claude': any('claude' in ln for ln in lines),
        'codex': any('codex' in ln for ln in lines),
        'raw': (res.stdout or '').strip()[:400],
    }


def local_summary() -> dict:
    """이 PC 자체의 노드 정보 — 상태판에서 '나'를 한 줄로 보여주기 위한 요약.

    [제약] 원격 조회를 하지 않는다. 이 함수가 서버 왕복을 하면 상태판 첫 페인트가 느려진다.
    """
    return {
        'hostname': os.environ.get('COMPUTERNAME') or socket.gethostname(),
        'platform': sys.platform,
    }
