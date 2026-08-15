# -*- coding: utf-8 -*-
"""
FILE: scripts/setup_voice.py
DESCRIPTION: 음성 사이드카 환경 설치 — 별도 venv 를 만들고 requirements.txt 를 깐다.

             [WHY 별도 스크립트인가] 앱 설치(`pip install -e .`)에 음성 의존성을 얹으면
               음성을 안 쓰는 사람도 onnxruntime·ctranslate2 200MB+ 를 받는다. 음성은
               쓰겠다고 한 사람만 깔면 되는 기능이라 설치 경로를 분리했다.

             [🔴 파이썬 3.11 을 고집하는 이유] ctranslate2(faster-whisper 백엔드) 휠이
               3.13 에 없다(2026-08). 3.13 venv 로 만들면 설치가 컴파일로 떨어져 실패한다.
               uv 는 --python 3.11 로 없는 버전을 알아서 받아 온다 — 그래서 uv 를 먼저 본다.

             [제약] 이 스크립트는 앱 venv 에서 돈다. 만들어지는 것은 다른 venv 다 —
               자기 자신에게 설치하지 않는다.

REVISION HISTORY:
- 2026-08-15 Claude: 최초 작성 — 음성 설치가 수동이라 다른 PC 에서 재현 불가였던 문제
"""

from __future__ import annotations

import os
import shutil
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
VOICE_DIR = ROOT / '.ai_monitor' / 'voice-server'
VENV = VOICE_DIR / '.venv'
REQ = VOICE_DIR / 'requirements.txt'
PY_VERSION = '3.11'


def _venv_python() -> Path:
    return VENV / ('Scripts/python.exe' if os.name == 'nt' else 'bin/python')


def _run(cmd: list[str]) -> int:
    print(f'$ {" ".join(cmd)}', flush=True)
    # [WHY 이 스크립트만 창을 허용하나] 규칙 10 은 '사람이 안 시킨 실행'이 대상이다.
    #   이건 사람이 직접 부른 설치이고, 진행 상황(수백 MB 내려받기)이 보여야 한다.
    return subprocess.run(cmd, cwd=str(ROOT)).returncode


def main() -> int:
    if not REQ.exists():
        print(f'[!] 의존성 목록이 없다: {REQ}')
        return 1

    uv = shutil.which('uv')
    if _venv_python().exists():
        print(f'[=] venv 가 이미 있다: {VENV}')
    elif uv:
        if _run([uv, 'venv', str(VENV), '--python', PY_VERSION]) != 0:
            return 1
    else:
        # [🔴 폴백의 한계] uv 가 없으면 지금 돌고 있는 파이썬으로 만든다. 그게 3.13 이면
        #   ctranslate2 설치가 실패한다 — 그때 사용자가 원인을 알 수 있게 미리 경고한다.
        v = f'{sys.version_info.major}.{sys.version_info.minor}'
        if v not in ('3.11', '3.12'):
            print(f'[!] 현재 파이썬 {v} 로는 faster-whisper 설치가 실패할 수 있다. '
                  f'uv 를 설치하거나 파이썬 {PY_VERSION} 로 실행할 것.')
        if _run([sys.executable, '-m', 'venv', str(VENV)]) != 0:
            return 1

    py = _venv_python()
    if uv:
        env = {**os.environ, 'VIRTUAL_ENV': str(VENV)}
        print(f'$ uv pip install -r {REQ}', flush=True)
        rc = subprocess.run([uv, 'pip', 'install', '-r', str(REQ)],
                            cwd=str(ROOT), env=env).returncode
    else:
        rc = _run([str(py), '-m', 'pip', 'install', '-r', str(REQ)])
    if rc != 0:
        return rc

    # 설치가 됐는지는 import 로 확인한다 — pip 성공 코드만으로는 실제 로드 가능 여부를 모른다.
    check = (
        'import faster_whisper, sherpa_onnx\n'
        'print("STT/TTS 임포트 OK")\n'
        # [🔴 edge 는 기본 낭독 엔진이라 여기서 확인한다] 없으면 조용히 폴백으로만 돌아
        #   사용자는 '왜 목소리가 이 모양이지'만 느끼고 원인을 못 찾는다.
        'try:\n'
        '    import edge_tts\n'
        '    print("edge-tts 사용 가능 - 기본 낭독")\n'
        'except Exception as e:\n'
        '    print(f"edge-tts 없음 - 이 PC 안 목소리로만 읽는다: {e}")\n'
        'try:\n'
        '    import win32com.client\n'
        '    print("Windows 내장 음성 사용 가능")\n'
        'except Exception:\n'
        '    print("Windows 내장 음성 없음 - sherpa 만 쓸 수 있다")\n'
    )
    print('$ (설치 검증)', flush=True)
    rc = subprocess.run([str(py), '-c', check], cwd=str(ROOT)).returncode
    if rc == 0:
        print('\n[✓] 음성 설치 완료. 앱에서 터미널 하단 음성 바의 ⚙ 로 목소리를 고를 수 있다.')
    return rc


if __name__ == '__main__':
    sys.exit(main())
