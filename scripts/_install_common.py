# -*- coding: utf-8 -*-
"""
FILE: scripts/_install_common.py
DESCRIPTION: 설치 스크립트들이 **창 없이** 외부 명령을 부르게 하는 공용 실행기(규칙 10).

             [🔴 왜 생겼나 — 2026-08-17 사장 신고] "바이브 코딩 실행 시 node.exe 콘솔이
               계속 뜬다." 자동 설치 경로는 부모(api/tools_api.launch_ai_toolchain_installer)가
               이미 `proc.popen` 으로 **무창**으로 띄우고 있었다. 그런데
               **CREATE_NO_WINDOW 는 손자에게 상속되지 않는다** — 이 스크립트들이
               `subprocess.run([npm, 'install', '-g', ...])` 를 맨손으로 부르는 순간
               `npm.cmd` 가 `node.exe` 를 띄우며 **새 검은 창**을 받는다.
               부모 쪽 주석이 이미 그 자리를 정확히 예고하고 있었다:
                 "install_ai_toolchain.py 쪽도 infra.proc 를 써야 완전히 무창이다."
               예고만 되어 있고 **고쳐지지는 않았다.** 이 파일이 그 자리다.

             [🔴 왜 되풀이해 뜨나] 자동 설치는 앱을 켤 때마다 도는 경로다(총 3회 상한 —
               api/setup_api.py:_AUTO_INSTALL_MAX_ATTEMPTS). 한 번 돌 때마다 패키지 수만큼
               npm 이 돌아 창도 그만큼 뜬다. 도구가 끝내 안 잡히면 상한까지 반복된다.

             [WHY 별도 모듈] 같은 6줄을 네 스크립트에 복사하면 다음에 한쪽만 고쳐진다
               (이 저장소가 이미 두 번 겪은 실패 모양). 실행기는 한 곳이어야 한다.

             [🔴 창을 막는 것이 import 보다 중요하다] 이 스크립트들은 '아무것도 없는 PC'의
               복구 경로다. infra 를 못 불러오는 상황이 실제로 있을 수 있으므로, 그때는
               인라인 플래그로라도 창을 막는다 — 여기서 예외를 내면 설치 자체가 죽는다.

             [제약] 출력은 그대로 부모에게 흐른다. CREATE_NO_WINDOW 는 '콘솔 창을 안
               만든다'일 뿐 표준출력을 끊지 않는다 — 사람이 직접 띄운 콘솔에서 돌리면
               npm 진행이 그 창에 그대로 보인다(수동 경로가 안 망가진다).

REVISION HISTORY:
- 2026-08-17 Claude: 최초 작성 — node.exe 검은 창이 되풀이해 뜨던 사고
"""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

_SCRIPT_DIR = Path(__file__).resolve().parent

# 인라인 폴백용. infra.proc 를 못 불러왔을 때만 쓴다.
_NO_WINDOW = getattr(subprocess, 'CREATE_NO_WINDOW', 0) if sys.platform == 'win32' else 0


def _proc_module():
    """infra.proc 를 찾아본다. 없으면 None."""
    ai_monitor = _SCRIPT_DIR.parent / '.ai_monitor'
    if ai_monitor.is_dir() and str(ai_monitor) not in sys.path:
        sys.path.insert(0, str(ai_monitor))
    try:
        from infra import proc
        return proc
    except Exception:                                        # noqa: BLE001
        return None


def run(cmd, **kwargs):
    """`subprocess.run` 과 같은 규약. 다만 **콘솔 창을 만들지 않는다.**

    [불변식] 설치 스크립트에서 외부 명령을 부를 때는 반드시 이것을 쓴다.
      맨손 `subprocess.run` 으로 되돌리면 그 자리에서 검은 창이 다시 뜬다.
    """
    p = _proc_module()
    if p is not None:
        return p.run(cmd, **kwargs)
    kwargs.setdefault('creationflags', _NO_WINDOW)
    return subprocess.run(cmd, **kwargs)


def popen(cmd, **kwargs):
    """`subprocess.Popen` 과 같은 규약. run() 과 같은 이유로 창을 만들지 않는다."""
    p = _proc_module()
    if p is not None:
        return p.popen(cmd, **kwargs)
    kwargs.setdefault('creationflags', _NO_WINDOW)
    return subprocess.Popen(cmd, **kwargs)
