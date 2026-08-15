# -*- coding: utf-8 -*-
"""
FILE: scripts/console_flicker_watch.py
DESCRIPTION: 순간적으로 떴다 사라지는 콘솔 창의 '범인'을 잡는 감시기.
             창이 뜨는 순간(SetWinEventHook)을 잡아 exe·부모·명령줄을 기록한다.
             규칙 10(사람이 안 시킨 실행은 창을 띄우지 않는다) 위반 지점 추적용.

             [🔴 왜 폴링이 아니라 후킹인가 — 과거사고 2026-08-14]
               콘솔 깜빡임 사고는 창이 0.05~0.2초만 떴다 사라진다. 0.1초 폴링으로도
               대부분 놓쳐서, 사고 당시 "재현이 안 된다"로 며칠을 태웠다. 창 생성은
               이벤트라 이벤트로 받아야 한다.

             [🔴 conhost 생성 ≠ 창이 뜸] node-pty(ConPTY)는 `conhost --headless`를
               정상적으로 만든다 — 창이 없다. conhost 존재만 세면 터미널 슬롯이 전부
               범인으로 잡힌다. 그래서 창 클래스(ConsoleWindowClass)로 거른다.

             [🔴 argtypes 를 반드시 선언한다] 생략하면 64비트에서 HWND 가 32비트로
               잘려 콜백이 엉뚱한 창을 보고, 증상이 '조용히 0건'이라 감시기가 고장난
               줄도 모른다(상태판 개발 때 같은 함정을 밟았다).

             [제약] 윈도우 전용. 메시지 루프를 도는 전경 프로세스라 이 스크립트 자체는
               사람이 직접 띄운다 — 규칙 10의 대상이 아니다.

             사용법:
               python scripts/console_flicker_watch.py            # Ctrl+C 까지 감시
               python scripts/console_flicker_watch.py --seconds 300

REVISION HISTORY:
- 2026-08-15 Claude: 최초 작성 — "바이브 코딩 켜면 콘솔 창이 자꾸 뜬다" 실측용
"""

from __future__ import annotations

import argparse
import ctypes
import ctypes.wintypes as wt
import sys
import time
from datetime import datetime
from pathlib import Path

if sys.platform != 'win32':
    print('윈도우 전용입니다.')
    raise SystemExit(0)

user32 = ctypes.WinDLL('user32', use_last_error=True)
kernel32 = ctypes.WinDLL('kernel32', use_last_error=True)

EVENT_OBJECT_SHOW = 0x8002
EVENT_OBJECT_CREATE = 0x8000
WINEVENT_OUTOFCONTEXT = 0x0000
WINEVENT_SKIPOWNPROCESS = 0x0002
PROCESS_QUERY_LIMITED_INFORMATION = 0x1000
TH32CS_SNAPPROCESS = 0x00000002

user32.GetClassNameW.argtypes = [wt.HWND, wt.LPWSTR, ctypes.c_int]
user32.GetClassNameW.restype = ctypes.c_int
user32.GetWindowTextW.argtypes = [wt.HWND, wt.LPWSTR, ctypes.c_int]
user32.GetWindowTextW.restype = ctypes.c_int
user32.GetWindowThreadProcessId.argtypes = [wt.HWND, ctypes.POINTER(wt.DWORD)]
user32.GetWindowThreadProcessId.restype = wt.DWORD
kernel32.OpenProcess.argtypes = [wt.DWORD, wt.BOOL, wt.DWORD]
kernel32.OpenProcess.restype = wt.HANDLE
kernel32.QueryFullProcessImageNameW.argtypes = [
    wt.HANDLE, wt.DWORD, wt.LPWSTR, ctypes.POINTER(wt.DWORD)]
kernel32.QueryFullProcessImageNameW.restype = wt.BOOL


class PROCESSENTRY32W(ctypes.Structure):
    _fields_ = [
        ('dwSize', wt.DWORD), ('cntUsage', wt.DWORD), ('th32ProcessID', wt.DWORD),
        ('th32DefaultHeapID', ctypes.POINTER(ctypes.c_ulong)),
        ('th32ModuleID', wt.DWORD), ('cntThreads', wt.DWORD),
        ('th32ParentProcessID', wt.DWORD), ('pcPriClassBase', ctypes.c_long),
        ('dwFlags', wt.DWORD), ('szExeFile', ctypes.c_wchar * 260),
    ]


def _proc_table() -> dict[int, tuple[int, str]]:
    """pid → (부모pid, exe이름). [WHY toolhelp 인가] CIM 스냅샷은 ~700ms 라 콜백 안에서
    쓰면 이벤트를 놓친다. toolhelp 는 수 ms 다."""
    out: dict[int, tuple[int, str]] = {}
    snap = kernel32.CreateToolhelp32Snapshot(TH32CS_SNAPPROCESS, 0)
    if snap == -1:
        return out
    try:
        e = PROCESSENTRY32W()
        e.dwSize = ctypes.sizeof(PROCESSENTRY32W)
        ok = kernel32.Process32FirstW(snap, ctypes.byref(e))
        while ok:
            out[e.th32ProcessID] = (e.th32ParentProcessID, e.szExeFile)
            ok = kernel32.Process32NextW(snap, ctypes.byref(e))
    finally:
        kernel32.CloseHandle(snap)
    return out


