# -*- coding: utf-8 -*-
"""
FILE: .ai_monitor/voice-server/voice_server.py
DESCRIPTION: 음성 사이드카 — STT(faster-whisper) / TTS(edge-tts 단일) 서버.
             앱 서버(server.py)가 /api/voice/* 를 이쪽으로 프록시한다.

             [🔴 낭독 엔진은 edge 하나뿐이다 — 2026-08-15 정리] sherpa VITS·SAPI·CosyVoice
               어댑터를 걷어냈다. 되돌아갈 길은 **프론트의 브라우저 내장 합성기**
               (browserVoice.ts)가 맡는다 — 그쪽은 서버도 네트워크도 안 타서 이 프로세스가
               통째로 죽어도 살아 있는, 더 나은 마지막 수단이다. 폴백을 서버 안에도 두면
               '왜 이 목소리가 났는지'를 설명할 수 없게 된다(do_POST /tts 주석과 짝).

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
- 2026-08-15 Claude: 낭독 엔진을 edge 하나로 정리 — sherpa·SAPI·CosyVoice 제거(사용자 지시).
  폴백은 프론트 브라우저 합성기 단일 경로가 됐다
- 2026-08-16 Claude: 두 번째 엔진 qwen(사장님 목소리 복제) 배선 — _new_engine 이 접두사로
  가르고 /voices 가 목록에 얹는다. 기본값은 그대로 edge 다(engines/tts_qwen.py 헤더).
  [🔴 실측] 예열 뒤에도 문장당 12.7~15.1초(RTF 6.1~6.7)라 그때그때 읽기에는 못 쓴다.
  정해진 문구를 미리 구워 tts_cache 에 넣어 두는 쓰임이 이 엔진의 본래 자리다
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
# [WHY edge 하나만 남았나 — 2026-08-15 실측] 로컬 후보 6종(MeloTTS·XTTS-v2·OmniVoice·
#   VoxCPM2·Qwen3-TTS·Kokoro)이 전부 떨어졌다(Kokoro 는 한국어가 0개). edge-tts 는
#   모델 0개·GPU 0·문장당 0.5~1.1초로 통과했다 — engines/tts_edge.py 헤더에 근거.
# [🔴 이 값은 이제 사실상 상수다] 다른 값을 넣어도 어댑터가 없어 edge 로 돈다. 환경변수를
#   남겨 둔 것은 다음에 엔진을 하나 더 붙일 때 배선 자리를 알아보게 하려는 것뿐이다.
TTS_ENGINE = os.environ.get('VOICE_TTS_ENGINE', 'edge').strip().lower()
STT_MODEL = os.environ.get('VOICE_STT_MODEL', 'small').strip()

# 목소리 식별자는 '<엔진>:<그 엔진 안의 이름>' 한 문자열이다.
# [WHY 엔진이 하나인데도 접두사를 유지하나] 프론트가 이 접두사로 '사이드카가 읽을 것'과
#   '브라우저가 읽을 것'(web:)을 가른다 — browserVoice.ts 의 WEB_PREFIX 와 짝이다.
#   떼면 두 경로가 같은 id 공간을 쓰게 되어 폴백이 자기 자신을 다시 부른다.
ENV_VOICE = os.environ.get('VOICE_TTS_VOICE', '').strip()

# [🔴 어느 목소리로 구웠는지 한 칸 — 2026-08-16] 서버는 참조가 바뀐 것을 알아야
#   캐시 열쇠를 새로 만든다. 길이만으로는 못 가른다(같은 길이로 다시 녹음하시면 그대로다).
#   그래서 **지문(sha256)** 을 함께 낸다. 값은 굽는 쪽(G:\apix-voice2 의 ag_bake_now)이
#   적어 두고 여기서는 **읽기만** 한다 — 이쪽이 참조를 고르지 않는다.
#   [🔴 없으면 조용히 None] 굽는 쪽이 안 떠 있어도 /status 는 그대로 떠야 한다.
#   [🔴 읽는 곳은 한 군데다 — engines/tts_qwen.ref_info()] 그 값이 **캐시 열쇠에도**
#     들어가므로, 여기서 따로 읽으면 '화면에 뜬 지문'과 '소리를 가른 지문'이 어긋날 수
#     있다. 그러면 "왜 이 목소리가 났나"를 못 밝힌다.


def _qwen_ref():
    """{key, file, sha256, sec} 또는 None."""
    try:
        from engines.tts_qwen import ref_info
        return ref_info()
    except Exception:                                  # noqa: BLE001
        return None


def _qwen_setup():
    """{installed, running, step, error, home} 또는 None — 모델 준비 진행 상황."""
    try:
        from engines.tts_qwen import setup_state
        return setup_state()
    except Exception:                                  # noqa: BLE001
        return None


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
    """voice_id 로 어댑터 인스턴스를 만든다(로딩은 아직 안 한다).

    [🔴 모르는 접두사도 edge 로 보낸다 — 무음 방지] 예전 설정이 localStorage 에 남아
      'sherpa:default' 같은 죽은 id 가 올라올 수 있다. 여기서 예외를 던지면 그 사용자는
      목소리를 다시 고르기 전까지 사이드카가 매번 500 을 내고, 프론트는 그때마다 브라우저
      폴백으로 내려간다 — 소리는 나지만 아무도 이유를 모른다. 그냥 edge 로 읽는다.

    [🔴 qwen 만 예외로 가른다 — 2026-08-16] 사장님 목소리 복제(engines/tts_qwen.py)가
      두 번째 엔진으로 들어왔다. 'qwen:' 으로 시작하는 id 만 그쪽으로 보내고 나머지는
      전부 edge 다. 이 한 줄이 '엔진 교체가 load_tts 의 한 줄'이라는 engines/__init__ 의
      불변식이 실제로 지켜지는 자리다.

    [🔴 moss 를 한 칸 더했다 — 2026-08-17 사장 지시] "MOSS-TTS-Nano 이것도 가능하게,
      Qwen 과 골라 쓰게." **갈아타는 것이 아니라 얹는 것이라** qwen 줄은 그대로 두고
      한 줄만 더한다 — 이 함수가 그 불변식의 자리라는 것이 여기서 한 번 더 확인된다.
    """
    _engines_dir_on_path()
    kind = voice_id.split(':', 1)[0].lower()
    if kind == 'qwen':
        from engines.tts_qwen import QwenEngine
        return QwenEngine(voice_id)
    if kind == 'moss':
        from engines.tts_moss import MossEngine
        return MossEngine(voice_id)
    from engines.tts_edge import EdgeEngine
    return EdgeEngine(voice_id if kind == 'edge' else '')


def _pick_default_voice() -> str:
    """처음 켰을 때 쓸 목소리 = edge 한국어 첫 번째(선희).

    [🔴 왜 로컬 엔진이 기본이 아닌가 — 2026-08-15 명료도 실측] 같은 문장을 합성해 그 소리를
      다시 faster-whisper 로 받아쓰게 했더니
        · sherpa VITS : "테스트를 모두 통과했습니다. 코미딸까요?"   (원문 = 커밋할까요)
        · SAPI Heami  : "테스트를 모두 통과했습니다. 커밋할까요?"   (원문 일치)
      로컬 후보는 그렇게 갈렸고, edge 는 신경망 합성이라 둘 다보다 확연히 자연스러웠다.
      그 실측이 두 어댑터를 걷어낸 근거다 — 되돌리려면 이 수치부터 다시 잴 것.
    [🔴 빈 문자열을 돌려주지 않는다] 빈 값이면 load_tts 가 매번 이 함수를 다시 불러
      edge 목록 조회(네트워크)를 낭독 경로에 얹는다.
    """
    if ENV_VOICE:
        return ENV_VOICE
    for v in list_voices():
        if v.get('lang') == 'ko':
            return v['id']
    # 목록 조회가 실패한 경우(오프라인 등). 이 id 로 합성해 보고, 그것도 실패하면
    # 프론트가 브라우저 합성기로 내려간다.
    return 'edge:ko-KR-SunHiNeural'


def load_tts(voice_id: str = ''):
    """목소리별 TTS 엔진 로딩(캐시).

    [WHY 목소리마다 인스턴스를 따로 두나] edge 어댑터는 올릴 모델이 없어 지금은 캐시의
      값이 크지 않다. 그래도 유지하는 이유는 목소리별 상태(선택된 화자)를 인스턴스가
      들고 있기 때문이다 — 하나를 공유하면 두 슬롯이 다른 목소리를 쓸 때 서로 덮어쓴다.
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
    """고를 수 있는 목소리 전부 = edge 한국어 3종.

    [WHY 캐시하나] /status 가 주기적으로 불린다. edge 목록은 상수라 계산이 싸지만,
      실패했을 때 매 /status 마다 같은 실패를 반복 기록하는 것을 막는 값이 더 크다.
    [🔴 빈 목록도 캐시한다] 실패를 캐시하지 않으면 오프라인 상태에서 /status 폴링이
      그대로 재시도 루프가 된다. 화면은 목록이 비면 브라우저 목소리만 그린다.
    """
    global _voices_cache
    if _voices_cache is not None:
        return _voices_cache
    _engines_dir_on_path()
    out: list = []
    try:
        from engines.tts_edge import list_voices as _edge
        out += _edge()
    except Exception as e:                                 # noqa: BLE001
        _log(f'edge 목록 실패(무시): {e}')
    # [WHY qwen 이 뒤인가] 앞에 두면 _pick_default_voice 가 한국어 첫 번째로 이걸 골라
    #   음성을 켠 모든 사람이 GPU 를 물게 된다. 기본은 edge 로 두고, 사장님 목소리는
    #   고른 사람에게만 뜬다. 목록에 아예 안 나오는 경우(미설치·VOICE_QWEN=0)도 정상이다.
    try:
        from engines.tts_qwen import list_voices as _qwen
        out += _qwen()
    except Exception as e:                                 # noqa: BLE001
        _log(f'qwen 목록 실패(무시): {e}')
    # [🔴 세 번째 칸 — MOSS-TTS-Nano] qwen 과 같은 이유로 맨 뒤다(기본이 되면 음성을
    #   켠 모든 사람이 GPU 를 문다). 살림이 없는 PC 에서는 빈 목록이 와서 칸이 안 뜬다 —
    #   그것이 정상이다(tts_moss.available 주석).
    try:
        from engines.tts_moss import list_voices as _moss
        out += _moss()
    except Exception as e:                                 # noqa: BLE001
        _log(f'moss 목록 실패(무시): {e}')
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

    [🔴 mime 을 여기서 못 박지 않는다] 지금은 edge 하나뿐이라 늘 audio/mpeg 이지만,
      wav 로 고정해 내보내면 브라우저가 mp3 를 wav 로 알고 재생에 실패한다 — 소리만
      안 나고 오류는 안 뜨는, 가장 찾기 나쁜 형태의 고장이 된다(engines/__init__ 규약).
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
                'ref': _qwen_ref(),
                # [🔴 진행을 화면으로 낸다 — 규칙 10] 모델 받기는 창 없이 도는 일이라
                #   진행을 볼 곳이 화면뿐이다. 이게 없으면 사용자는 5GB 를 받는 동안
                #   '목소리가 안 나온다'로만 겪는다(2026-08-16 음성 사고와 같은 모양).
                'qwen': _qwen_setup(),
            })
            return
        if self.path.startswith('/voices'):
            self._json({'voices': list_voices()})
            return
        self._json({'error': 'not found'}, 404)

    def _tts_seq(self, raw: bytes) -> None:
        """긴 글을 문장으로 잘라 **되는 대로 하나씩** 흘려보낸다(이어 굽기).

        [WHY 새 엔드포인트인가] /tts 는 '한 요청 = 한 오디오'다. 여러 문장짜리를 그 규약에
          담으면 마지막 문장까지 다 구운 뒤에야 첫 소리가 난다(131자 = 120초). 기존 규약을
          바꾸면 지금 잘 도는 화면이 깨지므로, 더하는 쪽을 골랐다.
        [형식] 줄 단위 JSON(NDJSON). 한 줄에 조각 하나:
          {"i":0,"text":"...","mime":"audio/wav","b64":"..."}   조각
          {"done":true,"parts":3}                                끝
          {"error":"..."}                                        도중 실패
          [WHY base64 인가] 한 연결로 여러 오디오를 흘려야 한다. multipart 는 브라우저에서
          조각별로 꺼내 쓰기가 번거롭고, NDJSON 은 한 줄 읽을 때마다 바로 재생할 수 있다.
        [🔴 첫 줄이 곧 첫 소리다] Transfer-Encoding: chunked 로 열어 두고 조각마다 flush
          한다. 버퍼에 모으면 이 엔드포인트를 만든 이유가 사라진다.
        [🔴 이 엔진만 받는다] edge 는 이미 0.5초라 쪼갤 이유가 없고, 쪼개면 mp3 프레임
          경계 문제(tts_cache 헤더)를 다시 만난다.
        """
        try:
            req = json.loads(raw or b'{}') or {}
        except ValueError:
            req = {}
        text = req.get('text', '')
        voice = str(req.get('voice') or 'qwen:apix')
        if not text:
            self._json({'error': 'no text'}, 400)
            return
        if not voice.lower().startswith('qwen'):
            self._json({'error': 'qwen 목소리에서만 씁니다'}, 400)
            return

        try:
            eng = load_tts(voice)
            parts = eng.synth_parts(text)
        except Exception as e:                             # noqa: BLE001
            _log(traceback.format_exc())
            self._json({'error': f'{type(e).__name__}: {e}'}, 500)
            return

        import base64
        self.send_response(200)
        self.send_header('Content-Type', 'application/x-ndjson;charset=utf-8')
        self.send_header('Transfer-Encoding', 'chunked')
        self.send_header('Cache-Control', 'no-store')
        self.end_headers()

        def emit(obj) -> None:
            body = (json.dumps(obj, ensure_ascii=False) + '\n').encode('utf-8')
            self.wfile.write(f'{len(body):X}\r\n'.encode('ascii'))
            self.wfile.write(body)
            self.wfile.write(b'\r\n')
            self.wfile.flush()

        n = 0
        try:
            for i, (ptext, audio) in enumerate(parts):
                emit({'i': i, 'text': ptext,
                      'mime': getattr(eng, 'mime', 'audio/wav'),
                      'b64': base64.b64encode(audio).decode('ascii')})
                n = i + 1
            emit({'done': True, 'parts': n})
        except Exception as e:                             # noqa: BLE001
            # [🔴 여기서 500 을 낼 수 없다] 헤더가 이미 나갔다. 오류도 한 줄로 흘려보내야
            #   듣는 쪽이 '왜 멈췄는지'를 안다. 그러지 않으면 조용히 끊긴 것처럼 보인다.
            _log(traceback.format_exc())
            try:
                emit({'error': f'{type(e).__name__}: {e}', 'parts': n})
            except Exception:                              # noqa: BLE001
                pass
        try:
            self.wfile.write(b'0\r\n\r\n')                 # chunked 끝 표시
            self.wfile.flush()
        except Exception:                                  # noqa: BLE001
            pass

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

        # [🔴 /tts 보다 먼저 본다] startswith('/tts') 가 '/tts/seq' 도 삼킨다.
        if self.path.startswith('/tts/seq'):
            self._tts_seq(raw)
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
