# -*- coding: utf-8 -*-
"""
FILE: .ai_monitor/infra/webview_health.py
DESCRIPTION: WebView2 엔진이 창에 실제로 붙었는지 감시하고, 안 붙었으면 원인을 진단해
             사용자에게 알린 뒤 단일 인스턴스 락을 놓고 종료시킨다.

             [🔴 왜 이 파일이 필요한가 — 사고 2026-08-15]
               윈도우가 WebView2 런타임을 151.0.4129.78 → .86 으로 자동 업데이트했다.
               그런데 창을 이미 잃은 옛 앱 프로세스가 UDF(사용자 데이터 폴더)를 구버전으로
               점유한 채 살아 있었다. UDF 는 런타임 버전 하나에만 귀속되므로, 새로 뜬 앱이
               같은 UDF 에 붙으려다 CreateCoreWebView2ControllerAsync 에서
               0x80010108(RPC_E_DISCONNECTED) 로 실패했다.

               문제는 실패 방식이다. pywebview 6.1 은 이 실패를 예외로 올리지 않고
               stdout 에만 찍는다 → **창은 만들어졌는데 그 안에 브라우저가 없다**(하얀 창).
               게다가 그 프로세스가 단일 인스턴스 락을 계속 쥐고 있어, 사용자가 아이콘을
               다시 눌러도 새 창이 뜨지 않고 하얀 창만 앞으로 나온다
               (instance_lock.acquire_single_instance_lock 이 기존 창을 포커스하고 exit).
               결과적으로 사용자는 **재실행으로도 빠져나올 수 없는 상태**에 갇힌다.

             [🔴🔴 감시 방법으로 CoreWebView2 폴링을 절대 쓰지 말 것 — 자책 사고 2026-08-15]
               이 파일의 첫 판(4fde303)은 `BrowserView.instances → browser.webview.CoreWebView2`
               를 0.2초마다 읽어 생존을 판정했다. 그 접근이 **부팅 자체를 교착시켰다**.

               WebView2 는 WinForms 컨트롤이고, 그 컨트롤은 창을 만든 **STA 스레드 전용**이다.
               `webview.CoreWebView2` 게터를 다른 스레드에서 읽으면 UI 스레드와의 동기화가
               필요한데, 마침 그 STA 스레드는 스플래시를 그리는 중(NavigateToString)이었다.
               서로를 기다리며 STA 메시지 루프가 멈췄고 → loaded 이벤트가 영영 안 오고 →
               `_update_splash` 의 evaluate_js 가 무한 대기 → **부팅이 통째로 정지**했다.
               증상은 '하얀 창' 이 아니라 '응답 없음' 이라 원인이 더 안 보였다.
               (실측: 같은 커밋을 되돌리자 Responding=True + 서버 포트 즉시 확보)

               그래서 지금은 **순수 Python 신호만** 본다 — `window.events.loaded` 는
               pywebview 가 관리하는 threading.Event 라 어느 스레드에서 기다려도 안전하고,
               '엔진이 붙어 페이지가 실제로 떴는가' 라는 질문에 CoreWebView2 존재 여부보다
               오히려 더 정확히 답한다(엔진만 붙고 로드가 안 되는 경우까지 걸러낸다).

             [WHY 자동으로 구버전 프로세스를 죽이지 않는가]
               UDF 를 점유한 msedgewebview2 를 죽이면 락은 풀린다. 하지만 그 엔진이
               '창을 잃은 좀비' 가 아니라 **정상 사용 중인 다른 인스턴스**의 것이면,
               멀쩡히 쓰고 있던 창을 우리가 하얗게 만드는 셈이다. 오판의 대가가
               '남의 창 파괴' 라 비대칭적으로 크다. 그래서 여기서는 **원인을 정확히
               말해주고 길을 열어주는 것**까지만 한다.

             [불변식] on_dead 콜백은 반드시 락 해제를 수행해야 한다 — 그것이 이 감시의
               존재 이유다. 락을 쥔 채 죽으면 다음 실행이 다시 '이미 실행 중' 으로 오판한다.

REVISION HISTORY:
- 2026-08-15 Claude: 감시 방식을 CoreWebView2 폴링 → window.events.loaded 대기로 교체.
                     폴링이 STA 스레드와 교착해 부팅을 멈춘 자책 사고 수정.
- 2026-08-15 Claude: 최초 작성 — WebView2 런타임 자동 업데이트로 인한 '하얀 창 + 재실행 불가'
                     사고(0x80010108) 대응. 감지·진단·탈출로 확보.
"""

