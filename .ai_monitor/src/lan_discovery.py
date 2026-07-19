"""
FILE: src/lan_discovery.py
DESCRIPTION: LAN 자동발견 — UDP 브로드캐스트로 같은 네트워크의 다른 바이브코딩 브리지를
             주기적으로 알리고(announce) 수신(listen)해 온라인 피어 목록을 유지한다.
             수동 IP 입력 없이 서로를 찾게 한다.

REVISION HISTORY:
- 2026-07-19 Claude: 신규 — LAN 브리지 Phase 1 Task 2. project_id 비의존(이식성).
"""
# [WHY] mDNS(zeroconf) 대신 순수 UDP 브로드캐스트 — 외부 의존성 0(stdlib socket만)으로
#   이식성 유지(바이브 본질). 같은 서브넷 한정이라 '같은 LAN' 요구와 정확히 일치.
# [제약] 255.255.255.255 브로드캐스트는 라우터를 못 넘음 = 다른 서브넷/VPN엔 안 보임(의도된 경계).
# [불변식] announce의 peer_id로 자기 자신을 걸러낸다 — 안 그러면 자기 목록에 자기가 뜸.
from __future__ import annotations

import json
import socket
import threading
import time

DISCOVERY_PORT = 9021         # [제약] 9019(heartbeat)·9020(브리지 HTTP)와 겹치지 않는 UDP 대역
ANNOUNCE_INTERVAL_SEC = 3.0
PEER_TTL_SEC = 10.0           # 이 시간 announce 없으면 오프라인 — INTERVAL의 ~3배로 유실 흡수
_BROADCAST = '255.255.255.255'


class LanDiscovery:
    """announce/listen 두 데몬 스레드 + 온라인 피어 레지스트리.

    [제약] 브리지 프로세스 1개당 1인스턴스 전제. get_peers()는 락으로 보호(listen 스레드와 공유).
    """

    def __init__(self, peer_id: str, http_port: int, name: str = ''):
        self.peer_id = peer_id
        self.http_port = http_port
        self.name = name or socket.gethostname()
        self._peers: dict[str, dict] = {}      # peer_id -> {name, ip, http_port, last_seen}
        self._lock = threading.Lock()
        self._stop = threading.Event()
        self._threads: list[threading.Thread] = []

    # ── 수명주기 ─────────────────────────────────────────────────────────
    def start(self) -> None:
        self._stop.clear()
        for target in (self._announce_loop, self._listen_loop):
            t = threading.Thread(target=target, daemon=True)
            t.start()
            self._threads.append(t)

    def stop(self) -> None:
        self._stop.set()

    def get_peers(self) -> list[dict]:
        """TTL 안에 살아있는 피어만. last_seen 초과분은 조회 시점에 제외(오프라인)."""
        now = time.time()
        with self._lock:
            return [
                {'peer_id': pid, 'name': p['name'], 'ip': p['ip'], 'http_port': p['http_port']}
                for pid, p in self._peers.items()
                if now - p['last_seen'] <= PEER_TTL_SEC
            ]

    # ── announce ─────────────────────────────────────────────────────────
    def _announce_loop(self) -> None:
        sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        sock.setsockopt(socket.SOL_SOCKET, socket.SO_BROADCAST, 1)
        payload = json.dumps({
            'app': 'vibe-coding', 'peer_id': self.peer_id,
            'name': self.name, 'http_port': self.http_port,
        }).encode()
        try:
            while not self._stop.is_set():
                try:
                    sock.sendto(payload, (_BROADCAST, DISCOVERY_PORT))
                except OSError:
                    # [WHY] 네트워크 일시 단절(WiFi 전환 등)에 죽지 않고 다음 주기 재시도.
                    pass
                self._stop.wait(ANNOUNCE_INTERVAL_SEC)
        finally:
            sock.close()

    # ── listen ───────────────────────────────────────────────────────────
    def _listen_loop(self) -> None:
        sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        try:
            # [제약] 같은 PC에서 2인스턴스 테스트하려면 REUSEADDR 필수(포트 공유 수신).
            sock.bind(('', DISCOVERY_PORT))
        except OSError:
            sock.close()
            return
        sock.settimeout(1.0)   # stop 이벤트를 1초마다 확인하려는 폴링 타임아웃
        try:
            while not self._stop.is_set():
                try:
                    data, addr = sock.recvfrom(2048)
                except socket.timeout:
                    continue
                except OSError:
                    break
                self._on_announce(data, addr[0])
        finally:
            sock.close()

    def _on_announce(self, data: bytes, ip: str) -> None:
        try:
            msg = json.loads(data.decode())
        except (json.JSONDecodeError, UnicodeDecodeError):
            return
        # 다른 앱 브로드캐스트·자기 자신 제외.
        if msg.get('app') != 'vibe-coding':
            return
        pid = msg.get('peer_id')
        if not pid or pid == self.peer_id:
            return
        with self._lock:
            self._peers[pid] = {
                'name': msg.get('name', ''), 'ip': ip,
                'http_port': int(msg.get('http_port', 0)), 'last_seen': time.time(),
            }
