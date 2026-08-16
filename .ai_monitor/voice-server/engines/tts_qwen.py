# -*- coding: utf-8 -*-
"""
FILE: .ai_monitor/voice-server/engines/tts_qwen.py
DESCRIPTION: 낭독 엔진 — Qwen3-TTS 로 사장님 목소리를 복제해 읽는다.

             [WHY 두 번째 엔진이 생겼나 — 2026-08-16 청취 판정] edge-tts 는 남의 목소리다.
               사장님 샘플(25.7초)로 복제한 Qwen3-TTS-12Hz-0.6B-Base 를 직접 들으시고
               "속도 맞춤보다 그냥이 훨씬 좋은데. 굿. 교체 진행해보자" 로 채택됐다.
               edge 는 걷어내지 않는다 — 이 엔진이 못 뜨면(GPU 점유·모델 없음) 소리가
               아예 안 나기 때문이다. voice_server._new_engine 이 접두사로 가른다.

             [🔴 속도를 손대지 않는다] 6.5자/초로 맞춘 판을 같이 들려드렸는데 사장님이
               '그냥'(원본 속도)을 고르셨다. 그래서 synth 의 speed 인자를 무시한다.
               무시한다는 사실 자체가 결정이므로 조용히 받아만 두지 않고 여기에 적는다.

             [🔴 이 엔진은 GPU 를 계속 문다 — 그 대가를 알고 쓴다] 모델 ~2.2GB 가 상주해야
               문장당 지연이 산다. 같은 카드에서 학습이 돌면 그만큼 학습 몫이 준다.
               그래서 load() 는 여유 VRAM 을 재고 FLOOR_MB 밑이면 올리지 않고 예외를 낸다
               — 프론트(voiceBus)가 브라우저 합성기로 내려가 소리는 계속 난다.
               내 몫에도 천장을 씌운다. 넘치면 학습이 아니라 이쪽이 죽어야 한다.

             [🔴 캐시가 이 엔진의 본체다] 굽기가 문장당 수 초라 edge(0.5~1.1초)보다 느리다.
               대신 이 앱이 읽는 말은 심하게 반복된다 — 완료 보고·정해진 안내 문구는
               미리 구워 캐시에 넣어 두면 파일 읽기(~10ms)가 된다. tts_cache 규약을
               edge 와 똑같이 따르므로, PC 에서 미리 구운 wav 를 같은 키로 넣어 두기만 하면
               이 엔진이 뜨기 전에도 그 문장들은 사장님 목소리로 나간다.

REVISION HISTORY:
- 2026-08-16 Claude: 최초 작성 — 사장님 목소리 복제 낭독(청취 판정으로 채택)
"""

from __future__ import annotations

import io
import os
import subprocess
import threading

from engines import tts_cache

# 켜고 끄는 스위치. [WHY 필요한가] 학습이 카드를 꽉 쓰는 밤에는 아예 안 뜨게 두는 편이
# 낫다. 값을 0 으로 두면 목록에도 안 나오므로 사용자가 고를 수조차 없다(고르고 실패하는
# 것보다 낫다 — tts_edge.available 과 같은 판단).
ENABLED = os.environ.get('VOICE_QWEN', '1').strip() not in ('0', 'false', 'off')

MODEL_ID = os.environ.get('VOICE_QWEN_MODEL', 'Qwen/Qwen3-TTS-12Hz-0.6B-Base')
# 사장님 목소리 참조와 그 원문. 참조 길이 셋(3.8·14.5·25.7초)을 모두 들으시고 25.7초가
# 채택됐다. ref_text 는 필수다 — Base 판은 원문 없이는 ICL 모드를 거절한다(실측).
REF_WAV = os.environ.get('VOICE_QWEN_REF', r'G:\apix-voice2\ref\ref_merged.wav')
REF_TXT_JSON = os.environ.get('VOICE_QWEN_REF_TEXT',
                              r'G:\apix-voice2\work\ref_text.json')
REF_TXT_KEY = os.environ.get('VOICE_QWEN_REF_KEY', 'ref_merged')

# 여유 VRAM 이 이 밑이면 올리지 않는다. [WHY 1GB 인가] 같은 카드에서 도는 학습이
# 한 스텝 안에 쓰는 여유분이 그 정도다. 여기를 밑돌 때 모델을 올리면 학습이 죽는다.
FLOOR_MB = int(os.environ.get('VOICE_QWEN_FLOOR_MB', '1024'))
# 내 몫 천장(카드 전체 대비). 넘치면 학습이 아니라 이 프로세스가 OOM 으로 죽는다.
MEM_FRACTION = float(os.environ.get('VOICE_QWEN_MEM_FRACTION', '0.25'))

VOICES = [
    {
        'id': 'qwen:apix',
        'label': '아픽스 (사장님 목소리 복제)',
        'engine': 'qwen',
        'lang': 'ko',
        'note': 'GPU 상주 · 정해진 문구는 미리 구워 즉시 · 새 문장은 수 초',
    },
]

