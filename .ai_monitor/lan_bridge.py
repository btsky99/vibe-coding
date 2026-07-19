"""
FILE: .ai_monitor/lan_bridge.py
DESCRIPTION: LAN 브리지 — 별도 프로세스로 실행되어 0.0.0.0:9020에 HTTP를 열고(기존 서버는
             127.0.0.1 불변) 같은 네트워크의 다른 바이브코딩과 자동발견·페어링·파일전송한다.
             LAN에 노출되는 유일한 표면 = 이 파일의 인증된 라우트뿐.

REVISION HISTORY:
- 2026-07-19 Claude: 신규 — LAN 브리지 Phase 1 Task 3~5. office_server 구조 복제.
"""
# [보안 불변식] 라우트는 2계층:
#   ① 로컬 전용(127.0.0.1만) — pair-begin/pair-connect/send/status. 외부가 내 파일전송을
#      트리거하지 못하게 client_address로 강제 차단.
#   ② 인증 필요(외부 피어 대상) — pair-request/recv-file. HMAC 토큰(lan_peers) 검증 통과만.
# [WHY 별도 프로세스] 기존 server.py를 0.0.0.0으로 열면 모든 API가 LAN 노출 → 위험.
#   브리지만 노출하고 노출 표면을 이 파일로 국한한다.
from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import threading
from http.server import HTTPServer, BaseHTTPRequestHandler
from pathlib import Path
from socketserver import ThreadingMixIn
from urllib.error import URLError
from urllib.parse import urlparse, quote, unquote
from urllib.request import Request, urlopen

BASE_DIR = Path(__file__).resolve().parent
if str(BASE_DIR) not in sys.path:
    sys.path.insert(0, str(BASE_DIR))

from src.lan_peers import LanPeers
from src.lan_discovery import LanDiscovery, DISCOVERY_PORT

HTTP_PORT_START = 9020
FIREWALL_RULE = 'VibeCoding-LAN'
_NO_WINDOW = getattr(subprocess, 'CREATE_NO_WINDOW', 0x08000000)

# 모듈 전역 — Handler가 참조. 단일 프로세스라 락 불필요(핸들러 스레드는 읽기 위주,
# pending_code만 로컬 라우트에서 교체되고 이는 순간적).
STATE: dict = {
    'peers': None,       # LanPeers
    'disc': None,        # LanDiscovery
    'port': 0,           # 실제 HTTP 포트
    'firewall_ok': False,
    'pending_code': None,  # 페어링 개시 시 표시한 코드 (상대 요청 검증용)
    'inbox': None,       # Path — 수신 파일 저장 루트
    'name': '',
}


class ThreadedHTTPServer(ThreadingMixIn, HTTPServer):
    daemon_threads = True
    # [보안] 0.0.0.0 노출 소켓이라 allow_reuse_address=False — Windows에서 True면 다른
    # 프로세스가 SO_REUSEADDR로 같은 포트를 가로챌 수 있고(하이재킹), 포트 충돌도 조용히
    # 겹쳐 오작동한다. False면 이미 쓰는 포트는 bind가 정상 실패 → 순차 재시도로 넘어감.
    allow_reuse_address = False


def _bind_server(preferred: int, fixed: bool = False) -> tuple[ThreadedHTTPServer, int]:
    """preferred부터 순차로 실제 bind를 시도(TOCTOU 없는 확정 바인딩). fixed면 그 포트만.

    [WHY] find_free_port(bind-test-후-close)는 두 프로세스가 거의 동시에 뜨면 같은 포트를
    free로 오판(race). 실제 서버 소켓을 직접 bind해 성공한 포트를 확정한다.
    """
    span = 1 if fixed else 20
    last_err: OSError | None = None
    for port in range(preferred, preferred + span):
        try:
            return ThreadedHTTPServer(('0.0.0.0', port), Handler), port
        except OSError as e:
            last_err = e
    raise last_err or OSError('bind 실패')


# ── 방화벽 (블로커) ──────────────────────────────────────────────────────
def ensure_firewall(tcp_port: int, udp_port: int) -> bool:
    """netsh로 인바운드 허용 규칙 등록. 관리자 권한 없으면 False(크래시 금지).

    [WHY] 규칙을 매번 delete→add — find_free_port로 HTTP 포트가 바뀔 수 있어 stale 규칙을
    남기지 않고 항상 현재 포트를 반영(멱등). delete는 규칙이 없으면 실패하나 무시.
    [블로커] 이게 없으면 Windows Defender가 인바운드를 막아 '됐다는데 연결 안 됨' 사고.
    """
    try:
        subprocess.run(['netsh', 'advfirewall', 'firewall', 'delete', 'rule',
                        f'name={FIREWALL_RULE}'],
                       capture_output=True, text=True, creationflags=_NO_WINDOW)
        ok = True
        for proto, port in (('TCP', tcp_port), ('UDP', udp_port)):
            r = subprocess.run(['netsh', 'advfirewall', 'firewall', 'add', 'rule',
                                f'name={FIREWALL_RULE}', 'dir=in', 'action=allow',
                                f'protocol={proto}', f'localport={port}'],
                               capture_output=True, text=True, creationflags=_NO_WINDOW)
            ok = ok and (r.returncode == 0)
        return ok
    except Exception:
        return False


