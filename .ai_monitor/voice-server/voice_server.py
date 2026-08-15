# -*- coding: utf-8 -*-
"""
FILE: .ai_monitor/voice-server/voice_server.py
DESCRIPTION: 음성 사이드카 — STT(faster-whisper) / TTS(edge-tts 기본, sapi·sherpa 폴백) 서버.
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
               GET  /status            → {ready, ttsReady, loading, stt, tts, engine, device,
                                          detail, voices, cache}
               GET  /voices            → {voices: [{id, label, engine, lang}]}
               POST /stt   (audio/wav) → {text, ms}
               POST /tts   (json)      → audio/mpeg 또는 audio/wav (엔진에 따라 다름 —
                                         synthesize 주석)  body: {text, voice?, speed?}
               POST /shutdown          → 종료(앱이 내릴 때)

REVISION HISTORY:
- 2026-08-15 Claude: 최초 작성 — 로컬 음성 스택 사이드카
- 2026-08-15 Claude: 목소리 선택 — 엔진을 voice_id 별로 캐시하고 /voices 로 목록을 연다
- 2026-08-15 Claude: 기본 낭독을 edge-tts 로 교체(로컬 6종 전부 탈락 — tts_edge.py 헤더).
  응답 형식이 엔진마다 달라져 MIME 을 같이 반환하고, ttsReady 를 ready 에서 분리했다
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
# [🔴 9021 금지 — 2026-08-15 사고] LAN 브리지가 인스턴스마다 9020,9021,… 로 번진다.
#   기본값을 바꿀 때는 api/voice_api.py 의 VOICE_PORT 와 반드시 같이 고칠 것(양쪽 수동 동기).
PORT = int(os.environ.get('VOICE_PORT', '9030'))

# 어떤 TTS 엔진을 쓸지.
# [WHY 기본이 edge 인가 — 2026-08-15 실측] 로컬 후보 6종(MeloTTS·XTTS-v2·OmniVoice·
#   VoxCPM2·Qwen3-TTS·Kokoro)이 전부 떨어졌다(Kokoro 는 한국어가 0개). edge-tts 는
#   모델 0개·GPU 0·문장당 0.5~1.1초로 통과했다 — engines/tts_edge.py 헤더에 근거.
#   sherpa 와 sapi 는 **네트워크가 끊겼을 때 되돌아갈 길**로 남는다.
TTS_ENGINE = os.environ.get('VOICE_TTS_ENGINE', 'edge').strip().lower()
STT_MODEL = os.environ.get('VOICE_STT_MODEL', 'small').strip()

# 목소리 식별자는 '<엔진>:<그 엔진 안의 이름>' 한 문자열이다.
# [WHY 엔진과 목소리를 한 문자열로 묶나] 화면은 '목소리 하나를 고른다'만 알면 된다.
#   엔진을 따로 고르게 하면 sherpa 를 고른 뒤 sapi 목소리를 고르는 잘못된 조합이 생긴다.
ENV_VOICE = os.environ.get('VOICE_TTS_VOICE', '').strip()

_state = {
    'stt': False,
    'tts': False,
    'loading': False,
    'detail': '',
    'device': 'unknown',
    'engine': TTS_ENGINE,
    'voice': ENV_VOICE,          # 빈 값이면 예열 때 _pick_default_voice() 가 채운다
}
_lock = threading.Lock()
_stt = None
_engines: dict = {}          # voice_id → 엔진 인스턴스
_engine_lock = threading.Lock()
_voices_cache: list | None = None


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


def _engines_dir_on_path() -> None:
    d = os.path.dirname(os.path.abspath(__file__))
    if d not in sys.path:
        sys.path.insert(0, d)


def _new_engine(voice_id: str):
    """voice_id 로 어댑터 인스턴스를 만든다(로딩은 아직 안 한다)."""
    _engines_dir_on_path()
    kind = voice_id.split(':', 1)[0].lower()
    if kind == 'edge':
        from engines.tts_edge import EdgeEngine
        return EdgeEngine(voice_id)
    if kind == 'sapi':
        from engines.tts_sapi import SapiEngine
        return SapiEngine(voice_id)
    if kind == 'cosyvoice':
        from engines.tts_cosyvoice import CosyVoiceEngine
        return CosyVoiceEngine()
    from engines.tts_sherpa import SherpaKoEngine
    return SherpaKoEngine()


def _pick_default_voice() -> str:
    """처음 켰을 때 쓸 목소리. 순서 = edge → SAPI(Heami) → sherpa.

    [🔴 왜 sherpa 가 기본이 아닌가 — 2026-08-15 명료도 실측] 같은 문장을 합성해 그 소리를
      다시 faster-whisper 로 받아쓰게 했더니
        · sherpa VITS : "테스트를 모두 통과했습니다. 코미딸까요?"   (원문 = 커밋할까요)
        · SAPI Heami  : "테스트를 모두 통과했습니다. 커밋할까요?"   (원문 일치)
      Heami 가 더 정확했고, 내려받을 모델도 없어 첫 기동까지 빨라진다.
    [🔴 그 위에 edge 가 앉는다] edge 는 신경망 합성이라 Heami 보다 확연히 자연스럽고
      역시 모델을 안 내려받는다. 다만 **네트워크가 필요하다** — 그래서 순서가 중요하다.
      edge 를 못 쓰는 상황(오프라인·VOICE_EDGE=0)에서는 available() 이 false 라
      목록에 아예 없고, 자연히 그 아래 후보가 기본값이 된다.
    """
    if ENV_VOICE:
        return ENV_VOICE
    voices = list_voices()
    for engine in ('edge', 'sapi'):
        for v in voices:
            if v.get('engine') == engine and v.get('lang') == 'ko':
                return v['id']
    return f'{TTS_ENGINE}:default' if TTS_ENGINE != 'edge' else 'sherpa:default'


def load_tts(voice_id: str = ''):
    """목소리별 TTS 엔진 로딩(캐시).

    [🔴 목소리마다 인스턴스를 따로 둔다] sherpa 는 62MB 를 상주시키고 sapi 는 아무것도
      안 올린다. 목소리를 바꿀 때마다 앞의 것을 버리면, 두 목소리를 번갈아 쓰는 사용자가
      매번 모델 로딩(수 초)을 기다린다. 개수가 한 자릿수라 캐시가 커질 위험이 없다.
    """
    vid = voice_id or _state['voice'] or _pick_default_voice()
    hit = _engines.get(vid)
    if hit is not None:
        return hit
    with _engine_lock:
        hit = _engines.get(vid)
        if hit is not None:
            return hit
        _log(f'TTS 로딩: {vid}')
        eng = _new_engine(vid)
        eng.load()
        _engines[vid] = eng
        _state['tts'] = True
        return eng


def list_voices() -> list:
    """고를 수 있는 목소리 전부. [WHY 캐시하나] /status 가 주기적으로 불리는데 SAPI 열거는
      매번 COM 아파트를 열고 닫는다. 목소리는 앱이 도는 동안 늘거나 줄지 않는다.
    """
    global _voices_cache
    if _voices_cache is not None:
        return _voices_cache
    _engines_dir_on_path()
    out: list = []
    # [🔴 edge 를 맨 앞에 둔다] 목록 순서가 곧 '무엇을 권하는가'다. 화면도 이 순서를
    #   그대로 그리므로, 뒤에 두면 사용자가 되돌아갈 길(폴백)을 기본으로 고르게 된다.
    try:
        from engines.tts_edge import list_voices as _edge
        out += _edge()
    except Exception as e:                                 # noqa: BLE001
        _log(f'edge 목록 실패(무시): {e}')
    out.append({
        'id': 'sherpa:default',
        'label': '로컬 VITS (한국어)',
        'engine': 'sherpa',
        'lang': 'ko',
        'note': '모델 62MB · GPU 0 · 또렷하지만 기계적',
    })
    try:
        from engines.tts_sapi import list_voices as _sapi
        out += _sapi()
    except Exception as e:                                 # noqa: BLE001
        _log(f'SAPI 목록 실패(무시): {e}')
    _voices_cache = out
    return out


def _cache_stats() -> dict:
    """캐시 현황. [WHY /status 에 싣나] 캐시는 눈에 안 보이는 장치라, 안 도는 채로
    몇 달이 가도 아무도 모른다. 파일 수가 안 늘면 그 자체가 고장 신호다."""
    try:
        _engines_dir_on_path()
        from engines import tts_cache
        return tts_cache.stats()
    except Exception:                                  # noqa: BLE001
        return {}


def warmup() -> None:
    """백그라운드 예열.

    [WHY 필요한가] 첫 발화에서 모델 로딩(수십 초)을 기다리면 사용자는 고장으로 읽는다.
      기동 직후 미리 올려 두면 '켜는 순간 느리고 그 뒤로는 빠른' 익숙한 형태가 된다.
    """
    _state['loading'] = True
    if not _state['voice']:
        _state['voice'] = _pick_default_voice()
    # [🔴 TTS 를 먼저 올린다 — 순서가 체감을 가른다] STT(whisper small)는 수십 초가
    #   걸리는데 edge TTS 는 올릴 모델이 없어 즉시 끝난다. STT 를 먼저 두면 '읽기'가
    #   '듣기'를 기다리느라 그 수십 초 동안 브라우저 폴백으로만 읽힌다 — 사용자는 자기가
    #   고른 목소리가 아닌 소리를 듣고 설정이 안 먹었다고 판단한다.
    try:
        load_tts()
    except Exception as e:                             # noqa: BLE001
        _state['detail'] = f'TTS 로딩 실패: {e}'
        _log(_state['detail'])
        _log(traceback.format_exc())
    try:
        load_stt()
    except Exception as e:                             # noqa: BLE001
        _state['detail'] = f'STT 로딩 실패: {e}'
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


def synthesize(text: str, voice: str = '', speed: float = 0.0) -> tuple[bytes, str]:
    """합성 결과와 그 형식(MIME).

    [🔴 형식이 엔진마다 다르다] edge 는 mp3, sherpa/sapi 는 wav 다. 예전처럼 wav 로
      못 박아 내보내면 브라우저가 mp3 를 wav 로 알고 재생에 실패한다 — 소리만 안 나고
      오류는 안 뜨는, 가장 찾기 나쁜 형태의 고장이 된다.
    """
    eng = load_tts(voice)
    return eng.synth(text, speed), getattr(eng, 'mime', 'audio/wav')


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
            # [🔴 ttsReady 를 따로 낸다] ready 는 '받아쓰기까지 다 됐는가'다. 낭독은
            #   그것을 기다릴 이유가 없는데(TTS 는 이미 떴다), 화면이 ready 하나만 보면
            #   whisper 가 올라오는 수십 초 동안 고른 목소리를 안 쓴다. 두 준비 상태는
            #   수명이 달라졌으므로 값도 갈라야 한다.
            self._json({
                **_state,
                'ready': ready,
                'ttsReady': bool(_state['tts']),
                'voices': list_voices(),
                'cache': _cache_stats(),
            })
            return
        if self.path.startswith('/voices'):
            self._json({'voices': list_voices()})
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
                req = json.loads(raw or b'{}') or {}
            except ValueError:
                req = {}
            text = req.get('text', '')
            voice = str(req.get('voice') or '')
            try:
                speed = float(req.get('speed') or 0)
            except (TypeError, ValueError):
                speed = 0.0
            if not text:
                self._json({'error': 'no text'}, 400)
                return
            try:
                audio, mime = synthesize(text, voice, speed)
            except Exception as e:                     # noqa: BLE001
                # [🔴 여기서 다른 엔진으로 갈아타지 않는다] 폴백은 프론트(voiceBus.speak)가
                #   한다 — 그쪽은 브라우저 내장 합성기라는, 서버가 닿을 수 없는 마지막
                #   수단을 갖고 있다. 여기서 절반쯤 폴백하면 폴백이 두 군데가 되어
                #   '왜 이 목소리가 났는지' 를 아무도 설명 못 하게 된다.
                _log(traceback.format_exc())
                self._json({'error': f'{type(e).__name__}: {e}'}, 500)
                return
            self.send_response(200)
            self.send_header('Content-Type', mime)
            self.send_header('Content-Length', str(len(audio)))
            self.end_headers()
            self.wfile.write(audio)
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
