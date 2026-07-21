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
import hashlib
import json
import os
import subprocess
import sys
import threading
import time
from collections import deque
from http.server import HTTPServer, BaseHTTPRequestHandler
from pathlib import Path
from socketserver import ThreadingMixIn
from urllib.error import URLError
from urllib.parse import urlparse, quote, unquote, parse_qs
from urllib.request import Request, urlopen

BASE_DIR = Path(__file__).resolve().parent
if str(BASE_DIR) not in sys.path:
    sys.path.insert(0, str(BASE_DIR))

from src.lan_peers import LanPeers, derive_key, make_pair_proof, verify_pair_proof
from src.lan_discovery import LanDiscovery, DISCOVERY_PORT
from infra import proc  # [표준] 콘솔 숨김 subprocess 래퍼 — 인라인 CREATE_NO_WINDOW 금지

HTTP_PORT_START = 9020
FIREWALL_RULE = 'VibeCoding-LAN'

# [보안C3] 본문 크기 상한 — 미인증 경로가 무제한 read로 메모리 고갈되는 것 차단.
MAX_CTRL_BYTES = 256 * 1024                 # 페어링/제어 라우트(작은 JSON)
MAX_FILE_BYTES = 2 * 1024 * 1024 * 1024     # 파일 수신 상한 2GB
# [보안C1] 페어링 창 수명·시도 한도 — 브루트포스 구조적 봉쇄.
PAIR_TTL_SEC = 90
PAIR_MAX_ATTEMPTS = 5
# [Phase2] 채팅 메시지 상한 — 텍스트 채팅이라 8KB로 충분, DoS 방어.
CHAT_MAX_BYTES = 8 * 1024
# [Phase3] 원격 실행 태스크/출력 상한. 태스크는 자연어 지시라 16KB로 충분,
#   출력 청크는 stream-json 라인 누적이라 64KB(대용량 로그는 청크 분할로 흐름).
EXEC_TASK_MAX_BYTES = 16 * 1024
EXEC_OUTPUT_MAX_BYTES = 64 * 1024
# [보안 W2] 요청자측 동시 출력 스트림 수 상한 — 페어링 피어가 매번 다른 임의 exec_id로
#   출력을 밀어 exec_output 딕셔너리를 무한 증식시키는 메모리 고갈(DoS) 차단.
MAX_EXEC_STREAMS = 50

# 모듈 전역 — Handler가 참조. 단일 프로세스라 락 불필요(핸들러 스레드는 읽기 위주,
# pending_code만 로컬 라우트에서 교체되고 이는 순간적).
STATE: dict = {
    'peers': None,       # LanPeers
    'disc': None,        # LanDiscovery
    'port': 0,           # 실제 HTTP 포트
    'firewall_ok': False,
    'pending_code': None,   # 페어링 개시 시 표시한 코드 (상대 요청 검증용)
    'pending_at': 0.0,      # 코드 생성 시각 (TTL)
    'pending_attempts': 0,  # 실패 시도 카운트 (브루트포스 차단)
    'inbox': None,       # Path — 수신 파일 저장 루트
    'name': '',
    # [Phase2] 채팅 수신 버퍼 — server(lan_api)가 chat-drain으로 꺼내 DB에 옮길 때까지의 전달버퍼.
    # [제약] 영구성은 DB(lan_messages)가 책임. 이 큐는 drain 전 재시작 시 유실 가능(전달버퍼 한정).
    'chat_inbox': deque(maxlen=500),
    # [Phase3] 원격 실행 릴레이 버퍼 (브리지=릴레이 불변식: 실행·DB 없음).
    #   exec_inbox: 대상측 — 수신한 태스크 승인 대기열. server(lan_api)가 pending-drain으로 꺼냄.
    #   exec_output: 요청자측 — exec_id별 수신 출력청크. server가 output-drain으로 꺼냄.
    'exec_inbox': deque(maxlen=100),
    'exec_output': {},   # exec_id -> deque(maxlen=1000)
}


