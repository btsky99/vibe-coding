"""
FILE: infra/embed_service.py
DESCRIPTION: fastembed 기반 임베딩 서비스 싱글톤 — 회상 v2(pgvector)의 심장.
             warm 모델 1개를 서버 프로세스에 상주시키고 embed_floats(pgvector용)/
             embed(레거시 bytes)/cosine_sim을 제공한다.

REVISION HISTORY:
- 2026-08-14 Claude: 모델을 multilingual-e5-small로 교체 — 기존 모델이 fastembed 0.8의
                     풀링 변경으로 **순위가 뒤집혀** 있었다(아래 과거사고). + EMBED_SIGNATURE 도입
- 2026-07-15 Claude: load_error() 신설 — 로드 실패 사유를 계측에 노출. pythonw(콘솔 없음)에서
                     print가 유실돼 'fastembed 미설치'가 not_warm으로 위장했던 사각지대 해소
- 2026-06-10 Claude: memory_watcher.py의 고아 임베딩 헬퍼 이관 + embed_floats 신설
                     (자가 치유 2.0 Task 1)
"""
from __future__ import annotations

import os
import threading

# ═══════════════════════════════════════════════════════════════════════════
# [🔴🔴 과거사고 2026-08-14 — 회상이 "아무 질문에나 쓰레기를 반환"하던 진짜 원인]
#
#   fastembed 0.8이 paraphrase-multilingual-MiniLM-L12-v2의 풀링을 **CLS → MEAN으로
#   바꿨다**(라이브러리가 로드할 때마다 UserWarning으로 경고하고 있었다). 모델 **이름은
#   그대로**여서 아래 불일치 가드도, 계측(커버리지 100% 🟢)도 전부 통과했다.
#
#   실측 결과(지식노트 452건, 질의 5건):
#     현행 모델 : top3 적중 2/5 · 관련 최저 0.470 / 무관 최고 0.563 → 간격 **-0.093**
#     e5-small : top3 적중 4/5 · 관련 최저 0.879 / 무관 최고 0.840 → 간격 **+0.039**
#   "설치본에서 데몬 파이썬 실행기를 어떻게 고르지"의 정답 노트가 **452건 중 364위**였다.
#
#   🔴 교훈: 간격이 음수면 **어떤 임계값으로도 못 가른다.** 2026-08-08부터 6일간
#     0.45→0.55→0.66으로 임계를 만진 것은 전부 헛수고였다 — 순위 자체가 뒤집혀 있었다.
#     임계값을 의심하기 전에 **랭킹(정답 순위)을 먼저 재라**. scripts/recall_quality.py.
#
#   🔴 재발 방지: EMBED_SIGNATURE에 라이브러리 버전과 풀링을 함께 넣는다. 모델 이름만
#     비교하면 같은 이름으로 벡터 공간이 통째로 바뀌는 이 사고를 또 못 잡는다.
# ═══════════════════════════════════════════════════════════════════════════

# [WHY e5] 다국어 검색 전용으로 학습돼 한국어 기술문서에서 순위가 안정적이고, 384차원이라
#   기존 vector(384) 컬럼을 **그대로 쓴다**(스키마 마이그레이션 불필요).
# [제약] e5 계열은 비대칭 검색 모델이다 — 질의는 'query: ', 문서는 'passage: ' 접두어가
#   **필수**다. 빼면 성능이 눈에 띄게 떨어진다. embed_floats(kind=)가 이걸 강제한다.
# [제약] e5는 코사인이 0.7~0.9의 좁은 띠에 몰린다. 절대 임계값보다 **순위**가 정보다 —
#   pg_vector_search의 임계는 이 특성에 맞춰 잡는다.
EMBED_MODEL_NAME = "e5-small-ml"
_HF_REPO = "intfloat/multilingual-e5-small"
EMBED_DIM = 384

# [불변식] 벡터 공간을 바꾸는 **모든 요소**를 여기에 적는다. 이 문자열이 달라지면
#   저장된 벡터는 전부 무효다 — pg_vector_search가 이 값을 메타와 대조해 차단한다.
def _lib_version() -> str:
    try:
        import importlib.metadata as _md
        return _md.version('fastembed')
    except Exception:
        return '?'


EMBED_SIGNATURE = f"{_HF_REPO}|dim{EMBED_DIM}|mean|e5-prefix|fastembed{_lib_version()}"

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
                    from fastembed.common.model_description import (
                        PoolingType, ModelSource,
                    )
                    # [WHY 커스텀 등록] multilingual-e5-small은 fastembed 기본 목록에
                    #   없다(목록의 384차원 다국어 모델은 위 사고를 낸 그것 하나뿐).
                    #   add_custom_model로 풀링·정규화를 **코드가 명시**해 두면
                    #   라이브러리가 기본값을 바꿔도 우리 벡터 공간은 안 흔들린다 —
                    #   이번 사고의 직접적 재발 방지선이다.
                    try:
                        TextEmbedding.add_custom_model(
                            model=EMBED_MODEL_NAME, pooling=PoolingType.MEAN,
                            normalization=True, sources=ModelSource(hf=_HF_REPO),
                            dim=EMBED_DIM, model_file='onnx/model.onnx',
                            description='multilingual-e5-small (회상 v2)',
                        )
                    except ValueError:
                        pass  # 이미 등록됨(같은 프로세스에서 재호출) — 정상
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


def embed_floats(text: str, kind: str = 'passage') -> list[float] | None:
    """텍스트 → float 리스트 (pgvector vector(384) INSERT용). 실패 시 None.

    [🔴 제약 — e5 접두어] kind='query'(검색어) / 'passage'(저장 대상)를 **반드시 구분**한다.
      e5는 비대칭 검색 모델이라 접두어가 곧 역할 지정이다. 둘을 뒤섞으면(둘 다 passage로
      넣는 등) 순위가 흐트러진다 — 겉으로는 여전히 숫자가 나오므로 조용히 나빠진다.
      기본값을 'passage'로 둔 이유: 호출부 대다수(백필/저장 경로)가 문서 쪽이고,
      검색 경로는 memory_api 한 곳뿐이라 그쪽만 명시하면 된다.
    [제약] 512자 절단 — 토큰 한도 + 회상 대상은 제목/요약이라 충분.
    """
    try:
        embedder = _get_embedder()
        if embedder is None:
            return None
        prefix = 'query: ' if kind == 'query' else 'passage: '
        vec = list(embedder.embed([prefix + text[:512]]))[0]
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
