"""
FILE: src/codex_quota.py
DESCRIPTION: Codex CLI(OpenAI)의 플랜 쿼터 사용률(5h/7d %) 공급자.
             1차: ~/.codex/auth.json 토큰으로 ChatGPT 백엔드 wham/usage 조회 (실시간).
             2차: 토큰 만료/네트워크 실패 시 ~/.codex/sessions/**.jsonl의 마지막
             rate_limits 이벤트 파싱 (stale=True + observed_at 표기).
             hive_api의 /api/agent-quota 응답 'codex' 필드 공급자.

REVISION HISTORY:
- 2026-07-04 Claude: 신규 생성 — 터미널 슬롯 헤더 쿼터 배지에 Codex도 표시 (claude_quota와 동일 계약)
"""

import json
import threading
import time
from datetime import datetime, timezone
from pathlib import Path

# [외부 의존 가정] wham/usage는 비공개 백엔드 — Codex CLI/CodexBar가 쓰는 엔드포인트.
# 401(token_expired)이면 Codex CLI가 다음 실행 때 토큰을 갱신할 때까지 세션 파일 폴백.
# 우리가 refresh_token으로 직접 갱신하지 않는 이유: auth.json을 재작성하다 Codex CLI와
# 동시 쓰기가 겹치면 로그인 자체가 깨질 수 있음 — 읽기 전용 유지가 안전.
_USAGE_URL = 'https://chatgpt.com/backend-api/wham/usage'

# [WHY] claude_quota와 동일한 캐시 정책 — 성공 60s / 실패 180s.
_TTL_OK = 60.0
_TTL_FAIL = 180.0

_lock = threading.Lock()
_cache: dict = {'ts': 0.0, 'data': None}


def _epoch_to_iso(sec) -> str:
    """rate_limits.resets_at(epoch 초) → ISO 문자열. 프론트 fmtReset과 호환."""
    try:
        return datetime.fromtimestamp(float(sec), tz=timezone.utc).isoformat()
    except Exception:
        return ''


def _window_from_rl(rl) -> dict | None:
    """rate_limits.primary/secondary({used_percent, resets_at, ...}) → claude_quota와 동일 축약형."""
    if not isinstance(rl, dict):
        return None
    used = rl.get('used_percent')
    if used is None:
        return None
    return {'utilization': used, 'resets_at': _epoch_to_iso(rl.get('resets_at'))}


def _shape(rate_limits: dict) -> dict | None:
    """rate_limits 블록(primary=5h, secondary=7d 관례) → 응답 골격. 형식 불일치 시 None."""
    five = _window_from_rl(rate_limits.get('primary'))
    seven = _window_from_rl(rate_limits.get('secondary'))
    if five is None and seven is None:
        return None
    return {
        'available': True,
        'plan': rate_limits.get('plan_type') or '',
        'five_hour': five,
        'seven_day': seven,
    }


def _read_auth() -> tuple:
    """~/.codex/auth.json → (access_token, account_id). 없으면 ('', '')."""
    p = Path.home() / '.codex' / 'auth.json'
    if not p.exists():
        return '', ''
    try:
        d = json.loads(p.read_text(encoding='utf-8'))
    except Exception:
        return '', ''
    tokens = d.get('tokens') or {}
    return tokens.get('access_token') or '', tokens.get('account_id') or ''


def _fetch_api(token: str, account_id: str) -> dict | None:
    """wham/usage 1회 호출. 응답에서 rate_limits 블록을 찾으면 축약형, 못 찾으면 None.

    [외부 의존 가정] 응답 스키마 미공개 — 최상위 또는 'rate_limits' 키 아래에
    primary/secondary가 온다고 가정하고 방어적으로 양쪽 다 시도한다.
    """
    import urllib.request
    req = urllib.request.Request(
        _USAGE_URL,
        headers={
            'Authorization': f'Bearer {token}',
            'chatgpt-account-id': account_id,
            'Accept': 'application/json',
            'User-Agent': 'vibe-coding-dashboard/1.0 (usage-monitor)',
        },
        method='GET',
    )
    with urllib.request.urlopen(req, timeout=10) as resp:
        data = json.loads(resp.read().decode('utf-8'))
    if not isinstance(data, dict):
        return None
    for block in (data.get('rate_limits'), data):
        shaped = _shape(block) if isinstance(block, dict) else None
        if shaped:
            return shaped
    return None


def _latest_session_file() -> Path | None:
    """~/.codex/sessions/YYYY/MM/DD/*.jsonl 중 mtime 최신 파일."""
    root = Path.home() / '.codex' / 'sessions'
    if not root.exists():
        return None
    try:
        files = list(root.glob('*/*/*/*.jsonl'))
        return max(files, key=lambda f: f.stat().st_mtime) if files else None
    except Exception:
        return None


def _fetch_sessions() -> dict | None:
    """최신 세션 jsonl의 마지막 rate_limits 이벤트 → 축약형 + stale 표기.

    [제약] 파일 끝 256KB만 읽음 — 세션 파일은 수 MB까지 자라고 rate_limits는
    매 턴 기록되므로 tail만으로 충분. 전체 파싱은 폴링 경로에서 과비용.
    """
    f = _latest_session_file()
    if f is None:
        return None
    try:
        size = f.stat().st_size
        with open(f, 'rb') as fh:
            fh.seek(max(0, size - 256 * 1024))
            tail = fh.read().decode('utf-8', errors='replace')
        for line in reversed(tail.splitlines()):
            if '"rate_limits"' not in line:
                continue
            try:
                evt = json.loads(line)
            except Exception:
                continue
            # rate_limits는 payload 깊이에 있을 수 있어 재귀 탐색
            rl = _find_rate_limits(evt)
            shaped = _shape(rl) if rl else None
            if shaped:
                shaped['stale'] = True
                shaped['observed_at'] = datetime.fromtimestamp(
                    f.stat().st_mtime, tz=timezone.utc).isoformat()
                return shaped
        return None
    except Exception:
        return None


def _find_rate_limits(node, depth: int = 0):
    """이벤트 JSON에서 'rate_limits' dict를 깊이 4까지 탐색. 스키마 버전차 흡수용."""
    if depth > 4 or not isinstance(node, dict):
        return None
    if isinstance(node.get('rate_limits'), dict):
        return node['rate_limits']
    for v in node.values():
        found = _find_rate_limits(v, depth + 1)
        if found:
            return found
    return None


def get_codex_quota() -> dict:
    """캐시된 Codex 쿼터 조회. 항상 dict 반환 (예외 없음) — claude_quota와 동일 계약.

    성공: {'available': True, 'plan': str, 'five_hour': {...}, 'seven_day': {...},
           ('stale': True, 'observed_at': iso — 세션 파일 폴백일 때만)}
    실패: {'available': False, 'reason': str}
    """
    now = time.time()
    with _lock:
        cached = _cache['data']
        if cached is not None:
            ttl = _TTL_OK if cached.get('available') else _TTL_FAIL
            if now - _cache['ts'] < ttl:
                return cached

    import urllib.error
    token, account_id = _read_auth()
    result = None
    if token:
        try:
            result = _fetch_api(token, account_id)
        except (urllib.error.HTTPError, Exception):
            result = None  # 401/스키마 변경/오프라인 전부 세션 폴백으로
    if result is None:
        result = _fetch_sessions()
    if result is None:
        result = {'available': False,
                  'reason': 'no_auth' if not token else 'api_and_session_failed'}

    with _lock:
        _cache['data'] = result
        _cache['ts'] = time.time()
    return result
