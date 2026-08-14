# -*- coding: utf-8 -*-
"""
FILE: .ai_monitor/voice-server/engines/tts_sherpa.py
DESCRIPTION: sherpa-onnx VITS 한국어 낭독 어댑터. 텍스트 → WAV 바이트.

             [WHY 이 엔진인가 — 2026-08-15 실측 비교]
               제약 세 가지(한국어 / 가벼움 / GPU 를 적게)를 동시에 만족한 유일한 후보다.
                 · 모델 62MB, **GPU 0** (onnxruntime CPU)
                 · RTF 0.10 — 9.5초 음성을 0.94초에 생성(i5-9500F 4스레드)
                 · 합성음을 faster-whisper 로 되받아쓴 명료도 검사에서 원문과 거의 일치
               비교군: MeloTTS-ko ONNX 는 전처리 4조합 모두 발음이 뭉개져 폐기,
               CosyVoice2·IndexTTS2 는 품질은 위지만 VRAM 2~5GB 상주라 이 PC(학습 병행)에
               맞지 않았다.

             [제약 — 목소리 선택지가 없다] 이 체크포인트(mimic3 ko_KO-kss low)는 화자가
               하나뿐이고 품질 등급도 low 다. 톤을 바꾸는 수단은 speed 뿐이다. 더 나은
               목소리가 필요해지면 엔진을 바꿔야 한다 — 그래서 이 파일은 어댑터로 격리돼 있다.

             [🔴 espeak-ng-data 를 같이 옮겨야 한다] 모델 파일만 복사하면 로딩은 되고
               합성에서 빈 소리가 나온다. data_dir 이 없으면 발음 사전을 못 찾는다.

REVISION HISTORY:
- 2026-08-15 Claude: 최초 작성 — 실측 비교 후 기본 엔진으로 채택
"""

from __future__ import annotations

import io
import os
import wave
from pathlib import Path

import numpy as np

# [🔴 절대경로를 박지 않는다] 이 앱은 다른 PC·다른 드라이브에 설치된다(바이브 코딩의
#   이식성 원칙). 기본값은 이 파일 기준 상대 경로이고, 환경변수로만 덮어쓴다.
MODEL_NAME = 'vits-mimic3-ko_KO-kss_low'
MODEL_DIR = Path(os.environ.get(
    'VOICE_SHERPA_DIR',
    str(Path(__file__).resolve().parent.parent / 'models' / MODEL_NAME)))
# 모델이 없을 때 받아올 곳. [WHY 자동 내려받기가 필요한가] 설치본에 동봉하더라도
#   소스 체크아웃(개발 모드)이나 경량 업데이트 경로에는 빠질 수 있다. 그때 조용히
#   실패하는 대신 한 번 받아 오면 사용자가 겪는 고장이 사라진다.
MODEL_URL = (f'https://github.com/k2-fsa/sherpa-onnx/releases/download/tts-models/'
             f'{MODEL_NAME}.tar.bz2')
# 낭독 속도. [실측] 1.0 은 또렷하지만 조금 급하다. 알림 성격의 낭독에는 살짝 느린 편이 낫다.
SPEED = float(os.environ.get('VOICE_TTS_SPEED', '0.95'))
THREADS = int(os.environ.get('VOICE_TTS_THREADS', '4'))


def _download_model() -> None:
    """모델이 없으면 한 번 받아 푼다.

    [🔴 원자적으로 만든다] 받다 끊긴 반쪽 폴더가 남으면 다음 기동에서 '파일은 있는데
      합성만 실패'가 된다 — 가장 진단하기 나쁜 상태다. 임시 폴더에 풀고 마지막에 옮긴다.
    """
    import shutil
    import tarfile
    import tempfile
    import urllib.request

    MODEL_DIR.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(dir=str(MODEL_DIR.parent)) as tmp:
        arc = Path(tmp) / 'model.tar.bz2'
        with urllib.request.urlopen(MODEL_URL, timeout=300) as r, open(arc, 'wb') as f:
            shutil.copyfileobj(r, f)
        with tarfile.open(arc, 'r:bz2') as t:
            t.extractall(tmp)
        src = Path(tmp) / MODEL_NAME
        if not src.exists():
            raise RuntimeError(f'내려받은 묶음에 {MODEL_NAME} 이 없다')
        if MODEL_DIR.exists():
            shutil.rmtree(MODEL_DIR, ignore_errors=True)
        shutil.move(str(src), str(MODEL_DIR))


class SherpaKoEngine:
    name = 'sherpa'

    def __init__(self) -> None:
        self.tts = None
        self.sample_rate = 22050

    def load(self) -> None:
        model = MODEL_DIR / 'ko_KO-kss_low.onnx'
        tokens = MODEL_DIR / 'tokens.txt'
        data_dir = MODEL_DIR / 'espeak-ng-data'
        if not all(p.exists() for p in (model, tokens, data_dir)):
            _download_model()
        for p in (model, tokens, data_dir):
            if not p.exists():
                raise RuntimeError(f'sherpa 한국어 모델 파일이 없다: {p}')

        import sherpa_onnx
        cfg = sherpa_onnx.OfflineTtsConfig(
            model=sherpa_onnx.OfflineTtsModelConfig(
                vits=sherpa_onnx.OfflineTtsVitsModelConfig(
                    model=str(model),
                    tokens=str(tokens),
                    data_dir=str(data_dir),
                ),
                num_threads=THREADS,
                provider='cpu',
            ),
            # [WHY 1인가] 문장마다 따로 합성하면 사이가 어색하게 끊긴다. 낭독 텍스트는
            #   이미 프론트(speech.ts)가 한 덩어리로 다듬어 보낸다.
            max_num_sentences=1,
        )
        self.tts = sherpa_onnx.OfflineTts(cfg)

    def synth(self, text: str, speed: float = 0.0) -> bytes:
        if self.tts is None:
            self.load()
        # speed<=0 은 '지정 안 함' — 환경변수 기본값을 쓴다. 화면에서 속도를 만지면 그 값이 온다.
        audio = self.tts.generate(text, sid=0, speed=(speed if speed > 0 else SPEED))
        pcm = np.clip(np.asarray(audio.samples, dtype=np.float32), -1.0, 1.0)
        pcm = (pcm * 32767).astype('<i2')

        buf = io.BytesIO()
        with wave.open(buf, 'wb') as w:
            w.setnchannels(1)
            w.setsampwidth(2)
            w.setframerate(audio.sample_rate)
            w.writeframes(pcm.tobytes())
        return buf.getvalue()
