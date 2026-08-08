#!/usr/bin/env python3
"""
FILE: scripts/vps_status_api.py
DESCRIPTION: VPS 상태를 JSON으로 뱉는 읽기 전용 API. nginx가 정적 상태판과 함께 서빙한다.

             [WHY 읽기 전용인가] 설정 변경 UI는 뚫리면 서버가 통째로 넘어간다.
             반면 상태 조회는 최악의 경우에도 잃는 것이 '정보'뿐이라 위험이 비대칭이다.
             매일 볼 화면부터 만들고, 쓰기는 정말 반복되는 작업이 생기면 그때 붙인다.

             [보안] 어떤 입력도 받지 않는다(쿼리스트링 무시). 실행하는 명령은
             아래 화이트리스트로 고정 — 외부 입력이 명령에 닿는 경로가 없다.

             127.0.0.1:9100 에만 바인딩하고 nginx가 프록시한다.
             직접 공인망에 열지 않는 이유는 TLS/헤더/레이트리밋을 nginx에 맡기기 위함.

REVISION HISTORY:
- 2026-08-08 Claude: 최초 작성 — 상태판 백엔드.
"""
from __future__ import annotations

import json
import shutil
import subprocess
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

PORT = 9100
SERVICES = ['vibe-bridge', 'hbbs', 'hbbr', 'nginx', 'postgresql']
START = time.time()


def _sh(args: list[str], timeout: int = 5) -> str:
    """화이트리스트 명령만 실행한다. 셸을 거치지 않으므로 인젝션 경로가 없다."""
    try:
        r = subprocess.run(args, capture_output=True, text=True,
                           timeout=timeout, encoding='utf-8', errors='replace')
        return (r.stdout or '').strip()
    except Exception:
        return ''


def services() -> list[dict]:
    out = []
    for name in SERVICES:
        active = _sh(['systemctl', 'is-active', name]) == 'active'
        restarts = _sh(['systemctl', 'show', name, '-p', 'NRestarts', '--value'])
        since = _sh(['systemctl', 'show', name, '-p', 'ActiveEnterTimestamp', '--value'])
        out.append({
            'name': name,
            'active': active,
            'restarts': int(restarts) if restarts.isdigit() else 0,
            'since': since,
        })
    return out


