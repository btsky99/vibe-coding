# -*- coding: utf-8 -*-
"""
FILE: .ai_monitor/voice-server/engines/tts_moss.py
DESCRIPTION: 두 번째 복제 엔진 — MOSS-TTS-Nano(0.1B, ONNX) 어댑터.

             [🔴 왜 붙였나 — 사장 지시] "MOSS-TTS-Nano 이것도 가능하게 만들어 줘.
               Qwen 과 골라서 쓸 수 있게." **갈아타는 것이 아니라 얹는 것이다.**
               engines/tts_qwen.py 는 한 줄도 안 고친다 — 사장이 지금 그 길로 들으신다.

             [🔴 이 엔진의 값어치는 첫 소리 하나다]
               사람이 직접 연 창이 같은 자(문장 셋 · boss_pick 참조)로 재 놓은 값
               (G:\\apix-voice2\\rtf1\\moss_rtf.json · moss_ttfa.json · moss_score.json):
                 첫 소리(TTFA) 0.18~0.22초   ← Qwen 은 스트리밍이 없어 첫 소리 = 총 시간
                 RTF           1.245~1.274   (Qwen 묶음 0.605 · 한 문장 1.8)
                 목소리 닮음    cos 0.673 / 0.820 / 0.795  (Qwen 0.68~0.86 과 동급)
                 한국어 CER     0.000 / 0.333 / 0.065
                 크기·면허      0.1B · Apache-2.0 · ONNX 728MB
               굽는 총량은 Qwen 이 빠르다. **첫 소리는 MOSS 가 60배 빠르다** —
               오늘 밤 사장이 겪으신 「한참 있다 나온다」가 바로 그 값이다.

             [🔴 규격은 engines/__init__ 의 계약 그대로다] 밖으로 내는 것은
               `load()` 와 `synth(text) -> wav bytes` 둘 뿐이다. 나머지(일꾼 살리기·
               캐시·참조 지문)는 이 파일 안에서 끝낸다.

             [🔴 캐시 열쇠에 엔진 이름이 들어간다] 안 넣으면 사장이 목소리를 바꾸셔도
               옛 소리가 그대로 난다 — 2026-08-16 에 참조 지문에서 정확히 그 사고를
               겪었다(tts_qwen._key 주석). 그래서 열쇠 첫 칸이 'moss' 다.

             [🔴 GPU 는 하나다] Qwen 일꾼이 같은 카드를 물고 사장 낭독을 굽는다.
               MOSS 는 0.1B 라 몫이 작지만, 그래도 **놀면 내린다**(IDLE_S).

REVISION HISTORY:
- 2026-08-17 Claude: 최초 작성 — 고르는 칸을 하나 더한다(사장 지시).
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile
import threading
import time

from . import tts_cache

_VOICE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

MODEL_ID = os.environ.get('VOICE_MOSS_MODEL', 'OpenMOSS-Team/MOSS-TTS-Nano-100M-ONNX')

# 일꾼과 그 살림. [🔴 왜 G: 인가] 이 모델은 아직 **이 개발 PC 에서만** 돈다 —
#   ONNX 살림 728MB 와 전용 venv(onnxruntime-gpu + nvidia cu12)가 rtf1 에 있다.
#   동봉본에 실어 보낼 물건이 되면 그때 tts_qwen 처럼 seed 경로를 더한다.
#   그때까지는 **없으면 목록에 안 뜬다**(available()) — 새로 깐 PC 에서 조용히 실패하지 않게.
WORKER_PY = os.environ.get(
    'VOICE_MOSS_PY', r'G:\apix-voice2\rtf1\mossenv\Scripts\python.exe')
WORKER_JOB = os.environ.get(
    'VOICE_MOSS_WORKER', r'G:\apix-voice2\work\z_moss_worker.py')

# 일꾼이 뜰 때까지. 실측 load 17.5초 + 워밍업 5.0초 = 23초. 세 배를 둔다.
BOOT_S = int(os.environ.get('VOICE_MOSS_BOOT', '120'))
# 한 문장 굽기 상한. 실측 64자 15.7초. 그 네 배.
SAY_S = int(os.environ.get('VOICE_MOSS_TIMEOUT', '60'))
# 이만큼 아무도 안 부르면 내린다 — 같은 카드를 Qwen 낭독이 쓴다.
IDLE_S = int(os.environ.get('VOICE_MOSS_IDLE', '600'))

# 일꾼이 제 답에 붙이는 표식(work/z_moss_worker.py 의 MARK 와 반드시 같아야 한다).
MARK = '@@M@@'

VOICES = [
    {
        'id': 'moss:apix',
        'label': '아픽스 나노 (사장님 목소리 · 첫 소리 0.2초)',
        'engine': 'moss',
        'lang': 'ko',
        'note': '첫 소리가 빠릅니다(0.2초). 긴 글 전체 속도는 Qwen 이 빠릅니다',
    },
]

_proc: subprocess.Popen | None = None
_lock = threading.RLock()
_last_used = 0.0
_reaper: threading.Thread | None = None


def _ref_sha() -> str:
    """참조(사장님 목소리 원본)의 지문. **tts_qwen 이 읽는 곳과 같은 자리**를 쓴다 —
    두 엔진이 같은 참조로 굽는데 지문을 따로 재면 '왜 이 목소리가 났나'를 못 밝힌다."""
    try:
        from .tts_qwen import _ref_sha as qwen_ref_sha
        return qwen_ref_sha()
    except Exception:                                          # noqa: BLE001
        return ''


def installed() -> bool:
    return os.path.exists(WORKER_PY) and os.path.exists(WORKER_JOB)


def available() -> bool:
    """[🔴 없으면 목록에 아예 안 올린다] tts_qwen 은 '고르면 받는다'를 하지만 이쪽은
    아직 받아 오는 절차가 없다. 못 쓰는 칸을 화면에 띄우면 고른 사람은 무음을 겪는다."""
    if os.environ.get('VOICE_MOSS', '1').strip() in ('0', 'false', 'off'):
        return False
    return installed()


def list_voices() -> list[dict]:
    return [dict(v) for v in VOICES] if available() else []


def worker_alive() -> bool:
    return _proc is not None and _proc.poll() is None


def _kill_worker(why: str = '') -> None:
    global _proc
    with _lock:
        p, _proc = _proc, None
    if p is None:
        return
    try:
        p.stdin.write(json.dumps({'cmd': 'quit'}) + '\n')
        p.stdin.flush()
        p.wait(timeout=10)
    except Exception:                                          # noqa: BLE001
        try:
            p.kill()
        except Exception:                                      # noqa: BLE001
            pass


def _start_reaper() -> None:
    """놀고 있으면 내려 카드를 돌려준다. Qwen 쪽과 같은 장치다."""
    global _reaper
    if _reaper is not None and _reaper.is_alive():
        return

    def run():
        while True:
            time.sleep(30)
            if not worker_alive():
                return
            if _last_used and time.time() - _last_used > IDLE_S:
                _kill_worker('idle')
                return

    _reaper = threading.Thread(target=run, name='moss-reaper', daemon=True)
    _reaper.start()


def _read_line(p: subprocess.Popen, timeout_s: int) -> dict:
    """표식 붙은 한 줄을 시한 안에 읽는다.
    [WHY 스레드로 감싸나] 윈도에서는 파이프에 select 를 못 쓴다 — 시한이 없으면
      일꾼이 굳었을 때 낭독 스레드가 영원히 잡힌다(tts_qwen._read_line 과 같은 이유).
    [🔴 표식 없는 줄은 버린다] onnxruntime 이 뜰 때 경고를 여러 줄 찍는다."""
    box: dict = {}

    def rd():
        try:
            while True:
                line = p.stdout.readline()
                if not line:
                    box['line'] = ''
                    return
                if MARK in line:
                    box['line'] = line[line.index(MARK) + len(MARK):]
                    return
        except Exception as e:                                 # noqa: BLE001
            box['err'] = str(e)

    t = threading.Thread(target=rd, daemon=True)
    t.start()
    t.join(timeout_s)
    if t.is_alive():
        raise RuntimeError(f'MOSS 일꾼이 {timeout_s}초 안에 답하지 않았습니다')
    line = (box.get('line') or '').strip()
    if not line:
        raise RuntimeError(f"MOSS 일꾼이 끊겼습니다({box.get('err', 'EOF')})")
    try:
        return json.loads(line)
    except ValueError:
        return {'ok': False, 'error': f'알 수 없는 응답: {line[:200]}'}


def _ensure_worker() -> subprocess.Popen:
    global _proc
    with _lock:
        if worker_alive():
            return _proc
        if not available():
            raise RuntimeError(f'MOSS 일꾼을 찾을 수 없습니다({WORKER_PY} / {WORKER_JOB})')
        # [제약] stderr 는 파이프로 받지 않는다 — 아무도 안 읽으면 자식이 멈춘다.
        #   onnxruntime 은 경고를 많이 찍어 이 함정이 특히 잘 걸린다.
        env = dict(os.environ, PYTHONIOENCODING='utf-8')
        _proc = subprocess.Popen(
            [WORKER_PY, '-u', WORKER_JOB],
            stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL,
            text=True, encoding='utf-8', errors='replace', bufsize=1, env=env,
            creationflags=getattr(subprocess, 'CREATE_NO_WINDOW', 0))
        ready = _read_line(_proc, BOOT_S)
        if not ready.get('ok'):
            err = ready.get('error', '')
            _kill_worker('boot-failed')
            raise RuntimeError(f'MOSS 일꾼이 뜨지 못했습니다: {err or ready}')
        # [🔴 CPU 로 조용히 떨어진 것을 여기서 잡는다] 일꾼이 등록한 CUDA DLL 자리 수가
        #   0 이면 EP 가 cuda 여도 실제로는 CPU 다(z_moss_worker 헤더의 함정).
        if ready.get('ep') == 'cuda' and not ready.get('cuda_dirs'):
            print('[moss] CUDA DLL 자리를 못 잡았다 — CPU 로 돌고 있다(느리다)',
                  file=sys.stderr, flush=True)
        _start_reaper()
        return _proc


def _bake(text: str) -> bytes:
    """일꾼에게 한 문장을 시키고 wav 바이트를 받는다."""
    global _last_used
    fd, tmp = tempfile.mkstemp(suffix='.wav', prefix='moss_')
    os.close(fd)
    try:
        with _lock:                       # 일꾼은 하나다 — 요청을 줄 세운다
            p = _ensure_worker()
            req = json.dumps({'cmd': 'say', 'text': text, 'out': tmp},
                             ensure_ascii=False)
            try:
                p.stdin.write(req + '\n')
                p.stdin.flush()
            except Exception as e:                             # noqa: BLE001
                _kill_worker('write-failed')
                raise RuntimeError(f'MOSS 일꾼에 말을 걸지 못했습니다: {e}') from e
            res = _read_line(p, SAY_S)
            _last_used = time.time()
        if not res.get('ok'):
            raise RuntimeError(f"MOSS 굽기 실패: {res.get('error')}")
        with open(tmp, 'rb') as fp:
            data = fp.read()
        if not data:
            raise RuntimeError('MOSS 일꾼이 빈 소리를 냈습니다')
    finally:
        try:
            os.unlink(tmp)
        except OSError:
            pass
    return data


class MossEngine:
    """voice_id = 'moss:apix'. 밖으로 내는 것은 load() 와 synth() 둘뿐이다."""

    mime = 'audio/wav'
    ext = 'wav'

    def __init__(self, voice_id: str = '') -> None:
        self.voice = 'apix'

    def _key(self, text: str) -> str:
        """[🔴 첫 칸이 엔진이다] Qwen 과 MOSS 는 **같은 문장 · 같은 참조**로도 다른
        소리다. 엔진을 안 넣으면 칸을 바꿔도 앞 엔진이 구워 둔 소리가 그대로 나온다 —
        2026-08-16 에 참조 지문에서 겪은 사고와 같은 모양이다(tts_qwen._key 주석)."""
        return tts_cache.key_of('moss', self.voice, MODEL_ID, _ref_sha(), text)

    def load(self) -> None:
        """[🔴 기본은 안 띄운다] 예열이 카드를 무는 순간 Qwen 낭독이 그만큼 굶는다.
        일꾼은 첫 낭독 요청 때 뜬다(실측 23초). 미리 띄우려면 VOICE_MOSS_PRELOAD=1."""
        if not available():
            raise RuntimeError(f'MOSS 일꾼을 찾을 수 없습니다({WORKER_PY})')
        if os.environ.get('VOICE_MOSS_PRELOAD', '').strip() in ('1', 'true', 'on'):
            _ensure_worker()

    def synth(self, text: str, speed: float = 1.0) -> bytes:
        key = self._key(text)
        hit = tts_cache.get(key, self.ext)
        if hit is not None:
            return hit
        data = _bake(text)
        tts_cache.put(key, data, self.ext)
        return data

    def synth_parts(self, text: str, speed: float = 1.0):
        """소리가 **나는 대로** 조각을 내놓는다(voice_server._tts_seq 가 이걸 쓴다).

        [🔴 왜 따로 두나 — 이 엔진을 붙인 값어치의 전부가 여기 있다] `synth()` 는 계약대로
          다 구운 한 덩어리를 준다. 그런데 이 모델은 소리를 **0.2초에 이미 만든다**
          (rtf1/moss_ttfa.json). 한 덩어리로 주면 그 0.2초가 사장 귀까지 못 온다.
          그래서 `synth()` 의 계약은 건드리지 않고 **조각을 흘려보내는 길을 따로** 뒀다.

        [🔴 Qwen 의 synth_parts 와 무엇이 다른가] 저쪽은 **문장을 잘라** 조각마다 굽는다
          (조각 하나 = 문장 한 도막, 그래서 첫 소리 = 첫 도막을 다 굽는 시간).
          이쪽은 **한 문장을 굽는 도중에** 만들어지는 소리를 그대로 흘려보낸다 —
          자르지 않으므로 이어 붙이는 자리가 없고, 첫 소리는 굽기가 끝나기 훨씬 전이다.

        [🔴 첫 조각에도 바닥이 있다] 런타임이 맨 처음 내놓는 것은 0.08초짜리 부스러기라,
          그대로 내보내면 시작하자마자 딸꾹질한다. 일꾼이 0.4초는 모아서 낸다
          (VOICE_MOSS_SEG_FIRST). 실측 첫 소리 0.49~0.56초.

        [🔴 캐시는 통짜로만] 조각에는 제 글이 없다(문장을 안 자르므로). 조각을 열쇠로
          담을 수 없으니 **다 끝난 뒤 원문 열쇠로 한 번** 담는다 — 같은 문장이 다시 오면
          위 synth() 가 즉시 돌려준다(실측 0.01초).
        """
        key = self._key(text)
        hit = tts_cache.get(key, self.ext)
        if hit is not None:
            yield text, hit                   # 이미 구운 문장 — 흘려보낼 것이 없다
            return

        fd, dst = tempfile.mkstemp(suffix='.wav', prefix='moss_seq_')
        os.close(fd)
        segs: list[str] = []
        try:
            with _lock:                       # 일꾼은 하나다 — 한 요청씩 줄 세운다
                p = _ensure_worker()
                p.stdin.write(json.dumps({'cmd': 'say_stream', 'text': text, 'out': dst},
                                         ensure_ascii=False) + '\n')
                p.stdin.flush()
                first = True
                while True:
                    res = _read_line(p, SAY_S)
                    if not res.get('ok'):
                        raise RuntimeError(f"MOSS 흘려보내기 실패: {res.get('error')}")
                    if res.get('done'):
                        break
                    path = res.get('path') or ''
                    segs.append(path)
                    try:
                        with open(path, 'rb') as fp:
                            data = fp.read()
                    except OSError:
                        continue
                    if data:
                        # 글은 첫 조각에만 싣는다 — 뒤 조각은 같은 문장의 이어지는 소리다.
                        yield (text if first else ''), data
                        first = False
            globals()['_last_used'] = time.time()
            try:                              # 통짜를 캐시에 담아 다음번을 즉시로
                with open(dst, 'rb') as fp:
                    whole = fp.read()
                if whole:
                    tts_cache.put(key, whole, self.ext)
            except OSError:
                pass
        finally:
            for p2 in segs + [dst]:
                try:
                    os.unlink(p2)
                except OSError:
                    pass
