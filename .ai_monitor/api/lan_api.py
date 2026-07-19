"""
FILE: api/lan_api.py
DESCRIPTION: /api/lan/* 핸들러 — 프론트(127.0.0.1 로컬서버)가 LAN 브리지를 제어하는 통로.
             실제 LAN 통신은 lan_bridge.py 프로세스가 하고, 여기서는 로컬 프록시만 한다.
             브리지 포트는 data_dir/lan_bridge_port 파일에서 얻는다(파일 부재=브리지 꺼짐).

REVISION HISTORY:
- 2026-07-19 Claude: 신규 — LAN 브리지 Phase 1 Task 6. project_id 비의존(이식성).
"""
# [WHY 프록시 구조] 프론트 → 로컬서버(lan_api) → 브리지(로컬 9020~). 프론트가 브리지에 직접
#   붙지 않는 이유: 브리지 포트가 동적이라 프론트가 모르고, 기존 UI는 전부 로컬서버 경유라
#   경로 일관성 유지. 브리지 꺼짐/살아있음도 여기서 running 플래그로 흡수.
import json
from pathlib import Path
from urllib.error import URLError
from urllib.request import Request, urlopen

from src.server_utils import send_json


def _bridge_port(data_dir: Path) -> int | None:
    f = Path(data_dir) / 'lan_bridge_port'
    if not f.exists():
        return None
    try:
        return int(f.read_text(encoding='utf-8').strip())
    except (ValueError, OSError):
        return None


def _proxy(data_dir: Path, method: str, subpath: str, body: dict | None = None) -> dict:
    """브리지로 요청 전달. 브리지 꺼짐이면 running:false, 통신 실패면 error."""
    port = _bridge_port(data_dir)
    if not port:
        return {'running': False, 'error': 'LAN 브리지가 꺼져 있음'}
    url = f'http://127.0.0.1:{port}/lan/{subpath}'
    data = json.dumps(body).encode() if body is not None else None
    headers = {'Content-Type': 'application/json'} if data else {}
    try:
        req = Request(url, data=data, method=method, headers=headers)
        with urlopen(req, timeout=20) as resp:
            out = json.loads(resp.read())
        out.setdefault('running', True)
        return out
    except URLError as e:
        # 포트 파일은 있으나 연결 불가 = 브리지 비정상 종료(파일 stale).
        return {'running': False, 'error': f'브리지 통신 실패: {e}'}


def handle_get(handler, path: str, params: dict, *, DATA_DIR) -> bool:
    """GET /api/lan/status — 브리지 상태(온라인 피어·신뢰목록·방화벽·페어링코드)."""
    if path == '/api/lan/status':
        send_json(handler, _proxy(Path(DATA_DIR), 'GET', 'status'))
        return True
    return False


def handle_post(handler, path: str, data: dict, *, DATA_DIR) -> bool:
    """POST /api/lan/{pair-begin,pair-connect,send} — 페어링 개시/연결/파일전송 트리거."""
    dd = Path(DATA_DIR)
    if path == '/api/lan/pair-begin':
        send_json(handler, _proxy(dd, 'POST', 'pair-begin', {}))
        return True
    if path == '/api/lan/pair-connect':
        # body: {ip, http_port, code}
        send_json(handler, _proxy(dd, 'POST', 'pair-connect', data or {}))
        return True
    if path == '/api/lan/send':
        # body: {peer_id, path}
        send_json(handler, _proxy(dd, 'POST', 'send', data or {}))
        return True
    return False