from __future__ import annotations

import ctypes
import os
import sys
import threading
from pathlib import Path

# WebView2 런타임(에버그린)의 EdgeUpdate 등록 GUID. 시스템/사용자 설치 양쪽에서 같다.
_RUNTIME_GUID = '{F3017226-FE2A-4295-8BDF-00C3A9A7E4C5}'

# 스플래시(인라인 HTML, 외부 리소스 0)는 실측 0.7~1.2초에 loaded 가 뜬다. 45초를 넘겼다면
# '느린 것' 이 아니라 '안 오는 것' 이다. 느린 PC 를 오판해 멀쩡한 부팅을 죽이는 쪽이
# 하얀 창을 방치하는 것보다 나쁘므로 여유를 크게 준다.
_LOADED_TIMEOUT = 45.0


def installed_runtime_version() -> str | None:
    """설치된 WebView2 런타임 버전. 못 읽으면 None.

    [WHY 레지스트리인가] 파일 경로(Application/<버전>/)에는 이전 버전 폴더가 남아 있어
      '어느 것이 현역인지' 를 알 수 없다. 업데이트 직후 두 버전이 공존하는 상태가 정확히
      이 사고의 무대였다 — 폴더로 판정하면 사고를 못 본다.
    """
    if not sys.platform.startswith('win'):
        return None
    import winreg

    for hive, path in (
        (winreg.HKEY_LOCAL_MACHINE, rf'SOFTWARE\WOW6432Node\Microsoft\EdgeUpdate\Clients\{_RUNTIME_GUID}'),
        (winreg.HKEY_LOCAL_MACHINE, rf'SOFTWARE\Microsoft\EdgeUpdate\Clients\{_RUNTIME_GUID}'),
        (winreg.HKEY_CURRENT_USER, rf'Software\Microsoft\EdgeUpdate\Clients\{_RUNTIME_GUID}'),
    ):
        try:
            with winreg.OpenKey(hive, path) as k:
                pv, _ = winreg.QueryValueEx(k, 'pv')
                if pv:
                    return str(pv)
        except OSError:
            continue
    return None


def udf_last_version(storage_path: Path) -> str | None:
    """UDF 가 마지막으로 열렸을 때의 런타임 버전. 아직 한 번도 안 열렸으면 None.

    WebView2 가 UDF 루트(EBWebView)에 'Last Version' 파일로 직접 남긴다.
    """
    try:
        return (Path(storage_path) / 'EBWebView' / 'Last Version').read_text(
            encoding='utf-8', errors='replace').strip() or None
    except OSError:
        return None


def diagnose(storage_path: Path) -> str:
    """왜 화면이 안 떴는지 사람이 읽을 수 있는 진단문. 비전문가가 그대로 따라할 수 있게 쓴다.

    [WHY 진단을 여기서 만드나] 실패 시점에는 이미 창이 하얗고 로그는 안 보인다. 사용자가
      볼 수 있는 유일한 표면이 이 문자열이므로, 원인 추정과 '다음에 할 일' 을 한 덩어리로 준다.
    """
    installed = installed_runtime_version()
    last = udf_last_version(storage_path)

    head = ('화면을 그리는 윈도우 내장 브라우저(WebView2)가 열리지 않았습니다.\n'
            '앱과 서버는 정상입니다 — 화면만 못 붙은 상태입니다.\n\n')
    tail = ('해결:\n'
            '  1. 작업 관리자(Ctrl+Shift+Esc)에서 "바이브 코딩"을 모두 종료\n'
            '  2. 앱을 다시 실행\n'
            '  (그래도 안 되면 PC를 재시작하면 확실히 풀립니다)')

    if installed and last and installed != last:
        return (head +
                f'원인: WebView2가 {last} → {installed} 로 업데이트됐는데,\n'
                f'옛 버전을 쓰던 바이브 코딩 프로세스가 아직 남아 설정 폴더를 붙잡고 있습니다.\n\n'
                + tail)

    if installed is None:
        return (head +
                '원인: WebView2 런타임이 설치되어 있지 않은 것으로 보입니다.\n\n'
                '해결: "Microsoft Edge WebView2 Runtime" 을 설치한 뒤 다시 실행하세요.')

    return (head +
            f'원인: WebView2({installed}) 초기화 실패. 다른 프로세스가 앱 설정 폴더를\n'
            '붙잡고 있을 때 주로 발생합니다.\n\n' + tail)


