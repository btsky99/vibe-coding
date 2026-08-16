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

             [🔴 이어 굽기 — 이제 '첫 조각 홀로 + 나머지 묶음'이다(2026-08-16 보드 이식)]
               예전에는 조각을 하나씩 차례로 구웠다(cmd:say). 지금은 목록을 통째로 맡기고
               (cmd:say_parts) 일꾼이 **첫 조각만 작게 홀로** 굽고 그 자리에서 답을 한 줄
               보낸 뒤, **나머지를 한 번에 묶어** 굽는다. 왜 묶는 것이 빠른가 — 병목이
               계산이 아니라 커널을 하나씩 띄우는 값이라 배치1 22.1초 vs 배치16 36.9초다
               (일 16배에 시간 1.7배, 보드 ac_batch_bench 실측).
               [🔴 CUDA 그래프는 일꾼 쪽에 있다] code_predictor 15스텝을 그래프 한 장으로
                 묶어 replay 한 번으로 만든 것(보드 커밋 f1e3dd4, work/qgraph.py).
                 **이 파일이 그 일꾼 파일을 그대로 부르므로 여기서 할 일은 없다** — 다만
                 끄는 길은 알아 둘 것: 환경변수 VOICE_QWEN_GRAPH=0 또는 파일
                 G:\\apix-voice2\\work\\graph.off 를 만들고 일꾼을 내리면 옛 길로 돈다.

             [🔴 속도를 손대지 않는다] 사장님이 원본 속도를 고르셨다. speed 인자를 무시하고
               캐시 키에도 넣지 않는다 — 넣으면 미리 구워 둔 문장이 빗나가 매번 새로 굽는다.

             [🔴 참조 지문은 캐시 열쇠에 넣는다] 안 넣으면 사장님이 참조(목소리 원본)를
               바꾸셔도 옛 소리가 그대로 난다 — 보드가 2026-08-16 정확히 그 사고를 겪었다.
               ref_info() 참조.

REVISION HISTORY:
- 2026-08-16 Claude: 최초 작성 — 사장님 목소리 복제 낭독(청취 판정으로 채택)
- 2026-08-16 Claude: 모델을 사이드카 venv 에 들이는 대신 외부 파이썬을 자식으로 부르게 고침
- 2026-08-16 Claude: 자식을 상주시켜 61초 → 13초(사장 지시). 학습이 오면 내려간다.
  이어 굽기(synth_parts) 추가 — 첫 소리를 앞당긴다
- 2026-08-16 Claude: 보드에서 완성한 것 이식 — ① 조각내 굽기를 일꾼의 say_parts(첫 조각
  홀로 + 나머지 묶음)로 교체 ② 참조 wav 지문을 캐시 열쇠에 ③ GPU 를 보드 일꾼과 나눠
  쓰도록 몫 상한을 걸어 띄운다
