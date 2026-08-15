---
title: 터미널과 PTY
type: 시스템
sources:
  - .ai_monitor/api/pty_api.py:31
  - .ai_monitor/infra/app_boot.py:1
  - .ai_monitor/infra/app_boot.py:71
  - .ai_monitor/infra/app_boot.py:79
  - .ai_monitor/infra/app_boot.py:93
  - .ai_monitor/infra/app_boot.py:165
  - .ai_monitor/infra/app_boot.py:183
  - .ai_monitor/infra/app_boot.py:236
  - .ai_monitor/infra/app_boot.py:272
  - .ai_monitor/infra/app_boot.py:295
  - .ai_monitor/infra/app_boot.py:352
  - .ai_monitor/infra/app_boot.py:381
  - .ai_monitor/infra/pty_process.py:27
  - .ai_monitor/infra/pty_process.py:32
  - .ai_monitor/infra/pty_process.py:132
  - .ai_monitor/infra/pty_process.py:277
  - .ai_monitor/infra/pty_process.py:411
  - .ai_monitor/infra/pty_process.py:434
  - .ai_monitor/vibe-view/src/components/TerminalSlot.tsx:166
  - .ai_monitor/vibe-view/src/components/TerminalSlot.tsx:172
  # …외 18건 (본문 각 항목에 경로 표기)
related: []
confidence: high
updated: 2026-08-15
---

# 터미널과 PTY

## 한 줄

슬롯 포트는 런타임에 정해져 import 시점 상수가 될 수 없다. 소비자가

> 자동 합성 (코드 주석 38건 · 파일 5개 · 추출 b28ef16).
> 🔴 **여기를 고치기 전에** 원본(주석 또는 사고 장부)을 먼저 고칠 것 — 다음 빌드에 덮어써진다.

## 코드에 박힌 지식

## `.ai_monitor/api/pty_api.py`

### get_pty_rest_url `[WHY]`

현재 Node PTY REST URL. 아직 주입 전이면 빈 문자열.
[WHY 게터인가] 슬롯 포트는 런타임에 정해져 import 시점 상수가 될 수 없다. 소비자가
모듈 전역을 직접 읽으면 import 시점 값(None)이 박히므로 반드시 호출 시점에 읽는다.

출처: `.ai_monitor/api/pty_api.py:31`

## `.ai_monitor/infra/app_boot.py`

### 모듈 상단 `[불변식]` `[제약]`

백그라운드 콜백(_init_and_load_app)에서 PG/PTY/HTTP/데몬을 순차 초기화한
뒤 앱을 로드한다. 창 종료 시 자식 프로세스/PG/HTTP/락을 정리한다.
server.py main()의 GUI try 블록 전체를 이관 — 부팅에 필요한 server.py 고유
함수/객체/값은 BootConfig로 명시 주입받는다(R20).
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

출처: `.ai_monitor/infra/app_boot.py:1`

### BootConfig `[WHY]`

[헤드리스 2026-07-29] 창 없이 서버·데몬만 띄운다. 기본값이 있어 기존 호출부 무영향.
[WHY 필요한가] SSH 세션에는 데스크톱(윈도우 스테이션)이 없어 WebView2 창 생성이 실패한다.
실측: 원격 상주 노드에서 앱을 띄우면 PostgreSQL·데몬까지는 뜨는데 창 단계에서 죽어
HTTP 서버(9000번대)가 끝내 안 올라온다 → 원격에서 상태를 볼 수단이 사라진다.

출처: `.ai_monitor/infra/app_boot.py:71`

### _HeadlessWindow `[제약]`

pywebview 창 대역 — _init_and_load_app이 쓰는 두 메서드만 흉내 낸다.
[제약] 창 객체에서 실제로 쓰이는 것은 evaluate_js(스플래시 문구)와 load_url뿐이다.
더 붙이면 진짜 창과의 계약이 벌어져 유지보수가 어려워지므로 의도적으로 최소만 구현한다.

출처: `.ai_monitor/infra/app_boot.py:79`

### _ClipboardBridge `[WHY]` `[제약]`

