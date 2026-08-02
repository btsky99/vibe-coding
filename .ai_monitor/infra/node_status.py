"""
FILE: infra/node_status.py
DESCRIPTION: Tailscale 노드 온/오프라인 상태 조회 + 원격 노드의 CLI(claude/codex) 설치 점검.
  상태판 창과 tui.py가 "그 노드 지금 살아있나 / 거기 클로드 깔려 있나"를 아는 유일한 경로.

[WHY tailscale CLI인가 — API 아님]
  Tailscale API는 토큰 발급·갱신이 필요하고 토큰을 어딘가 저장해야 한다. 로컬 CLI는
  이미 로그인된 상태를 그대로 읽으므로 비밀 정보를 이 프로젝트가 하나도 안 갖는다.
  (프로젝트 원칙: 접속 정보는 ~/.ssh/config와 tailscale 데몬이 소유, 코드는 참조만)

[🔴 왜 ssh config만으로는 부족한가]
  ssh config는 "어디로 붙을지"만 알고 "지금 켜져 있는지"는 모른다. 노드가 꺼져 있으면
  ssh가 22번에서 타임아웃될 때까지(수십 초) 매달린다. tailscale status를 먼저 보면
  오프라인 노드는 아예 시도하지 않는다 — 실측 2026-08-02: 레노버가 2일째 offline이라
  원격 접속이 전부 타임아웃이었는데, 이유를 알려면 CLI를 직접 쳐봐야 했다.

[제약] CLI 설치 점검은 SSH 왕복이라 느리다(수 초). 폴링에 절대 넣지 않는다 —
  사용자가 명시적으로 "점검" 했을 때만 실행하고 결과는 caller가 캐시한다.
  자동 실행하면 노드마다 SSH 세션이 주기적으로 열려 로그가 오염되고 느려진다.

REVISION HISTORY:
- 2026-08-02 Claude: 최초 작성 — 상태판 독립 창의 원격 노드 섹션.
"""
from __future__ import annotations

import json
import os
import shutil
import sys

from infra import proc  # [표준] 콘솔 숨김 subprocess 래퍼 — 인라인 CREATE_NO_WINDOW 금지

# [WHY 경로 폴백] tailscale은 PATH에 없는 설치가 흔하다(윈도우 기본 설치가 PATH를 안 건드림).
#   PATH 우선 탐색 → 플랫폼별 표준 설치 경로 폴백. 하드코딩 단독 사용 금지(맥 이전 대비).
_TAILSCALE_FALLBACKS = [
    r'C:\Program Files\Tailscale\tailscale.exe',
    r'C:\Program Files (x86)\Tailscale\tailscale.exe',
    '/usr/local/bin/tailscale',
    '/opt/homebrew/bin/tailscale',
    '/Applications/Tailscale.app/Contents/MacOS/Tailscale',
]


def tailscale_path() -> str | None:
    found = shutil.which('tailscale')
    if found:
        return found
    for p in _TAILSCALE_FALLBACKS:
        if os.path.exists(p):
            return p
    return None


def tailscale_status() -> dict:
    """tailnet 피어 상태를 {소문자호스트명: {...}} + {tailscale IP: {...}} 양쪽 키로 반환.

    [WHY 두 종류 키] ssh config는 노드를 HostName(=100.x IP)으로 적고, 사람은 호스트명으로
      기억한다. 어느 쪽으로 조회해도 맞도록 같은 레코드를 두 키에 넣는다.

    반환: {'available': bool, 'peers': {...}, 'self': {...}, 'error': str}
    """
    exe = tailscale_path()
    if not exe:
        return {'available': False, 'peers': {}, 'self': {}, 'error': 'tailscale 미설치'}
    try:
        res = proc.run([exe, 'status', '--json'], capture_output=True, text=True,
                       encoding='utf-8', errors='replace', timeout=10)
        data = json.loads(res.stdout or '{}')
    except Exception as e:
        return {'available': False, 'peers': {}, 'self': {}, 'error': str(e)}

    peers: dict[str, dict] = {}

    def _add(node: dict) -> None:
        if not isinstance(node, dict):
            return
        host = (node.get('HostName') or '').strip()
        ips = node.get('TailscaleIPs') or []
        rec = {
            'hostname': host,
            'dns_name': (node.get('DNSName') or '').rstrip('.'),
            'ips': ips,
            'os': node.get('OS') or '',
            'online': bool(node.get('Online')),
            'last_seen': node.get('LastSeen') or '',
            'active': bool(node.get('Active')),
        }
        if host:
            peers[host.lower()] = rec
        for ip in ips:
            peers[ip] = rec

    self_node = (data.get('Self') or {})
    _add(self_node)
    for node in (data.get('Peer') or {}).values():
        _add(node)

    return {
        'available': True,
        'peers': peers,
        'self': {
            'hostname': (self_node.get('HostName') or ''),
            'ips': self_node.get('TailscaleIPs') or [],
        },
        'error': '',
    }


def match_peer(status: dict, alias: str, host_name: str) -> dict | None:
    """ssh config 항목(별칭 + HostName)에 대응하는 tailnet 피어를 찾는다.

    [제약] 매칭은 IP → 별칭 → HostName 순. ssh config의 HostName이 LAN IP로 잘못 적혀 있으면
      (과거사고 2026-07-29 레노버) IP 매칭이 실패하므로 별칭으로도 시도해야 한다.
    """
    peers = status.get('peers') or {}
    for key in (host_name, (alias or '').lower(), (host_name or '').lower()):
        if key and key in peers:
            return peers[key]
    return None


def check_remote_clis(alias: str, timeout: int = 12) -> dict:
    """원격 노드에 claude/codex가 설치돼 있는지 SSH 1회 왕복으로 확인한다.

    [제약] 폴링 금지 — 호출부가 사용자 액션에만 부른다(모듈 헤더 참조).
    [WHY BatchMode] 비밀번호 프롬프트가 뜨면 무인 호출이 통째로 매달린다. 키 인증만 허용하고
      실패는 즉시 에러로 받는다.
    [WHY command -v] `where`(윈도우)와 `which`(POSIX)가 갈리는데 원격 OS를 모른다.
      셸 빌트인 command -v는 POSIX 셸이면 동작하고, 윈도우 OpenSSH 기본 셸이 cmd면
      실패하므로 그때는 where로 한 번 더 시도한다.
    """
    if not shutil.which('ssh'):
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
    """이 PC 자체의 노드 정보 — 상태판에서 '나'를 한 줄로 보여주기 위한 요약."""
    st = tailscale_status()
    return {
        'hostname': (st.get('self') or {}).get('hostname') or os.environ.get('COMPUTERNAME', ''),
        'ips': (st.get('self') or {}).get('ips') or [],
        'tailscale': st.get('available', False),
        'platform': sys.platform,
    }
