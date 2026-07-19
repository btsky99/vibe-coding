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
import hashlib
import json
import time
from collections import deque
from pathlib import Path
from urllib.error import URLError
from urllib.request import Request, urlopen

from src.server_utils import send_json
from src.pg_lan import save_lan_message, get_lan_messages


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


def _self_id(dd: Path) -> str:
    """브리지 status에서 이 기기 self_id 획득 — 채팅 DB 저장/조회의 '나' 식별자."""
    return _proxy(dd, 'GET', 'status').get('self_id', '')


# ── 자동 공유(auto-share) 안전장치 유틸 ──────────────────────────────
# [WHY] 클로드 자율 판단 발송은 오발송/프라이버시 사고 위험이 커, 서버측에서 강제하는
#   방어선(민감필터·dedup·레이트리밋)을 프론트/스킬이 우회 못하게 여기 고정한다.
#   설계: memory project_lan_auto_share.md (A안, 마스터 토글 기본 OFF).

# [불변식] 파일명(경로 아님) 소문자에 부분일치. 확장자·키워드 양쪽 커버.
_SENSITIVE_PATTERNS = (
    '.env', 'credential', 'secret', 'token', 'password', 'passwd',
    '.pem', '.key', '.pfx', '.p12', 'id_rsa', '.keystore', 'apikey', 'api_key',
)
# [제약] 레이트리밋은 프로세스 메모리(단일 lan_api 프로세스 전제). 재시작 시 리셋 — 스팸
#   억제가 목적이라 영속화 불필요. dedup은 파일로 영속(재시작 후에도 재발송 방지).
_SHARE_SENT_TS: deque = deque()
_RATE_MAX_PER_MIN = 20


def _config(dd: Path) -> dict:
    f = dd / 'config.json'
    if f.exists():
        try:
            return json.loads(f.read_text(encoding='utf-8'))
        except (ValueError, OSError):
            return {}
    return {}


def _is_sensitive(path: str) -> bool:
    """민감 파일이면 True — 발송 차단. 경로 구분자 무관하게 파일명만 검사."""
    name = path.lower().replace('\\', '/').rsplit('/', 1)[-1]
    return any(pat in name for pat in _SENSITIVE_PATTERNS)


def _hash_file(path: str) -> str | None:
    """파일 내용 sha256. dedup 키 — 내용이 바뀌면 해시가 달라져 재발송 허용."""
    try:
        h = hashlib.sha256()
        with open(path, 'rb') as fp:
            for chunk in iter(lambda: fp.read(65536), b''):
                h.update(chunk)
        return h.hexdigest()
    except OSError:
        return None


def _load_seen(dd: Path) -> set:
    f = dd / 'lan_share_seen.json'
    if f.exists():
        try:
            return set(json.loads(f.read_text(encoding='utf-8')))
        except (ValueError, OSError):
            return set()
    return set()


def _save_seen(dd: Path, seen: set) -> None:
    # [제약] 무한 증가 방지 — 최근 500개만 유지. 오래된 해시는 재발송 가능해지지만
    #   실사용상 같은 산출물을 500건 뒤에 다시 보낼 일은 드물어 수용.
    try:
        (dd / 'lan_share_seen.json').write_text(
            json.dumps(sorted(seen)[-500:]), encoding='utf-8')
    except OSError:
        pass


def _rate_ok() -> bool:
    now = time.time()
    while _SHARE_SENT_TS and now - _SHARE_SENT_TS[0] > 60:
        _SHARE_SENT_TS.popleft()
    return len(_SHARE_SENT_TS) < _RATE_MAX_PER_MIN


def _pick_online_peer(dd: Path, req_peer: str):
    """온라인이면서 페어링된(신뢰) 피어를 고른다.
    반환: (peer_dict, reason). peer_dict None이면 reason에 실패 사유.
    [불변식] online ∩ trusted 만 대상 — 발견됐지만 미페어링 피어로는 절대 안 보냄."""
    status = _proxy(dd, 'GET', 'status')
    if not status.get('running', False):
        return None, {'reason': 'bridge_off'}
    online = status.get('online', []) or []
    trusted_ids = {p.get('peer_id') for p in (status.get('trusted', []) or [])}
    paired = [p for p in online if p.get('peer_id') in trusted_ids]
    if req_peer:
        peer = next((p for p in paired if p.get('peer_id') == req_peer), None)
        return (peer, None) if peer else (None, {'reason': 'peer_offline'})
    if len(paired) == 1:
        return paired[0], None
    if not paired:
        return None, {'reason': 'no_peer'}
    return None, {'reason': 'ambiguous', 'peers': paired}