_model = None
_lock = threading.Lock()


def _smi_free_mb() -> int:
    """실여유 VRAM. [🔴 torch.cuda.mem_get_info 를 믿지 않는다] WDDM(윈도)에서 이 값이
    실제보다 두 배 넘게 크게 나오는 것을 실측했다(11GB 로 보고, 실제 5.4GB). 그 숫자로
    판단하면 '여유 있다'고 오판해 학습을 밀어낸다. nvidia-smi 가 기준이다."""
    try:
        out = subprocess.run(
            ['nvidia-smi', '--query-gpu=memory.free', '--format=csv,noheader,nounits'],
            capture_output=True, text=True, timeout=20).stdout.strip()
        return int(out.splitlines()[0])
    except Exception:                                      # noqa: BLE001
        return -1                                          # 못 재면 -1 — 판정에서 통과시킨다


def available() -> bool:
    if not ENABLED:
        return False
    try:
        import torch                                       # noqa: F401
        from qwen_tts import Qwen3TTSModel                 # noqa: F401
    except Exception:                                      # noqa: BLE001
        return False
    return os.path.exists(REF_WAV)


def list_voices() -> list[dict]:
    return list(VOICES) if available() else []


def _ref_text() -> str:
    import json
    with open(REF_TXT_JSON, encoding='utf-8') as fp:
        return json.load(fp)[REF_TXT_KEY]


class QwenEngine:
    """voice_id = 'qwen:apix'. 지금은 목소리가 하나뿐이다(사장님 샘플)."""

    mime = 'audio/wav'
    ext = 'wav'

    def __init__(self, voice_id: str = '') -> None:
        self.voice = 'apix'
        self._ref_text_cache = ''

    def load(self) -> None:
        """모델 상주. [WHY synth 안이 아니라 여기인가] 첫 문장에서 20초를 기다리면
        사용자는 고장으로 읽는다. 사이드카 예열(voice_server.warmup)이 이걸 부른다."""
        global _model
        if _model is not None:
            return
        if not available():
            raise RuntimeError('qwen-tts 를 쓸 수 없습니다(미설치 또는 VOICE_QWEN=0)')
        free = _smi_free_mb()
        if 0 <= free < FLOOR_MB:
            # [🔴 여기서 CPU 로 내려가지 않는다] CPU 는 문장당 수 분이라 낭독으로 못 쓴다.
            #   예외를 내면 프론트가 브라우저 합성기로 내려가 소리는 계속 난다.
            raise RuntimeError(f'GPU 여유 부족({free}MB < {FLOOR_MB}MB) — 학습 보호로 안 올립니다')
        with _lock:
            if _model is not None:
                return
            import torch
            from qwen_tts import Qwen3TTSModel
            total = torch.cuda.mem_get_info(0)[1] // (1 << 20)
            torch.cuda.set_per_process_memory_fraction(MEM_FRACTION, 0)
            _model = Qwen3TTSModel.from_pretrained(
                MODEL_ID, device_map='cuda:0', dtype=torch.bfloat16,
                attn_implementation='eager')
            self._ref_text_cache = _ref_text()

    def synth(self, text: str, speed: float = 1.0) -> bytes:
        """[🔴 speed 는 무시한다] 파일 헤더 참조 — 사장님이 원본 속도를 고르셨다.
        캐시 키에도 speed 를 넣지 않는다. 넣으면 미리 구워 둔 문장이 speed 값이 다르다는
        이유로 빗나가 매번 새로 굽게 된다."""
        key = tts_cache.key_of('qwen', self.voice, MODEL_ID, text)
        hit = tts_cache.get(key, self.ext)
        if hit is not None:
            return hit

        self.load()
        import soundfile as sf
        free = _smi_free_mb()
        if 0 <= free < FLOOR_MB:
            raise RuntimeError(f'GPU 여유 부족({free}MB) — 학습 보호로 굽지 않습니다')
        wavs, sr = _model.generate_voice_clone(
            text=text, language='Korean',
            ref_audio=REF_WAV, ref_text=self._ref_text_cache or _ref_text())
        w = wavs[0]
        if hasattr(w, 'detach'):
            w = w.detach().float().cpu().numpy()
        buf = io.BytesIO()
        # [WHY PCM_16 인가] 브라우저가 어디서나 재생하는 형식이고, 이 모델의 출력이
        #   float32 라 그대로 내보내면 크기가 두 배가 된다(HTTP 로 나르는 값이다).
        sf.write(buf, w, sr, format='WAV', subtype='PCM_16')
        data = buf.getvalue()
        if not data:
            raise RuntimeError('Qwen 이 오디오를 만들지 못했습니다')
        tts_cache.put(key, data, self.ext)
        return data
