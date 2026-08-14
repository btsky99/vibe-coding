# -*- coding: utf-8 -*-
"""
FILE: .ai_monitor/voice-server/voice_server.py
DESCRIPTION: 음성 사이드카 — 로컬 STT(faster-whisper) / TTS(CosyVoice2·IndexTTS2) 서버.
             앱 서버(server.py)가 /api/voice/* 를 이쪽으로 프록시한다.

             [🔴 왜 앱과 같은 프로세스가 아닌가 — 이 구조의 존재 이유]
               음성 스택은 python 3.10 + torch(CUDA) 를 요구한다. 앱 venv 는 3.12/3.13 에
               가벼운 의존성으로 서 있다. 한 환경에 섞으면
                 ① torch 버전 핀이 앱 의존성과 충돌하고
                 ② 모델 로딩(수십 초, GPU 수 GB)이 앱 기동을 붙잡고
                 ③ 음성 라이브러리가 죽을 때 대시보드까지 같이 죽는다.
               프로세스를 가르면 셋 다 사라진다. node PTY 서버를 따로 띄우는 것과 같은 판단.

             [🔴 모델은 첫 요청 때 올린다] 기동만으로 GPU 를 물면, 음성을 안 쓰는 사람도
               VRAM 을 뺏긴다. 대신 /status 가 loading 을 알려 화면이 '준비 중'을 그린다.

             [제약] 이 파일은 **음성 venv** 에서 돈다. 앱 패키지(ai_monitor.*)를 import 하지
               말 것 — 그 순간 두 환경이 다시 묶인다. 표준 라이브러리와 음성 라이브러리만.

             [엔드포인트]
               GET  /status            → {ready, loading, stt, tts, engine, device, detail}
               POST /stt   (audio/wav) → {text, ms}
               POST /tts   (json)      → audio/wav
               POST /shutdown          → 종료(앱이 내릴 때)

REVISION HISTORY:
- 2026-08-15 Claude: 최초 작성 — 로컬 음성 스택 사이드카
"""

from __future__ import annotations

import io
import json
import os
import sys
import threading
import time
import traceback
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

# 업로드 상한. [WHY] VAD 가 잘라 보내는 한 발화는 길어야 20초(=16k*2byte*20 ≈ 640KB)다.
# 그보다 큰 요청은 우리 클라이언트가 보낸 것이 아니다.
MAX_BODY = 4 * 1024 * 1024

HOST = '127.0.0.1'
PORT = int(os.environ.get('VOICE_PORT', '9021'))

# 어떤 TTS 엔진을 쓸지.
# [WHY 기본이 sherpa 인가 — 2026-08-15 실측] 한국어·경량·GPU 0 을 동시에 만족한 유일한
#   후보다(engines/tts_sherpa.py 헤더에 비교 근거). cosyvoice 는 품질이 위지만 VRAM 을
#   2GB 상주하므로, 이 PC 처럼 학습을 병행하는 기계에서는 기본값이 될 수 없다.
TTS_ENGINE = os.environ.get('VOICE_TTS_ENGINE', 'sherpa').strip().lower()
STT_MODEL = os.environ.get('VOICE_STT_MODEL', 'small').strip()

_state = {
    'stt': False,
    'tts': False,
    'loading': False,
    'detail': '',
    'device': 'unknown',
    'engine': TTS_ENGINE,
}
_lock = threading.Lock()
_stt = None
_tts = None


def _log(msg: str) -> None:
    # [제약] 이 프로세스는 콘솔 없이 뜬다(규칙 10). stdout 은 앱이 파이프로 받아 로그에 남긴다.
    print(f'[voice] {msg}', flush=True)


def _device() -> str:
    try:
        import torch
        if torch.cuda.is_available():
            return 'cuda'
    except Exception:                                  # noqa: BLE001
        pass
    return 'cpu'


def load_stt():
    """faster-whisper 로딩. [WHY 지연 로딩인가] 파일 상단 참조."""
    global _stt
    if _stt is not None:
        return _stt
    with _lock:
        if _stt is not None:
            return _stt
        from faster_whisper import WhisperModel
        dev = _device()
        # [🔴 compute_type 은 장치별로 다르다] GPU 에서 int8 을 쓰면 오히려 느리고,
        #   CPU 에서 float16 은 아예 지원되지 않아 예외가 난다.
        ct = 'float16' if dev == 'cuda' else 'int8'
        _log(f'STT 로딩: {STT_MODEL} on {dev}/{ct}')
        _stt = WhisperModel(STT_MODEL, device=dev, compute_type=ct)
        _state['stt'] = True
        _state['device'] = dev
        return _stt


