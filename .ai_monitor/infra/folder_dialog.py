"""
FILE: infra/folder_dialog.py
DESCRIPTION: 윈도우 네이티브 폴더 선택 다이얼로그(SHBrowseForFolderW, ctypes).
             외부 python.exe·tkinter 없이 프로세스 안에서 직접 띄운다.

[🔴 왜 tkinter 서브프로세스로는 안 되는가 — 설치본에서 통째로 죽어 있었다]
  vibe-coding.spec 은 tkinter/_tkinter 를 excludes 한다(onedir 빌드가 pyi_rth__tkinter 에서
  기동조차 못 했던 문제 때문). 그래서 EXE 안에는 tkinter 가 없고, 폴더 다이얼로그는
  **PATH 에서 찾은 외부 python.exe** 에 tkinter 가 있다는 가정 위에 서 있었다.
  그 가정이 깨지는 PC(파이썬 미설치 / Store 스텁 python3 / tkinter 없는 배포판)에서는
    runtime.open_folder_dialog_subprocess(['python', '-c', ...]) → FileNotFoundError
    → fs_dialog_api 가 {"status":"error"} 로 삼킴 → 프론트가 null 로 삼킴
  이 되어 **버튼을 눌러도 아무 일도 일어나지 않는다**. 화면에 실패가 전혀 드러나지 않아
  '개발에선 되는데 설치본에서만 안 되는' 형태로만 보였다(2026-08-11 실사고).
  네이티브 호출은 의존성이 shell32/ole32 뿐이라 이 가정 자체를 없앤다.

[🔴 CoInitializeEx 가 아니라 OleInitialize 여야 한다 — 워커 스레드에서 갈린다]
  이 함수는 **GUI 스레드가 아닌 워커 스레드**(HTTP 핸들러)에서 호출된다.
  BIF_NEWDIALOGSTYLE 는 드래그&드롭을 쓰므로 MS 문서가 OleInitialize 를 요구한다.
  CoInitializeEx 만으로도 **메인 스레드에서는 우연히 뜬다** — 그래서 대충 짜면 통과한 것처럼
  보인다. 워커 스레드에서는 창이 아예 생성되지 않고, 반환도 예외도 없이 그대로 멈춘다
  (2026-08-11 실측: 콜백/구조체/argtypes 를 차례로 의심했으나 전부 무죄였고 이것이 범인).
  실패가 '조용한 정지'라 로그로는 절대 안 잡힌다 — 검증은 반드시 스레드에서 할 것.

[🔴 argtypes/restype 를 반드시 선언한다] 선언하지 않으면 ctypes 가 반환값을 32비트 int 로
  잘라, 64비트 프로세스에서 PIDL 포인터 상위 비트가 날아간다. 증상은 예외가 아니라
  '항상 취소됨'이다 — 같은 함정으로 상태판이 조용히 0건을 돌려준 전례가 있다.

REVISION HISTORY:
- 2026-08-11 Claude: 신규. 설치본에서 폴더 변경이 전혀 동작하지 않던 문제의 근본 수정.
"""
from __future__ import annotations

import sys

# 상수 — MS 문서(BROWSEINFO) 기준.
_BIF_RETURNONLYFSDIRS = 0x0001    # 파일시스템 폴더만 (내 컴퓨터 같은 가상 항목 배제)
_BIF_NEWDIALOGSTYLE = 0x0040      # 크기 조절 + '새 폴더' 버튼. COM 초기화 필요.
_BFFM_INITIALIZED = 1
_BFFM_SETSELECTIONW = 0x0467


def is_supported() -> bool:
    return sys.platform == 'win32'


