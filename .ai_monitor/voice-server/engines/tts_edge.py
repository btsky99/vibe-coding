# -*- coding: utf-8 -*-
"""
FILE: .ai_monitor/voice-server/engines/tts_edge.py
DESCRIPTION: edge-tts 낭독 어댑터. 텍스트 → MP3 바이트. 이 앱의 기본 낭독 경로다.

             [WHY 로컬 모델을 버리고 이걸 골랐나 — 2026-08-15 실측]
               후보 6종(MeloTTS·XTTS-v2·OmniVoice·VoxCPM2·Qwen3-TTS·Kokoro)이 전부
               떨어졌다. Kokoro 는 한국어 목소리가 **아예 0개**였다(LANG_CODES 에 k 없음).
               edge-tts 만 통과했고, 대가가 가장 싸다 — 모델 0개, GPU 0, 설치는
               `pip install edge-tts` 한 줄. 이 PC 는 학습을 병행하므로 VRAM 을 무는
               후보(CosyVoice2·IndexTTS2 는 2~5GB)는 애초에 기본값이 될 수 없다.

             [🔴 GPU 를 쓰지 않는다 — 이것이 채택 이유의 절반이다] 2026-08-15 21:34
               학습 OOM 으로 4시간을 잃었다. 합성이 네트워크 너머에서 일어나므로 이 PC 의
               VRAM 은 1바이트도 안 준다.

             [🔴 우리 서버(보드)를 경유하지 않는다] 보드에도 같은 스택이 붙어 있지만,
               각 앱이 각자 부르는 편이 단순하다. 경유하면 보드가 죽을 때 이쪽 낭독도
               같이 죽고, 어느 쪽 장애인지 가리는 일이 새로 생긴다.

             [🔴 네트워크에 의존한다 — 실패는 정상 경로다] 인터넷이 끊기거나 MS 가
               막으면 합성이 실패한다. 그때 조용히 **프론트의 브라우저 내장 합성기**
               (vibe-view/src/lib/browserVoice.ts, 이 PC 의 Heami)로 내려가야 한다.
               **무음은 어떤 경우에도 안 된다** — 폴백 판단은 호출부(voice_server.synthesize
               → 프론트 voiceBus.speak)에 있고, 여기서는 예외를 그대로 올리는 것이
               계약이다(삼키면 폴백이 안 돈다).
             [🔴 이 사이드카 안에는 되돌아갈 길이 없다 — 2026-08-15 정리] 예전엔 sherpa·
               SAPI 어댑터가 같은 프로세스에 있었지만 걷어냈다. 즉 이 파일이 실패하면
               서버가 낼 수 있는 소리는 0 이다. 그래서 예외를 올리는 계약이 전보다
               더 중요해졌다 — 여기서 삼키면 그대로 무음이다.

             [🔴 asyncio 를 요청 스레드마다 새로 연다] 사이드카는 ThreadingHTTPServer 라
               synth 가 매번 다른 스레드에서 불린다. 전역 이벤트 루프를 하나 두면 그 루프가
               붙은 스레드가 아닌 곳에서 부를 때 "attached to a different loop" 로 깨진다.
               asyncio.run() 은 루프 생성·종료를 스레드 안에서 닫으므로 그 문제가 없다.

             [실측 2026-08-15 — 이 PC, 문장 "테스트를 모두 통과했습니다. 커밋할까요?"]
               SunHi 521ms · InJoon 778ms · Hyunsu 1138ms (캐시 적중 시 ~10ms)

REVISION HISTORY:
- 2026-08-15 Claude: 최초 작성 — 로컬 TTS 6종을 대체하는 기본 낭독 엔진
"""

from __future__ import annotations

import asyncio
import os

from . import tts_cache

# 켜고 끄는 스위치(서버 쪽).
# [WHY 프론트 스위치와 둘 다 두나] 프론트 스위치는 이 PC 사용자의 취향이고, 이쪽은
#   '이 기계에서는 아예 쓰지 않는다'는 환경의 결정이다(폐쇄망·오프라인 노드). 환경이
#   껐으면 목록에 아예 안 실려 사용자가 고를 수도 없다.
ENABLED = os.environ.get('VOICE_EDGE', '1').strip().lower() not in ('0', 'false', 'off', 'no')

