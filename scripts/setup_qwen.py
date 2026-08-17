# -*- coding: utf-8 -*-
"""
FILE: scripts/setup_qwen.py
DESCRIPTION: 사장님 목소리(Qwen3-TTS) 굽기 환경 설치 — 전용 venv + CUDA 토치 + 모델 내려받기.
             CLI(사람이 직접)와 앱(사이드카가 자동)이 **같은 절차**를 공유한다.

             [🔴 왜 설치본에 통째로 못 싣나 — 2026-08-17 실측] 모델만 2.4GB,
               CUDA 토치가 ~3GB 다. 깃허브 릴리즈는 **파일 하나에 2GB** 가 한도라
               인스톨러에 넣을 수 없다. 그래서 남은 길은 첫 실행 때 받는 것뿐이다.
               [실려 가는 것] 일꾼(worker.py)·그래프(qgraph.py)·참조(boss_pick.wav)·
               참조 원문(ref_text.json)은 다 합쳐 620KB 라 **설치본에 동봉한다**.
               참조가 빠지면 소리는 나는데 사장님 목소리가 아니다.

             [🔴 GPU 가 없으면 여기서 멈춘다 — 그게 맞다] 이 모델은 CUDA 전용이다.
               NVIDIA 카드가 없는 PC 에서 5GB 를 받게 하면 몇십 분을 버린 뒤에야 실패한다.
               먼저 보고, 없으면 그 사실을 사람이 읽을 문장으로 돌려준다 —
               그 PC 는 edge 목소리로 계속 잘 돈다(소리가 끊기지 않는다).

             [🔴 규칙 10 — 창을 띄우지 않는다] 앱이 부를 때는 run 이 infra.proc 경유라
               콘솔이 안 뜬다. 사람이 CLI 로 부를 때만 진행이 보인다. 절차를 두 벌 두면
               한쪽만 고쳐지므로(리포가 두 번 겪음) 다른 것은 실행기 하나뿐이게 갈랐다.
               setup_voice.ensure_env 와 같은 모양이다 — 그쪽을 고치면 여기도 본다.

             [🔴 버전을 박아 둔다] 보드에서 실제로 도는 조합을 그대로 적는다. 최신을
               받게 두면 어느 날 조용히 안 맞는 판이 깔려 '어제는 됐는데'가 된다.
               근거는 실물 —
                 G:\\apix-voice2\\envs\\qwen_cuda\\Lib\\site-packages\\
                   qwen_tts-0.1.1.dist-info / torch-2.13.0+cu130.dist-info

REVISION HISTORY:
- 2026-08-17 Claude: 최초 작성 — 깐 직후 사장님 목소리가 나게(모델은 첫 실행 때 받는다)
"""

from __future__ import annotations

import os
import shutil
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
# [WHY 3.12 인가] 보드에서 실제로 도는 판이다. torch cu130 휠이 3.13 에 아직 없다(2026-08).
PY_VERSION = '3.12'

MODEL_ID = 'Qwen/Qwen3-TTS-12Hz-0.6B-Base'
# 받는 데 필요한 자리. [근거 — 2026-08-17 실측] CUDA 토치+패키지가 4.76GB, 모델이 2.4GB.
# 받는 도중 임시 파일이 겹치므로 여유를 얹어 8GB 를 본다.
# [🔴 왜 미리 재나] 실제로 이 자리에서 터졌다: D: 여유가 4.8GB 뿐이라 토치를 다 받은 뒤
#   모델 단계에서 `OSError: [Errno 28] No space left on device` — **4.76GB 를 받고 나서**
#   실패했다. 미리 재면 1초 만에 알려 줄 수 있는 것을 3분 받고 알려 준 셈이다.
NEED_BYTES = 8 * (1 << 30)
TORCH_INDEX = 'https://download.pytorch.org/whl/cu130'
TORCH_PINS = ['torch==2.13.0', 'torchaudio==2.11.0']
PKG_PINS = ['qwen-tts==0.1.1', 'soundfile', 'huggingface_hub']

# 설치 검증. pip 성공만으로는 실제 로드 여부를 모른다(설치본 사고의 교훈).
# [🔴 모델 적재까지는 하지 않는다] 여기서 GPU 에 2.2GB 를 올리면 검증이 곧 점유다.
#   파일이 다 왔는지는 snapshot_download 가 이미 보장한다.
_VERIFY = (
    'import torch\n'
    'assert torch.cuda.is_available(), "CUDA 를 못 씁니다"\n'
    'import qwen_tts, soundfile\n'
    'print("Qwen 굽기 임포트 OK", torch.__version__, torch.cuda.get_device_name(0))\n'
)


def qwen_dir(root: Path) -> Path:
    return root / '.ai_monitor' / 'voice-server' / 'qwen'


def venv_python(home: Path) -> Path:
    base = Path(home) / '.venv'
    return base / ('Scripts/python.exe' if os.name == 'nt' else 'bin/python')