pywebview js_api — 프론트가 window.pywebview.api.clip_read/clip_write로 호출.
[WHY / 맥포팅 2026-07-22] 맥 WKWebView는 async Clipboard API의 권한 프롬프트를 구현하지 않아
navigator.clipboard.readText가 NotAllowedError로 조용히 거부됨(윈도우 WebView2는 허용) →
우클릭 메뉴 복사/붙여넣기가 맥에서만 전멸. NSPasteboard 직접 접근으로 우회한다.
[제약] js_api 호출은 pywebview 워커 스레드에서 실행됨 — NSPasteboard는 XPC 기반이라
오프메인 호출이 실무상 안전. 비-맥 플랫폼은 None/False 반환 → 프론트(lib/clipboard.ts)가
navigator.clipboard로 폴백(윈도우는 그걸로 충분).

출처: `.ai_monitor/infra/app_boot.py:93`

### _install_mac_edit_menu `[WHY]` `[제약]`

[맥] 메뉴바 렌더링을 강제해 pywebview의 Edit 메뉴(복사/붙여넣기)를 활성화한다.
[WHY / 맥포팅 2026-07-22] pywebview는 이미 Edit 메뉴(cut/copy/paste/selectAll, 네이티브
selector — cocoa.py _add_edit_menu)를 만든다. 그런데 이 앱의 스플래시→load_url 부팅
흐름에선 메뉴바가 앱 메뉴만 렌더되고 Edit/View가 활성화되지 않아, 채팅 등 일반 HTML
입력창에서 Cmd+C/V(복사/붙여넣기)가 먹지 않았다(xterm 터미널은 xterm.js가 JS로 자체 처리해
영향 없음). setMainMenu_로 메인 메뉴를 재지정하면 메뉴바가 재드로우되며 Edit 메뉴의
키equivalent가 first responder(WKWebView)로 라우팅된다 → 복붙 정상화. 별도 커스텀 메뉴를
추가하지 않아 'Edit' 중복을 피한다. [제약] NSMenu 조작은 메인스레드 전용 — caller가 메인
런루프(AppHelper.callAfter)로 디스패치한다.

출처: `.ai_monitor/infra/app_boot.py:165`

### _install_mac_edit_menu `[WHY]`

pywebview의 Edit 서브메뉴를 찾아 항상-활성화로 전환.
[WHY] macOS 메뉴는 autoenablesItems=YES(기본)면 first responder가 validate 안 하는 항목을
비활성화한다. WKWebView 텍스트 입력 포커스 시 paste:/copy: 검증이 어긋나 메뉴 항목이 회색
처리되면 Cmd+V의 performKeyEquivalent가 매칭돼도 액션이 안 나가 붙여넣기가 실패한다.
autoenablesItems=NO로 두면 항목이 항상 활성 → Cmd+C/V/X가 responder chain(WKWebView)의
copy:/paste:/cut:로 라우팅돼 복붙이 동작한다.

출처: `.ai_monitor/infra/app_boot.py:183`

### _setup_edit_menu `[WHY]`

[WHY] NSMenu 조작은 메인스레드 전용 — pywebview가 쓰는 PyObjCTools.AppHelper의
callAfter로 메인 런루프에 태워 안전하게 실행. 메뉴바 렌더 안 되는 건 부팅
시점(스플래시→load_url) 일회성 문제라, 초기 ~20초 동안만 몇 차례 갱신해
load_url 이후 포커스 시점을 확실히 커버한 뒤 종료한다(무한 갱신 불필요).

출처: `.ai_monitor/infra/app_boot.py:236`

### _update_splash `[WHY]`

[WHY] pg_store 분할(2026-06-10) 후 _SCHEMA_READY는 pg_schema 내부
상태 — 모듈 속성 직접 대입은 무효라 reset_schema_cache()로 캡슐화

출처: `.ai_monitor/infra/app_boot.py:272`

### _init_and_load_app `[WHY]`

[회상 v2 즉시 활성] 기동 시 embed 모델을 백그라운드 워밍 — 첫 recall miss 전에도
벡터 회상이 되도록. 논블로킹(0.001s 반환).
[WHY] recall-smart는 미로드면 fallback → 모델이 recall 경로로 안 올라오는
닭-달걀. 데몬만으론 90초 창(+데몬 사망 시 영구) 비활성 → 여기서 선제 워밍.
[R18] 데몬 일괄 기동 직전으로 이동 — backfill 데몬은 내부 90초 대기라 순서 무관.

출처: `.ai_monitor/infra/app_boot.py:295`

