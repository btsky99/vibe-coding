# -*- coding: utf-8 -*-
"""
FILE: scripts/console_watch.py
DESCRIPTION: 검은 콘솔 창이 뜨는 **그 순간** 주인을 잡아 적는다(규칙 10 위반 추적용).

             [🔴 왜 필요한가 — 2026-08-17] 사장 신고 "실행 시 node.exe 콘솔이 계속 뜬다".
               창은 번쩍이고 사라지므로 **뜬 뒤에 프로세스를 물으면 이미 늦다**. 그래서
               EnumWindows 로 훑다가 새 콘솔이 보이는 즉시 그 창의 pid → 명령줄 → **부모**
               까지 붙잡아 남긴다. 범인을 코드에서 짐작하지 않고 **현장에서 잡는 도구**다.

             [🔴 이 저장소가 같은 자리에서 세 번 헤맸다] 콘솔 깜빡임 사고가 이미 두 번
               있었고(d423a7d / 2026-08-14), 그때마다 '어디서 띄우나'를 찾는 데 시간을 다 썼다.
               도구를 남겨 두면 다음엔 5분이면 끝난다.

             [쓰는 법] 앱을 켜기 **직전에** 띄운다:
                 python scripts/console_watch.py 180
               창이 뜰 때마다 제목·pid·명령줄·부모를 찍는다. 아무것도 안 찍히면 그 구간에
               콘솔은 안 뜬 것이다(그 자체가 근거가 된다).

             [제약] 고전 콘솔(ConsoleWindowClass)만 센다 — Windows Terminal 은 사람이 연
               창이라 잡음이 된다(실측에서 실제로 걸렸다).

REVISION HISTORY:
- 2026-08-17 Claude: 최초 작성 — node.exe 콘솔 추적
"""
import ctypes, subprocess, sys, time
from ctypes import wintypes

u32 = ctypes.windll.user32
WNDENUMPROC = ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.HWND, wintypes.LPARAM)
u32.EnumWindows.argtypes = [WNDENUMPROC, wintypes.LPARAM]
u32.GetClassNameW.argtypes = [wintypes.HWND, wintypes.LPWSTR, ctypes.c_int]
u32.GetWindowTextW.argtypes = [wintypes.HWND, wintypes.LPWSTR, ctypes.c_int]
u32.IsWindowVisible.argtypes = [wintypes.HWND]
u32.GetWindowThreadProcessId.argtypes = [wintypes.HWND, ctypes.POINTER(wintypes.DWORD)]

NO_WIN = 0x08000000


def owner(pid):
    try:
        r = subprocess.run(
            ['powershell', '-NoProfile', '-Command',
             f"$p=Get-CimInstance Win32_Process -Filter 'ProcessId={pid}';"
             f"if($p){{$q=Get-CimInstance Win32_Process -Filter ('ProcessId='+$p.ParentProcessId);"
             f"'{{0}} | 부모: {{1}} {{2}}' -f $p.CommandLine,$q.Name,$q.CommandLine}}"],
            capture_output=True, text=True, timeout=20, encoding='utf-8',
            errors='replace', creationflags=NO_WIN)
        return (r.stdout or '').strip()[:260]
    except Exception as e:
        return f'(못 읽음 {e})'


def scan():
    got = {}

    def cb(h, _):
        if not u32.IsWindowVisible(h):
            return True
        c = ctypes.create_unicode_buffer(256); u32.GetClassNameW(h, c, 256)
        if c.value != 'ConsoleWindowClass':
            return True
        t = ctypes.create_unicode_buffer(300); u32.GetWindowTextW(h, t, 300)
        pid = wintypes.DWORD(); u32.GetWindowThreadProcessId(h, ctypes.byref(pid))
        got[h] = (t.value, pid.value)
        return True
    u32.EnumWindows(WNDENUMPROC(cb), 0)
    return got


SEC = int(sys.argv[1]) if len(sys.argv) > 1 else 150
seen, base = {}, set(scan())
print(f'감시 시작 — {SEC}초. 시작 시점 콘솔 창 {len(base)}개', flush=True)
t0 = time.time()
while time.time() - t0 < SEC:
    for h, (title, pid) in scan().items():
        if h in base or h in seen:
            continue
        seen[h] = True
        print(f'[{time.time()-t0:6.1f}초] 🔴 콘솔 창 떴다  제목={title!r}  pid={pid}', flush=True)
        print(f'          주인: {owner(pid)}', flush=True)
    time.sleep(0.03)
print(f'끝 — 새로 뜬 콘솔 창 {len(seen)}개')