def model_home(home: Path) -> Path:
    """worker.py 의 HF_HOME 기본값과 **반드시 같아야 한다**(worker.py:HERE_DIR/models/hf).
    어긋나면 다 받아 놓고도 일꾼이 다시 받는다."""
    return Path(home) / 'models' / 'hf'


def free_bytes(path: Path) -> int:
    """이 자리가 놓인 드라이브의 남은 바이트. 못 재면 -1(그때는 막지 않는다 —
    잴 수 없다는 이유로 설치를 거부하면 멀쩡한 PC 에서 목소리가 죽는다)."""
    p = Path(path)
    while not p.exists() and p != p.parent:
        p = p.parent
    try:
        return shutil.disk_usage(str(p)).free
    except OSError:
        return -1


def has_nvidia() -> bool:
    """[WHY nvidia-smi 인가] torch 가 아직 없는 시점에 물어야 한다. 창은 안 뜬다 —
    아래 호출부가 CREATE_NO_WINDOW 를 붙인다(규칙 10)."""
    exe = shutil.which('nvidia-smi')
    if not exe:
        return False
    try:
        r = subprocess.run([exe, '-L'], capture_output=True, timeout=20,
                           creationflags=getattr(subprocess, 'CREATE_NO_WINDOW', 0))
        return r.returncode == 0 and b'GPU' in (r.stdout or b'')
    except (OSError, subprocess.SubprocessError):
        return False


def installed(home: Path) -> bool:
    """이미 다 깔렸나. [🔴 venv 만 보지 않는다] venv 는 만들어졌는데 모델이 안 온
    중간 상태가 실제로 생긴다(받다가 끊김). 그러면 일꾼이 뜨다가 죽는다."""
    if not venv_python(home).exists():
        return False
    hub = model_home(home) / 'hub'
    name = 'models--' + MODEL_ID.replace('/', '--')
    snap = hub / name / 'snapshots'
    if not snap.is_dir():
        return False
    return any(d.is_dir() and any(d.iterdir()) for d in snap.iterdir())


def _base_python() -> list[str] | None:
    """venv 를 만들어 줄 '진짜' 파이썬. setup_voice._base_python 과 같은 이유로
    frozen 의 sys.executable 은 못 쓴다(그건 앱 EXE 다)."""
    py = shutil.which('py')
    if py:
        for v in (PY_VERSION, '3.11'):
            try:
                if subprocess.run(
                        [py, f'-{v}', '-c', 'pass'], capture_output=True, timeout=20,
                        creationflags=getattr(subprocess, 'CREATE_NO_WINDOW', 0)
                ).returncode == 0:
                    return [py, f'-{v}']
            except (OSError, subprocess.SubprocessError):
                pass
    if not getattr(sys, 'frozen', False):
        return [sys.executable]
    for name in ('python3.12', 'python3.11', 'python3', 'python'):
        found = shutil.which(name)
        if found:
            return [found]
    return None