### run_gui_app `[WHY]`

── 헤드리스 분기 ────────────────────────────────────────────────────
[WHY webview.start()를 안 부르는가] 그 호출이 창을 만들고 이벤트 루프를 잡는다.
데스크톱이 없는 세션에서는 여기서 예외가 나거나 멈춘다. 초기화 본체
(_init_and_load_app)는 창과 무관하므로 직접 호출하고 프로세스만 살려둔다.

출처: `.ai_monitor/infra/app_boot.py:352`

### run_gui_app `[WHY]`

[WHY] js_api=클립보드 브리지 — 맥 WKWebView의 navigator.clipboard 거부 우회
(lib/clipboard.ts가 window.pywebview.api.clip_read/clip_write로 호출).

출처: `.ai_monitor/infra/app_boot.py:381`

## `.ai_monitor/infra/pty_process.py`

### 모듈 상단 `[주의]`

[주의] pty_server_state['proc']는 dict 키라 모듈 proc과 무관. 단, 지역변수/파라미터로
proc을 쓰던 함수(start_node_pty_server, _kill_pty_proc)는 child로 rename해 충돌 회피.

출처: `.ai_monitor/infra/pty_process.py:27`

### get_node_pty_sessions `[주의]`

Node PTY 서버에서 세션 정보를 REST로 조회합니다.
[주의] rest_url은 call-time에 caller(server.py 모듈 전역 _NODE_PTY_REST_URL)가
넘긴 값을 그대로 사용한다 — 원본이 모듈 전역을 호출 시점에 읽던 의미를 보존.

출처: `.ai_monitor/infra/pty_process.py:32`

### kill_runtime_mei_orphans `[WHY]` `[제약]`

고정 runtime_tmpdir(%APPDATA%\\VibeCoding\\runtime) 하위 _MEI* 추출 폴더에서
실행 중인 node.exe(PTY 서버 등)를 강제 종료하고, 종료한 PID 목록을 반환한다.
[WHY / 과거사고 v3.7.244] onefile 부트로더는 Python 코드보다 **먼저** python DLL을
로드한다. 업데이트 시 updater.apply_update_from_temp의 os._exit(0)가 atexit 정리를
통째로 건너뛰어, 이전 인스턴스의 node PTY 서버가 좀비로 남아 자기 _MEI\\pty-server를
잠근다. 다음(새 EXE) 부팅의 부트로더가 잠긴 잔여 _MEI와 충돌 → python DLL 부분 추출 →
"Failed to load Python DLL. LoadLibrary: 지정된 모듈을 찾을 수 없습니다" 부팅 실패 +
"Failed to remove temporary directory" 경고. 부트로더 단계라 앱 내부 정리로는 못 막으므로,
*이전 프로세스(updater 또는 정상 종료 경로)가 새 EXE 기동 전에 반드시 호출**해야 한다.
[제약/불변식] node.exe의 ExecutablePath가 runtime_dir 하위인 것만 대상 → 개발 인스턴스
(node가 프로젝트 node_modules/pty-server에서 실행)나 무관한 node는 절대 건드리지 않음.
exclude_mei가 주어지면 그 _MEI(현재 실행 인스턴스) 소속 node는 보호.
[only_orphans 모드 — 다중 인스턴스 보호] True면 node의 **부모(vibe-coding.exe)가
살아있는 경우 보호**하고, 부모가 죽은 진짜 좀비만 죽인다. 정상 종료/시작 경로에서 사용 —
동시에 켜둔 다른 설치 인스턴스의 살아있는 PTY 서버를 몰살하던 v3.7.122 사고 재발 방지.
False(업데이터)면 install 전체를 교체 중이므로 부모 생사 무관하게 모두 정리(자기 것 포함).
[플랫폼] wmic 의존(기존 kill_orphan_pty_servers와 동일 패턴). Win11 24H2+에서 wmic가
제거되면 이 함수는 조용히 no-op(전체 try/except) — 그 경우 CIM(Get-CimInstance Win32_Process)
전환 필요. 실패해도 기존 동작보다 나빠지지 않음(정리를 안 할 뿐).
[보존] subprocess.call(아래 taskkill)은 헬퍼 미제공이라 미변환 → _no_window 유지 필수.

출처: `.ai_monitor/infra/pty_process.py:132`

### start_node_pty_server `[불변식]`