def _exe_path(pid: int) -> str:
    h = kernel32.OpenProcess(PROCESS_QUERY_LIMITED_INFORMATION, False, pid)
    if not h:
        return ''
    try:
        size = wt.DWORD(1024)
        buf = ctypes.create_unicode_buffer(1024)
        if kernel32.QueryFullProcessImageNameW(h, 0, buf, ctypes.byref(size)):
            return buf.value
        return ''
    finally:
        kernel32.CloseHandle(h)


def _ancestry(pid: int, table: dict[int, tuple[int, str]], depth: int = 5) -> str:
    """부모를 거슬러 올라간 사슬. [WHY 필요한가] 창을 띄운 것은 보통 cmd.exe·conhost 라,
    범인은 그 위에 있다. 사슬이 없으면 '또 cmd 가 떴다'만 알고 끝난다."""
    chain, cur = [], pid
    for _ in range(depth):
        ent = table.get(cur)
        if not ent:
            break
        ppid, name = ent
        chain.append(f'{name}({cur})')
        cur = ppid
        if cur in (0, 4):
            break
    return ' ← '.join(chain)


LOG = Path(__file__).resolve().parent.parent / '.local' / 'console_flicker.log'
LOG.parent.mkdir(parents=True, exist_ok=True)
_seen: set[tuple[int, str]] = set()
_count = 0


def _on_event(hook, event, hwnd, id_object, id_child, thread, ts):
    global _count
    if not hwnd:
        return
    cls = ctypes.create_unicode_buffer(64)
    if user32.GetClassNameW(hwnd, cls, 64) <= 0:
        return
    if cls.value != 'ConsoleWindowClass':
        return

    pid = wt.DWORD()
    user32.GetWindowThreadProcessId(hwnd, ctypes.byref(pid))
    pid = int(pid.value)
    if not pid:
        return

    title = ctypes.create_unicode_buffer(256)
    user32.GetWindowTextW(hwnd, title, 256)

    table = _proc_table()
    # 창을 소유한 것은 conhost 다. 실제 범인은 그 부모 사슬에 있다.
    key = (pid, title.value)
    if key in _seen:
        return
    _seen.add(key)
    _count += 1

    line = (f'[{datetime.now():%H:%M:%S.%f}] #{_count} '
            f'title={title.value!r}\n'
            f'    exe={_exe_path(pid)}\n'
            f'    계보={_ancestry(pid, table)}\n')
    print(line, end='', flush=True)
    with LOG.open('a', encoding='utf-8') as f:
        f.write(line)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument('--seconds', type=int, default=0, help='0이면 Ctrl+C 까지')
    args = ap.parse_args()

    proto = ctypes.WINFUNCTYPE(
        None, wt.HANDLE, wt.DWORD, wt.HWND, wt.LONG, wt.LONG, wt.DWORD, wt.DWORD)
    cb = proto(_on_event)

    # [WHY SHOW 와 CREATE 둘 다] 창이 만들어질 때(CREATE)와 숨겨졌다 보일 때(SHOW)가
    #   다르다. 재사용되는 콘솔은 CREATE 없이 SHOW 만 온다.
    hooks = []
    for ev in (EVENT_OBJECT_CREATE, EVENT_OBJECT_SHOW):
        h = user32.SetWinEventHook(ev, ev, 0, cb, 0, 0,
                                   WINEVENT_OUTOFCONTEXT | WINEVENT_SKIPOWNPROCESS)
        if h:
            hooks.append(h)
    if not hooks:
        print('후킹 실패')
        return 1

    print(f'감시 시작 — 로그: {LOG}\n(앱을 평소처럼 쓰세요. Ctrl+C 로 종료)')
    msg = wt.MSG()
    deadline = time.time() + args.seconds if args.seconds else None
    try:
        while True:
            # PeekMessage + sleep 으로 돈다. [WHY GetMessage 가 아닌가] GetMessage 는
            #   블로킹이라 --seconds 시한과 Ctrl+C 를 같이 처리할 수 없다.
            while user32.PeekMessageW(ctypes.byref(msg), 0, 0, 0, 1):
                user32.TranslateMessage(ctypes.byref(msg))
                user32.DispatchMessageW(ctypes.byref(msg))
            if deadline and time.time() > deadline:
                break
            time.sleep(0.01)
    except KeyboardInterrupt:
        pass
    finally:
        for h in hooks:
            user32.UnhookWinEvent(h)
    print(f'\n총 {_count}건. 로그: {LOG}')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
