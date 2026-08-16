# -*- coding: utf-8 -*-
"""
FILE: .ai_monitor/voice-server/engines/tts_qwen.py
DESCRIPTION: 낭독 엔진 — Qwen3-TTS 로 사장님 목소리를 복제해 읽는다.

             [WHY 두 번째 엔진이 생겼나 — 2026-08-16 청취 판정] edge-tts 는 남의 목소리다.
               사장님 샘플(25.7초)로 복제한 Qwen3-TTS-12Hz-0.6B-Base 를 직접 들으시고
               "속도 맞춤보다 그냥이 훨씬 좋은데. 굿. 교체 진행해보자" 로 채택됐다.
               edge 는 걷어내지 않는다 — 이 엔진이 못 뜨면 소리가 아예 안 나기 때문이다.
               voice_server._new_engine 이 접두사로 가른다.

             [🔴 모델을 이 venv 에 들이지 않는다 — 이 파일의 핵심 결정]
               낭독 사이드카 venv 에는 torch 가 아예 없다(faster-whisper 는 ctranslate2 를
               쓴다). 여기에 CUDA torch ~3GB 를 밀어 넣으면 받아쓰기까지 같이 흔들리고,
               '프로세스를 갈라 뒀다'는 이 폴더의 존재 이유와도 어긋난다.
               Qwen 은 이미 G:\\apix-voice2\\envs\\qwen_cuda 에서 돈다. 그래서 이 어댑터는
               **그쪽 파이썬을 자식으로 부르기만 한다**(work/z_qwen_say.py). 앱이 이
               사이드카를 자식으로 띄우는 것과 같은 방식이라 새 통로가 아니다.

             [🔴 캐시가 이 엔진의 본체다] 한 번 굽는 데 예열 뒤에도 12~17초, 프로세스를
               새로 띄우면 거기에 40초가 더 붙는다. 그때그때 읽기에는 못 쓴다.
               대신 이 앱이 읽는 말은 심하게 반복된다 — 완료 보고·정해진 안내 문구는
               PC 에서 미리 구워 cache/tts 에 같은 키로 넣어 두면 파일 읽기(~10ms)가 된다.
               미리 구운 문장은 **이 어댑터가 자식을 띄우지 않고, GPU 도 안 물고** 나간다.

             [🔴 속도를 손대지 않는다] 6.5자/초로 맞춘 판을 같이 들려드렸는데 사장님이
               '그냥'(원본 속도)을 고르셨다. 그래서 synth 의 speed 인자를 무시하고,
               캐시 키에도 넣지 않는다 — 넣으면 미리 구워 둔 문장이 speed 가 다르다는
               이유로 빗나가 매번 새로 굽게 된다.

             [🔴 GPU 를 무는 대가] 자식이 도는 동안만 ~2.2GB 를 쓴다(상주가 아니다).
               같은 카드에서 학습이 돌면 그만큼 학습 몫이 준다. 자식 쪽(z_qwen_say.py)이
               굽기 전 실여유를 재고 1GB 밑이면 아무것도 안 하고 물러난다. 그때 이 어댑터는
               예외를 내고, 프론트(voiceBus)가 브라우저 합성기로 내려가 소리는 계속 난다.

REVISION HISTORY:
- 2026-08-16 Claude: 최초 작성 — 사장님 목소리 복제 낭독(청취 판정으로 채택)
- 2026-08-16 Claude: 모델을 사이드카 venv 에 들이는 대신 외부 파이썬을 자식으로 부르게
  고침 — 이 venv 에는 torch 가 없고, 넣으면 STT 까지 흔들린다
"""

from __future__ import annotations

import os
import subprocess
import tempfile

from engines import tts_cache

# 켜고 끄는 스위치. [WHY 필요한가] 학습이 카드를 꽉 쓰는 밤에는 아예 안 뜨게 두는 편이
# 낫다. 0 이면 목록에도 안 나오므로 사용자가 고르고 실패하는 일이 없다(tts_edge 와 같은 판단).
ENABLED = os.environ.get('VOICE_QWEN', '1').strip() not in ('0', 'false', 'off')

# 굽는 일꾼(외부 venv). 이 둘이 다 있어야 이 목소리를 목록에 올린다.
WORKER_PY = os.environ.get(
    'VOICE_QWEN_PYTHON', r'G:\apix-voice2\envs\qwen_cuda\Scripts\python.exe')
