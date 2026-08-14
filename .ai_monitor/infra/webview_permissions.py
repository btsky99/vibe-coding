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
- 2026-08-15 Claude: 최초 작성 — 아픽스 음성 기능 이식(마이크 권한 전제)
"""

from __future__ import annotations

import sys
import threading
import time

# 마이크만 허용한다. 카메라·위치·알림 등은 손대지 않고 WebView2 기본 동작에 맡긴다.
_ALLOWED_KINDS = ('Microphone',)


def _find_core(window, timeout: float) -> object | None:
    """창의 CoreWebView2 객체를 기다렸다 반환. 없으면 None."""
    from webview.platforms.winforms import BrowserView

    deadline = time.time() + timeout
    while time.time() < deadline:
        inst = BrowserView.instances.get(getattr(window, 'uid', 'master'))
        browser = getattr(inst, 'browser', None) if inst else None
        wv = getattr(browser, 'webview', None) if browser else None
        core = getattr(wv, 'CoreWebView2', None) if wv else None
        if core is not None:
            return core
        time.sleep(0.2)
    return None


def _attach(window, timeout: float) -> None:
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

    core = _find_core(window, timeout)
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

    try:
        core.PermissionRequested += EventHandler[CoreWebView2PermissionRequestedEventArgs](
            on_permission)
        print('[voice] 마이크 권한 배선 완료 (WebView2 PermissionRequested)')
    except Exception as e:                                    # noqa: BLE001
        print(f'[voice] 마이크 권한 배선 실패: {e} (음성 입력 불가)')


def enable_microphone(window, timeout: float = 30.0) -> None:
    """창에 마이크 권한 자동 허용을 붙인다. 실패해도 앱 기동을 막지 않는다.

    [WHY 스레드인가] CoreWebView2 생성을 기다려야 하는데, 호출부(app_boot)는 그 사이
      스플래시·서버 기동 같은 진짜 일을 해야 한다. 이 부가 기능이 부팅을 붙잡으면 안 된다.
    """
    if not sys.platform.startswith('win'):
        return
    threading.Thread(target=_attach, args=(window, timeout),
                     daemon=True, name='voice-mic-permission').start()
