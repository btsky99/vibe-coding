# ────────────────────────────────────────────────────────────────────────────
# 📄 파일명: src/recall_client.py
# 📝 설명: 훅(단명 프로세스)용 회상 클라이언트 — 서버 recall-smart API 우선,
#          실패 시 회상 v1(ILIKE) 직접 호출 폴백. 자가 치유 2.0 ④ (Task 5).
# 🕒 변경 이력:
# [2026-06-10] Claude — 신설
#   - [제약] 호출자는 hive_hook.py(UserPromptSubmit) — 총 지연 상한 2초.
#     이 모듈에서 fastembed를 import/로드하는 것 절대 금지 (모델 로드 수십 초).
#   - [WHY] 포트 탐색은 hook_bridge.py:57 패턴 재사용 — VIBE_SERVER_PORT 우선,
#     없으면 9000번대 스캔. 헬스 프로브 0.3초 × 최대 20포트지만 보통 9000 즉답.
#   - [불변식] 어떤 실패에서도 예외를 밖으로 던지지 않는다 — 훅 전체 중단 금지.
# ────────────────────────────────────────────────────────────────────────────
import json
import os
import urllib.request as _urllib_request

_RECALL_TIMEOUT = 2.0  # 훅 지연 상한 — 서버가 이 안에 못 주면 v1 폴백


def _find_active_server_port(start: int = 9000, count: int = 20) -> int | None:
    """응답하는 서버 포트 탐색. 못 찾으면 None — 호출부가 즉시 폴백."""
    env_port = os.getenv('VIBE_SERVER_PORT')
    if env_port:
        try:
            return int(env_port)
        except ValueError:
            pass
    for port in range(start, start + count):
        try:
            _urllib_request.urlopen(
                f'http://localhost:{port}/api/hive/health', timeout=0.3)
            return port
        except Exception:
            continue
    return None


def _fallback_summary(query: str, limit: int) -> str:
    """회상 v1 — 서버 없이도 동작하는 ILIKE 경로 (외부 프로젝트 CLI 환경 포함)."""
    parts = []
    try:
        from src.pg_store import recall_context_summary, recall_knowledge_summary
        s1 = recall_context_summary(query, limit=min(limit, 3))
        if s1:
            parts.append(s1)
        s2 = recall_knowledge_summary(query, limit=min(limit, 3))
        if s2:
            parts.append(s2)
    except Exception:
        pass
    return '\n'.join(parts)


def smart_recall_summary(query: str, limit: int = 5) -> str:
    """통합 회상 — 주입할 텍스트를 반환. 빈 문자열이면 '주입할 것 없음'.

    경로: ① 서버 recall-smart(임베딩, 0.45 임계) → ② 서버가 폴백 응답이면
    그 안의 v1 요약 사용 → ③ 서버 자체 불통이면 로컬 v1 직접 호출.
    """
    query = (query or '').strip()
    if not query:
        return ''
    port = _find_active_server_port()
    if port is not None:
        try:
            req = _urllib_request.Request(
                f'http://localhost:{port}/api/memory/recall-smart',
                data=json.dumps({'query': query, 'limit': limit}).encode('utf-8'),
                headers={'Content-Type': 'application/json'},
                method='POST',
            )
            with _urllib_request.urlopen(req, timeout=_RECALL_TIMEOUT) as resp:
                body = json.loads(resp.read().decode('utf-8'))
            # fallback=True여도 서버가 만든 v1 요약이 있으면 그대로 사용
            summary = str(body.get('summary') or '')
            if summary or not body.get('fallback'):
                # fallback=False + 빈 summary = "관련 지식 없음" 판정 — 주입 생략
                return summary
        except Exception:
            pass  # 서버 불통/타임아웃 → 로컬 폴백
    return _fallback_summary(query, limit)
