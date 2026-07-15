"""
FILE: infra/embed_service.py
DESCRIPTION: fastembed 기반 임베딩 서비스 싱글톤 — 회상 v2(pgvector)의 심장.
             warm 모델 1개를 서버 프로세스에 상주시키고 embed_floats(pgvector용)/
             embed(레거시 bytes)/cosine_sim을 제공한다.

REVISION HISTORY:
- 2026-07-15 Claude: load_error() 신설 — 로드 실패 사유를 계측에 노출. pythonw(콘솔 없음)에서
                     print가 유실돼 'fastembed 미설치'가 not_warm으로 위장했던 사각지대 해소
- 2026-06-10 Claude: memory_watcher.py의 고아 임베딩 헬퍼 이관 + embed_floats 신설
                     (자가 치유 2.0 Task 1)
"""
from __future__ import annotations

import os
import threading

# [WHY] 모델 고정 — vector(384) 컬럼 차원과 1:1 결합. 모델 교체 시 컬럼 재생성 필요하므로
# pg_vector_search.ensure_vector_schema가 이 상수를 메타에 기록해 불일치를 감지한다.
EMBED_MODEL_NAME = "sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2"
EMBED_DIM = 384

_embedder = None
_embedder_lock = threading.Lock()
_warming = False              # 백그라운드 워밍업 진행 중 플래그
_warming_lock = threading.Lock()
_load_error = ''              # 마지막 로드 실패 사유 — recall-smart 폴백 로그가 계측에 실어 보냄


def _get_embedder():
    """fastembed 모델 lazy 초기화 — 첫 호출 시 한 번만 로드.

    [제약] 첫 로드는 모델 다운로드(~100MB)로 수십 초 걸릴 수 있음 — 훅 같은
    단명 프로세스에서 호출 금지. 서버/데몬(warm 프로세스) 전용.
    [폴백] 로드 실패(오프라인/EXE 누락) 시 False로 마킹해 재시도 폭주 방지 →
    호출부는 None을 받고 기존 ILIKE 회상 경로로 폴백한다.
    """
    global _embedder, _load_error
    if _embedder is None:
        with _embedder_lock:
            if _embedder is None:
                try:
                    from fastembed import TextEmbedding
                    # [EXE 함정] 홈 디렉토리 오염 방지 — VIBE_EMBED_CACHE 지정 시
                    # 모델 캐시를 DATA_DIR 하위로 고정 (Task 7에서 server.py가 설정)
                    cache_dir = os.environ.get('VIBE_EMBED_CACHE') or None
                    kwargs = {'model_name': EMBED_MODEL_NAME}
                    if cache_dir:
                        kwargs['cache_dir'] = cache_dir
                    _embedder = TextEmbedding(**kwargs)
                    print(f"[Embedding] 모델 로드 완료: {EMBED_MODEL_NAME}")
                except Exception as e:
                    # [과거사고 2026-07-15] venv에 fastembed 미설치 → 여기서 False 확정 →
                    # recall-smart가 영구 'not_warm'으로 위장. pythonw는 print를 버리므로
                    # 사유를 _load_error에 남겨 계측(pg_logs reason)으로 드러낸다.
                    print(f"[Embedding] 모델 로드 실패: {e}")
                    _load_error = f"{type(e).__name__}: {e}"
                    _embedder = False  # 실패 표시 (재시도 방지)
    return _embedder if _embedder else None


def is_available() -> bool:
    """모델 사용 가능 여부 — 로드 시도 없이 상태만 확인.

    [WHY] recall-smart API가 폴백 여부를 빠르게 판단할 때 사용.
    아직 로드 전(None)이면 True 반환 — 첫 호출이 로드를 트리거하게 둔다.
    """
    return _embedder is not False


def load_error() -> str:
    """마지막 모델 로드 실패 사유 (빈 문자열 = 실패 없음). 로드를 트리거하지 않는다."""
    return _load_error


def is_loaded() -> bool:
    """모델이 이미 메모리에 로드됐는지 — 로드를 트리거하지 않는다.

    [제약] 동기 API 핸들러는 이걸로 가드할 것 — 첫 로드(~100MB 다운로드 포함)를
    핸들러에서 트리거하면 HTTP 요청이 수십 초 블로킹된다. 로드는
    run_embedding_backfill 데몬의 워밍업 호출만 담당.
    """
    return _embedder is not None and _embedder is not False


def warm_async() -> None:
    """모델을 백그라운드 스레드에서 로드(논블로킹). 이미 로드/실패/진행중이면 no-op.

    [WHY 닭-달걀 해소] recall-smart는 is_loaded()=False면 fallback을 반환하고 embed_floats를
      부르지 않는다(동기 블로킹 회피) → 모델이 recall 경로로는 영영 로드 안 됨. 유일 로더인
      백필 데몬이 죽거나(embed_floats 일시 실패) 아직 안 뜬 환경(기동 90초 내)에서는 회상 v2가
      영구 비활성. 이 함수를 recall-smart 미로드 게이트에서 호출하면 '이번 요청은 폴백, 다음
      요청부터 벡터 회상'으로 자가 회복한다.
    [불변식] _embedder is False(로드 실패 확정)면 재시도 안 함 — fastembed 부재 환경 폭주 방지.
    """
    global _warming
    if _embedder is not None:  # 로드 성공(객체) 또는 실패 확정(False) → 워밍 불필요
        return
    with _warming_lock:
        if _warming or _embedder is not None:
            return
        _warming = True

    def _run():
        global _warming
        try:
            _get_embedder()  # 자체 _embedder_lock으로 보호 — 여기선 _warming_lock 미보유
        finally:
            _warming = False

    threading.Thread(target=_run, daemon=True, name='embed-warm').start()


def embed_floats(text: str) -> list[float] | None:
    """텍스트 → float 리스트 (pgvector vector(384) INSERT용). 실패 시 None.

    [제약] 512자 절단 — MiniLM 토큰 한도 + 회상 대상은 제목/요약이라 충분.
    """
    try:
        embedder = _get_embedder()
        if embedder is None:
            return None
        vec = list(embedder.embed([text[:512]]))[0]
        return [float(x) for x in vec]
    except Exception as e:
        print(f"[Embedding] 변환 실패: {e}")
        return None


def embed(text: str) -> bytes | None:
    """텍스트 → float32 벡터 bytes — 레거시 호환용 (memory_watcher 재노출 경로)."""
    try:
        import numpy as np
        floats = embed_floats(text)
        if floats is None:
            return None
        return np.array(floats, dtype=np.float32).tobytes()
    except Exception as e:
        print(f"[Embedding] bytes 변환 실패: {e}")
        return None


def cosine_sim(a_bytes: bytes, b_bytes: bytes) -> float:
    """두 float32 벡터 bytes 간 코사인 유사도 (0~1)."""
    try:
        import numpy as np
        a = np.frombuffer(a_bytes, dtype=np.float32)
        b = np.frombuffer(b_bytes, dtype=np.float32)
        denom = np.linalg.norm(a) * np.linalg.norm(b)
        return float(np.dot(a, b) / denom) if denom > 1e-10 else 0.0
    except Exception:
        return 0.0  # 벡터 유사도 계산 실패 — 0.0 반환