# 한국어 목소리 3종. [🔴 여기 있는 것만 고를 수 있다] edge 는 수백 개를 제공하지만
#   목록을 통째로 실으면 사용자가 한국어 아닌 것을 골라 낭독이 알아들을 수 없게 된다.
#   `edge-tts --list-voices` 로 늘릴 수 있으나, 늘릴 때는 ko-KR 인지 확인할 것.
VOICES = [
    {
        'id': 'edge:ko-KR-SunHiNeural',
        'label': '선희 (edge-tts)',
        'engine': 'edge',
        'lang': 'ko',
        'note': '여성 · 기본값 · 가장 빠름',
    },
    {
        'id': 'edge:ko-KR-InJoonNeural',
        'label': '인준 (edge-tts)',
        'engine': 'edge',
        'lang': 'ko',
        'note': '남성 · 차분함',
    },
    {
        'id': 'edge:ko-KR-HyunsuMultilingualNeural',
        'label': '현수 (edge-tts)',
        'engine': 'edge',
        'lang': 'ko',
        'note': '남성 · 다국어 혼용 문장에 강함',
    },
]

DEFAULT_VOICE = VOICES[0]['id']


def available() -> bool:
    if not ENABLED:
        return False
    try:
        import edge_tts                                    # noqa: F401
    except Exception:                                      # noqa: BLE001
        return False
    return True


def list_voices() -> list[dict]:
    """설치·허용됐을 때만 목록을 준다. 못 쓰는 목소리를 보여 주면 매번 실패한다."""
    return list(VOICES) if available() else []


def _rate(speed: float) -> str:
    """배율(0.5~1.5) → edge 가 받는 '+10%' 형식.

    [🔴 형식이 어긋나면 조용히 죽는 게 아니라 예외가 난다] edge-tts 는 부호를 반드시
      요구한다('10%' 는 거부, '+10%' 는 통과). 0 도 '+0%' 로 적는다.
    [제약] 상·하한을 우리가 자른다 — 극단값은 알아들을 수 없는 소리가 되고, 그건
      사용자가 '고장'으로 읽는다.
    """
    pct = int(round((max(0.5, min(1.5, float(speed or 1.0))) - 1.0) * 100))
    pct = max(-50, min(50, pct))
    return f'{pct:+d}%'


async def _stream(text: str, voice: str, rate: str) -> bytes:
    import edge_tts

    buf = bytearray()
    # [WHY stream() 인가 — save() 가 아니라] save() 는 파일을 만든다. 우리는 바이트를
    #   HTTP 로 그대로 흘려보내므로 디스크를 거칠 이유가 없다(캐시는 별도 판단).
    async for chunk in edge_tts.Communicate(text, voice, rate=rate).stream():
        if chunk.get('type') == 'audio':
            buf += chunk['data']
    if not buf:
        # [🔴 빈 응답을 성공으로 넘기면 무음이 된다] 연결은 됐는데 오디오가 한 조각도
        #   안 온 경우가 있다(빈 텍스트·차단). 예외로 올려야 호출부가 폴백한다.
        raise RuntimeError('edge-tts 가 오디오를 한 조각도 주지 않았습니다')
    return bytes(buf)


class EdgeEngine:
    """voice_id = 'edge:<edge 목소리 이름>'. 모르는 이름이면 기본값으로 떨어진다."""

    # 이 엔진만 wav 가 아니다. voice_server 가 Content-Type 을 이 값으로 내보낸다.
    mime = 'audio/mpeg'
    ext = 'mp3'

    def __init__(self, voice_id: str = '') -> None:
        vid = voice_id or DEFAULT_VOICE
        name = vid.split(':', 1)[1] if ':' in vid else ''
        known = {v['id'].split(':', 1)[1] for v in VOICES}
        self.voice = name if name in known else DEFAULT_VOICE.split(':', 1)[1]

    def load(self) -> None:
        # [WHY 비어 있나] 올릴 모델이 없다. 인터페이스(engines/__init__.py 불변식)를
        #   맞추기 위한 no-op 이고, 이 '아무것도 안 함'이 edge 를 고른 이유이기도 하다.
        if not available():
            raise RuntimeError('edge-tts 를 쓸 수 없습니다(미설치 또는 VOICE_EDGE=0)')

    def synth(self, text: str, speed: float = 1.0) -> bytes:
        rate = _rate(speed)
        key = tts_cache.key_of('edge', self.voice, rate, text)
        hit = tts_cache.get(key, self.ext)
        if hit is not None:
            return hit
        data = asyncio.run(_stream(text, self.voice, rate))
        tts_cache.put(key, data, self.ext)
        return data
