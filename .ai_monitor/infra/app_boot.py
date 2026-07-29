"""
FILE: infra/app_boot.py
DESCRIPTION: PyWebView 데스크톱 앱 부팅 오케스트레이션. 스플래시 창을 먼저 띄우고
             백그라운드 콜백(_init_and_load_app)에서 PG/PTY/HTTP/데몬을 순차 초기화한
             뒤 앱을 로드한다. 창 종료 시 자식 프로세스/PG/HTTP/락을 정리한다.
             server.py main()의 GUI try 블록 전체를 이관 — 부팅에 필요한 server.py 고유
             함수/객체/값은 BootConfig로 명시 주입받는다(R20).

REVISION HISTORY:
- 2026-07-26 Codex: macOS 네이티브 폴더 선택 브리지를 추가해 상단 메뉴 무반응 수정.
- 2026-07-22 Claude: _ClipboardBridge(js_api) 신설 — 맥 WKWebView가 navigator.clipboard를 조용히
                     거부해 우클릭 복붙 전멸 → NSPasteboard 브리지로 우회. Edit 메뉴 탐색을
                     서브메뉴 title 기준으로 수정(pywebview 6.x는 아이템 title이 빈 값).
- 2026-07-08 Claude: server.py main() _init_and_load_app + webview 블록 전체 이관
                     (Phase 3 R20). 로직·주석 verbatim 유지, 심볼만 cfg 참조로 치환.
                     [불변식] _NODE_PTY_REST_URL은 server.py 모듈 전역이라 여기서 global
                     대입 불가 → cfg.set_node_pty_rest_url 콜백 경유(소비자 call-time 참조).
                     [불변식] pty_server_state·child_procs·http_server_ref는 caller가
                     소유한 가변 객체를 그대로 변형 — 재생성 금지(워치독/정리 코드와 공유).
                     [제약] PG-PTY 병렬 최적화(v3.7.179): prepare_pty_async가 반환한 Event를
                     3단계에서 wait — 그 사이 PG를 시작해 부팅 체감 지연을 줄인다.
"""
from __future__ import annotations

import atexit
import os
import sys
import threading
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Callable


@dataclass
class BootConfig:
    """부팅에 필요한 server.py 고유 값/객체/콜백 묶음 — main()이 구성해 주입."""
    # ── 값/가변 객체 ──
    http_port: int
    ws_port: int
    base_dir: Path
    data_dir: Path
    project_root: Path
    project_id: str
    official_icon: str
    splash_html: str
    window_title: str
    pty_server_state: dict
    child_procs: list
    agent_status: dict
    agent_status_lock: object
    http_server_ref: list
    lock_sock: object
    # ── 클래스/팩토리 ──
    http_server_factory: Callable   # ThreadedHTTPServer(addr, handler)
    handler_cls: type               # SSEHandler
    memory_watcher_factory: Callable  # MemoryWatcher(project_id) → .start()
    daemon_env_factory: Callable    # () → DaemonEnv (HTTP_PORT late-binding)
    find_free_port: Callable
    # ── 콜백 ──
    ensure_postgres_running: Callable
    cleanup_postgres: Callable
    cleanup_child_procs: Callable
    init_project_db: Callable       # (project_id)
    restore_agent_status: Callable
    load_task_logs: Callable        # 스레드 target
    agent_broadcast_worker: Callable  # 스레드 target
    start_fs_watcher: Callable      # (project_root)
    set_node_pty_rest_url: Callable  # (url) — 모듈 전역 + pty/agent api 반영
    open_app_window: Callable       # (url) GUI 실패 폴백
    # [헤드리스 2026-07-29] 창 없이 서버·데몬만 띄운다. 기본값이 있어 기존 호출부 무영향.
    # [WHY 필요한가] SSH 세션에는 데스크톱(윈도우 스테이션)이 없어 WebView2 창 생성이 실패한다.
    #   실측: 원격 상주 노드에서 앱을 띄우면 PostgreSQL·데몬까지는 뜨는데 창 단계에서 죽어
    #   HTTP 서버(9000번대)가 끝내 안 올라온다 → 원격에서 상태를 볼 수단이 사라진다.
    headless: bool = False