# ── 파일명 sanitize (경로 traversal 차단) ────────────────────────────────
def sanitize_filename(name: str) -> str:
    """수신 파일명을 안전화 — 경로 분리자·상위참조·제어문자 제거. 항상 basename만 남긴다.

    [보안] '../../etc/passwd', 'C:\\evil', 절대경로가 inbox 밖으로 못 나가게. 빈 결과는 대체명.
    """
    name = unquote(name or '')
    name = name.replace('\\', '/').split('/')[-1]     # 경로 성분 제거 → basename
    name = ''.join(c for c in name if c.isprintable() and c not in '<>:"|?*')
    name = name.strip().lstrip('.')                    # 선행 '.' 제거(숨김/상위참조 방지)
    return name or 'received.bin'


# ── 파일 송신 (로컬 트리거 → 상대에게 POST) ──────────────────────────────
def send_file(peer_id: str, filepath: str) -> dict:
    """신뢰 피어(peer_id)에게 파일 전송. 발견 목록에서 ip/port 조회 + HMAC 토큰 첨부."""
    peers: LanPeers = STATE['peers']
    disc: LanDiscovery = STATE['disc']
    if not peers.is_trusted(peer_id):
        return {'ok': False, 'error': '페어링되지 않은 상대'}
    target = next((p for p in disc.get_peers() if p['peer_id'] == peer_id), None)
    if not target:
        return {'ok': False, 'error': '상대가 오프라인(발견 안 됨)'}
    path = Path(filepath)
    if not path.is_file():
        return {'ok': False, 'error': f'파일 없음: {filepath}'}
    token = peers.make_token(peer_id)
    url = f"http://{target['ip']}:{target['http_port']}/lan/recv-file"
    req = Request(url, data=path.read_bytes(), method='POST', headers={
        'X-Peer-Id': peers.self_id, 'X-Token': token or '',
        'X-Filename': quote(path.name), 'Content-Type': 'application/octet-stream',
    })
    try:
        with urlopen(req, timeout=60) as resp:
            return {'ok': resp.status == 200, 'status': resp.status}
    except URLError as e:
        return {'ok': False, 'error': str(e)}