"""

from __future__ import annotations

import hashlib
import json
import os
import shutil
import subprocess
import sys
import tempfile
import threading
import time
from pathlib import Path

from engines import tts_cache, tts_split

ENABLED = os.environ.get('VOICE_QWEN', '1').strip() not in ('0', 'false', 'off')

# ── 어디에 굽는 살림이 있나 ──────────────────────────────────────────────────────
# [🔴 2026-08-17 — G: 고정 경로를 벗어난 이유] 여기 적혀 있던 자리는 이 개발 PC 의
#   G:\apix-voice2 였다. 설치본이 깔리는 PC 에는 그런 드라이브가 없어, 새로 깐 사람은
#   사장님 목소리를 **영영 못 썼다**(조용히 available()=False 로 목록에서 빠졌다).
#   이제 살림은 앱이 들고 다닌다 — 일꾼·그래프·참조는 동봉(620KB), 모델과 CUDA 토치만
#   첫 실행 때 받는다(scripts/setup_qwen.py 헤더에 못 싣는 이유가 적혀 있다).
# [불변식] 이 경로는 scripts/setup_qwen.qwen_dir() 와 **같은 자리를 가리켜야 한다**.
#   어긋나면 다 받아 놓고도 여기서는 '없다'가 되어 무한히 다시 받는다.
_HERE = os.path.dirname(os.path.abspath(__file__))          # .../voice-server/engines
_VOICE_DIR = os.path.dirname(_HERE)                          # .../voice-server


def _qwen_home() -> str:
    """굽는 살림이 놓일 자리.

    [🔴 번들 안(_MEIPASS)에는 깔면 안 된다] onefile 이 푸는 임시 폴더라 앱이 꺼지면
      지워진다. 거기에 5GB 를 받으면 켤 때마다 다시 받는다. 그 경우만 사용자 폴더로 뺀다.
    """
    cand = os.path.join(_VOICE_DIR, 'qwen')
    mei = getattr(sys, '_MEIPASS', '')
    if mei and os.path.abspath(cand).startswith(os.path.abspath(mei)):
        base = os.environ.get('LOCALAPPDATA') or os.path.expanduser('~')
        return os.path.join(base, 'VibeCoding', 'qwen')
    return cand


QWEN_HOME = os.environ.get('VOICE_QWEN_HOME', '') or _qwen_home()
# 동봉본(번들/체크아웃)의 자리 — QWEN_HOME 이 사용자 폴더로 빠졌을 때 여기서 복사해 온다.
QWEN_SEED = os.path.join(_VOICE_DIR, 'qwen')

# [🔴 개발 PC 의 옛 자리는 폴백으로만 남긴다] 보드(G:\apix-voice2)가 이미 다 깔린
#   이 PC 에서는 5GB 를 또 받을 이유가 없다. 살림이 아직 없고 옛 자리가 살아 있으면
#   그쪽을 쓴다. 새로 깐 PC 에는 이 경로가 아예 없으므로 자연히 무시된다.
_DEV_PY = r'G:\apix-voice2\envs\qwen_cuda\Scripts\python.exe'
_DEV_JOB = r'G:\apix-voice2\work\z_qwen_worker.py'


def _worker_paths() -> tuple[str, str]:
    """(실행기, 일꾼). 환경변수 > 내 살림 > 개발 PC 옛 자리 순."""
    py = os.environ.get('VOICE_QWEN_PYTHON', '')
    job = os.environ.get('VOICE_QWEN_WORKER', '')
    if py and job:
        return py, job
    mine_py = os.path.join(QWEN_HOME, '.venv', 'Scripts', 'python.exe')
    if os.name != 'nt':
        mine_py = os.path.join(QWEN_HOME, '.venv', 'bin', 'python')
    mine_job = os.path.join(QWEN_HOME, 'worker.py')
    if os.path.exists(mine_py) and os.path.exists(mine_job):
        return mine_py, mine_job
    if os.path.exists(_DEV_PY) and os.path.exists(_DEV_JOB):
        return _DEV_PY, _DEV_JOB
    return mine_py, mine_job                 # 아직 없다 — 설치가 채울 자리를 가리킨다


WORKER_PY, WORKER_JOB = _worker_paths()
MODEL_ID = os.environ.get('VOICE_QWEN_MODEL', 'Qwen/Qwen3-TTS-12Hz-0.6B-Base')

# 프로젝트 뿌리와 scripts/ — 설치 절차(setup_qwen)를 불러오기 위한 자리.
_ROOT = os.path.dirname(os.path.dirname(_VOICE_DIR))          # .../<프로젝트>
_SCRIPTS_DIR = os.path.join(_ROOT, 'scripts')

_can_cache: dict = {'at': 0.0, 'val': False}
# 설치 진행 상태. /status 가 이걸 그대로 내보내 화면이 '지금 뭘 받는 중'을 띄운다
# (규칙 10 — 콘솔이 없으니 진행을 볼 곳은 화면뿐이다).
_setup: dict = {'running': False, 'step': '', 'error': ''}
_setup_thread: threading.Thread | None = None
_setup_lock = threading.Lock()

# 일꾼이 뜰 때까지(=모델 올림) 기다리는 상한. import 30초 + 올림 21초를 넉넉히 덮는다.
BOOT_S = int(os.environ.get('VOICE_QWEN_BOOT', '120'))
# 한 문장 굽기 상한. 실측 12~17초, 긴 문장 28초. 그 세 배를 둔다.
SAY_S = int(os.environ.get('VOICE_QWEN_TIMEOUT', '90'))
# 이만큼 아무도 안 부르면 일꾼을 내려 GPU 를 돌려준다.
IDLE_S = int(os.environ.get('VOICE_QWEN_IDLE', '600'))
# 묶음 굽기 상한의 천장. 조각 수에 따라 늘리되 여기서 멈춘다.
BATCH_MAX_S = int(os.environ.get('VOICE_QWEN_BATCH_TIMEOUT', '600'))

# [🔴 GPU 는 하나다 — 보드 굽기와 나눠 쓴다(2026-08-16)] 같은 카드(12GB)에서 보드 쪽
#   일꾼(G:\apix-voice2 의 ag_bake_now 가 물고 있는 z_qwen_worker)이 이미 4~5GB 를 쓴다.
#   일꾼 기본 몫은 0.55(=6.8GB)라 둘이 그 값으로 서면 합이 카드보다 커진다.
#   그래서 **이쪽 일꾼에게만** 더 작은 몫을 씌워 띄운다. 이쪽은 조각이 24자 이하라
#   묶음 봉우리가 작다(보드는 배치 16까지 쓴다).
#   [제약] 이 값은 상한이지 예약이 아니다 — 넘치면 학습이 아니라 **내 일꾼이 먼저 터진다**.
#     그것이 이 저장소가 뜻한 '학습이 이긴다' 이고, 터지면 부모가 일꾼을 내려 카드를 돌려준다.
FRACTION = os.environ.get('VOICE_QWEN_FRACTION', '0.35')

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


# ── 참조(사장님 목소리 원본) 지문 ────────────────────────────────────────────────
# [🔴 왜 지문이 캐시 열쇠에 들어가야 하나 — 2026-08-16 보드 사고] 참조 wav 를 바꿔도
#   열쇠가 그대로면 **옛 목소리가 그대로 난다**. 길이로는 못 가른다(같은 길이로 다시
#   녹음하시면 그대로다). 그래서 파일 내용의 sha256 을 넣는다.
# [🔴 이쪽은 참조를 고르지 않는다] 어느 참조로 굽는지는 굽는 쪽(z_qwen_worker 의 REF_WAV)이
#   정하고 ag_bake_now 가 ref_info.json 에 적어 둔다. 여기서는 **읽기만** 한다.
# [🔴 참조 파일은 내 살림 것이 먼저다 — 2026-08-17] 동봉본을 실어 보내므로 새로 깐 PC 도
#   같은 참조를 갖는다. G: 자리는 이 개발 PC 에만 있는 폴백이다.
_REF_INFO_PATH = os.environ.get(
    'VOICE_REF_INFO', r'G:\apix-voice2\work\bake_now\ref_info.json')


def _ref_wav_path() -> str:
    env = os.environ.get('VOICE_QWEN_REF', '')
    if env:
        return env
    for base in (QWEN_HOME, QWEN_SEED):
        p = os.path.join(base, 'boss_pick.wav')
        if os.path.exists(p):
            return p
    return r'G:\apix-voice2\ref\boss_pick.wav'
_ref_cache: dict = {'at': 0.0, 'val': None}
_REF_TTL_S = 5.0


def ref_info() -> dict | None:
    """{key, file, sha256, sec} 또는 None. voice_server 의 /status 도 이걸 쓴다
    (같은 값을 두 군데서 읽지 않게 — 어긋나면 '왜 이 목소리가 났나'를 못 밝힌다).

    [WHY 파일을 직접 해시하는 길을 남기나] 굽는 쪽이 한 번도 안 떴으면 ref_info.json 이
      없다. 그래도 참조 wav 는 제자리에 있으므로 그것을 직접 재면 같은 값이 나온다.
    [🔴 못 구하면 None 이다 — 열쇠에는 빈 칸으로 들어간다] 그 상태로 구운 소리와
      지문을 아는 상태로 구운 소리는 열쇠가 달라 서로를 덮지 않는다(그게 맞다)."""
    now = time.time()
    if now - _ref_cache['at'] < _REF_TTL_S:
        return _ref_cache['val']
    val = None
    try:
        with open(_REF_INFO_PATH, encoding='utf-8') as f:
            d = json.load(f)
        if isinstance(d, dict) and d.get('sha256'):
            val = d
    except (OSError, ValueError):
        val = None
    if val is None:
        ref = _ref_wav_path()
        try:
            h = hashlib.sha256()
            with open(ref, 'rb') as f:
                for blk in iter(lambda: f.read(1 << 20), b''):
                    h.update(blk)
            val = {'key': os.path.splitext(os.path.basename(ref))[0],
                   'file': ref, 'sha256': h.hexdigest()}
        except OSError:
            val = None
    _ref_cache['at'], _ref_cache['val'] = now, val
    return val


def _ref_sha() -> str:
    return (ref_info() or {}).get('sha256') or ''


def installed() -> bool:
    """굽는 살림이 다 깔렸나(= 지금 당장 부를 수 있나)."""
    py, job = _worker_paths()
    return os.path.exists(py) and os.path.exists(job)


def available() -> bool:
    """목록에 이 목소리를 올릴 것인가.

    [🔴 아직 안 깔렸어도 올린다 — 2026-08-17] 예전에는 '파일이 있나'만 봐서, 새로 깐 PC 는
      목록에 아예 안 떴고 사용자는 **고를 수조차 없었다**. 고를 수 없으면 설치가 시작될
      계기도 없다 — 영영 안 되는 상태로 굳는다. 그래서 '깔 수 있는가'로 바꿨다.
    [🔴 단 NVIDIA 카드가 없으면 올리지 않는다] 이 모델은 CUDA 전용이다. 못 쓸 목소리를
      목록에 띄우면 고른 사람은 5GB 를 받은 뒤에야 실패를 안다.
    [WHY 여기서 qwen_tts 를 import 해 보지 않나] 그 패키지는 이 venv 가 아니라 일꾼 쪽에
      있다. 여기서 볼 것은 '부를 수 있는가' 뿐이다."""
    if not ENABLED:
        return False
    if installed():
        return True
    return _can_install()


def _can_install() -> bool:
    """동봉된 씨앗이 있고 GPU 가 있으면 깔 수 있다. 판정은 30초 되쓴다 —
    /voices 는 자주 불리는데 nvidia-smi 를 매번 부르면 그 값이 목록 응답에 얹힌다."""
    now = time.time()
    if now - _can_cache['at'] < 30.0:
        return bool(_can_cache['val'])
    val = False
    try:
        seed = QWEN_SEED if os.path.exists(os.path.join(QWEN_SEED, 'worker.py')) else QWEN_HOME
        if os.path.exists(os.path.join(seed, 'worker.py')):
            sys.path.insert(0, _SCRIPTS_DIR)
            import setup_qwen
            val = setup_qwen.has_nvidia()
    except Exception:                                          # noqa: BLE001
        val = False
    _can_cache['at'], _can_cache['val'] = now, val
    return val


def list_voices() -> list[dict]:
    """[🔴 아직 안 깔린 상태도 목록에 올린다] 고를 수 없으면 설치가 시작될 계기가 없다
    (available() 주석 참조). 대신 note 로 '처음 한 번 받는다'를 미리 알린다 —
    고른 뒤에야 알면 사용자는 고장으로 받아들인다."""
    if not available():
        return []
    out = [dict(v) for v in VOICES]
    if not installed():
        out[0]['note'] = ('처음 고르시면 목소리 파일을 받습니다(약 5GB, 한 번만) — '
                          '받는 동안은 다른 목소리로 읽습니다')
        out[0]['needsSetup'] = True
    return out


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


def setup_state() -> dict:
    """설치 진행 상태. /status 가 그대로 실어 화면에 띄운다."""
    return {'installed': installed(), 'running': bool(_setup['running']),
            'step': _setup['step'], 'error': _setup['error'], 'home': QWEN_HOME}


def _seed_assets() -> None:
    """살림 자리가 사용자 폴더로 빠졌으면 동봉본(일꾼·그래프·참조)을 거기로 옮겨 둔다.
    [🔴 덮어쓰지 않는다] 이미 있는 것을 새 판이 덮으면, 받다 만 상태와 섞인다."""
    if os.path.abspath(QWEN_SEED) == os.path.abspath(QWEN_HOME):
        return
    os.makedirs(QWEN_HOME, exist_ok=True)
    for name in ('worker.py', 'qgraph.py', 'ref_text.json', 'boss_pick.wav'):
        src, dst = os.path.join(QWEN_SEED, name), os.path.join(QWEN_HOME, name)
        if os.path.exists(src) and not os.path.exists(dst):
            shutil.copy2(src, dst)


def start_setup() -> str:
    """굽는 살림을 백그라운드로 깐다. 이미 도는 중이면 그 사실만 알린다.

    [🔴 왜 자동인가] 사장님이 이 목소리를 고르신 것이 곧 '쓰겠다'는 의사표시다. 여기서
      멈추고 명령줄을 치라고 하면 그게 2026-08-16 음성 사고의 모습이다(안내조차 화면에
      안 떠서 사용자는 '단추가 안 먹는다'로만 겪었다).
    [🔴 규칙 10] 사람이 누른 실행이 아니다 — infra.proc 로 창 없이 돌린다. 5GB 를 받는
      수십 분 동안 검은 창이 사장님 화면 위에 떠 있으면 그 자체가 사고다.
    [불변식] 스레드는 한 번에 하나 — /status 는 4초마다 온다. 매번 걸면 pip 이 겹쳐 돌아
      venv 가 반쯤 만들어진 채 서로를 덮는다(setup_voice 가 겪은 자리와 같다)."""
    global _setup_thread
    with _setup_lock:
        if _setup_thread is not None and _setup_thread.is_alive():
            return _setup['step'] or '준비 중입니다'
        if _setup['error']:
            return _setup['error']              # 실패는 다시 두드려도 같다

        log_path = os.path.join(_VOICE_DIR, 'qwen-setup.log')

        def _quiet(cmd, env):
            from infra import proc                            # noqa: PLC0415
            with open(log_path, 'ab') as fp:
                fp.write(f'\n$ {" ".join(cmd)}\n'.encode('utf-8', 'replace'))
                fp.flush()
                return proc.run(cmd, cwd=_ROOT, env=env, stdin=subprocess.DEVNULL,
                                stdout=fp, stderr=subprocess.STDOUT).returncode

        def _work():
            try:
                _seed_assets()
                if _SCRIPTS_DIR not in sys.path:
                    sys.path.insert(0, _SCRIPTS_DIR)
                import setup_qwen                             # noqa: PLC0415
                # [🔴 자리를 넘겨준다] 설치본에서는 살림이 사용자 폴더에 있다.
                #   설치 절차가 스스로 계산하게 두면 서로 다른 곳을 보게 된다.
                ok, msg = setup_qwen.ensure_qwen(
                    Path(QWEN_HOME), _quiet,
                    note=lambda m: _setup.__setitem__('step', m))
                _setup['error'] = '' if ok else msg
                _setup['step'] = '' if ok else msg
            except Exception as e:                            # noqa: BLE001
                _setup['error'] = f'목소리 준비 실패: {type(e).__name__}: {e}'
            finally:
                _setup['running'] = False

        _setup['running'], _setup['step'], _setup['error'] = True, '준비를 시작합니다', ''
        _setup_thread = threading.Thread(target=_work, name='qwen-setup', daemon=True)
        _setup_thread.start()
        return _setup['step']


def _ensure_worker() -> subprocess.Popen:
    global _proc, WORKER_PY, WORKER_JOB
    with _lock:
        if worker_alive():
            return _proc
        # [🔴 매번 다시 잡는다] 설치가 끝나면 경로가 생긴다 — 모듈을 읽을 때 잡아 둔
        #   값에 매달리면 다 깔고도 '없다'가 되어 사이드카를 재기동해야만 소리가 난다.
        WORKER_PY, WORKER_JOB = _worker_paths()
        if not installed():
            # 아직 살림이 없다 — 지금 깔기 시작하고, 이번 요청은 물러난다.
            # (프론트가 브라우저 목소리로 내려가 소리는 계속 난다.)
            msg = start_setup()
            raise RuntimeError(f'사장님 목소리를 준비하는 중입니다 — {msg}. '
                               f'준비될 때까지는 다른 목소리로 읽습니다')
        if not available():
            raise RuntimeError(f'Qwen 일꾼을 찾을 수 없습니다({WORKER_PY} / {WORKER_JOB})')
        # [제약] stderr 는 파이프로 받지 않는다 — 아무도 안 읽으면 자식이 멈춘다.
        #   진단이 필요하면 일꾼이 stdout 한 줄로 error 를 돌려준다.
        # [🔴 몫을 씌워 띄운다] 위 FRACTION 주석 — 보드 일꾼과 같은 카드를 쓴다.
        #   환경으로 이미 정해 두셨으면 그것을 존중한다(사람이 정한 값이 이긴다).
        env = dict(os.environ, PYTHONIOENCODING='utf-8')
        env.setdefault('VOICE_QWEN_FRACTION', FRACTION)
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
            # [🔴 여기가 '학습이 이긴다'가 실제로 일어나는 자리] busy 면 _fail 이 일꾼을
            #   내려 GPU 를 돌려주고, 예외로 올려 프론트가 브라우저 합성기로 내려간다.
            _fail(res)
        data = _read_wav(tmp)
    finally:
        try:
            os.unlink(tmp)
        except OSError:
            pass
    return data


def _read_wav(path: str) -> bytes:
    with open(path, 'rb') as fp:
        data = fp.read()
    if not data:
        raise RuntimeError(f'Qwen 이 오디오를 만들지 못했습니다({os.path.basename(path)})')
    return data


def _bake_parts(parts: list[str]):
    """조각 목록을 일꾼에게 **한 번에** 맡기고, 나오는 대로 (차례, wav바이트)를 내놓는다.

    [WHY 하나씩 안 맡기나] 커널을 하나씩 띄우는 값이 시간을 다 먹는다 — 배치1 22.1초 vs
      배치16 36.9초(일 16배에 시간 1.7배, 보드 ac_batch_bench 실측). 묶으면 그 값이 나뉜다.
    [🔴 첫 조각만 홀로다] 묶으면 묶음이 다 끝나야 첫 소리가 난다 — 그러면 이 함수를 만든
      이유가 사라진다. 그래서 일꾼은 첫 조각을 홀로 굽고 **그 자리에서 답 한 줄**을 보낸다.
      답이 두 줄 온다(stage=first, stage=full) — 그 규약이 z_qwen_worker.py 의 say_parts 다.
    [🔴 답 줄 수를 반드시 맞춘다 — 이것이 이 함수의 불변식] 듣는 쪽이 중간에 끊어
      두 번째 줄을 안 읽고 나가면, **다음 요청이 그 줄을 제 답으로 읽는다**(파이프 어긋남).
      그래서 finally 에서 남은 줄을 비우고, 못 비우면 일꾼을 내린다.
    [제약] 일꾼은 하나다 — 이 교환이 끝날 때까지 _lock 을 쥔다. 듣는 쪽이 generator 를
      버리면 close() 때 GeneratorExit 가 아래 yield 에서 올라와 finally 가 돈다."""
    global _last_used
    tmpdir = tempfile.mkdtemp(prefix='qwenp_')
    first_out = os.path.join(tmpdir, 'first.wav')
    full_out = os.path.join(tmpdir, 'full.wav')
    prefix = os.path.join(tmpdir, 'q')
    # 묶음은 조각 수만큼 오래 걸린다. 한 조각당 SAY_S 를 다 주면 지나치므로 절반씩 더한다.
    rest_s = min(BATCH_MAX_S, SAY_S + (SAY_S // 2) * max(0, len(parts) - 1))

    with _lock:
        p = _ensure_worker()
        pending = 2                       # 일꾼이 보낼 답 줄 수(first, full)
        try:
            req = json.dumps({'cmd': 'say_parts', 'parts': parts,
                              'first_out': first_out, 'out': full_out,
                              'prefix': prefix}, ensure_ascii=False)
            try:
                p.stdin.write(req + '\n')
                p.stdin.flush()
            except Exception as e:                         # noqa: BLE001
                pending = 0
                _kill_worker('write-failed')
                raise RuntimeError(f'Qwen 일꾼에 말을 걸지 못했습니다: {e}') from e

            res = _read_line(p, SAY_S)
            pending -= 1
            if not res.get('ok'):
                pending = 0               # 첫 판에 엎어지면 두 번째 줄은 오지 않는다
                _fail(res)
            _last_used = time.time()
            yield 0, _read_wav(first_out)

            res = _read_line(p, rest_s)
            pending -= 1
            if not res.get('ok'):
                _fail(res)
            _last_used = time.time()
            for i in range(1, len(parts)):
                yield i, _read_wav(prefix + ('.p%02d.wav' % i))
        finally:
            while pending > 0:
                try:
                    _read_line(p, rest_s)
                    pending -= 1
                except Exception:                          # noqa: BLE001
                    _kill_worker('desync')                 # 못 비웠다 — 어긋난 채 두느니 내린다
                    break
            shutil.rmtree(tmpdir, ignore_errors=True)


def _fail(res: dict) -> None:
    """일꾼의 거절을 예외로 바꾼다. busy 면 일꾼을 내려 GPU 를 학습에 돌려준다."""
    if res.get('error') == 'busy':
        _kill_worker('busy')
        raise RuntimeError('GPU 여유 부족 — 학습 보호로 굽지 않았습니다')
    raise RuntimeError(f"Qwen 굽기 실패: {res.get('error')}")


class QwenEngine:
    """voice_id = 'qwen:apix'. 지금은 목소리가 하나뿐이다(사장님 샘플)."""

    mime = 'audio/wav'
    ext = 'wav'

    def __init__(self, voice_id: str = '') -> None:
        self.voice = 'apix'

    def _key(self, text: str) -> str:
        """[🔴 참조 지문이 열쇠에 들어간다 — 2026-08-16] 없으면 사장님이 목소리 원본을
        바꾸셔도 옛 소리가 그대로 난다(보드가 그 사고를 겪었다).
        [🔴 굽는 쪽과 같은 식이어야 한다] 미리 굽는 ag_bake_now.py 의 cache_key() 가 이
          순서·구분자를 그대로 흉내 내 같은 폴더에 파일을 놓는다. 한쪽만 고치면 미리
          구운 문장이 조용히 안 맞아 첫 소리가 도로 느려진다."""
        return tts_cache.key_of('qwen', self.voice, MODEL_ID, _ref_sha(), text)

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
        """긴 글을 조각으로 잘라 **되는 대로 하나씩** 내놓는다(이어 굽기).

        [WHY 전체를 다 굽고 주지 않나] 그러면 첫 소리가 글 전체 길이만큼 늦는다
          (131자 = 120초). 앞에서부터 주면 첫 소리는 첫 조각 값이다.
        [🔴 예전 판과 무엇이 다른가] 예전에는 조각마다 일꾼을 한 번씩 불렀다. 지금은
          **못 맞힌 조각들을 한 목록으로 맡긴다**(_bake_parts). 일꾼이 첫 조각만 홀로
          굽고 나머지는 묶어 구우므로, 첫 소리는 그대로 빠르면서 뒤가 훨씬 빨리 따라온다.
        [🔴 캐시에 있는 것은 목록에서 뺀다] 미리 구워 둔 문장(ag_bake_now 가 넣어 둔 것)은
          GPU 도 일꾼도 필요 없다. 앞쪽이 통째로 캐시면 일꾼을 아예 안 부른다.
          일꾼의 '첫 조각 홀로' 최적화는 **맡긴 목록의 첫 번째**에 걸리는데, 그 앞의
          캐시분은 즉시 나가므로 사장님이 듣는 '첫 소리'와 어긋나지 않는다.
        """
        parts = tts_split.split(text)
        if not parts:
            return
        keys = [self._key(p) for p in parts]
        hits = [tts_cache.get(k, self.ext) for k in keys]
        todo = [i for i, h in enumerate(hits) if h is None]

        baker = _bake_parts([parts[i] for i in todo]) if todo else None
        try:
            for i, part in enumerate(parts):
                data = hits[i]
                if data is None:
                    if baker is not None:
                        try:
                            _, data = next(baker)
                        except StopIteration:
                            baker = None
                        except RuntimeError as e:
                            # [🔴 소리가 먼저다 — 보드와 같은 규약] 묶어 굽기가 깨지면
                            #   **옛 길(한 조각씩)로 내려간다**. 느릴 뿐 소리는 난다.
                            #   단 busy 는 내려가지 않는다 — 그건 '학습에 자리를 내주라'는
                            #   뜻이라 다시 시도하면 규칙을 어긴다. 그대로 올려 프론트가
                            #   브라우저 합성기로 가게 둔다.
                            if 'GPU 여유 부족' in str(e):
                                raise
                            print(f'[qwen] 묶어 굽기 실패 — 한 조각씩으로 내려간다: {e}',
                                  file=sys.stderr, flush=True)
                            baker = None
                    if data is None:
                        data = _bake(part)
                    tts_cache.put(keys[i], data, self.ext)
                yield part, data
        finally:
            # [🔴 반드시 닫는다] 듣는 쪽이 중간에 끊으면 _bake_parts 의 finally 가 돌아야
            #   일꾼과의 답 줄 수가 맞는다(안 맞으면 다음 요청이 남의 답을 읽는다).
            if baker is not None:
                baker.close()