class _HeadlessWindow:
    """pywebview 창 대역 — _init_and_load_app이 쓰는 두 메서드만 흉내 낸다.

    [제약] 창 객체에서 실제로 쓰이는 것은 evaluate_js(스플래시 문구)와 load_url뿐이다.
      더 붙이면 진짜 창과의 계약이 벌어져 유지보수가 어려워지므로 의도적으로 최소만 구현한다.
    """

    def evaluate_js(self, _script: str):
        return None

    def load_url(self, url: str):
        print(f'[*] 헤드리스 모드 — 창 없이 서버만 가동: {url}')


class _ClipboardBridge:
    """pywebview js_api — 프론트가 window.pywebview.api.clip_read/clip_write로 호출.

    [WHY / 맥포팅 2026-07-22] 맥 WKWebView는 async Clipboard API의 권한 프롬프트를 구현하지 않아
      navigator.clipboard.readText가 NotAllowedError로 조용히 거부됨(윈도우 WebView2는 허용) →
      우클릭 메뉴 복사/붙여넣기가 맥에서만 전멸. NSPasteboard 직접 접근으로 우회한다.
    [제약] js_api 호출은 pywebview 워커 스레드에서 실행됨 — NSPasteboard는 XPC 기반이라
      오프메인 호출이 실무상 안전. 비-맥 플랫폼은 None/False 반환 → 프론트(lib/clipboard.ts)가
      navigator.clipboard로 폴백(윈도우는 그걸로 충분).
    """

    def clip_read(self):
        if sys.platform != 'darwin':
            return None
        try:
            import AppKit
            pb = AppKit.NSPasteboard.generalPasteboard()
            s = pb.stringForType_(AppKit.NSPasteboardTypeString)
            return str(s) if s is not None else ''
        except Exception as e:
            print(f"[clipboard] NSPasteboard 읽기 실패: {e}")
            return None

    def clip_write(self, text):
        if sys.platform != 'darwin':
            return False
        try:
            import AppKit
            pb = AppKit.NSPasteboard.generalPasteboard()
            pb.clearContents()
            return bool(pb.setString_forType_(str(text or ''), AppKit.NSPasteboardTypeString))
        except Exception as e:
            print(f"[clipboard] NSPasteboard 쓰기 실패: {e}")
            return False

    def select_folder(self):
        """macOS WKWebView에서 NSOpenPanel을 메인 스레드로 열어 선택 경로를 반환한다."""
        if sys.platform != 'darwin':
            return {"status": "unsupported"}
        try:
            import threading
            import AppKit
            from PyObjCTools import AppHelper

            done = threading.Event()
            result = {"status": "cancelled"}

            def _show_panel():
                try:
                    panel = AppKit.NSOpenPanel.openPanel()
                    panel.setCanChooseFiles_(False)
                    panel.setCanChooseDirectories_(True)
                    panel.setAllowsMultipleSelection_(False)
                    panel.setPrompt_("선택")
                    if panel.runModal() == AppKit.NSModalResponseOK:
                        urls = panel.URLs()
                        if urls:
                            result.update({"status": "success", "path": str(urls[0].path())})
                except Exception as exc:
                    result.update({"status": "error", "message": str(exc)})
                finally:
                    done.set()

            AppHelper.callAfter(_show_panel)
            if not done.wait(timeout=120):
                return {"status": "error", "message": "폴더 선택 시간 초과"}
            return result
        except Exception as e:
            print(f"[folder-dialog] NSOpenPanel 실패: {e}")
            return {"status": "error", "message": str(e)}