# ── HTTP 핸들러 ──────────────────────────────────────────────────────────
class Handler(BaseHTTPRequestHandler):

    def log_message(self, *args):  # 콘솔 스팸 억제
        pass

    def _is_local(self) -> bool:
        return self.client_address[0] in ('127.0.0.1', '::1', 'localhost')

    def _json(self, obj: dict, status: int = 200) -> None:
        body = json.dumps(obj, ensure_ascii=False).encode()
        self.send_response(status)
        self.send_header('Content-Type', 'application/json; charset=utf-8')
        self.send_header('Content-Length', str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _body(self) -> bytes:
        n = int(self.headers.get('Content-Length', 0) or 0)
        return self.rfile.read(n) if n else b''

    # ── GET ──────────────────────────────────────────────────────────
    def do_GET(self):
        path = urlparse(self.path).path
        peers: LanPeers = STATE['peers']
        if path == '/lan/ping':
            # 발견 확인용 — 인증 불요, 최소 정보만.
            self._json({'app': 'vibe-coding', 'peer_id': peers.self_id, 'name': STATE['name']})
        elif path == '/lan/status':
            if not self._is_local():
                self._json({'error': 'local only'}, 403); return
            self._json({
                'port': STATE['port'], 'firewall_ok': STATE['firewall_ok'],
                'self_id': peers.self_id, 'name': STATE['name'],
                'pending_code': STATE['pending_code'],
                'online': STATE['disc'].get_peers(),
                'trusted': peers.list_peers(),
            })
        else:
            self._json({'error': 'not found'}, 404)

    # ── POST ─────────────────────────────────────────────────────────
    def do_POST(self):
        path = urlparse(self.path).path
        peers: LanPeers = STATE['peers']

        # ① 로컬 전용 라우트
        if path in ('/lan/pair-begin', '/lan/pair-connect', '/lan/send'):
            if not self._is_local():
                self._json({'error': 'local only'}, 403); return
            body = json.loads(self._body() or b'{}')
            if path == '/lan/pair-begin':
                # 개시자: 6자리 코드 생성·표시. 상대의 pair-request가 이 코드로 검증됨.
                STATE['pending_code'] = LanPeers.generate_pair_code()
                self._json({'code': STATE['pending_code'], 'self_id': peers.self_id})
            elif path == '/lan/pair-connect':
                # 입력자: 상대(ip/port)에게 pair-request 전송. 코드 일치 시 shared_key 수령·저장.
                self._json(self._pair_connect(body))
            elif path == '/lan/send':
                self._json(send_file(body.get('peer_id', ''), body.get('path', '')))
            return

        # ② 인증 필요 라우트 (외부 피어)
        if path == '/lan/pair-request':
            self._json(self._pair_request(json.loads(self._body() or b'{}')))
        elif path == '/lan/recv-file':
            self._json(self._recv_file())
        else:
            self._json({'error': 'not found'}, 404)

    # ── 페어링: 입력자 측 ────────────────────────────────────────────
    def _pair_connect(self, body: dict) -> dict:
        peers: LanPeers = STATE['peers']
        ip, port, code = body.get('ip'), body.get('http_port'), body.get('code')
        if not (ip and port and code):
            return {'ok': False, 'error': 'ip/http_port/code 필요'}
        url = f'http://{ip}:{port}/lan/pair-request'
        req = Request(url, data=json.dumps({
            'code': code, 'peer_id': peers.self_id, 'name': STATE['name'],
        }).encode(), method='POST', headers={'Content-Type': 'application/json'})
        try:
            with urlopen(req, timeout=15) as resp:
                res = json.loads(resp.read())
        except URLError as e:
            return {'ok': False, 'error': str(e)}
        if not res.get('ok'):
            return res
        # 상대가 준 shared_key로 상대를 신뢰 등록(대칭키).
        peers.add_peer(res['self_id'], res.get('name', ''), res['shared_key'])
        return {'ok': True, 'peer_id': res['self_id'], 'name': res.get('name', '')}

    # ── 페어링: 개시자 측 (상대의 요청 수신) ────────────────────────
    def _pair_request(self, body: dict) -> dict:
        peers: LanPeers = STATE['peers']
        if not STATE['pending_code']:
            return {'ok': False, 'error': '페어링 대기 중 아님'}
        if body.get('code') != STATE['pending_code']:
            return {'ok': False, 'error': '코드 불일치'}
        peer_id, name = body.get('peer_id'), body.get('name', '')
        if not peer_id:
            return {'ok': False, 'error': 'peer_id 없음'}
        shared_key = LanPeers.new_shared_key()
        peers.add_peer(peer_id, name, shared_key)
        STATE['pending_code'] = None   # 일회성 — 재사용 방지
        return {'ok': True, 'self_id': peers.self_id, 'name': STATE['name'],
                'shared_key': shared_key}

    # ── 파일 수신 ────────────────────────────────────────────────────
    def _recv_file(self) -> dict:
        peers: LanPeers = STATE['peers']
        peer_id = self.headers.get('X-Peer-Id', '')
        token = self.headers.get('X-Token', '')
        if not peers.verify_token(peer_id, token):
            return {'ok': False, 'error': '인증 실패'}
        raw = self._body()
        fname = sanitize_filename(self.headers.get('X-Filename', ''))
        peer_name = next((p['name'] for p in peers.list_peers() if p['peer_id'] == peer_id),
                         peer_id)
        dest_dir = STATE['inbox'] / sanitize_filename(peer_name)
        dest_dir.mkdir(parents=True, exist_ok=True)
        (dest_dir / fname).write_bytes(raw)
        return {'ok': True, 'saved': fname, 'bytes': len(raw)}


# ── 부팅 ─────────────────────────────────────────────────────────────────
def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument('--data-dir', required=True, help='lan_peers.json + lan_inbox 루트')
    ap.add_argument('--port', type=int, default=0,
                    help='HTTP 포트 고정(0=9020부터 자동 스캔). 같은 PC 다중 기동/테스트용.')
    args = ap.parse_args()

    data_dir = Path(args.data_dir).resolve()
    data_dir.mkdir(parents=True, exist_ok=True)
    peers = LanPeers(data_dir)
    import socket as _sock
    name = _sock.gethostname()

    # 실제 서버 소켓을 먼저 확정 bind한 뒤(포트 결정) 그 포트로 방화벽·발견을 구성.
    srv, port = _bind_server(args.port or HTTP_PORT_START, fixed=bool(args.port))
    STATE.update({
        'peers': peers, 'port': port, 'name': name,
        'inbox': data_dir / 'lan_inbox',
        'firewall_ok': ensure_firewall(port, DISCOVERY_PORT),
    })
    disc = LanDiscovery(peers.self_id, port, name=name)
    STATE['disc'] = disc
    disc.start()

    # [WHY] 브리지 HTTP 포트는 동적(9020부터 스캔) → server.py의 lan_api가 어느 포트로
    # 프록시할지 알 방법이 없다. 확정 포트를 파일에 남겨 lan_api가 읽게 한다(파일 부재=브리지 꺼짐).
    port_file = data_dir / 'lan_bridge_port'
    port_file.write_text(str(port), encoding='utf-8')

    print(f'[lan_bridge] 0.0.0.0:{port} | self_id={peers.self_id[:8]} '
          f'| firewall_ok={STATE["firewall_ok"]}', flush=True)
    try:
        srv.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        disc.stop()
        try:
            port_file.unlink()   # 정상 종료 시 '꺼짐'을 lan_api가 즉시 인지
        except OSError:
            pass


if __name__ == '__main__':
    main()