PTY 서버를 시작하고 프로세스 핸들을 반환합니다.
[불변식] pty_server_state는 caller가 주입한 동일 dict를 그대로 변형한다 —
워치독(pty_watchdog_loop)이 동일 객체의 ['proc']를 읽어 프로세스 사망을
감지하므로, 여기서 새 dict를 만들면 워치독이 죽은 proc을 못 잡는다.

출처: `.ai_monitor/infra/pty_process.py:277`

### prepare_pty_async `[WHY]`

PTY 준비(좀비 정리 + node_modules 빌드)를 백그라운드로 시작하고 완료 Event 반환.
[WHY] PG 시작과 병렬로 돌려 부팅 체감 지연을 줄이는 최적화(v3.7.179) — caller는
이 Event를 3단계에서 wait 한 뒤 PTY 서버를 띄운다. 반환된 Event 계약을 지켜야
PG-PTY 병렬성이 보존된다.

출처: `.ai_monitor/infra/pty_process.py:411`

### start_pty_server_and_watchdog `[불변식]`

PTY 준비 완료를 기다린 뒤 PTY 서버를 띄우고 헬스체크 워치독을 시작한다.
server.py main() 내부 nested 래퍼(_pty_health_check/_kill_pty_proc/_pty_watchdog_loop)를
이관 — WS_PORT/_child_procs 캡처를 ws_port/child_procs 인자로 치환(R19).
[불변식] pty_server_state(가변 dict)는 start와 watchdog이 동일 객체를 공유해야
프로세스 사망 감지가 성립 — 재생성 금지, caller 주입 dict를 그대로 변형한다.

출처: `.ai_monitor/infra/pty_process.py:434`

## `.ai_monitor/vibe-view/src/components/TerminalSlot.tsx`

### 모듈 상단 `[WHY]`

터미널 우클릭 컨텍스트 메뉴 위치 + 복사 대상 텍스트 스냅샷
[WHY] hasSelection 불리언 대신 텍스트 자체를 담는다 — 메뉴가 뜬 뒤 클릭 시점에
getSelection()을 다시 읽으면 TUI의 DSR 응답으로 선택이 이미 지워져 빈 문자열이 복사되는 사고 방지.
mouseTracking: TUI가 마우스 리포팅(DECSET 1000/1006)을 켜면 드래그가 로컬 선택을 못 만듦 —
이때 복사 비활성 사유를 메뉴에 안내하기 위한 플래그 (2026-07-04 사고: 복사 버튼 미표시 재발)

출처: `.ai_monitor/vibe-view/src/components/TerminalSlot.tsx:166`

### 모듈 상단 `[WHY]`

[WHY] 아래 명령어 전송 textarea는 xterm과 별개다. 맥 PyWebView(WKWebView) 백엔드는 편집 입력창에
기본 우클릭 복사/붙여넣기 메뉴를 제공하지 않아(자동완성 항목만 뜸) — textarea 전용 커스텀 메뉴로 보완.
윈도우 WebView2에선 기본 메뉴가 떠서 안 보이던 차이가 맥 대응 후 드러난 문제.

출처: `.ai_monitor/vibe-view/src/components/TerminalSlot.tsx:172`

### 모듈 상단 `[WHY]`

[WHY] xterm은 onUserInput마다 선택을 지운다(TUI 자동 응답 포함) — 우클릭 시점에 선택이
사라져 있어도 복사가 가능하도록 마지막 비어있지 않은 선택 텍스트를 캐시.

출처: `.ai_monitor/vibe-view/src/components/TerminalSlot.tsx:177`

### 모듈 상단 `[WHY]`

[WHY] 하이라이트 유지용 — TUI(claude)가 DSR 자동응답을 userInput으로 집계해 선택을 만들자마자
지운다(복사는 캐시로 되지만 파란 영역이 순식간에 사라짐). getSelectionPosition의 버퍼 절대 좌표를
저장해 두었다가 spurious clear가 오면 select()로 즉시 재적용해 시각적 선택을 유지한다.

출처: `.ai_monitor/vibe-view/src/components/TerminalSlot.tsx:184`

### 모듈 상단 `[불변식]`

[불변식] 사용자가 새 좌클릭/복사로 의도적으로 선택을 지운 경우에만 true — 이때는 복원하지 않는다.
TUI의 자동 clear(userClearedSelRef=false)와 사용자 clear를 구분하는 유일한 신호.