def _install_mac_edit_menu() -> bool:
    """[맥] 메뉴바 렌더링을 강제해 pywebview의 Edit 메뉴(복사/붙여넣기)를 활성화한다.

    [WHY / 맥포팅 2026-07-22] pywebview는 이미 Edit 메뉴(cut/copy/paste/selectAll, 네이티브
      selector — cocoa.py _add_edit_menu)를 만든다. 그런데 이 앱의 스플래시→load_url 부팅
      흐름에선 메뉴바가 앱 메뉴만 렌더되고 Edit/View가 활성화되지 않아, 채팅 등 일반 HTML
      입력창에서 Cmd+C/V(복사/붙여넣기)가 먹지 않았다(xterm 터미널은 xterm.js가 JS로 자체 처리해
      영향 없음). setMainMenu_로 메인 메뉴를 재지정하면 메뉴바가 재드로우되며 Edit 메뉴의
      키equivalent가 first responder(WKWebView)로 라우팅된다 → 복붙 정상화. 별도 커스텀 메뉴를
      추가하지 않아 'Edit' 중복을 피한다. [제약] NSMenu 조작은 메인스레드 전용 — caller가 메인
      런루프(AppHelper.callAfter)로 디스패치한다.
    """
    try:
        import AppKit
        app = AppKit.NSApplication.sharedApplication()
        main_menu = app.mainMenu()
        if main_menu is None or main_menu.numberOfItems() == 0:
            return False

        # pywebview의 Edit 서브메뉴를 찾아 항상-활성화로 전환.
        # [WHY] macOS 메뉴는 autoenablesItems=YES(기본)면 first responder가 validate 안 하는 항목을
        #   비활성화한다. WKWebView 텍스트 입력 포커스 시 paste:/copy: 검증이 어긋나 메뉴 항목이 회색
        #   처리되면 Cmd+V의 performKeyEquivalent가 매칭돼도 액션이 안 나가 붙여넣기가 실패한다.
        #   autoenablesItems=NO로 두면 항목이 항상 활성 → Cmd+C/V/X가 responder chain(WKWebView)의
        #   copy:/paste:/cut:로 라우팅돼 복붙이 동작한다.
        edit_menu = None
        for i in range(main_menu.numberOfItems()):
            it = main_menu.itemAtIndex_(i)
            sub = it.submenu()
            # [과거사고 2026-07-22] pywebview 6.x _add_edit_menu는 NSMenuItem엔 title을 안 주고
            # 서브메뉴에만 'Edit'을 준다 — 아이템 title만 검사하면 탐색이 항상 실패해 중복 '편집'
            # 메뉴를 만들고, 정작 keyEquivalent(⌘C/⌘V)를 소비하는 진짜 Edit 메뉴는 autoenables
            # 그대로 남아 회색 항목이 키를 삼켰다(전 플랫폼 무반응). 서브메뉴 title도 함께 검사.
            if sub is not None and (it.title() in ('Edit', '편집') or sub.title() in ('Edit', '편집')):
                edit_menu = sub
                break
        if edit_menu is None:
            # pywebview Edit 메뉴가 없으면 직접 생성(네이티브 selector).
            edit_item = AppKit.NSMenuItem.alloc().initWithTitle_action_keyEquivalent_('편집', None, '')
            edit_menu = AppKit.NSMenu.alloc().initWithTitle_('편집')
            for title, sel, key in (('실행 취소', 'undo:', 'z'), ('잘라내기', 'cut:', 'x'),
                                    ('복사', 'copy:', 'c'), ('붙여넣기', 'paste:', 'v'),
                                    ('전체 선택', 'selectAll:', 'a')):
                edit_menu.addItem_(
                    AppKit.NSMenuItem.alloc().initWithTitle_action_keyEquivalent_(title, sel, key))
            edit_item.setSubmenu_(edit_menu)
            main_menu.addItem_(edit_item)
        edit_menu.setAutoenablesItems_(False)  # 복사/붙여넣기 항상 활성화 → Cmd+C/V/X 라우팅
        app.setMainMenu_(main_menu)  # 메뉴바 재드로우 강제
        return True
    except Exception as e:
        print(f"[edit-menu] 맥 Edit 메뉴 설정 실패(무시): {e}")
        return False