WORKER_JOB = os.environ.get(
    'VOICE_QWEN_WORKER', r'G:\apix-voice2\work\z_qwen_say.py')
MODEL_ID = os.environ.get('VOICE_QWEN_MODEL', 'Qwen/Qwen3-TTS-12Hz-0.6B-Base')

# 자식 상한. [WHY 넉넉한가] 모델 올림 8~21초 + 굽기 12~17초 + import 30초가 겹칠 수 있다.
# [🔴 상한이 없으면 낭독 요청 하나가 사이드카 스레드를 영원히 잡는다]
TIMEOUT_S = int(os.environ.get('VOICE_QWEN_TIMEOUT', '180'))

VOICES = [
    {
        'id': 'qwen:apix',
        'label': '아픽스 (사장님 목소리 복제)',
        'engine': 'qwen',
        'lang': 'ko',
        'note': '미리 구운 문구는 즉시 · 새 문장은 1분 안팎(GPU)',
    },
]


def available() -> bool:
    """[🔴 여기서 qwen_tts 를 import 해 보지 않는다] 그 패키지는 이 venv 가 아니라
    일꾼 쪽에 있다. 여기서 확인할 것은 '부를 수 있는가' 뿐이다."""
    if not ENABLED:
        return False
    return os.path.exists(WORKER_PY) and os.path.exists(WORKER_JOB)


def list_voices() -> list[dict]:
    return list(VOICES) if available() else []


class QwenEngine:
    """voice_id = 'qwen:apix'. 지금은 목소리가 하나뿐이다(사장님 샘플)."""

    mime = 'audio/wav'
    ext = 'wav'

    def __init__(self, voice_id: str = '') -> None:
        self.voice = 'apix'

    def load(self) -> None:
        """[WHY 비어 있나] 이 프로세스에는 올릴 모델이 없다 — 일꾼이 들고 있다.
        인터페이스(engines/__init__.py 불변식)를 맞추되, 여기서 자식을 미리 띄우지는
        않는다. 예열이 GPU 를 무는 순간 '음성을 켠 것만으로 학습이 굶는' 일이 된다."""
        if not available():
            raise RuntimeError(
                f'Qwen 일꾼을 찾을 수 없습니다({WORKER_PY} / {WORKER_JOB})')

    def synth(self, text: str, speed: float = 1.0) -> bytes:
        key = tts_cache.key_of('qwen', self.voice, MODEL_ID, text)
        hit = tts_cache.get(key, self.ext)
        if hit is not None:
            return hit                     # 미리 구운 문장 — 자식도 GPU 도 필요 없다

        self.load()
        # [WHY 임시 파일로 받나] 자식의 stdout 으로 wav 를 흘리면 진행 로그와 섞인다.
        #   파일이면 부분 쓰기도 자식 쪽에서 os.replace 로 막힌다.
        fd, tmp = tempfile.mkstemp(suffix='.wav', prefix='qwen_')
        os.close(fd)
        try:
            proc = subprocess.run(
                [WORKER_PY, '-u', WORKER_JOB, '--text', text, '--out', tmp],
                capture_output=True, text=True, timeout=TIMEOUT_S)
            if proc.returncode == 3:
                # 학습 보호로 물러난 것. 고장이 아니라 정해진 양보다 — 문구를 그렇게 적는다.
                raise RuntimeError('GPU 여유 부족 — 학습 보호로 굽지 않았습니다')
            if proc.returncode != 0:
                raise RuntimeError(
                    f'Qwen 일꾼 실패(코드 {proc.returncode}): {(proc.stderr or "")[-300:]}')
            with open(tmp, 'rb') as fp:
                data = fp.read()
        except subprocess.TimeoutExpired as e:
            raise RuntimeError(f'Qwen 일꾼이 {TIMEOUT_S}초 안에 끝내지 못했습니다') from e
        finally:
            try:
                os.unlink(tmp)
            except OSError:
                pass

        if not data:
            # [🔴 빈 결과를 성공으로 넘기면 무음이 된다] 예외로 올려야 프론트가 폴백한다.
            raise RuntimeError('Qwen 이 오디오를 만들지 못했습니다')
        tts_cache.put(key, data, self.ext)
        return data
