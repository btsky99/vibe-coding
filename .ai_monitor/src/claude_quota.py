"""
FILE: src/claude_quota.py
DESCRIPTION: Claude Code CLI의 OAuth 토큰을 재사용해 Anthropic 사용량 엔드포인트
             (/api/oauth/usage)에서 5시간/7일 쿼터 사용률(%)·리셋 시각을 조회한다.
             hive_api의 /api/context-usage 응답 'quota' 필드 공급자.
             API 키 발급·추가 로그인 불필요 (CodexBar steipete/CodexBar 방식 이식).

REVISION HISTORY:
- 2026-07-03 Claude: 신규 생성 — JSONL 절대값 집계로는 쿼터 한도 대비 %를 알 수 없던
                     한계 해소. 실패 시 available=False 강등 → 프론트가 기존 표시로 폴백.
"""

import json
import threading
import time
import urllib.error
import urllib.request
from pathlib import Path

# [외부 의존 가정] 비공개 베타 엔드포인트 — Claude Code CLI 자신이 상태줄 사용량에
# 쓰는 것과 동일하다. 스펙이 예고 없이 바뀔 수 있으므로 어떤 실패든 예외를 삼키고
# available=False만 반환한다. 프론트(TerminalSlot)는 그 경우 JSONL 절대값 표시 유지.
_USAGE_URL = 'https://api.anthropic.com/api/oauth/usage'
_BETA_HEADER = 'oauth-2025-04-20'

# [WHY] 성공 60s 캐시: 프론트 폴링(수 초 간격)이 그대로 API를 때리면 429 위험.
# 실패는 180s 쿨다운 — 토큰 만료/오프라인 상태에서 매 폴링마다 재시도하지 않게.
_TTL_OK = 60.0
_TTL_FAIL = 180.0

# [제약] server.py는 스레드당 요청 처리 — 캐시 접근은 lock 보호.
# fetch 자체는 lock 밖에서 수행 (10s 타임아웃 동안 다른 요청을 막지 않기 위해).
# 드물게 중복 fetch가 발생할 수 있으나 읽기 전용 GET이라 무해.
_lock = threading.Lock()
_cache: dict = {'ts': 0.0, 'data': None}


def _read_oauth() -> tuple:
    """~/.claude/.credentials.json에서 (accessToken, 플랜 라벨, 실패 사유)를 읽는다.

    [호환성 가정] Windows/Linux는 파일 저장. macOS는 Keychain이라 이 파일이 없을 수
    있음 — 그 경우 available=False로 강등될 뿐 다른 기능엔 영향 없음.
    """
    creds_path = Path.home() / '.claude' / '.credentials.json'
    if not creds_path.exists():
        return '', '', 'credentials_not_found'
    try:
        creds = json.loads(creds_path.read_text(encoding='utf-8'))
    except Exception:
        return '', '', 'credentials_unreadable'
    oauth = creds.get('claudeAiOauth') or {}
    token = oauth.get('accessToken') or ''
    if not token:
        return '', '', 'no_access_token'
    # expiresAt은 epoch 밀리초. 만료 토큰으로 401 받는 대신 여기서 스킵 —
    # 갱신은 Claude CLI가 다음 실행 때 수행하므로 우리는 기다리기만 한다.
    expires_ms = oauth.get('expiresAt') or 0
    if expires_ms and (expires_ms / 1000.0) < time.time():
        return '', '', 'token_expired'
    plan = oauth.get('subscriptionType') or ''
    tier = oauth.get('rateLimitTier') or ''
    # 표시용 라벨: "max (20x)" 형태. tier 예: default_claude_max_20x
    label = plan
    if '20x' in tier:
        label = f'{plan} 20x'
    elif '5x' in tier:
        label = f'{plan} 5x'
    return token, label, ''


def _window(raw) -> dict | None:
    """윈도우 응답({utilization, resets_at, ...}) → 필요한 필드만 축약. 형식 불일치 시 None."""
    if not isinstance(raw, dict):
        return None
    util = raw.get('utilization')
    if util is None:
        return None
    return {'utilization': util, 'resets_at': raw.get('resets_at') or ''}


def _fetch(token: str) -> dict:
    """엔드포인트 1회 호출 → 축약 dict. 예외는 호출자에게 전파."""
    req = urllib.request.Request(
        _USAGE_URL,
        headers={
            'Authorization': f'Bearer {token}',
            'Accept': 'application/json',
            'Content-Type': 'application/json',
            'anthropic-beta': _BETA_HEADER,
            # [WHY] CLI로 위장하지 않는 식별 가능한 UA — CodexBar도 자체 UA 사용
            'User-Agent': 'vibe-coding-dashboard/1.0 (usage-monitor)',
        },
        method='GET',
    )
    with urllib.request.urlopen(req, timeout=10) as resp:
        data = json.loads(resp.read().decode('utf-8'))
    return {
        'five_hour': _window(data.get('five_hour')),
        'seven_day': _window(data.get('seven_day')),
        # 플랜에 따라 null — 존재할 때만 프론트가 표시
        'seven_day_opus': _window(data.get('seven_day_opus')),
        'seven_day_sonnet': _window(data.get('seven_day_sonnet')),
    }


def get_claude_quota() -> dict:
    """캐시된 쿼터 사용률 조회. 항상 dict 반환 (예외 없음).

    성공: {'available': True, 'plan': str, 'five_hour': {...}, 'seven_day': {...}, ...}
    실패: {'available': False, 'reason': str}
    """
    now = time.time()
    with _lock:
        cached = _cache['data']
        if cached is not None:
            ttl = _TTL_OK if cached.get('available') else _TTL_FAIL
            if now - _cache['ts'] < ttl:
                return cached

    token, plan_label, reason = _read_oauth()
    if not token:
        result = {'available': False, 'reason': reason}
    else:
        try:
            windows = _fetch(token)
            result = {'available': True, 'plan': plan_label, **windows}
        except urllib.error.HTTPError as e:
            # 401=토큰 무효(파일은 미만료지만 서버가 거부), 429=레이트리밋 등
            result = {'available': False, 'reason': f'http_{e.code}'}
        except Exception as e:
            result = {'available': False, 'reason': type(e).__name__}

    with _lock:
        _cache['data'] = result
        _cache['ts'] = time.time()
    return result
