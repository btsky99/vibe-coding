# -*- coding: utf-8 -*-
"""
FILE: .ai_monitor/infra/webview_permissions.py
DESCRIPTION: WebView2(Windows)에서 마이크 권한 요청을 허용하는 배선.
             음성 입력(SpeechRecognition)이 실제로 동작하기 위한 전제다.

             [🔴 왜 이 파일이 필요한가 — 실측 2026-08-15]
               pywebview 6.1 의 edgechromium 백엔드는 CoreWebView2.PermissionRequested 를
               **아무도 처리하지 않는다**(Qt 백엔드에만 있다). 그 상태에서 페이지가
               getUserMedia/SpeechRecognition 을 부르면 요청이 허용도 거부도 되지 않고
               **응답 없이 매달린다** — 에러조차 안 온다. 실측에서 6초를 기다려도
               onerror/onstart 어느 쪽도 오지 않았고, 핸들러를 붙이자 곧바로
               gum:ok → onstart → onaudiostart 가 나왔다.
               이 실패가 나쁜 이유: 화면에는 '듣는 중…'만 떠 있고 사용자는 자기 마이크를
               의심하게 된다.

             [WHY --use-fake-ui-for-media-stream 플래그를 안 쓰나]
               브라우저 인자로 전 미디어 자동허용을 켜면 카메라까지 무조건 허용된다.
               여기서 필요한 것은 마이크 하나다. 종류를 보고 허용하는 쪽이 정확하다.

             [제약] Windows + EdgeChromium 백엔드 전용. 맥(WKWebView)은 시스템 권한
               대화상자를 OS 가 직접 띄우므로 이 배선이 필요 없고, 여기서는 조용히 논다.

             [제약] CoreWebView2 는 창이 뜬 뒤 비동기로 만들어진다. 창 생성 직후에는
               아직 None 이라 붙일 수 없다 — 그래서 폴링으로 기다린다.

REVISION HISTORY:
- 2026-08-15 Claude: 배선 시점을 loaded 이후로 미룸 — create_window 직후에는 WebView2
                     어셈블리가 아직 로드 전이라 import 가 항상 실패해 마이크가 조용히
                     죽어 있었다(실측: 로그에 '바인딩 없음' 만 반복).
- 2026-08-15 Claude: 최초 작성 — 아픽스 음성 기능 이식(마이크 권한 전제)
"""

from __future__ import annotations

import sys
import threading
import time

# 마이크만 허용한다. 카메라·위치·알림 등은 손대지 않고 WebView2 기본 동작에 맡긴다.
_ALLOWED_KINDS = ('Microphone',)


def _run_on_ui(window, fn):
    """fn 을 창의 UI 스레드에서 실행하고 결과를 돌려준다. 못 하면 (None, 예외).

    [🔴🔴 이 우회가 없으면 마이크가 조용히 죽는다 — 실측 2026-08-15]
      `webview.CoreWebView2` 게터를 다른 스레드에서 읽으면 .NET 이 그대로 거절한다:
        System.InvalidOperationException: CoreWebView2 can only be accessed from the UI thread.
      (내부적으로 ICoreWebView2Controller QueryInterface 가 E_NOINTERFACE 로 실패한다.)
      예외는 배선 스레드만 죽이고 로그 한 줄로 끝나 **화면에는 아무 표시도 안 난다** —
      사용자는 마이크가 고장 났다고 생각하게 된다.

      게다가 그냥 읽으면 위험하기까지 하다. 다른 스레드에서의 접근은 UI 스레드와 동기화를
      요구하는데, 그 스레드가 스플래시를 그리는 중(NavigateToString)이면 서로를 기다려
      **부팅 전체가 멈춘다**(자책 사고 1건 — infra/webview_health.py 헤더).

    [WHY Invoke 인가] pywebview 자신이 같은 문제를 이렇게 푼다
      (winforms.py 의 `i.Invoke(Func[Type](create))`, `set_title`). 우리도 같은 관문을 쓴다.
    [제약] Invoke 는 동기다 — UI 스레드가 막혀 있으면 반환하지 않는다. 그래서 호출부는
      반드시 events.loaded **이후**에만 이 함수를 부른다(그 시점의 UI 스레드는 유휴).
    """
    from System import Func, Type                              # type: ignore[import-not-found]
    from webview.platforms.winforms import BrowserView

    inst = BrowserView.instances.get(getattr(window, 'uid', 'master'))
    if inst is None:
        return None, RuntimeError('BrowserView 인스턴스 없음')

    box: dict = {}

    def _do():
        try:
            box['value'] = fn(inst)
        except Exception as e:                                 # noqa: BLE001
            box['error'] = e
        return None

    try:
        if getattr(inst, 'InvokeRequired', False):
            inst.Invoke(Func[Type](_do))
        else:
            _do()
    except Exception as e:                                     # noqa: BLE001
        return None, e
    return box.get('value'), box.get('error')


