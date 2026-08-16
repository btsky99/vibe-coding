# -*- coding: utf-8 -*-
"""
FILE: .ai_monitor/voice-server/engines/tts_qwen.py
DESCRIPTION: 낭독 엔진 — Qwen3-TTS 로 사장님 목소리를 복제해 읽는다.

             [WHY 두 번째 엔진이 생겼나 — 2026-08-16 청취 판정] edge-tts 는 남의 목소리다.
               사장님 샘플(25.7초)로 복제한 Qwen3-TTS-12Hz-0.6B-Base 를 직접 들으시고
               "속도 맞춤보다 그냥이 훨씬 좋은데. 굿. 교체 진행해보자" 로 채택됐다.
               edge 는 걷어내지 않는다 — 이 엔진이 못 뜨면 소리가 아예 안 난다.

             [🔴 모델을 이 venv 에 들이지 않는다] 낭독 사이드카 venv 에는 torch 가 아예
               없다(faster-whisper 는 ctranslate2 를 쓴다 — 실측 확인). CUDA torch ~3GB 를
               들이면 받아쓰기까지 흔들리고, 프로세스를 갈라 둔 이유와 어긋난다.
               Qwen 은 이미 G:\\apix-voice2\\envs\\qwen_cuda 에 서 있다.

             [🔴 일꾼을 상주시킨다 — 2026-08-16 사장 지시] 부를 때마다 프로세스를 새로
               띄우면 import 30초 + 모델 올림 8~21초가 매번 붙어 61초가 된다. 모델을 물고
               있으면 12~17초다. 그 대가로 GPU 2.2GB 를 계속 문다. 사장이 그 값을 알고
               "13초가 걸린다고? 일단 붙여봐" 라고 하셨다.

             [🔴 학습이 이긴다 — 코드로 박아 둔 규칙]
               ① 일꾼이 굽기 전마다 실여유를 재고 1GB 밑이면 'busy' 를 돌려준다.
               ② 그 답을 받으면 여기서 일꾼을 **내린다** — 2.2GB 가 학습으로 돌아간다.
               ③ IDLE_S 동안 아무도 안 부르면 저절로 내려간다. 낭독을 안 쓰는 밤에
                  카드가 잡혀 있을 이유가 없다.
               ④ 일꾼이 내려가도 소리는 안 끊긴다 — 예외를 내면 프론트가 브라우저
                  합성기로 내려가고, 미리 구운 문장은 캐시에서 그대로 나간다.

             [🔴 오디오는 파이프로 나르지 않는다] 이 저장소는 stdout=PIPE 를 안 읽어 자식이
               멈춘 사고를 두 번 겪었다(voice_api.py 헤더). 일꾼은 wav 를 파일로 쓰고,
               파이프에는 짧은 JSON 한 줄만 흘린다. 요청 하나에 한 줄 — 부모가 반드시 읽는다.

             [🔴 이어 굽기] synth_parts() 는 긴 글을 문장으로 잘라 앞에서부터 굽고 하나씩
               내놓는다. 첫 소리는 첫 조각이 끝나는 대로 나간다(전체를 기다리지 않는다).
               [실측이 말하는 한계] 굽기는 소리보다 6배 느리다(RTF ~6). 즉 재생이 굽기를
               앞질러 두 번째 조각부터는 기다림이 생긴다 — 첫 소리를 앞당기는 장치이지
               끊김을 없애는 장치가 아니다. 숫자는 docs/voice-qwen-교체.md 에 적어 뒀다.

             [🔴 속도를 손대지 않는다] 사장님이 원본 속도를 고르셨다. speed 인자를 무시하고
               캐시 키에도 넣지 않는다 — 넣으면 미리 구워 둔 문장이 빗나가 매번 새로 굽는다.

REVISION HISTORY:
- 2026-08-16 Claude: 최초 작성 — 사장님 목소리 복제 낭독(청취 판정으로 채택)
- 2026-08-16 Claude: 모델을 사이드카 venv 에 들이는 대신 외부 파이썬을 자식으로 부르게 고침
- 2026-08-16 Claude: 자식을 상주시켜 61초 → 13초(사장 지시). 학습이 오면 내려간다.
  이어 굽기(synth_parts) 추가 — 첫 소리를 앞당긴다
"""

from __future__ import annotations

import json
import os
import subprocess
import tempfile
import threading
import time

from engines import tts_cache, tts_split

ENABLED = os.environ.get('VOICE_QWEN', '1').strip() not in ('0', 'false', 'off')

WORKER_PY = os.environ.get(
    'VOICE_QWEN_PYTHON', r'G:\apix-voice2\envs\qwen_cuda\Scripts\python.exe')
WORKER_JOB = os.environ.get(
    'VOICE_QWEN_WORKER', r'G:\apix-voice2\work\z_qwen_worker.py')