def _seclog(msg: str) -> None:
    """[보안W3] 보안 이벤트를 stderr에 기록 — 페어링/인증 실패를 은폐하지 않는다.
    log_message는 억제하되 이 함수로 실패만 남겨 브루트포스를 가시화."""
    print(f'[lan_bridge][sec] {time.strftime("%H:%M:%S")} {msg}', file=sys.stderr, flush=True)


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
        proc.run(['netsh', 'advfirewall', 'firewall', 'delete', 'rule',
                  f'name={FIREWALL_RULE}'],
                 capture_output=True, text=True)
        ok = True
        for proto, port in (('TCP', tcp_port), ('UDP', udp_port)):
            r = proc.run(['netsh', 'advfirewall', 'firewall', 'add', 'rule',
                          f'name={FIREWALL_RULE}', 'dir=in', 'action=allow',
                          f'protocol={proto}', f'localport={port}'],
                         capture_output=True, text=True)
            ok = ok and (r.returncode == 0)
        return ok
    except Exception:
        return False


# ── 파일명 sanitize (경로 traversal 차단) ────────────────────────────────
_RESERVED_NAMES = ({'CON', 'PRN', 'AUX', 'NUL'}
                   | {f'COM{i}' for i in range(1, 10)}
                   | {f'LPT{i}' for i in range(1, 10)})


def sanitize_filename(name: str) -> str:
    """수신 파일명을 안전화 — 경로 분리자·상위참조·제어문자·Windows 예약명 제거.

    [보안] '../../etc/passwd', 'C:\\evil', 절대경로가 inbox 밖으로 못 나가게. 빈 결과는 대체명.
    [불변식] 멱등이어야 함 — send_file이 sanitize된 이름으로 토큰을 서명하고, recv-file이
    unquote→sanitize한 결과와 정확히 일치해야 인증 통과(재적용해도 같은 값).
    """
    name = unquote(name or '')
    name = name.replace('\\', '/').split('/')[-1]     # 경로 성분 제거 → basename
    name = ''.join(c for c in name if c.isprintable() and c not in '<>:"|?*')
    name = name.strip().lstrip('.').rstrip('. ')       # 선·후행 '.'/공백 제거(숨김·Windows 함정)
    if name.split('.')[0].upper() in _RESERVED_NAMES:  # CON/NUL/COM1 등 장치명 회피
        name = '_' + name
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
    raw = path.read_bytes()
    # [W1 일관성] 송·수신 모두 sanitize된 파일명으로 서명/검증 — sanitize는 멱등이라
    # 수신측 unquote→sanitize 결과와 정확히 일치한다(불일치 시 인증 실패).
    safe_name = sanitize_filename(path.name)
    body_hash = hashlib.sha256(raw).hexdigest()
    token = peers.make_token(peer_id, body_hash, safe_name)
    url = f"http://{target['ip']}:{target['http_port']}/lan/recv-file"
    req = Request(url, data=raw, method='POST', headers={
        'X-Peer-Id': peers.self_id, 'X-Token': token or '',
        'X-Filename': quote(safe_name), 'Content-Type': 'application/octet-stream',
    })
    try:
        with urlopen(req, timeout=60) as resp:
            return {'ok': resp.status == 200, 'status': resp.status}
    except URLError as e:
        return {'ok': False, 'error': str(e)}


# ── 채팅 송신 (로컬 트리거 → 상대에게 POST) ──────────────────────────────
def send_chat(peer_id: str, content: str) -> dict:
    """신뢰 피어에게 텍스트 메시지 전송. body_hash=sha256(content)로 토큰 서명(파일과 동일 규약)."""
    peers: LanPeers = STATE['peers']
    disc: LanDiscovery = STATE['disc']
    if not peers.is_trusted(peer_id):
        return {'ok': False, 'error': '페어링되지 않은 상대'}
    if not content or len(content.encode('utf-8')) > CHAT_MAX_BYTES:
        return {'ok': False, 'error': '빈 메시지 또는 8KB 초과'}
    target = next((p for p in disc.get_peers() if p['peer_id'] == peer_id), None)
    if not target:
        return {'ok': False, 'error': '상대가 오프라인'}
    body_hash = hashlib.sha256(content.encode('utf-8')).hexdigest()
    token = peers.make_token(peer_id, body_hash, '')
    url = f"http://{target['ip']}:{target['http_port']}/lan/chat-recv"
    req = Request(url, data=json.dumps({'content': content}).encode(), method='POST', headers={
        'X-Peer-Id': peers.self_id, 'X-Token': token or '', 'Content-Type': 'application/json',
    })
    try:
        with urlopen(req, timeout=15) as resp:
            return {'ok': resp.status == 200}
    except URLError as e:
        return {'ok': False, 'error': str(e)}