출처: `.ai_monitor/vibe-view/src/components/TerminalSlot.tsx:188`

### connectPath `[제약]`

키보드 복붙 단축키 — 맥 ⌘C/⌘V, 윈도우 Ctrl+Shift+C/V (플랫폼 분기는 헬퍼 내부).
[제약] term.textarea는 open() 이후에만 존재 → 반드시 이 위치에서 호출.

출처: `.ai_monitor/vibe-view/src/components/TerminalSlot.tsx:336`

### connectPath `[제약]`

텍스트 드래그(선택) 시 자동 클립보드 복사 + 마지막 선택 캐시 + 하이라이트 유지 복원.
[제약] 선택 해제 이벤트에서도 발화하므로 hasSelection 가드 필수 — 캐시를 빈 값으로 덮지 않는다.

출처: `.ai_monitor/vibe-view/src/components/TerminalSlot.tsx:342`

### dragSelectHandler `[불변식]`

[불변식] 합성 이벤트는 shiftKey=true라 각 핸들러 첫 가드에서 return → 무한 재귀 없음.
드래그가 터미널 밖으로 나가도 추적되도록 document capture에 세션 리스너를 건다.

출처: `.ai_monitor/vibe-view/src/components/TerminalSlot.tsx:404`

### connectPath `[WHY]`

터미널 우클릭: 컨텍스트 메뉴 표시 — 복사 대상 텍스트를 이 시점에 스냅샷
[WHY] 라이브 선택이 TUI DSR 응답으로 이미 지워졌으면 캐시(lastSelectionRef)로 폴백 —
"드래그 → 우클릭했는데 복사 버튼이 없다" 사고(2026-07-03) 방지.

출처: `.ai_monitor/vibe-view/src/components/TerminalSlot.tsx:433`

### ctxHandler `[WHY]`

[WHY] enable-mouse-events 클래스 = TUI가 마우스 리포팅 중 — 일반 드래그로는 선택이
아예 생성되지 않는다(onSelectionChange 미발화). Shift+드래그만 로컬 선택 허용.

출처: `.ai_monitor/vibe-view/src/components/TerminalSlot.tsx:439`

### 모듈 상단 `[불변식]`

[슬롯별 프로젝트] 이 슬롯의 프로젝트 폴더 지정. 실행 중이면 재시작 확인 후 새 cwd로 재연결.
[불변식] PTY cwd는 spawn 시 고정 → 살아있는 터미널의 프로젝트는 재시작 없이 못 바꾼다.
재연결 시 launchAgent에 next를 명시 주입 — onPickProject 직후 effectivePath는 아직 옛 값(stale).

출처: `.ai_monitor/vibe-view/src/components/TerminalSlot.tsx:623`

### next `[불변식]`

[불변식] 재시작은 xterm dispose + 새 PTY spawn = 스크롤백 전량 소실. 사용자에게 명시.

출처: `.ai_monitor/vibe-view/src/components/TerminalSlot.tsx:635`

### 모듈 상단 `[제약]`

[음성] 이 슬롯을 음성 대상 후보로 등록한다.
[🔴 등록만 하고 마이크를 열지 않는다] 마이크는 앱 전체에 하나뿐이고(lib/voiceBus),
여는 시점은 사용자가 VoiceBar 를 누를 때다. 슬롯마다 열면 장치 경합으로 전부 죽는다.
[제약] 받아쓴 문장은 입력창을 거쳐 handleSend 로 간다 — 손으로 친 것과 같은 경로다.
별도 전송 경로를 만들면 오류 처리·IME 보정 같은 기존 방어가 음성에만 빠진다.

출처: `.ai_monitor/vibe-view/src/components/TerminalSlot.tsx:664`

### ringClass `[WHY]`

[WHY] 기본 메뉴(맥 WKWebView는 자동완성만 노출) 차단 후 커스텀 메뉴 오픈.
선택 여부를 이 시점에 스냅샷 — 메뉴 클릭 시 selectionStart/End는 유지되지만
포커스가 흔들려 빈 선택으로 읽히는 경우를 대비해 hasSel을 미리 저장.

출처: `.ai_monitor/vibe-view/src/components/TerminalSlot.tsx:857`

### ringClass `[WHY]`

