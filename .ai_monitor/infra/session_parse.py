"""
FILE: infra/session_parse.py
DESCRIPTION: CLI 세션 파일(JSONL/JSON) 토큰 usage 파서 모음.
             Claude Code 세션(.jsonl 꼬리 파싱)과 Antigravity CLI 세션(.json 전체)
             에서 컨텍스트 사용량 배지용 usage 정보를 추출한다.
             server.py 모듈 전역 순수 함수였던 것을 top-level 무상태 함수로 이전
             (Phase 2 Task 12 / R13) — 외부 전역 캡처 없이 Path 인자만 받는다.

REVISION HISTORY:
- 2026-07-06 Claude: server.py 세션 파서 2개(_parse_session_tail/_parse_antigravity_session)
                     분리 (Phase 2 Task 12 / R13). 클로저가 아닌 순수 함수라 시그니처·
                     로직·주석 verbatim 유지, 호출부(hive_api.handle_get 주입)만 경로 변경.
- 2026-08-14 Claude: claude_ctx_window를 hive_api에서 이관 — src/session_binding이
                     같은 매핑을 필요로 해 두 벌이 될 뻔했다(모델 추가 시 한쪽만
                     갱신되면 점유율이 5배 틀어진다: 1M 모델을 200k로 계산).
"""
from __future__ import annotations

import json
from pathlib import Path


# ── Claude 모델별 컨텍스트 창 매핑 ─────────────────────────────────────────
# Session JSONL의 `model` 필드는 base ID만 기록한다(`[1m]` 접미사 없음).
# Opus 4.7은 Claude Code CLI가 1M 컨텍스트로 구동하므로 1M으로 취급한다.
def claude_ctx_window(model: str) -> int:
    """모델명 → 컨텍스트 창 토큰 수. 알 수 없는 모델은 200k 기본.

    [불변식] 이 함수가 유일 원천 — 사용률(%)의 분모라 여기가 틀리면 리사이클이
      멀쩡한 세션을 죽이거나(과소 추정) 임계를 영영 못 넘는다(과대 추정).
    """
    if not model:
        return 200_000
    m = model.lower()
    # Opus 4.7 이상은 1M 컨텍스트 (Claude Code CLI 기본 운용)
    if 'opus-4-7' in m or 'opus-4-8' in m or 'opus-5' in m:
        return 1_000_000
    # 향후 확장: Sonnet 1M 변종 추가 시 여기에 조건 추가
    return 200_000


def parse_session_tail(path: Path, tail_bytes: int = 8192):
    """Claude Code 세션 JSONL 파일 꼬리에서 마지막 토큰 usage 정보 추출.

    대형 파일(수천 줄)의 불필요한 전체 읽기를 피하기 위해 파일 끝 일부만 읽어
    마지막 assistant 메시지의 usage 필드를 파싱합니다.
    발견 못하면 None 반환.

    [2026-08-14] tail_bytes를 인자로 뺐다 — 기본 8KB는 거대한 tool_result 한 줄에
      통째로 먹혀 usage를 놓친다(실측: 활발히 도는 세션이 model='unknown'/0토큰).
      기본값은 그대로라 기존 호출부 동작은 불변. 넓혀 읽는 판단은 호출부 몫이다
      (src/session_binding.parse_usage_deep).
    """
    try:
        TAIL_BYTES = max(1024, int(tail_bytes))
        with open(path, 'rb') as f:
            f.seek(0, 2)                      # 파일 끝으로 이동
            size = f.tell()
            f.seek(max(0, size - TAIL_BYTES)) # 끝 8KB 위치로
            raw = f.read().decode('utf-8', errors='ignore')

        # 완전한 줄만 추출 (첫 줄은 잘릴 수 있으므로 제외)
        lines = [l.strip() for l in raw.splitlines() if l.strip()]

        session_id = slug = model = cwd = last_ts = ''
        input_tokens = output_tokens = cache_read = cache_write = 0

        # 역순으로 탐색 → 가장 최신 데이터 우선
        for line in reversed(lines):
            try:
                obj = json.loads(line)
            except Exception:
                continue  # JSONL 개별 행 파싱 실패 허용

            # 세션 메타 수집 (처음 발견 시만 기록)
            if not session_id and obj.get('sessionId'):
                session_id = obj['sessionId']
            if not slug and obj.get('slug'):
                slug = obj['slug']
            if not cwd and obj.get('cwd'):
                cwd = obj['cwd']
            if not last_ts and obj.get('timestamp'):
                last_ts = obj['timestamp']

            # assistant 메시지에서 usage 추출
            if obj.get('type') == 'assistant' and isinstance(obj.get('message'), dict):
                usage = obj['message'].get('usage', {})
                if usage.get('input_tokens'):
                    if not model:
                        model = obj['message'].get('model', '')
                    input_tokens = usage.get('input_tokens', 0)
                    output_tokens = usage.get('output_tokens', 0)
                    cache_read = usage.get('cache_read_input_tokens', 0)
                    cache_write = usage.get('cache_creation_input_tokens', 0)
                    if not last_ts:
                        last_ts = obj.get('timestamp', '')
                    break  # 가장 최신 usage 찾으면 즉시 종료

        if not session_id:
            return None  # 유효한 세션 파일 아님

        return {
            'session_id': session_id,
            'slug': slug or path.stem[:12],   # slug 없으면 파일명 앞 12자
            'model': model or 'unknown',
            'input_tokens': input_tokens,
            'output_tokens': output_tokens,
            'cache_read': cache_read,
            'cache_write': cache_write,
            'last_ts': last_ts,
            'cwd': str(cwd).replace('\\', '/'),
        }
    except Exception as e:
        print(f"[FILE ERROR] parse_session_tail: {e}")
        return None


def parse_antigravity_session(path: Path):
    """Antigravity CLI 세션 JSON 파일에서 최신 토큰 usage 정보 추출.

    ~/.gemini/tmp/{project}/chats/session-*.json 파일을 읽어
    가장 최근 antigravity 타입 메시지의 tokens 필드를 파싱합니다.
    tokens 구조: { input, output, cached, thoughts, tool, total }
    [2026-02-27] Claude: Antigravity 컨텍스트 사용량 표시 기능 추가
    """
    try:
        with open(path, 'r', encoding='utf-8') as f:
            data = json.load(f)

        session_id = data.get('sessionId', '')
        if not session_id:
            return None  # 유효한 세션 파일 아님

        last_updated = data.get('lastUpdated', '')
        messages = data.get('messages', [])

        input_tokens = output_tokens = cached_tokens = 0
        model = ''

        # 역순으로 antigravity 타입 메시지 탐색 → 가장 최신 usage 우선
        for msg in reversed(messages):
            if msg.get('type') == 'antigravity':
                tokens = msg.get('tokens', {})
                if tokens.get('input'):
                    input_tokens  = tokens.get('input', 0)
                    output_tokens = tokens.get('output', 0)
                    cached_tokens = tokens.get('cached', 0)
                    model = msg.get('model', 'antigravity')
                    break

        return {
            'session_id':   session_id,
            'slug':         session_id[:8],        # 앞 8자리로 슬러그 대체
            'model':        model or 'antigravity',
            'input_tokens': input_tokens,
            'output_tokens': output_tokens,
            'cache_read':   cached_tokens,
            'last_ts':      last_updated,
            'cwd':          '',
        }
    except Exception as e:
        print(f"[FILE ERROR] parse_antigravity_session: {e}")
        return None