# ── 원격 실행: 태스크 송신 (요청자 → 대상) ───────────────────────────────
def send_exec(peer_id: str, exec_id: str, task: str) -> dict:
    """신뢰 피어에게 실행 태스크 전송. body_hash=sha256(task)로 토큰 서명(파일/채팅과 동일 규약).

    [보안] 페어링·토큰만으로는 RCE라, 대상측이 exec-recv에서 exec_trust/승인으로 2차 게이트.
    여기(송신)는 신뢰·오프라인·크기만 확인하고 실제 실행 허가는 대상 책임.
    """
    peers: LanPeers = STATE['peers']
    disc: LanDiscovery = STATE['disc']
    if not peers.is_trusted(peer_id):
        return {'ok': False, 'error': '페어링되지 않은 상대'}
    if not task or len(task.encode('utf-8')) > EXEC_TASK_MAX_BYTES:
        return {'ok': False, 'error': '빈 태스크 또는 16KB 초과'}
    target = next((p for p in disc.get_peers() if p['peer_id'] == peer_id), None)
    if not target:
        return {'ok': False, 'error': '상대가 오프라인'}
    body = json.dumps({'exec_id': exec_id, 'task': task}).encode()
    body_hash = hashlib.sha256(task.encode('utf-8')).hexdigest()
    token = peers.make_token(peer_id, body_hash, exec_id)
    url = f"http://{target['ip']}:{target['http_port']}/lan/exec-recv"
    req = Request(url, data=body, method='POST', headers={
        'X-Peer-Id': peers.self_id, 'X-Token': token or '', 'Content-Type': 'application/json',
    })
    try:
        with urlopen(req, timeout=15) as resp:
            return {'ok': resp.status == 200, 'exec_id': exec_id}
    except URLError as e:
        return {'ok': False, 'error': str(e)}


