# -*- coding: utf-8 -*-
"""
FILE: scripts/setup_voice.py
DESCRIPTION: 음성 사이드카 환경 설치 — 별도 venv 를 만들고 requirements.txt 를 깐다.
             CLI(사람이 직접)와 앱(voice_api 가 자동)이 **같은 절차**를 공유한다.

             [WHY 별도 스크립트인가] 앱 설치(`pip install -e .`)에 음성 의존성을 얹으면
               음성을 안 쓰는 사람도 onnxruntime·ctranslate2 200MB+ 를 받는다. 음성은
               쓰겠다고 한 사람만 깔면 되는 기능이라 설치 경로를 분리했다.

             [🔴 파이썬 3.11 을 고집하는 이유] ctranslate2(faster-whisper 백엔드) 휠이
               3.13 에 없다(2026-08). 3.13 venv 로 만들면 설치가 컴파일로 떨어져 실패한다.
               uv 는 --python 3.11 로 없는 버전을 알아서 받아 온다 — 그래서 uv 를 먼저 본다.

             [🔴 왜 run 을 주입받나 — 규칙 10] 같은 절차를 두 주인이 부른다.
               · 사람이 CLI 로 부르면 pip 진행(수백 MB)이 **보여야** 한다 → 콘솔 상속
               · 앱이 자동으로 부르면 콘솔이 뜨면 **그 자체가 사고**다 → infra.proc 경유
               절차를 복사해 두 벌 두면 한쪽만 고쳐지므로(리포가 이미 두 번 겪음)
               다른 것은 실행기 하나뿐이게 갈랐다.

             [제약] 이 스크립트는 앱 venv 에서 돈다. 만들어지는 것은 다른 venv 다 —
               자기 자신에게 설치하지 않는다.

REVISION HISTORY:
- 2026-08-15 Claude: 최초 작성 — 음성 설치가 수동이라 다른 PC 에서 재현 불가였던 문제
- 2026-08-16 Claude: 설치본에서 아무도 이 스크립트를 부르지 않아 마이크·목소리가 죽던
  사고 — 앱이 자동으로 부를 수 있게 ensure_env(root, run) 로 분리(창 없는 실행기 주입)
"""

from __future__ import annotations

import os
import shutil
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
PY_VERSION = '3.11'

# 설치 검증 코드. pip 성공 코드만으로는 실제 로드 가능 여부를 모른다.
# [🔴 둘을 갈라서 확인한다 — 2026-08-15 정리] 낭독(edge)과 듣기(whisper)는 부품을
#   공유하지 않는다. 한 줄로 묶어 확인하면 어느 쪽이 죽었는지 모른 채 "음성이 안 된다"만
#   남는다. 마이크가 죽은 것과 목소리가 죽은 것은 대처가 다르다.
_VERIFY = (
    'import faster_whisper\n'
    'print("듣기(STT) 임포트 OK - faster-whisper")\n'
    'try:\n'
    '    import edge_tts\n'
    '    print("낭독(TTS) 임포트 OK - edge-tts")\n'
    'except Exception as e:\n'
    '    print(f"[!] edge-tts 없음 - 낭독은 브라우저 목소리로만 난다: {e}")\n'
)


def voice_dir(root: Path) -> Path:
    return root / '.ai_monitor' / 'voice-server'


def venv_python(root: Path) -> Path:
    base = voice_dir(root) / '.venv'
    return base / ('Scripts/python.exe' if os.name == 'nt' else 'bin/python')


def _base_python() -> list[str] | None:
    """venv 를 만들어 줄 '진짜' 파이썬.

    [🔴 frozen 의 sys.executable 을 쓰면 안 된다] 그건 앱 EXE 다. `-m venv` 가 없고,
      인자를 주면 앱이 한 벌 더 뜬다. 설치본에서는 py 런처/시스템 파이썬만 후보다.
    """
    py = shutil.which('py')
    if py:
        for v in (PY_VERSION, '3.12'):
            try:
                if subprocess.run([py, f'-{v}', '-c', 'pass'],
                                  capture_output=True, timeout=20).returncode == 0:
                    return [py, f'-{v}']
            except (OSError, subprocess.SubprocessError):
                pass
    if not getattr(sys, 'frozen', False):
        return [sys.executable]
    for name in ('python3.11', 'python3.12', 'python3', 'python'):
        found = shutil.which(name)
        if found:
            return [found]
    return None


def ensure_env(root: Path, run) -> tuple[bool, str]:
    """음성 venv 를 준비한다. 이미 있으면 아무것도 하지 않는다.

    run(cmd: list[str], env: dict | None) -> int 를 주입받는다 — 주석 [WHY run] 참조.
    반환은 (성공, 사람이 읽을 실패 사유). 예외를 던지지 않는다 — 호출부가 화면에
    그대로 띄울 문장이 필요하지 실패 유형이 필요한 게 아니다.
    """
    vd = voice_dir(root)
    req = vd / 'requirements.txt'
    venv = vd / '.venv'
    py = venv_python(root)

    if not req.exists():
        return False, f'의존성 목록이 없습니다: {req}'

    uv = shutil.which('uv')
    if not py.exists():
        if uv:
            if run([uv, 'venv', str(venv), '--python', PY_VERSION], None) != 0:
                return False, 'uv 로 음성용 파이썬 환경을 만들지 못했습니다'
        else:
            base = _base_python()
            if not base:
                # [🔴 여기서 조용히 끝내지 않는다] 파이썬이 없는 PC 는 실제로 있다.
                #   'venv 없음'만 남기면 사용자는 평생 원인을 못 찾는다.
                return False, ('음성 설치에 필요한 파이썬을 찾지 못했습니다. '
                               'uv 또는 파이썬 3.11 을 설치한 뒤 다시 시도하세요')
            if run([*base, '-m', 'venv', str(venv)], None) != 0:
                return False, '음성용 파이썬 환경을 만들지 못했습니다'

    if uv:
        rc = run([uv, 'pip', 'install', '-r', str(req)],
                 {**os.environ, 'VIRTUAL_ENV': str(venv)})
    else:
        rc = run([str(py), '-m', 'pip', 'install', '-r', str(req)], None)
    if rc != 0:
        return False, '음성 패키지 설치가 실패했습니다(voice-setup.log 참조)'

    if run([str(py), '-c', _VERIFY], None) != 0:
        return False, '음성 패키지를 깔았지만 불러오지 못했습니다(voice-setup.log 참조)'
    return True, ''


def main() -> int:
    # [WHY 이 실행기만 창을 허용하나] 규칙 10 은 '사람이 안 시킨 실행'이 대상이다.
    #   이건 사람이 직접 부른 설치이고, 진행 상황(수백 MB 내려받기)이 보여야 한다.
    def visible(cmd: list[str], env: dict | None) -> int:
        print(f'$ {" ".join(cmd)}', flush=True)
        return subprocess.run(cmd, cwd=str(ROOT), env=env).returncode

    ok, msg = ensure_env(ROOT, visible)
    if not ok:
        print(f'[!] {msg}')
        return 1
    print('\n[✓] 음성 설치 완료. 앱에서 터미널 하단 음성 바의 ⚙ 로 목소리를 고를 수 있다.')
    return 0


if __name__ == '__main__':
    sys.exit(main())