MODEL_ID = os.environ.get('VOICE_QWEN_MODEL', 'Qwen/Qwen3-TTS-12Hz-0.6B-Base')

# 일꾼이 뜰 때까지(=모델 올림) 기다리는 상한. import 30초 + 올림 21초를 넉넉히 덮는다.
BOOT_S = int(os.environ.get('VOICE_QWEN_BOOT', '120'))
# 한 문장 굽기 상한. 실측 12~17초, 긴 문장 28초. 그 세 배를 둔다.
SAY_S = int(os.environ.get('VOICE_QWEN_TIMEOUT', '90'))
# 이만큼 아무도 안 부르면 일꾼을 내려 GPU 를 돌려준다.
IDLE_S = int(os.environ.get('VOICE_QWEN_IDLE', '600'))

# 일꾼이 제 답에 붙이는 표식. 라이브러리 배너와 내 답을 가르는 유일한 수단이다
# (work/z_qwen_worker.py 의 MARK 와 반드시 같아야 한다).
MARK = '@@Q@@'

VOICES = [
    {
        'id': 'qwen:apix',
        'label': '아픽스 (사장님 목소리 복제)',
        'engine': 'qwen',
        'lang': 'ko',
        'note': '미리 구운 문구는 즉시 · 새 문장은 13초 안팎(GPU 상주)',
    },
]

_proc: subprocess.Popen | None = None
_lock = threading.RLock()
_last_used = 0.0
_reaper: threading.Thread | None = None


def available() -> bool:
    """[🔴 여기서 qwen_tts 를 import 해 보지 않는다] 그 패키지는 이 venv 가 아니라 일꾼
    쪽에 있다. 여기서 볼 것은 '부를 수 있는가' 뿐이다."""
    if not ENABLED:
        return False
    return os.path.exists(WORKER_PY) and os.path.exists(WORKER_JOB)


def list_voices() -> list[dict]:
    return list(VOICES) if available() else []


def worker_alive() -> bool:
    return _proc is not None and _proc.poll() is None


def _kill_worker(why: str = '') -> None:
    """일꾼을 내려 GPU 를 돌려준다. 실패해도 예외를 올리지 않는다 — 내리는 길이 막히면
    다음 요청이 죽은 자식을 붙들게 된다."""
    global _proc
    with _lock:
        p, _proc = _proc, None
        if p is None:
            return
        try:
            if p.poll() is None:
                try:
                    p.stdin.write('{"cmd":"quit"}\n')
                    p.stdin.flush()
                except Exception:                              # noqa: BLE001
                    pass
                try:
                    p.wait(timeout=10)
                except subprocess.TimeoutExpired:
                    p.kill()
        except Exception:                                      # noqa: BLE001
            pass
        finally:
            for s in (p.stdin, p.stdout):
                try:
                    if s:
                        s.close()
                except Exception:                              # noqa: BLE001
                    pass


def _start_reaper() -> None:
    """놀고 있는 일꾼을 내리는 시계. [WHY 스레드인가] 요청이 안 오면 아무도 시간을 안 본다 —
    '안 쓰면 내려간다'는 규칙이 요청 안에만 있으면 영영 안 내려간다."""
    global _reaper
    if _reaper is not None and _reaper.is_alive():
        return

    def run():
        while True:
            time.sleep(30)
            if worker_alive() and _last_used and (time.time() - _last_used) > IDLE_S:
                _kill_worker('idle')

    _reaper = threading.Thread(target=run, daemon=True, name='qwen-idle-reaper')
    _reaper.start()


def _ensure_worker() -> subprocess.Popen:
    global _proc
    with _lock:
        if worker_alive():
            return _proc
        if not available():
            raise RuntimeError(f'Qwen 일꾼을 찾을 수 없습니다({WORKER_PY} / {WORKER_JOB})')
        # [제약] stderr 는 파이프로 받지 않는다 — 아무도 안 읽으면 자식이 멈춘다.
        #   진단이 필요하면 일꾼이 stdout 한 줄로 error 를 돌려준다.
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
            if err == 'busy':
                raise RuntimeError('GPU 여유 부족 — 학습 보호로 일꾼을 올리지 않았습니다')
            raise RuntimeError(f'Qwen 일꾼이 뜨지 못했습니다: {err or ready}')
        _start_reaper()
        return _proc