def resources() -> dict:
    mem = {}
    try:
        with open('/proc/meminfo') as f:
            info = {k.strip(): v for k, v in
                    (line.split(':', 1) for line in f if ':' in line)}
        total = int(info['MemTotal'].split()[0]) // 1024
        avail = int(info['MemAvailable'].split()[0]) // 1024
        mem = {'total_mb': total, 'used_mb': total - avail, 'avail_mb': avail}
    except Exception:
        pass

    disk = {}
    try:
        du = shutil.disk_usage('/')
        disk = {'total_gb': round(du.total / 1e9, 1),
                'used_gb': round(du.used / 1e9, 1),
                'pct': round(du.used / du.total * 100)}
    except Exception:
        pass

    load = ''
    try:
        with open('/proc/loadavg') as f:
            load = f.read().split()[0]
    except Exception:
        pass

    up = ''
    try:
        with open('/proc/uptime') as f:
            sec = float(f.read().split()[0])
        d, rem = divmod(int(sec), 86400)
        h, m = divmod(rem // 60, 60)
        up = (f'{d}일 ' if d else '') + f'{h}시간 {m}분'
    except Exception:
        pass

    return {'mem': mem, 'disk': disk, 'load': load, 'uptime': up}


# 터널 포트 ↔ 노드 이름.
# [WHY 하드코딩인가] authorized_keys에는 permitlisten 제약만 있고 노드 이름과 포트를
#   잇는 단일 원천이 없다. 목록이 짧고 사람이 배정하므로 여기서 명시한다.
# [🔴 2026-08-08] 처음엔 번호 순서로 추측해 22004를 na2js로 적었으나 **틀렸다**.
#   SSH 배너로 검증하니 22004는 OpenSSH_10.2(유닉스)에 출발지가 1.242.15.27(맥미니 회선)
#   이었다. 22001은 OpenSSH_for_Windows_9.5 + 집 회선이라 윈도우가 맞았다.
#   → 노드를 추가하면 추측하지 말고 배너·출발지로 확인할 것:
#      python3 -c "import socket;s=socket.create_connection(('127.0.0.1',PORT));print(s.recv(100))"
# [2026-08-08] 이제 이 표는 '표시용'이 아니라 **서버 설정과 짝을 이루는 배정표**다.
#   authorized_keys 의 permitlisten 이 키마다 포트 하나로 고정돼 있어, 여기 적힌 포트와
#   노드의 -R 포트가 어긋나면 그 노드는 접속 자체가 거부된다. 노드를 추가·변경할 때
#   authorized_keys 와 이 표를 **함께** 고칠 것.
TUNNEL_NAMES = {
    22001: '크립토 PC (Windows)',
    22002: 'na2js (미접속)',   # 키만 등록됨 — 아직 한 번도 붙은 적 없음(auth.log 무기록)
    22004: '맥미니 (macOS)',
}


def _tunnel_alive(port: int) -> bool:
    """터널 끝단이 실제로 응답하는지 확인한다.

    [🔴 왜 포트 존재만으로는 안 되나 — 2026-08-08 실측]
      역터널은 상대 PC가 죽어도 VPS 쪽 리슨 포트가 남는다. 포트만 보고 '연결됨'이라
      표시했더니 22001·22004 둘 다 초록불이었는데 실제로는 **양쪽 다 응답이 없었다**.
      상대 PC의 sshd가 안 떠 있었던 것이다. 거짓 정상은 장애보다 나쁘다 —
      "연결돼 있다"고 믿고 다른 원인을 찾게 만들기 때문이다.
      그래서 실제로 TCP를 열어 SSH 배너가 오는지까지 본다.
    [제약] 타임아웃을 짧게(1.5초) 둔다. 상태판은 10초마다 호출되므로 느리면 안 된다.
    """
    import socket
    try:
        with socket.create_connection(('127.0.0.1', port), timeout=1.5) as s:
            s.settimeout(1.5)
            return s.recv(16).startswith(b'SSH-')
    except Exception:
        return False


def remote_nodes() -> list[dict]:
    """역터널 포트별 상태. 포트 존재가 아니라 **실응답**으로 판정한다.

    [제약] hbbs의 sqlite는 읽지 않는다 — 잠금 충돌 위험이 있고 스키마가 버전에 묶인다.
    """
    ports = set()
    for line in _sh(['ss', '-tlnH']).splitlines():
        parts = line.split()
        if len(parts) >= 4:
            addr = parts[3]
            tail = addr.rsplit(':', 1)[-1]
            if tail.isdigit() and 22001 <= int(tail) <= 22099:
                ports.add(int(tail))

    out = []
    for p in sorted(ports):
        out.append({
            'tunnel_port': p,
            'name': TUNNEL_NAMES.get(p, f'미등록 ({p})'),
            'alive': _tunnel_alive(p),
        })
    return out


def payload() -> dict:
    return {
        'node': 'vibe-seoul',
        'region': 'Seoul (ICN)',
        'checked_at': time.strftime('%Y-%m-%d %H:%M:%S'),
        'services': services(),
        'resources': resources(),
        'tunnels': remote_nodes(),
    }


class Handler(BaseHTTPRequestHandler):
    def do_GET(self):  # noqa: N802
        # [의도] 경로와 무관하게 같은 응답. 입력을 해석하지 않는 것이 곧 공격면 축소다.
        body = json.dumps(payload(), ensure_ascii=False).encode('utf-8')
        self.send_response(200)
        self.send_header('Content-Type', 'application/json;charset=utf-8')
        self.send_header('Cache-Control', 'no-store')
        self.send_header('Content-Length', str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, *args):  # 요청 로그 억제 — journal 오염 방지
        pass


def main() -> int:
    srv = ThreadingHTTPServer(('127.0.0.1', PORT), Handler)
    print(f'[status-api] 127.0.0.1:{PORT} 리슨', flush=True)
    srv.serve_forever()
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
