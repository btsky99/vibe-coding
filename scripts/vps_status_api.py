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


def remote_nodes() -> list[dict]:
    """RustDesk에 등록된 기기 수와 열린 역터널 포트.

    [제약] hbbs의 sqlite를 직접 읽지 않는다 — 잠금 충돌 위험이 있고 스키마가 버전에
      묶인다. 대신 '지금 열려 있는 터널 포트'라는 관측 가능한 사실만 본다.
    """
    tunnels = []
    ss = _sh(['ss', '-tlnH'])
    for line in ss.splitlines():
        parts = line.split()
        if len(parts) >= 4 and ':2200' in parts[3]:
            tunnels.append(parts[3].rsplit(':', 1)[-1])
    return [{'tunnel_port': p} for p in sorted(set(tunnels))]


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