[WHY] 클릭 시점 getSelection() 재조회 금지 — 메뉴가 떠 있는 사이 TUI 응답으로
선택이 지워지면 빈 문자열이 복사됨. 메뉴 오픈 시점 스냅샷(selText)을 사용.

출처: `.ai_monitor/vibe-view/src/components/TerminalSlot.tsx:931`

### ringClass `[WHY]`

[WHY] ws.send 직송 금지 — bracketed paste 모드를 우회해 TUI(claude CLI)에서
멀티라인 붙여넣기가 줄 단위로 즉시 실행됨. term.paste()는 onData 경유로
\x1b[200~ 래핑을 적용한 뒤 같은 ws로 흘러간다.

출처: `.ai_monitor/vibe-view/src/components/TerminalSlot.tsx:955`

### ringClass `[WHY]`

[WHY] 무음 실패 금지 — WebView2 클립보드 읽기 권한 거부 시 사용자가 원인을
알 수 없던 사고(2026-07-04). 로컬 표시 전용 write라 pty로는 전송되지 않는다.

출처: `.ai_monitor/vibe-view/src/components/TerminalSlot.tsx:961`

## `.ai_monitor/vibe-view/src/components/terminal/xtermSelection.ts`

### 모듈 상단 `[WHY]`

[WHY] navigator.platform은 deprecated지만 WKWebView/WebView2 양쪽에서 여전히 유효.
userAgent 폴백 병행 — 맥 판정이 틀리면 ⌘ 단축키가 통째로 죽으므로 이중 검사.

출처: `.ai_monitor/vibe-view/src/components/terminal/xtermSelection.ts:16`

### 모듈 상단 `[WHY]` `[불변식]`

[WHY] 터미널 키보드 복붙 단축키 설치 — 맥/윈도우 관례가 달라서 플랫폼 분기 필수.
맥: ⌘C 복사 / ⌘V 붙여넣기 (Ctrl+C는 SIGINT라 건드리지 않음)
윈도우/리눅스: Ctrl+Shift+C 복사 / Ctrl+Shift+V 붙여넣기 (터미널 표준 관례).
일반 Ctrl+V는 WebView2가 네이티브 paste 이벤트를 쏴줘서 이미 동작 — 개입하면 이중 붙여넣기.
[맥 WKWebView 함정 — 이 함수가 존재하는 이유]
1) xterm 선택은 캔버스 오버레이(DOM 선택 아님) → 네이티브 Edit 메뉴의 copy:가 빈 값을 복사.
→ document 'copy' 이벤트를 가로채 clipboardData에 터미널 선택/캐시를 직접 주입.
2) Edit 메뉴가 keyEquivalent를 소비하면 keydown이 JS에 안 오고, 메뉴가 죽어 있으면 keydown만 온다.
두 경로가 상호배타적이지 않은 환경(브라우저 dev 모드 등)이 있어 붙여넣기는 이중 실행 위험 —
keydown 경로를 140ms 지연 실행하고, 네이티브 paste 이벤트가 먼저 도착하면 지연분을 취소해 단일화.
[불변식] 붙여넣기는 반드시 term.paste() 경유 — ws.send 직송은 bracketed paste 모드를 우회해
TUI(claude CLI)에서 멀티라인 붙여넣기가 줄 단위로 즉시 실행되는 사고로 이어진다.

출처: `.ai_monitor/vibe-view/src/components/terminal/xtermSelection.ts:26`

### 모듈 상단 `[WHY]`

[WHY] 현재 선택을 나중에 term.select()로 재적용하기 위한 좌표 스냅샷.
getSelectionPosition은 버퍼 절대 좌표(0-based col, 스크롤백 포함 row)를 주고, start/end가
역방향(위로 드래그)일 수 있어 읽기 순서로 정규화한다. len = (행 차 × cols) + 열 차 —
select()가 length를 cols에서 wrap시키는 규칙의 역산이라 멀티라인 선택도 한 번에 복원된다.

출처: `.ai_monitor/vibe-view/src/components/terminal/xtermSelection.ts:94`

## 확인법

```bash
python scripts/wiki_lint.py        # 이 페이지의 출처가 아직 살아 있는지
python scripts/wiki_build.py       # 원본 주석 변경분 재합성
```

<!-- tags: WHY, 불변식, 제약, 주의 -->
