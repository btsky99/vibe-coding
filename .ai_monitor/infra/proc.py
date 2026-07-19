"""
FILE: infra/proc.py
DESCRIPTION: Windows 콘솔 숨김 subprocess 공용 래퍼. 앱의 모든 subprocess 호출이
             cmd 창 번쩍임 없이 돌도록 creationflags=CREATE_NO_WINDOW를 자동 주입한다.
             신규 subprocess 호출은 subprocess.run/Popen 대신 이 모듈의 run/popen을 쓴다.

REVISION HISTORY:
- 2026-07-19 Claude: 신설 — 45개 파일에 흩어진 인라인 CREATE_NO_WINDOW 패턴을 단일 소스로
  통일. "새 호출에서 플래그 깜빡임 → cmd 창 번쩍임 재발"을 구조적으로 차단하기 위함.
"""
import subprocess
import sys

# [WHY] windowed 부모(PyWebView/pythonw/frozen EXE)가 콘솔 프로그램을 자식으로 띄우면
# Windows가 새 콘솔을 할당한다 — 콘솔 숨김은 OS 기본이 아니다. CREATE_NO_WINDOW로 콘솔
# 자체를 안 만들게 강제. 비Windows엔 이 속성이 없어 0 → 플래그 무효과라 무해.
# [불변식] 이 값은 앱 전역 단일 소스. 인라인 getattr 재정의 금지 — 여기서만 import.
NO_WINDOW = getattr(subprocess, "CREATE_NO_WINDOW", 0) if sys.platform == "win32" else 0


def run(cmd, **kwargs):
    """subprocess.run에 콘솔 숨김을 기본 주입한 래퍼.

    [불변식] 호출자가 creationflags를 명시하면 존중한다 — 덮어쓰지 않는다.
    즉 CREATE_NEW_CONSOLE 등 '일부러 콘솔을 여는' 호출은 그 값을 그대로 넘기면 되고,
    미지정 시에만 NO_WINDOW가 들어간다. (setdefault 규약)
    """
    kwargs.setdefault("creationflags", NO_WINDOW)
    return subprocess.run(cmd, **kwargs)


def popen(cmd, **kwargs):
    """subprocess.Popen에 콘솔 숨김을 기본 주입한 래퍼. run()과 동일 규약."""
    kwargs.setdefault("creationflags", NO_WINDOW)
    return subprocess.Popen(cmd, **kwargs)