def open_folder_dialog(title: str = '프로젝트 폴더 선택', initial: str = '') -> str:
    """폴더를 고르게 하고 절대 경로를 돌려준다. 취소하면 ''.

    [불변식] 실패는 예외로 던진다. 빈 문자열은 오직 '사용자가 취소함'만을 뜻한다 —
      둘을 같은 값으로 뭉개면 호출부가 '취소'와 '못 띄움'을 구분할 수 없고, 그것이
      이 기능이 조용히 죽어 있던 원인이었다.
    """
    if not is_supported():
        raise RuntimeError('네이티브 폴더 다이얼로그는 윈도우 전용')

    import ctypes
    from ctypes import wintypes

    shell32 = ctypes.windll.shell32
    ole32 = ctypes.windll.ole32
    user32 = ctypes.windll.user32

    # BFFCALLBACK — 다이얼로그가 뜬 직후 초기 폴더를 지정하고 창을 앞으로 끌어온다.
    # [WHY 앞으로 끌어오는가] 소유자 창(hwndOwner)을 0으로 두면 다이얼로그가 앱 뒤로
    #   숨을 수 있다. 워커 스레드에서 앱의 HWND 를 안전하게 알아낼 방법이 없어
    #   (GetForegroundWindow 는 다른 앱을 집을 수 있다) 소유자 대신 이 방법을 쓴다.
    #   tkinter 판이 attributes('-topmost', True) 로 하던 것과 같은 목적이다.
    BFFCALLBACK = ctypes.WINFUNCTYPE(
        ctypes.c_int, wintypes.HWND, wintypes.UINT, wintypes.LPARAM, wintypes.LPARAM)

    def _callback(hwnd, msg, lparam, data):
        if msg == _BFFM_INITIALIZED:
            if initial:
                user32.SendMessageW(hwnd, _BFFM_SETSELECTIONW, 1,
                                    ctypes.c_wchar_p(initial))
            user32.SetForegroundWindow(hwnd)
        return 0

    cb = BFFCALLBACK(_callback)

    class BROWSEINFOW(ctypes.Structure):
        _fields_ = [
            ('hwndOwner', wintypes.HWND),
            ('pidlRoot', ctypes.c_void_p),
            ('pszDisplayName', wintypes.LPWSTR),
            ('lpszTitle', wintypes.LPCWSTR),
            ('ulFlags', wintypes.UINT),
            ('lpfn', BFFCALLBACK),
            ('lParam', wintypes.LPARAM),
            ('iImage', ctypes.c_int),
        ]

    shell32.SHBrowseForFolderW.argtypes = [ctypes.POINTER(BROWSEINFOW)]
    shell32.SHBrowseForFolderW.restype = ctypes.c_void_p
    shell32.SHGetPathFromIDListW.argtypes = [ctypes.c_void_p, wintypes.LPWSTR]
    shell32.SHGetPathFromIDListW.restype = wintypes.BOOL
    ole32.CoTaskMemFree.argtypes = [ctypes.c_void_p]
    ole32.CoTaskMemFree.restype = None
    ole32.OleInitialize.argtypes = [ctypes.c_void_p]
    ole32.OleInitialize.restype = ctypes.c_long
    user32.SetForegroundWindow.argtypes = [wintypes.HWND]
    user32.SendMessageW.argtypes = [wintypes.HWND, wintypes.UINT,
                                    wintypes.WPARAM, ctypes.c_void_p]

    # [제약] 이미 다른 모델로 초기화된 스레드면 RPC_E_CHANGED_MODE(0x80010106)가 온다.
    #   그때는 우리가 초기화한 것이 아니므로 OleUninitialize 를 부르면 안 된다
    #   (남의 참조 카운트를 깎아 그 스레드의 COM 을 망가뜨린다).
    hr = ole32.OleInitialize(None)
    should_uninit = (hr >= 0)

    try:
        display = ctypes.create_unicode_buffer(260)
        bi = BROWSEINFOW()
        bi.hwndOwner = None
        bi.pidlRoot = None
        bi.pszDisplayName = ctypes.cast(display, wintypes.LPWSTR)
        bi.lpszTitle = title
        bi.ulFlags = _BIF_RETURNONLYFSDIRS | _BIF_NEWDIALOGSTYLE
        bi.lpfn = cb
        bi.lParam = 0
        bi.iImage = 0

        pidl = shell32.SHBrowseForFolderW(ctypes.byref(bi))
        if not pidl:
            return ''                       # 사용자가 취소

        try:
            # [제약] 버퍼는 MAX_PATH(260)로 충분하다 — SHGetPathFromIDListW 는 긴 경로를
            #   지원하지 않고, 초과하면 FALSE 를 돌려준다. 그때는 취소가 아니라 실패다.
            buf = ctypes.create_unicode_buffer(260)
            if not shell32.SHGetPathFromIDListW(pidl, buf):
                raise RuntimeError('선택한 항목의 파일 경로를 얻지 못했다(긴 경로 또는 가상 폴더)')
            return buf.value
        finally:
            ole32.CoTaskMemFree(pidl)
    finally:
        if should_uninit:
            ole32.OleUninitialize()