def handle_get(handler, path: str, params: dict, *, DATA_DIR, PROJECT_ID='') -> bool:
    """GET /api/lan/{status,chat}."""
    dd = Path(DATA_DIR)
    if path == '/api/lan/status':
        send_json(handler, _proxy(dd, 'GET', 'status'))
        return True
    if path == '/api/lan/chat':
        peer_id = params.get('peer_id', [''])[0]
        since = params.get('since', ['0'])[0]
        self_id = _self_id(dd)
        # ① 브리지 수신버퍼를 비우며 내 DB로 옮긴다(브리지는 project_id 무지 → 여기서 저장).
        drained = _proxy(dd, 'GET', 'chat-drain')
        for m in drained.get('messages', []):
            save_lan_message(m.get('from_peer', ''), self_id, m.get('content', ''), PROJECT_ID)
        # ② DB에서 나↔peer 대화를 since 커서로 증분 반환.
        rows = get_lan_messages(self_id, peer_id, since, PROJECT_ID) if peer_id else []
        send_json(handler, {'self_id': self_id, 'messages': rows})
        return True
    return False


def handle_post(handler, path: str, data: dict, *, DATA_DIR, PROJECT_ID='') -> bool:
    """POST /api/lan/{pair-begin,pair-connect,send,chat-send}."""
    dd = Path(DATA_DIR)
    if path == '/api/lan/pair-begin':
        send_json(handler, _proxy(dd, 'POST', 'pair-begin', {}))
        return True
    if path == '/api/lan/pair-connect':
        send_json(handler, _proxy(dd, 'POST', 'pair-connect', data or {}))   # {ip, http_port, code}
        return True
    if path == '/api/lan/send':
        send_json(handler, _proxy(dd, 'POST', 'send', data or {}))           # {peer_id, path}
        return True
    if path == '/api/lan/chat-send':
        peer_id = (data or {}).get('peer_id', '')
        content = (data or {}).get('content', '')
        res = _proxy(dd, 'POST', 'chat-send', {'peer_id': peer_id, 'content': content})
        if res.get('ok'):
            # 내 발신분도 내 DB에 기록(양쪽이 각자 자기 DB에 이력 보유).
            save_lan_message(_self_id(dd), peer_id, content, PROJECT_ID)
        send_json(handler, res)
        return True
    if path == '/api/lan/auto-share':
        # [WHY] 클로드 자율 판단 발송의 서버측 관문. 입력 {files:[path...], summary, peer_id?}.
        #   마스터 토글 OFF면 no-op — 우회 불가하게 여기서 강제한다.
        if not _config(dd).get('lan_auto_share_enabled', False):
            send_json(handler, {'ok': False, 'reason': 'disabled'})
            return True
        files = (data or {}).get('files', []) or []
        summary = (data or {}).get('summary', '') or ''
        peer, err = _pick_online_peer(dd, (data or {}).get('peer_id', '') or '')
        if peer is None:
            send_json(handler, {'ok': False, **err})
            return True
        if not _rate_ok():
            send_json(handler, {'ok': False, 'reason': 'rate_limited'})
            return True
        peer_id = peer.get('peer_id', '')
        seen = _load_seen(dd)
        sent_files, skipped = [], []
        for fp in files:
            if _is_sensitive(fp):
                skipped.append({'path': fp, 'why': 'sensitive'}); continue
            fh = _hash_file(fp)
            if fh is None:
                skipped.append({'path': fp, 'why': 'unreadable'}); continue
            if ('f:' + fh) in seen:
                skipped.append({'path': fp, 'why': 'dup'}); continue
            if not _rate_ok():
                skipped.append({'path': fp, 'why': 'rate_limited'}); continue
            r = _proxy(dd, 'POST', 'send', {'peer_id': peer_id, 'path': fp})
            if r.get('ok'):
                sent_files.append(fp); seen.add('f:' + fh); _SHARE_SENT_TS.append(time.time())
            else:
                skipped.append({'path': fp, 'why': 'send_failed', 'detail': r.get('error', 'unknown')})
        summary_sent = False
        if summary:
            s = summary[:8000]   # 브리지 chat 상한(8KB) 상속
            skey = 's:' + hashlib.sha256(s.encode('utf-8')).hexdigest()
            if skey not in seen and _rate_ok():
                r = _proxy(dd, 'POST', 'chat-send', {'peer_id': peer_id, 'content': s})
                if r.get('ok'):
                    summary_sent = True; seen.add(skey); _SHARE_SENT_TS.append(time.time())
                    save_lan_message(_self_id(dd), peer_id, s, PROJECT_ID)
        _save_seen(dd, seen)
        send_json(handler, {
            'ok': True, 'peer': peer.get('name') or peer_id, 'peer_id': peer_id,
            'sent_files': sent_files, 'skipped': skipped, 'summary_sent': summary_sent,
        })
        return True
    return False