def load_tts():
    """선택된 TTS 엔진 로딩. 엔진 어댑터는 engines/ 아래에 있다."""
    global _tts
    if _tts is not None:
        return _tts
    with _lock:
        if _tts is not None:
            return _tts
        sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
        if TTS_ENGINE == 'cosyvoice':
            from engines.tts_cosyvoice import CosyVoiceEngine as E
        else:
            from engines.tts_sherpa import SherpaKoEngine as E
        _log(f'TTS 로딩: {TTS_ENGINE}')
        _tts = E()
        _tts.load()
        _state['tts'] = True
        return _tts


def warmup() -> None:
    """백그라운드 예열.

    [WHY 필요한가] 첫 발화에서 모델 로딩(수십 초)을 기다리면 사용자는 고장으로 읽는다.
      기동 직후 미리 올려 두면 '켜는 순간 느리고 그 뒤로는 빠른' 익숙한 형태가 된다.
    """
    _state['loading'] = True
    try:
        load_stt()
    except Exception as e:                             # noqa: BLE001
        _state['detail'] = f'STT 로딩 실패: {e}'
        _log(_state['detail'])
        _log(traceback.format_exc())
    try:
        load_tts()
    except Exception as e:                             # noqa: BLE001
        _state['detail'] = f'TTS 로딩 실패: {e}'
        _log(_state['detail'])
        _log(traceback.format_exc())
    _state['loading'] = False
    _log(f"예열 완료 stt={_state['stt']} tts={_state['tts']} device={_state['device']}")


def transcribe(wav: bytes) -> dict:
    t0 = time.time()
    model = load_stt()
    # [🔴 language 를 고정한다] 자동 감지는 짧은 한국어 발화를 일본어·중국어로 자주 오판하고,
    #   그러면 결과가 통째로 엉뚱한 문자로 돌아온다. 이 앱의 사용자는 한국어로 말한다.
    segments, _info = model.transcribe(
        io.BytesIO(wav),
        language='ko',
        beam_size=1,                # [WHY 1인가] 실시간 지시라 지연이 품질보다 중요하다.
        vad_filter=True,            # 앞뒤 무음 제거 — 브라우저 VAD 가 넉넉히 자르므로 한 번 더 조인다.
        condition_on_previous_text=False,  # [🔴] 켜면 이전 발화가 다음 인식을 오염시켜 헛말이 늘어난다.
    )
    text = ''.join(s.text for s in segments).strip()
    return {'text': text, 'ms': int((time.time() - t0) * 1000)}


def synthesize(text: str) -> bytes:
    return load_tts().synth(text)


class Handler(BaseHTTPRequestHandler):
    protocol_version = 'HTTP/1.1'

    def log_message(self, *args):                      # noqa: A003
        pass                                           # 접근 로그는 필요 없다 — 앱 로그가 이미 있다.

    def _json(self, obj, code: int = 200) -> None:
        body = json.dumps(obj, ensure_ascii=False).encode('utf-8')
        self.send_response(code)
        self.send_header('Content-Type', 'application/json;charset=utf-8')
        self.send_header('Content-Length', str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self):                                  # noqa: N802
        if self.path.startswith('/status'):
            ready = _state['stt'] and _state['tts']
            self._json({**_state, 'ready': ready})
            return
        self._json({'error': 'not found'}, 404)

    def do_POST(self):                                 # noqa: N802
        try:
            length = int(self.headers.get('Content-Length') or 0)
        except ValueError:
            length = 0
        if length > MAX_BODY:
            self._json({'error': 'too large'}, 413)
            return
        raw = self.rfile.read(length) if length else b''

        if self.path.startswith('/stt'):
            try:
                self._json(transcribe(raw))
            except Exception as e:                     # noqa: BLE001
                _log(traceback.format_exc())
                self._json({'text': '', 'error': f'{type(e).__name__}: {e}'}, 200)
            return

        if self.path.startswith('/tts'):
            try:
                text = (json.loads(raw or b'{}') or {}).get('text', '')
            except ValueError:
                text = ''
            if not text:
                self._json({'error': 'no text'}, 400)
                return
            try:
                wav = synthesize(text)
            except Exception as e:                     # noqa: BLE001
                _log(traceback.format_exc())
                self._json({'error': f'{type(e).__name__}: {e}'}, 500)
                return
            self.send_response(200)
            self.send_header('Content-Type', 'audio/wav')
            self.send_header('Content-Length', str(len(wav)))
            self.end_headers()
            self.wfile.write(wav)
            return

        if self.path.startswith('/shutdown'):
            self._json({'ok': True})
            threading.Thread(target=self.server.shutdown, daemon=True).start()
            return

        self._json({'error': 'not found'}, 404)


def main() -> int:
    threading.Thread(target=warmup, daemon=True, name='voice-warmup').start()
    srv = ThreadingHTTPServer((HOST, PORT), Handler)
    _log(f'listening on {HOST}:{PORT} engine={TTS_ENGINE} stt={STT_MODEL}')
    try:
        srv.serve_forever()
    except KeyboardInterrupt:
        pass
    return 0


if __name__ == '__main__':
    sys.exit(main())