def _read_line(p: subprocess.Popen, timeout_s: int) -> dict:
    """한 줄을 시한 안에 읽는다. [WHY 스레드로 감싸나] 윈도에서는 파이프에 select 를 못 쓴다.
    시한이 없으면 일꾼이 굳었을 때 낭독 스레드가 영원히 잡힌다."""
    box: dict = {}

    def rd():
        # [🔴 표식 없는 줄은 버린다] qwen_tts 가 뜰 때 배너를 stdout 에 찍는다. 그것을
        #   답으로 읽으면 '알 수 없는 응답'이 되어 멀쩡한 일꾼을 죽인다(2026-08-16 실측).
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
        raise RuntimeError(f'Qwen 일꾼이 {timeout_s}초 안에 답하지 않았습니다')
    line = (box.get('line') or '').strip()
    if not line:
        raise RuntimeError(f"Qwen 일꾼이 끊겼습니다({box.get('err', 'EOF')})")
    try:
        return json.loads(line)
    except ValueError:
        return {'ok': False, 'error': f'알 수 없는 응답: {line[:200]}'}


def _bake(text: str) -> bytes:
    """일꾼에게 한 문장을 시키고 wav 바이트를 받는다."""
    global _last_used
    fd, tmp = tempfile.mkstemp(suffix='.wav', prefix='qwen_')
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
                raise RuntimeError(f'Qwen 일꾼에 말을 걸지 못했습니다: {e}') from e
            res = _read_line(p, SAY_S)
            _last_used = time.time()
        if not res.get('ok'):
            if res.get('error') == 'busy':
                # [🔴 여기가 '학습이 이긴다'가 실제로 일어나는 자리] 일꾼을 내려 2.2GB 를
                #   돌려주고, 예외로 올려 프론트가 브라우저 합성기로 내려가게 한다.
                _kill_worker('busy')
                raise RuntimeError('GPU 여유 부족 — 학습 보호로 굽지 않았습니다')
            raise RuntimeError(f"Qwen 굽기 실패: {res.get('error')}")
        with open(tmp, 'rb') as fp:
            data = fp.read()
    finally:
        try:
            os.unlink(tmp)
        except OSError:
            pass
    if not data:
        raise RuntimeError('Qwen 이 오디오를 만들지 못했습니다')
    return data


class QwenEngine:
    """voice_id = 'qwen:apix'. 지금은 목소리가 하나뿐이다(사장님 샘플)."""

    mime = 'audio/wav'
    ext = 'wav'

    def __init__(self, voice_id: str = '') -> None:
        self.voice = 'apix'

    def _key(self, text: str) -> str:
        return tts_cache.key_of('qwen', self.voice, MODEL_ID, text)

    def load(self) -> None:
        """[WHY 기본값이 '안 띄운다' 인가] 예열이 GPU 를 무는 순간, 음성을 켠 것만으로
        학습이 굶는다. 그래서 일꾼은 첫 낭독 요청 때 뜬다.

        [🔴 그 대가는 첫 요청 한 번이 통째로 느려지는 것이다 — 실측 115초]
          일꾼을 띄우는 데 import 30초 + 모델 올림이 붙는다. 학습이 없는 낮에는
          VOICE_QWEN_PRELOAD=1 로 두면 사이드카 예열 때 미리 띄워 그 값을 없앤다.
          대신 그 순간부터 GPU 2.2GB 를 문다 — 켜고 끄는 것은 사람이 정한다.
        """
        if not available():
            raise RuntimeError(f'Qwen 일꾼을 찾을 수 없습니다({WORKER_PY})')
        if os.environ.get('VOICE_QWEN_PRELOAD', '').strip() in ('1', 'true', 'on'):
            _ensure_worker()

    def synth(self, text: str, speed: float = 1.0) -> bytes:
        key = self._key(text)
        hit = tts_cache.get(key, self.ext)
        if hit is not None:
            return hit                    # 미리 구운 문장 — 일꾼도 GPU 도 필요 없다
        data = _bake(text)
        tts_cache.put(key, data, self.ext)
        return data

    def synth_parts(self, text: str, speed: float = 1.0):
        """긴 글을 문장으로 잘라 앞에서부터 하나씩 내놓는다(이어 굽기).

        [WHY 미리 안 굽고 하나씩 주나] 전체를 다 구운 뒤 주면 첫 소리가 글 전체 길이만큼
          늦는다(131자 = 120초). 앞에서부터 주면 첫 소리는 첫 조각 값(13초 안팎)이다.
        [🔴 앞서 굽기를 몇 개 두나 — 두지 않는다] 굽기가 소리보다 6배 느리다(RTF ~6).
          한 조각을 굽는 12초 동안 재생은 2초를 쓴다. 몇 개를 앞서 굽든 재생이 굽기를
          앞지르므로 앞서 굽기는 끊김을 못 막고, 미리 굽는 만큼 첫 소리만 늦춘다.
          그래서 '한 조각 굽고 곧바로 내보내기'가 이 판에서 최선이다. 끊김을 없애려면
          모델이 바뀌어야 한다 — 배선으로 되는 일이 아니다.
        """
        for part in tts_split.split(text):
            key = self._key(part)
            hit = tts_cache.get(key, self.ext)
            if hit is None:
                hit = _bake(part)
                tts_cache.put(key, hit, self.ext)
            yield part, hit