def _notify(message: str) -> None:
    """진단문을 사용자에게 보여준다. 실패해도 종료 흐름을 막지 않는다.

    [WHY MessageBox 인가] 하얀 창 상태에서는 앱 내부 UI 로 아무것도 못 보여준다.
      OS 대화상자만이 이 상황에서 확실히 사용자 눈에 닿는 표면이다.
    [제약] MB_SETFOREGROUND(0x10000) 없이는 다른 창 뒤에 숨어 '아무 일도 안 일어난' 것처럼
      보인다 — 사고 당시 사용자가 본 것이 정확히 그 상태(하얀 창)였다.
    """
    print('[webview_health] ' + message.replace('\n', ' | '))
    try:
        ctypes.windll.user32.MessageBoxW(
            0, message, '바이브 코딩 — 화면을 열지 못했습니다',
            0x00000010 | 0x00010000)      # MB_ICONERROR | MB_SETFOREGROUND
    except Exception:                                          # noqa: BLE001
        pass


def _watch(window, storage_path: Path, on_dead) -> None:
    # [🔴 여기서 window 의 다른 속성을 건드리지 말 것] events.loaded 는 순수 threading.Event 라
    #   크로스스레드 대기가 안전하다. 반면 evaluate_js/CoreWebView2 등 WebView2 를 타는 것은
    #   STA 스레드와 동기화를 요구해 부팅을 교착시킨다(위 헤더의 자책 사고).
    try:
        loaded = window.events.loaded.wait(_LOADED_TIMEOUT)
    except Exception as e:                                     # noqa: BLE001
        # pywebview 내부 구조가 바뀌어 events.loaded 가 없어진 경우 — 감시를 포기한다.
        # 감시 실패가 부팅 실패가 되어선 안 된다.
        print(f'[webview_health] 감시 불가(무시하고 계속): {e}')
        return

    if loaded:
        return                                                 # 정상 — 조용히 물러난다

    _notify(diagnose(storage_path))
    try:
        on_dead()
    except Exception as e:                                     # noqa: BLE001
        print(f'[webview_health] 정리 콜백 실패(무시하고 종료): {e}')

    # [WHY os._exit 인가] 이 시점의 프로세스는 창은 있으나 그릴 엔진이 없는 껍데기다.
    #   정상 종료 경로는 webview 이벤트 루프가 돌아야 하는데 그 루프가 이미 죽어 있어
    #   sys.exit 가 메인 스레드까지 도달하지 못한다(실측: 하얀 창이 무한 생존).
    #   여기서 확실히 끊어야 '재실행하면 열린다' 가 성립한다.
    os._exit(1)


def watch_init(window, storage_path: Path, on_dead) -> None:
    """스플래시가 실제로 떴는지 감시한다. 안 뜨면 on_dead() 후 프로세스를 종료한다.

    on_dead 는 **락 해제**를 수행해야 한다 — 그것이 이 감시의 존재 이유다.
    감시 자체는 부팅을 막지 않는다(데몬 스레드).
    """
    if not sys.platform.startswith('win'):
        return
    threading.Thread(target=_watch, args=(window, Path(storage_path), on_dead),
                     daemon=True, name='webview-health').start()
