# -*- coding: utf-8 -*-
"""
FILE: .ai_monitor/voice-server/engines/tts_cosyvoice.py
DESCRIPTION: CosyVoice2 낭독 어댑터. 텍스트를 받아 WAV 바이트를 돌려준다.

             [🔴 이 모델에는 '기본 목소리'가 없다] CosyVoice2-0.5B 는 사전 정의 화자(SFT)를
             제공하지 않는다. 목소리는 **참조 음성 몇 초**로 정해진다(zero-shot). 그래서
             참조 wav 가 없으면 낭독 자체가 성립하지 않는다 — load() 에서 먼저 확인한다.

             [WHY cross_lingual 인가] inference_zero_shot 은 참조 음성의 **대사 텍스트**까지
             정확히 넘겨야 한다(안 맞으면 발음이 무너진다). cross_lingual 은 참조를 목소리로만
             쓰므로 참조가 한국어가 아니어도 한국어를 읽는다 — 참조 준비가 훨씬 쉽다.

             [제약] 이 파일은 음성 venv(python 3.10 + torch cu121)에서만 import 된다.
             앱 서버가 직접 부르면 ImportError 다 — 사이드카를 통해서만 쓴다.

REVISION HISTORY:
- 2026-08-15 Claude: 최초 작성 — 로컬 TTS 후보 ①
"""

from __future__ import annotations

import io
import os
import sys
from pathlib import Path

# 리포 위치. 앱에 동봉할 때는 설치 경로를 여기로 넘긴다.
HOME = Path(os.environ.get('VOICE_COSYVOICE_HOME', r'C:\voice-lab\cosyvoice'))
MODEL_DIR = Path(os.environ.get('VOICE_COSYVOICE_MODEL', str(HOME / 'pretrained_models' / 'CosyVoice2-0.5B')))
# 목소리를 정하는 참조 음성. 사용자가 바꾸면 그 목소리로 읽는다.
PROMPT_WAV = Path(os.environ.get('VOICE_PROMPT_WAV', str(HOME / 'asset' / 'zero_shot_prompt.wav')))


class CosyVoiceEngine:
    name = 'cosyvoice'

    def __init__(self) -> None:
        self.model = None
        self.prompt = None
        self.sample_rate = 24000

    def load(self) -> None:
        if not MODEL_DIR.exists():
            raise RuntimeError(f'CosyVoice2 모델이 없다: {MODEL_DIR}')
        if not PROMPT_WAV.exists():
            raise RuntimeError(f'참조 음성이 없다(목소리를 정할 수 없음): {PROMPT_WAV}')

        # [🔴 두 경로를 모두 넣어야 한다] Matcha-TTS 는 서브모듈이고 cosyvoice 내부가
        #   최상위 이름(matcha.*)으로 import 한다. 하나만 넣으면 ModuleNotFoundError 가
        #   모델 로딩 한복판에서 난다.
        for p in (str(HOME), str(HOME / 'third_party' / 'Matcha-TTS')):
            if p not in sys.path:
                sys.path.insert(0, p)

        from cosyvoice.cli.cosyvoice import CosyVoice2
        from cosyvoice.utils.file_utils import load_wav

        # [WHY jit/trt 를 끄나] 둘 다 리눅스 전용 가속 경로다. 윈도우에서 켜면 로딩이
        #   실패하거나 조용히 CPU 로 떨어진다. fp16 은 RTX 에서 켤 수 있지만, 첫 도입에서는
        #   품질 변수를 하나라도 줄인다.
        self.model = CosyVoice2(str(MODEL_DIR), load_jit=False, load_trt=False, fp16=False)
        # 참조는 16k 로 읽는다 — 모델이 그 전제로 화자 임베딩을 뽑는다.
        self.prompt = load_wav(str(PROMPT_WAV), 16000)
        self.sample_rate = getattr(self.model, 'sample_rate', 24000)

    def synth(self, text: str, speed: float = 0.0) -> bytes:
        # [제약] speed 는 받기만 하고 쓰지 않는다 — 어댑터 시그니처를 sherpa/sapi 와 맞추기
        #   위한 것이다. CosyVoice2 의 inference 에도 speed 인자가 있지만 이 PC 에 모델이
        #   없어 실측을 못 했다. 검증 없이 넘겨서 합성이 깨지는 쪽이 더 나쁘다.
        if self.model is None:
            self.load()

        import torch
        import torchaudio

        chunks = []
        # [제약] stream=False 여도 제너레이터다. 긴 문장은 내부에서 여러 조각으로 나뉘어
        #   나오므로 전부 이어 붙여야 한다 — 첫 조각만 쓰면 문장이 중간에서 끊긴다.
        for out in self.model.inference_cross_lingual(text, self.prompt, stream=False):
            chunks.append(out['tts_speech'])
        if not chunks:
            raise RuntimeError('합성 결과가 비었다')

        wav = torch.cat(chunks, dim=1) if len(chunks) > 1 else chunks[0]
        buf = io.BytesIO()
        torchaudio.save(buf, wav, self.sample_rate, format='wav')
        return buf.getvalue()