def _find_core(window, timeout: float) -> object | None:
    """창의 CoreWebView2 객체를 기다렸다 반환. 없으면 None.

    접근은 전부 _run_on_ui 를 통한다 — 직접 읽으면 UI 스레드 예외로 죽는다(위 참조).
    대기(sleep)는 UI 스레드가 아니라 **여기(백그라운드)** 에서 한다. UI 스레드 안에서
    기다리면 그 창의 메시지 루프가 그동안 멈춰 화면이 굳는다.
    """
    deadline = time.time() + timeout
    while time.time() < deadline:
        core, _err = _run_on_ui(
            window, lambda i: getattr(getattr(i, 'browser', None), 'webview', None)
            and i.browser.webview.CoreWebView2)
        if core is not None:
            return core
        time.sleep(0.2)
    return None


def _attach(window, timeout: float) -> None:
    # [🔴 순서가 전부다 — 실측 2026-08-15] pywebview 는 `webview.start()` 안에서
    #   platforms.edgechromium 을 import 하고, **그 모듈이** clr.AddReference 로 WebView2
    #   어셈블리를 로드한다(edgechromium.py:36-37). 이 스레드는 create_window 직후에
    #   시작되므로 그 시점엔 어셈블리가 아직 없다 → `from Microsoft...` 가 **항상**
    #   ImportError 를 내고 배선을 통째로 건너뛴다. 로그에는 '바인딩 없음' 한 줄만 남고
    #   마이크는 조용히 죽는다(getUserMedia 가 허용도 거부도 못 받아 매달림 — 이 파일
    #   헤더 참조). 창이 실제로 뜬 뒤라면 어셈블리는 확실히 로드돼 있다.
    # [WHY events.loaded 인가] 순수 threading.Event 라 크로스스레드 대기가 안전하다.
    #   WebView2 객체를 미리 건드려 확인하려 들면 STA 스레드와 교착한다(webview_health 헤더).
    deadline = time.time() + timeout
    try:
        if not window.events.loaded.wait(timeout):
            print('[voice] 마이크 권한 배선 생략 — 창이 끝내 뜨지 않음')
            return
    except Exception as e:                                    # noqa: BLE001
        print(f'[voice] 마이크 권한 배선 생략 (loaded 이벤트 없음: {e})')
        return

    try:
        from Microsoft.Web.WebView2.Core import (            # type: ignore[import-not-found]
            CoreWebView2PermissionKind,
            CoreWebView2PermissionRequestedEventArgs,
            CoreWebView2PermissionState,
        )
        from System import EventHandler                       # type: ignore[import-not-found]
    except Exception as e:                                    # noqa: BLE001
        print(f'[voice] 마이크 권한 배선 생략 (WebView2 바인딩 없음: {e})')
        return

    core = _find_core(window, max(5.0, deadline - time.time()))
    if core is None:
        print('[voice] 마이크 권한 배선 실패 — CoreWebView2 를 못 찾음 (음성 입력 불가)')
        return

    def on_permission(_sender, args):
        # [🔴 종류를 반드시 본다] 전부 Allow 로 두면 이 창이 여는 모든 권한이 무조건
        #   허용된다. 로컬 앱이라도 그건 필요 이상이다.
        try:
            for kind in _ALLOWED_KINDS:
                if args.PermissionKind == getattr(CoreWebView2PermissionKind, kind):
                    args.State = CoreWebView2PermissionState.Allow
                    return
        except Exception:                                     # noqa: BLE001
            # 여기서 예외가 .NET 이벤트 경계를 넘으면 창이 죽는다. 권한 하나 못 준 것과
            # 앱이 꺼지는 것은 비교 대상이 아니다.
            pass

    # [🔴] 이벤트 구독도 CoreWebView2 를 만지는 일이라 UI 스레드에서 해야 한다.
    #   읽기만 UI 스레드로 옮기고 등록을 백그라운드에서 하면 같은 예외로 되돌아간다.
    def _subscribe(_inst):
        core.PermissionRequested += EventHandler[CoreWebView2PermissionRequestedEventArgs](
            on_permission)
        return True

    ok, err = _run_on_ui(window, _subscribe)
    if ok:
        print('[voice] 마이크 권한 배선 완료 (WebView2 PermissionRequested)')
    else:
        print(f'[voice] 마이크 권한 배선 실패: {err} (음성 입력 불가)')


def enable_microphone(window, timeout: float = 30.0) -> None:
    """창에 마이크 권한 자동 허용을 붙인다. 실패해도 앱 기동을 막지 않는다.

    [WHY 스레드인가] CoreWebView2 생성을 기다려야 하는데, 호출부(app_boot)는 그 사이
      스플래시·서버 기동 같은 진짜 일을 해야 한다. 이 부가 기능이 부팅을 붙잡으면 안 된다.
    """
    if not sys.platform.startswith('win'):
        return
    threading.Thread(target=_attach, args=(window, timeout),
                     daemon=True, name='voice-mic-permission').start()
