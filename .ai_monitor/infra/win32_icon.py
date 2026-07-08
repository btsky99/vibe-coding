"""
FILE: infra/win32_icon.py
DESCRIPTION: Windows 작업표시줄/타이틀바 아이콘 강제 설정. PyWebView가 생성한 창의
             기본 아이콘을 앱 전용 .ico로 덮어쓴다. WM_SETICON(0x80) 메시지를 창 핸들에
             직접 보내는 방식으로, pywebview icon 파라미터가 EXE 모드에서 무시되는 문제를
             우회한다. server.py main() GUI 블록 nested 클로저에서 top-level로 승격됨.

REVISION HISTORY:
- 2026-07-08 Claude: server.py main() force_win32_icon + 아이콘 경로 해석 분리
                     (Phase 3 R17-4). 로직 verbatim 유지 — 캡처하던 official_icon/
                     PROJECT_ROOT.name을 인자(icon_path/window_title)로 명시 주입.
                     [제약] base_dir는 caller(server.py)의 os.path.dirname(__file__)를
                     주입 — infra의 __file__로 계산하면 bin/ 경로가 틀어짐.
"""
from __future__ import annotations

import os
import time


def resolve_app_icon(base_dir: str) -> str:
    """앱 아이콘 경로를 반환한다. vibe_final.ico 우선, 없으면 app_icon.ico 폴백."""
    official_icon = os.path.join(base_dir, "bin", "vibe_final.ico")
    if not os.path.exists(official_icon):
        official_icon = os.path.join(base_dir, "bin", "app_icon.ico")
    return official_icon


def force_win32_icon(official_icon: str, window_title: str) -> None:
    """창 제목으로 hwnd를 찾아 WM_SETICON으로 아이콘을 강제 설정한다(별도 스레드 호출).

    time.sleep(2): 창 생성 직후 FindWindowW가 hwnd를 못 잡는 경합을 피하기 위한 지연.
    """
    if os.name == 'nt' and os.path.exists(official_icon):
        try:
            import ctypes
            from ctypes import wintypes
            time.sleep(2)
            hwnd = ctypes.windll.user32.FindWindowW(None, window_title)
            if hwnd:
                hicon = ctypes.windll.user32.LoadImageW(
                    None, official_icon, 1, 0, 0, 0x00000010 | 0x00000040
                )
                if hicon:
                    ctypes.windll.user32.SendMessageW(hwnd, 0x80, 1, hicon)
                    ctypes.windll.user32.SendMessageW(hwnd, 0x80, 0, hicon)
                    print(f"[*] Win32 Taskbar Icon Forced: {official_icon}")
        except Exception as e:
            print(f"[!] Win32 Icon Fix Error: {e}")