# ── 원격 실행: 출력 역방향 송신 (대상 → 요청자) ──────────────────────────
def send_exec_output(peer_id: str, exec_id: str, chunk: str, done: bool) -> dict:
    """실행 출력 청크를 요청자에게 역방향 전송. body_hash=sha256(exec_id:chunk:done)로 서명.

    [불변식] 대상측 server가 agent_api 실행 출력을 청크로 잘라 여기로 밀어 넣는다.
    done=True 청크가 종료 신호(빈 chunk 가능). 요청자 브리지의 /lan/exec-output이 버퍼링.
    """
    peers: LanPeers = STATE['peers']
    disc: LanDiscovery = STATE['disc']
    if not peers.is_trusted(peer_id):
        return {'ok': False, 'error': '페어링되지 않은 상대'}
    if len(chunk.encode('utf-8')) > EXEC_OUTPUT_MAX_BYTES:
        chunk = chunk.encode('utf-8')[:EXEC_OUTPUT_MAX_BYTES].decode('utf-8', 'ignore')
    target = next((p for p in disc.get_peers() if p['peer_id'] == peer_id), None)
    if not target:
        return {'ok': False, 'error': '상대가 오프라인'}
    payload = {'exec_id': exec_id, 'chunk': chunk, 'done': bool(done)}
    body = json.dumps(payload).encode()
    # [W1] 서명 대상에 exec_id·chunk·done을 sha256으로 묶어 변조·재전송 차단.
    sig_src = f"{exec_id}:{chunk}:{int(bool(done))}"
    body_hash = hashlib.sha256(sig_src.encode('utf-8')).hexdigest()
    token = peers.make_token(peer_id, body_hash, exec_id)
    url = f"http://{target['ip']}:{target['http_port']}/lan/exec-output"
    req = Request(url, data=body, method='POST', headers={
        'X-Peer-Id': peers.self_id, 'X-Token': token or '', 'Content-Type': 'application/json',
    })
    try:
        with urlopen(req, timeout=15) as resp:
            return {'ok': resp.status == 200}
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

    def _body(self, max_bytes: int = MAX_CTRL_BYTES) -> bytes | None:
        """Content-Length만큼 읽되 상한 초과·음수는 None으로 거부(C3).

        [보안C3] int(...)이 음수면 rfile.read(-1)=EOF까지 무한 읽기 → OOM. 음수/초과를
        읽기 전에 차단한다. None 반환 시 호출부가 413으로 응답.
        """
        try:
            n = int(self.headers.get('Content-Length', 0) or 0)
        except ValueError:
            return None
        if n < 0 or n > max_bytes:
            return None
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
        elif path == '/lan/chat-drain':
            # 로컬(server)이 수신 버퍼를 통째로 꺼내 DB로 옮긴다. 큐는 비워짐(1회성).
            if not self._is_local():
                self._json({'error': 'local only'}, 403); return
            msgs = list(STATE['chat_inbox'])
            STATE['chat_inbox'].clear()
            self._json({'messages': msgs})
        elif path == '/lan/exec-pending-drain':
            # [Phase3] 대상측 server가 승인 대기 태스크를 꺼낸다. 큐 비워짐(server가 DB/UI로 이관).
            if not self._is_local():
                self._json({'error': 'local only'}, 403); return
            items = list(STATE['exec_inbox'])
            STATE['exec_inbox'].clear()
            self._json({'pending': items})
        elif path == '/lan/exec-output-drain':
            # [Phase3] 요청자측 server가 exec_id의 수신 출력청크를 꺼낸다. 해당 큐만 비움.
            if not self._is_local():
                self._json({'error': 'local only'}, 403); return
            qs = parse_qs(urlparse(self.path).query)
            exec_id = (qs.get('exec_id', ['']) or [''])[0]
            buf = STATE['exec_output'].get(exec_id)
            chunks = list(buf) if buf else []
            if buf is not None:
                # [W2] 소비 후 스트림 키 제거 — 빈 deque 누적 방지(다음 청크가 재생성).
                STATE['exec_output'].pop(exec_id, None)
            self._json({'chunks': chunks})
        else:
            self._json({'error': 'not found'}, 404)

    # ── POST ─────────────────────────────────────────────────────────
    def do_POST(self):
        path = urlparse(self.path).path
        peers: LanPeers = STATE['peers']

        # ① 로컬 전용 라우트
        if path in ('/lan/pair-begin', '/lan/pair-connect', '/lan/send', '/lan/chat-send',
                    '/lan/exec-send', '/lan/exec-emit', '/lan/exec-trust'):
            if not self._is_local():
                self._json({'error': 'local only'}, 403); return
            raw = self._body(MAX_CTRL_BYTES)
            if raw is None:
                self._json({'error': '본문 크기 초과'}, 413); return
            body = json.loads(raw or b'{}')
            if path == '/lan/pair-begin':
                # 개시자: 코드 생성·표시 + 창 오픈(TTL·시도카운터 리셋). 상대 proof가 이 코드로 검증됨.
                STATE['pending_code'] = LanPeers.generate_pair_code()
                STATE['pending_at'] = time.time()
                STATE['pending_attempts'] = 0
                self._json({'code': STATE['pending_code'], 'self_id': peers.self_id})
            elif path == '/lan/pair-connect':
                # 입력자: 코드에서 키 파생 + 상대에게 proof 전송. 키는 네트워크로 안 나감.
                self._json(self._pair_connect(body))
            elif path == '/lan/send':
                self._json(send_file(body.get('peer_id', ''), body.get('path', '')))
            elif path == '/lan/chat-send':
                self._json(send_chat(body.get('peer_id', ''), body.get('content', '')))
            elif path == '/lan/exec-send':
                # [Phase3] 요청자측 트리거 — 태스크 전송(server가 exec_id 생성해 넘김).
                self._json(send_exec(body.get('peer_id', ''), body.get('exec_id', ''),
                                     body.get('task', '')))
            elif path == '/lan/exec-emit':
                # [Phase3] 대상측 server가 실행 출력청크를 요청자에게 역방향 밀어넣기.
                self._json(send_exec_output(body.get('peer_id', ''), body.get('exec_id', ''),
                                            body.get('chunk', ''), body.get('done', False)))
            elif path == '/lan/exec-trust':
                # [Phase3] 승인 정책 변경(ask|auto). 자동승인 격상/회수.
                ok = peers.set_exec_trust(body.get('peer_id', ''), body.get('mode', 'ask'))
                self._json({'ok': ok})
            return

        # ② 인증 필요 라우트 (외부 피어)
        if path == '/lan/pair-request':
            raw = self._body(MAX_CTRL_BYTES)
            if raw is None:
                _seclog(f'pair-request 본문 초과 from {self.client_address[0]}')
                self._json({'error': '본문 크기 초과'}, 413); return
            self._json(self._pair_request(json.loads(raw or b'{}')))
        elif path == '/lan/recv-file':
            self._json(self._recv_file())
        elif path == '/lan/chat-recv':
            self._json(self._chat_recv())
        elif path == '/lan/exec-recv':
            self._json(self._exec_recv())
        elif path == '/lan/exec-output':
            self._json(self._exec_output())
        else:
            self._json({'error': 'not found'}, 404)

    # ── 페어링: 입력자 측 ────────────────────────────────────────────
    def _pair_connect(self, body: dict) -> dict:
        """코드에서 키를 파생하고 상대에게 init-proof 전송. 상대 ack-proof를 검증해야 신뢰 등록.

        [보안C2] shared_key = derive_key(code)로 로컬 계산 — 네트워크엔 proof(HMAC)만 나감.
        """
        peers: LanPeers = STATE['peers']
        ip, port, code = body.get('ip'), body.get('http_port'), body.get('code')
        if not (ip and port and code):
            return {'ok': False, 'error': 'ip/http_port/code 필요'}
        key = derive_key(code)
        proof = make_pair_proof(code, 'init', peers.self_id)
        url = f'http://{ip}:{port}/lan/pair-request'
        req = Request(url, data=json.dumps({
            'peer_id': peers.self_id, 'name': STATE['name'], 'proof': proof,
        }).encode(), method='POST', headers={'Content-Type': 'application/json'})
        try:
            with urlopen(req, timeout=15) as resp:
                res = json.loads(resp.read())
        except URLError as e:
            return {'ok': False, 'error': str(e)}
        if not res.get('ok'):
            return res
        # [보안] 상대의 ack-proof를 코드로 검증 — 코드를 모르는 가짜 응답자(MITM)를 배제.
        if not verify_pair_proof(code, 'ack', res.get('self_id', ''), res.get('proof', '')):
            return {'ok': False, 'error': '상대 응답 검증 실패(코드 불일치 또는 위조)'}
        peers.add_peer(res['self_id'], res.get('name', ''), key)
        return {'ok': True, 'peer_id': res['self_id'], 'name': res.get('name', '')}

    # ── 페어링: 개시자 측 (상대의 요청 수신) ────────────────────────
    def _pair_request(self, body: dict) -> dict:
        """상대 init-proof를 pending_code로 검증. [C1] TTL·시도 한도로 브루트포스 차단."""
        peers: LanPeers = STATE['peers']
        code = STATE['pending_code']
        src = self.client_address[0]
        if not code:
            return {'ok': False, 'error': '페어링 대기 중 아님'}
        # [C1] TTL 만료 → 창 폐기.
        if time.time() - STATE['pending_at'] > PAIR_TTL_SEC:
            STATE['pending_code'] = None
            _seclog(f'페어링 창 TTL 만료 — 폐기 (from {src})')
            return {'ok': False, 'error': '페어링 코드 만료'}
        peer_id, name = body.get('peer_id'), body.get('name', '')
        if not peer_id:
            return {'ok': False, 'error': 'peer_id 없음'}
        if not verify_pair_proof(code, 'init', peer_id, body.get('proof', '')):
            # [C1] 실패 카운트 — 한도 초과 시 창 폐기(무제한 시도 봉쇄).
            STATE['pending_attempts'] += 1
            _seclog(f'페어링 proof 실패 {STATE["pending_attempts"]}/{PAIR_MAX_ATTEMPTS} (from {src})')
            if STATE['pending_attempts'] >= PAIR_MAX_ATTEMPTS:
                STATE['pending_code'] = None
                _seclog(f'페어링 시도 한도 초과 — 창 폐기 (from {src})')
            return {'ok': False, 'error': '코드 불일치'}
        # 성공: 같은 코드로 파생한 키로 상대 신뢰 등록 + ack-proof 응답. 창은 일회성 소진.
        key = derive_key(code)
        peers.add_peer(peer_id, name, key)
        STATE['pending_code'] = None
        return {'ok': True, 'self_id': peers.self_id, 'name': STATE['name'],
                'proof': make_pair_proof(code, 'ack', peers.self_id)}

    # ── 파일 수신 ────────────────────────────────────────────────────
    def _recv_file(self) -> dict:
        """토큰(헤더)이 body_hash·filename까지 서명했는지 검증 후 저장. [W1/W2] 크기 상한·바인딩."""
        peers: LanPeers = STATE['peers']
        peer_id = self.headers.get('X-Peer-Id', '')
        token = self.headers.get('X-Token', '')
        fname = sanitize_filename(self.headers.get('X-Filename', ''))
        # [C3/W2] 본문을 상한 내에서만 읽음. 초과·음수는 413.
        raw = self._body(MAX_FILE_BYTES)
        if raw is None:
            _seclog(f'recv-file 크기 초과 from {self.client_address[0]}')
            self.send_response(413); self.end_headers()
            return {'ok': False, 'error': '파일 크기 초과'}
        body_hash = hashlib.sha256(raw).hexdigest()
        # [W1] 토큰 서명 범위 = peer_id:nonce:ts:body_hash:filename → 캡처-변조 재전송 차단.
        if not peers.verify_token(peer_id, token, body_hash, fname):
            _seclog(f'recv-file 인증 실패 peer={peer_id[:8]} from {self.client_address[0]}')
            return {'ok': False, 'error': '인증 실패'}
        peer_name = next((p['name'] for p in peers.list_peers() if p['peer_id'] == peer_id),
                         peer_id)
        dest_dir = STATE['inbox'] / sanitize_filename(peer_name)
        dest_dir.mkdir(parents=True, exist_ok=True)
        (dest_dir / fname).write_bytes(raw)
        return {'ok': True, 'saved': fname, 'bytes': len(raw)}

    # ── 채팅 수신 ────────────────────────────────────────────────────
    def _chat_recv(self) -> dict:
        """토큰(body_hash=sha256(content))으로 인증 후 수신 버퍼에 적재. server가 drain해 DB로."""
        peers: LanPeers = STATE['peers']
        peer_id = self.headers.get('X-Peer-Id', '')
        token = self.headers.get('X-Token', '')
        raw = self._body(CHAT_MAX_BYTES + 1024)   # content 8KB + JSON 봉투 여유
        if raw is None:
            _seclog(f'chat-recv 크기 초과 from {self.client_address[0]}')
            return {'ok': False, 'error': '메시지 크기 초과'}
        try:
            content = str(json.loads(raw or b'{}').get('content', ''))
        except json.JSONDecodeError:
            return {'ok': False, 'error': 'JSON 파싱 실패'}
        if not content or len(content.encode('utf-8')) > CHAT_MAX_BYTES:
            return {'ok': False, 'error': '빈 메시지 또는 초과'}
        body_hash = hashlib.sha256(content.encode('utf-8')).hexdigest()
        if not peers.verify_token(peer_id, token, body_hash, ''):
            _seclog(f'chat-recv 인증 실패 peer={peer_id[:8]} from {self.client_address[0]}')
            return {'ok': False, 'error': '인증 실패'}
        STATE['chat_inbox'].append({
            'from_peer': peer_id, 'content': content,
            'ts': time.strftime('%Y-%m-%dT%H:%M:%S'),
        })
        return {'ok': True}

    # ── 원격 실행: 태스크 수신 (대상측) ──────────────────────────────
    def _exec_recv(self) -> dict:
        """태스크 수신 — 토큰(body_hash=sha256(task)) 검증 후 승인 대기열 적재.

        [보안] 브리지는 실행하지 않는다(릴레이 불변식). exec_trust만 조회해 표기하고,
        실제 승인·실행은 대상 server(lan_api)가 pending-drain으로 꺼내 처리한다.
        auto여도 여기선 큐에 넣기만 — server가 auto면 팝업 생략하고 바로 실행.
        """
        peers: LanPeers = STATE['peers']
        peer_id = self.headers.get('X-Peer-Id', '')
        token = self.headers.get('X-Token', '')
        raw = self._body(EXEC_TASK_MAX_BYTES + 1024)   # task 16KB + JSON 봉투 여유
        if raw is None:
            _seclog(f'exec-recv 크기 초과 from {self.client_address[0]}')
            return {'ok': False, 'error': '태스크 크기 초과'}
        try:
            body = json.loads(raw or b'{}')
            exec_id = str(body.get('exec_id', ''))
            task = str(body.get('task', ''))
        except json.JSONDecodeError:
            return {'ok': False, 'error': 'JSON 파싱 실패'}
        if not exec_id or not task:
            return {'ok': False, 'error': 'exec_id/task 필요'}
        body_hash = hashlib.sha256(task.encode('utf-8')).hexdigest()
        if not peers.verify_token(peer_id, token, body_hash, exec_id):
            _seclog(f'exec-recv 인증 실패 peer={peer_id[:8]} from {self.client_address[0]}')
            return {'ok': False, 'error': '인증 실패'}
        trust = peers.get_exec_trust(peer_id)
        STATE['exec_inbox'].append({
            'exec_id': exec_id, 'from_peer': peer_id, 'task': task,
            'exec_trust': trust, 'ts': time.strftime('%Y-%m-%dT%H:%M:%S'),
        })
        return {'ok': True, 'exec_trust': trust}

    # ── 원격 실행: 출력 수신 (요청자측) ──────────────────────────────
    def _exec_output(self) -> dict:
        """출력청크 역방향 수신 — 토큰(body_hash=sha256(exec_id:chunk:done)) 검증 후 버퍼 적재."""
        peers: LanPeers = STATE['peers']
        peer_id = self.headers.get('X-Peer-Id', '')
        token = self.headers.get('X-Token', '')
        raw = self._body(EXEC_OUTPUT_MAX_BYTES + 1024)
        if raw is None:
            _seclog(f'exec-output 크기 초과 from {self.client_address[0]}')
            return {'ok': False, 'error': '출력 크기 초과'}
        try:
            body = json.loads(raw or b'{}')
            exec_id = str(body.get('exec_id', ''))
            chunk = str(body.get('chunk', ''))
            done = bool(body.get('done', False))
        except json.JSONDecodeError:
            return {'ok': False, 'error': 'JSON 파싱 실패'}
        if not exec_id:
            return {'ok': False, 'error': 'exec_id 필요'}
        sig_src = f"{exec_id}:{chunk}:{int(done)}"
        body_hash = hashlib.sha256(sig_src.encode('utf-8')).hexdigest()
        if not peers.verify_token(peer_id, token, body_hash, exec_id):
            _seclog(f'exec-output 인증 실패 peer={peer_id[:8]} from {self.client_address[0]}')
            return {'ok': False, 'error': '인증 실패'}
        buf = STATE['exec_output'].get(exec_id)
        if buf is None:
            # [W2 DoS] 스트림 수 상한 — 초과 시 가장 오래된 키 축출(dict 삽입순서=방치순).
            if len(STATE['exec_output']) >= MAX_EXEC_STREAMS:
                oldest = next(iter(STATE['exec_output']), None)
                if oldest is not None:
                    STATE['exec_output'].pop(oldest, None)
            buf = deque(maxlen=1000)
            STATE['exec_output'][exec_id] = buf
        buf.append({'chunk': chunk, 'done': done,
                    'ts': time.strftime('%Y-%m-%dT%H:%M:%S')})
        return {'ok': True}


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