def ensure_qwen(home: Path, run, note=None) -> tuple[bool, str]:
    """굽기 환경을 준비한다. 이미 있으면 아무것도 하지 않는다.

    [🔴 자리를 받아서 쓴다 — 스스로 계산하지 않는다] 설치본에서는 살림이 앱 폴더가 아니라
      사용자 폴더(%LOCALAPPDATA%\\VibeCoding\\qwen)에 놓인다. 여기서 root 로부터 자리를
      다시 계산하면 부르는 쪽(engines/tts_qwen.QWEN_HOME)과 어긋나 **다 받아 놓고도
      '없다'가 되어 무한히 다시 받는다.** 그 자리를 아는 것은 부르는 쪽뿐이다.

    run(cmd: list[str], env: dict | None) -> int 를 주입받는다(규칙 10 — 헤더 참조).
    note(str) 를 주면 단계마다 부른다 — 화면에 '지금 뭘 받는 중'을 띄우기 위한 것이다.
    반환은 (성공, 사람이 읽을 실패 사유). 예외를 던지지 않는다.
    """
    def say(msg: str) -> None:
        if note:
            try:
                note(msg)
            except Exception:                                  # noqa: BLE001
                pass

    qd = Path(home)
    if not (qd / 'worker.py').exists():
        return False, f'굽기 일꾼이 없습니다: {qd / "worker.py"}'
    if not (qd / 'boss_pick.wav').exists() or not (qd / 'ref_text.json').exists():
        # [🔴 참조가 없으면 아예 시작하지 않는다] 5GB 를 받은 뒤 '목소리가 다르다'로
        #   끝나는 것이 가장 나쁜 결말이다.
        return False, '참조(목소리 원본)가 설치본에 없습니다 — 다시 설치해야 합니다'
    if not has_nvidia():
        return False, ('이 PC 에는 NVIDIA 그래픽카드가 없어 사장님 목소리는 쓸 수 없습니다. '
                       '다른 목소리로는 그대로 읽습니다')

    # [🔴 받기 전에 자리를 잰다] 위 NEED_BYTES 주석 — 실제로 4.76GB 를 받고 나서 터졌다.
    #   실패 문구에 **어느 드라이브에 얼마가 필요한지**를 적는다. "설치 실패" 만 남으면
    #   사용자는 무엇을 해야 할지 모른 채 목소리만 안 나는 상태로 남는다.
    free = free_bytes(qd)
    if 0 <= free < NEED_BYTES:
        drive = str(qd.resolve())[:2]
        return False, (f'{drive} 여유 공간이 부족합니다 — '
                       f'{NEED_BYTES // (1 << 30)}GB 가 필요한데 '
                       f'{free / (1 << 30):.1f}GB 뿐입니다. '
                       f'자리를 비우거나 VOICE_QWEN_HOME 으로 다른 드라이브를 지정하세요')

    venv = qd / '.venv'
    py = venv_python(qd)
    uv = shutil.which('uv')

    if not py.exists():
        say('굽기용 파이썬 환경을 만드는 중')
        if uv:
            if run([uv, 'venv', str(venv), '--python', PY_VERSION], None) != 0:
                return False, 'uv 로 굽기용 파이썬 환경을 만들지 못했습니다'
        else:
            base = _base_python()
            if not base:
                return False, ('굽기 설치에 필요한 파이썬을 찾지 못했습니다. '
                               'uv 또는 파이썬 3.12 를 설치한 뒤 다시 시도하세요')
            if run([*base, '-m', 'venv', str(venv)], None) != 0:
                return False, '굽기용 파이썬 환경을 만들지 못했습니다'

    def pip(args: list[str]) -> int:
        if uv:
            return run([uv, 'pip', 'install', *args],
                       {**os.environ, 'VIRTUAL_ENV': str(venv)})
        return run([str(py), '-m', 'pip', 'install', *args], None)

    # [🔴 토치를 따로 먼저 깐다] qwen-tts 를 먼저 깔면 그 의존성으로 **CPU 판 토치**가
    #   딸려 들어온다. 그 뒤에 CUDA 판을 덮어도 이미 받은 3GB 는 버려진 셈이고,
    #   판이 섞여 cuda.is_available() 이 False 로 남은 사고가 흔하다.
    say('CUDA 토치를 받는 중 (약 3GB — 처음 한 번)')
    if pip(['--index-url', TORCH_INDEX, *TORCH_PINS]) != 0:
        return False, 'CUDA 토치 설치가 실패했습니다(qwen-setup.log 참조)'

    say('굽기 패키지를 받는 중')
    if pip(PKG_PINS) != 0:
        return False, '굽기 패키지 설치가 실패했습니다(qwen-setup.log 참조)'

    say('사장님 목소리 모델을 받는 중 (약 2.4GB — 처음 한 번)')
    mhome = model_home(qd)
    mhome.mkdir(parents=True, exist_ok=True)
    # [🔴 일꾼과 같은 자리에 받는다] worker.py 가 HF_HOME 을 제 옆 models/hf 로 잡는다.
    #   여기서 다른 데 받으면 일꾼이 뜨면서 처음부터 다시 받는다(사용자는 두 배를 기다린다).
    dl = ('import os,sys\n'
          'from huggingface_hub import snapshot_download\n'
          f'p = snapshot_download({MODEL_ID!r})\n'
          'print("모델 받음:", p)\n')
    if run([str(py), '-c', dl], {**os.environ, 'HF_HOME': str(mhome),
                                 'HF_HUB_DISABLE_SYMLINKS_WARNING': '1'}) != 0:
        return False, '목소리 모델 내려받기가 실패했습니다(qwen-setup.log 참조)'

    say('마무리 확인 중')
    if run([str(py), '-c', _VERIFY], None) != 0:
        return False, '굽기 환경을 깔았지만 불러오지 못했습니다(qwen-setup.log 참조)'
    return True, ''


def main() -> int:
    # [WHY 이 실행기만 창을 허용하나] 규칙 10 은 '사람이 안 시킨 실행'이 대상이다.
    #   이건 사람이 직접 부른 설치이고, 5GB 진행이 보여야 한다.
    def visible(cmd: list[str], env: dict | None) -> int:
        print(f'$ {" ".join(cmd)}', flush=True)
        return subprocess.run(cmd, cwd=str(ROOT), env=env).returncode

    if installed(qwen_dir(ROOT)):
        print('[✓] 이미 깔려 있습니다.')
        return 0
    ok, msg = ensure_qwen(qwen_dir(ROOT), visible, note=lambda m: print(f'== {m}', flush=True))
    if not ok:
        print(f'[!] {msg}')
        return 1
    print('\n[✓] 사장님 목소리 준비 완료. 음성 바의 ⚙ 에서 "아픽스"를 고르면 된다.')
    return 0


if __name__ == '__main__':
    sys.exit(main())