def run_gui_app(cfg: BootConfig) -> None:
    """스플래시 창 생성 → 백그라운드 초기화 → 앱 로드 → 종료 정리."""
    # ── GUI 창 먼저 표시 → 콜백에서 전체 초기화 수행 ──────────────────────────
    try:
        import webview
        from infra.win32_icon import force_win32_icon
        from infra import pty_process, daemons

        def _init_and_load_app(window):
            """[v3.7.179] 스플래시 표시 상태에서 PG/PTY/HTTP 전체 초기화 수행 후 앱 로드.
            이전: PG+PTY+HTTP 모두 끝난 후 창 생성 → 5~10초 무반응.
            수정: 창 즉시 표시 → 초기화 진행 → 완료 후 앱 전환."""
            import urllib.request as _ureq

            # ── [맥] WKWebView 입력창 복사/붙여넣기 활성화 — Edit 메뉴 주입(메인스레드 필수) ──
            if sys.platform == 'darwin':
                def _setup_edit_menu():
                    # [WHY] NSMenu 조작은 메인스레드 전용 — pywebview가 쓰는 PyObjCTools.AppHelper의
                    #   callAfter로 메인 런루프에 태워 안전하게 실행. 메뉴바 렌더 안 되는 건 부팅
                    #   시점(스플래시→load_url) 일회성 문제라, 초기 ~20초 동안만 몇 차례 갱신해
                    #   load_url 이후 포커스 시점을 확실히 커버한 뒤 종료한다(무한 갱신 불필요).
                    try:
                        from PyObjCTools import AppHelper
                        for _ in range(10):
                            time.sleep(2)
                            AppHelper.callAfter(_install_mac_edit_menu)
                    except Exception as _e:
                        print(f"[edit-menu] 설치 스레드 오류(무시): {_e}")
                threading.Thread(target=_setup_edit_menu, daemon=True,
                                 name='MacEditMenu').start()

            def _update_splash(msg):
                try:
                    window.evaluate_js(
                        f"document.getElementById('status').textContent='{msg}'"
                    )
                except Exception:
                    pass

            # ── 1단계: PostgreSQL + PTY 병렬 시작 ──
            _update_splash('데이터베이스 시작 중...')
            # [R19] PTY 준비(좀비정리+모듈빌드)를 백그라운드로 — 반환 Event를 3단계에서 wait.
            #   PG 시작과 병렬로 돌아가는 부팅 최적화(v3.7.179) 보존.
            _pty_prep_done = pty_process.prepare_pty_async(cfg.pty_server_state, cfg.base_dir)

            cfg.ensure_postgres_running()
            atexit.register(cfg.cleanup_postgres)

            # ── 2단계: 프로젝트 DB + 스키마 ──
            _update_splash('프로젝트 데이터베이스 초기화 중...')
            cfg.init_project_db(cfg.project_id)
            try:
                import src.pg_store as _pg_mod
                # [WHY] pg_store 분할(2026-06-10) 후 _SCHEMA_READY는 pg_schema 내부
                # 상태 — 모듈 속성 직접 대입은 무효라 reset_schema_cache()로 캡슐화
                _pg_mod.reset_schema_cache()
                _pg_mod.ensure_schema(cfg.data_dir)
            except Exception as e:
                print(f"[PG] 프로젝트 DB 스키마 초기화 실패: {e}")

            # ── 3단계: PTY 서버 시작 ──
            _update_splash('터미널 서버 시작 중...')
            # [R19] 준비 완료 대기 → PTY 서버 기동 → 헬스체크 워치독 시작을 일괄 위임.
            pty_process.start_pty_server_and_watchdog(
                cfg.pty_server_state, cfg.base_dir, cfg.ws_port, cfg.http_port,
                cfg.project_root, cfg.child_procs, _pty_prep_done)

            # [R20] _NODE_PTY_REST_URL 모듈 전역 + pty/agent api 갱신을 setter로 캡슐화.
            cfg.set_node_pty_rest_url(f"http://127.0.0.1:{cfg.ws_port}")

            # ── 4단계: 데몬 스레드 일괄 시작 ──
            _update_splash('서비스 시작 중...')
            threading.Thread(target=cfg.agent_broadcast_worker, daemon=True,
                             name='AgentBroadcast').start()
            cfg.start_fs_watcher(cfg.project_root)
            cfg.memory_watcher_factory(cfg.project_id).start()
            # [회상 v2 즉시 활성] 기동 시 embed 모델을 백그라운드 워밍 — 첫 recall miss 전에도
            #   벡터 회상이 되도록. 논블로킹(0.001s 반환).
            #   [WHY] recall-smart는 미로드면 fallback → 모델이 recall 경로로 안 올라오는
            #   닭-달걀. 데몬만으론 90초 창(+데몬 사망 시 영구) 비활성 → 여기서 선제 워밍.
            #   [R18] 데몬 일괄 기동 직전으로 이동 — backfill 데몬은 내부 90초 대기라 순서 무관.
            try:
                from infra.embed_service import warm_async as _warm_embed
                _warm_embed()
            except Exception:
                pass
            # [R18] 데몬 10종(watchdog/telegram/codex/orchestrator/doc/agent_sync/
            #   zettel_sync·refine/commit/embedding_backfill) 일괄 기동 — start_all_daemons 위임.
            #   env는 여기서 생성(HTTP_PORT 확정 후 = late-binding 계약 충족).
            daemons.start_all_daemons(cfg.daemon_env_factory(),
                                      cfg.agent_status, cfg.agent_status_lock)

            cfg.restore_agent_status()

            # ── 5단계: HTTP 서버 시작 ──
            _update_splash('웹 서버 시작 중...')
            _actual_port = cfg.http_port
            try:
                _srv = cfg.http_server_factory(('127.0.0.1', _actual_port), cfg.handler_cls)
                print(f"[*] Server running on http://localhost:{_actual_port}")
                threading.Thread(target=_srv.serve_forever, daemon=True).start()
                threading.Thread(target=cfg.load_task_logs, daemon=True,
                                 name='ThoughtPreload').start()
                cfg.http_server_ref[0] = _srv
            except OSError as e:
                if 'already in use' in str(e).lower() or '10048' in str(e):
                    print(f"[!] 포트 {_actual_port} 충돌 → 대체 포트 탐색")
                    try:
                        _actual_port = cfg.find_free_port(_actual_port + 10, max_tries=50)
                        _srv = cfg.http_server_factory(('127.0.0.1', _actual_port), cfg.handler_cls)
                        print(f"[*] 대안 포트로 서버 시작: http://localhost:{_actual_port}")
                        threading.Thread(target=_srv.serve_forever, daemon=True).start()
                        threading.Thread(target=cfg.load_task_logs, daemon=True,
                                         name='ThoughtPreload').start()
                        cfg.http_server_ref[0] = _srv
                    except Exception as e2:
                        print(f"[!] 대안 포트에서도 실패: {e2}")
                        return
                else:
                    print(f"[!] Server Start Error: {e}")
                    return

            # ── 6단계: 서버 응답 확인 후 앱 로드 ──
            _update_splash('앱 로딩 중...')
            for _ in range(50):  # 최대 5초
                try:
                    _ureq.urlopen(f'http://127.0.0.1:{_actual_port}/', timeout=0.1)
                    break
                except Exception:
                    time.sleep(0.1)
            window.load_url(f'http://localhost:{_actual_port}')
            print(f"[*] 앱 로드 완료 — http://localhost:{_actual_port}")

        # ── 헤드리스 분기 ────────────────────────────────────────────────────
        # [WHY webview.start()를 안 부르는가] 그 호출이 창을 만들고 이벤트 루프를 잡는다.
        #   데스크톱이 없는 세션에서는 여기서 예외가 나거나 멈춘다. 초기화 본체
        #   (_init_and_load_app)는 창과 무관하므로 직접 호출하고 프로세스만 살려둔다.
        if cfg.headless:
            print('[*] 헤드리스 모드 — GUI 창을 만들지 않습니다.')
            _init_and_load_app(_HeadlessWindow())
            print('[*] 헤드리스 가동 중 — Ctrl+C로 종료.')
            try:
                while True:
                    time.sleep(3600)
            except KeyboardInterrupt:
                print('[*] 종료 신호 — 정리 중...')
            cfg.cleanup_child_procs()
            cfg.cleanup_postgres()
            try:
                if cfg.http_server_ref[0]:
                    cfg.http_server_ref[0].shutdown()
                    cfg.http_server_ref[0].server_close()
            except Exception:
                pass
            try:
                if cfg.lock_sock:
                    cfg.lock_sock.close()
            except Exception:
                pass
            os._exit(0)

        print(f"[*] Launching Desktop Window with Splash...")
        # [WHY] js_api=클립보드 브리지 — 맥 WKWebView의 navigator.clipboard 거부 우회
        #   (lib/clipboard.ts가 window.pywebview.api.clip_read/clip_write로 호출).
        window = webview.create_window(cfg.window_title,
                              html=cfg.splash_html, width=1400, height=900,
                              js_api=_ClipboardBridge())

        threading.Thread(target=force_win32_icon,
                         args=(cfg.official_icon, cfg.window_title),
                         daemon=True).start()

        # ── WebView2 영구 저장소 경로 ──
        # 기본 private_mode=True 는 종료 시 localStorage 전체 삭제 → 프로필/설정 유실
        # %APPDATA%/vibe-coding/<dev|exe>/<프로젝트명>/webview_data 에 영구 저장
        # 개발/EXE 분리: 스키마 차이로 인한 데이터 손상 방지
        _appdata = os.environ.get('APPDATA') or str(Path.home() / 'AppData' / 'Roaming')
        _mode = 'exe' if getattr(sys, 'frozen', False) else 'dev'
        _webview_storage = Path(_appdata) / 'vibe-coding' / _mode / cfg.project_root.name / 'webview_data'
        _webview_storage.mkdir(parents=True, exist_ok=True)
        print(f"[*] WebView2 storage: {_webview_storage}")

        # webview.start() 블로킹 — _init_and_load_app이 별도 스레드에서 전체 초기화 수행
        webview.start(
            _init_and_load_app,
            args=[window],
            private_mode=False,
            storage_path=str(_webview_storage),
        )

        # ── 창 닫힘 → 정리 ──
        print("[*] GUI 창이 닫혔습니다. 모든 자식 프로세스 정리 중...")
        cfg.cleanup_child_procs()
        cfg.cleanup_postgres()
        try:
            if cfg.http_server_ref[0]:
                cfg.http_server_ref[0].shutdown()
                cfg.http_server_ref[0].server_close()
        except Exception:
            pass
        try:
            if cfg.lock_sock:
                cfg.lock_sock.close()
        except Exception:
            pass
        print("[*] 정리 완료 — 프로세스를 종료합니다.")
        os._exit(0)
    except Exception as e:
        print(f"[!] GUI Error: {e}")
        cfg.open_app_window(f"http://localhost:{cfg.http_port}")
        try:
            while True:
                time.sleep(1)
        except KeyboardInterrupt:
            print("[*] Ctrl+C 감지 — 정리 후 종료합니다.")
            cfg.cleanup_child_procs()
            try:
                if cfg.http_server_ref[0]:
                    cfg.http_server_ref[0].shutdown()
                    cfg.http_server_ref[0].server_close()
            except Exception:
                pass
            os._exit(0)
