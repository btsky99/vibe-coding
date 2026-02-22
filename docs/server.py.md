# 📄 `server.py` 파일 상세 문서

> **버전: v2.2.0 - [Gemini] PyWebView 네이티브 데스크탑 앱 래핑 적용**
> **메인 문서:** [README.md](README.md)

- **원본 파일 경로**: `.ai_monitor/server.py`
- **파일 역할**: 하이브 마인드의 파이썬 백엔드(Backend)로, 프론트엔드 React 클라이언트에 정적 파일, 파일 시스템 접근 API, 실시간 터미널 웹소켓 세션, SSE 로그 스트림 등을 제공합니다.

## 🛠️ 주요 기능 (Key Features)

1. **에이전트 작업 충돌 방지 (Lock System) [NEW]**
   - **`/api/locks` (GET/POST)**: 여러 에이전트(Gemini, Claude 등)가 동시에 같은 파일을 수정하여 발생하는 충돌을 방지합니다.
   - 특정 파일에 대해 어떤 에이전트가 작업 중인지 기록하고, 다른 에이전트가 락을 시도할 경우 `conflict` 상태를 반환합니다.
   - 락 획득/해제 시 `task_logs.jsonl`에 자동으로 이벤트를 로깅하여 넥서스 뷰 대시보드에 실시간 표시합니다.

2. **정적 파일 서비스 및 라우팅**
   - PyInstaller로 빌드될 경우(frozen)와 스크립트로 직접 실행될 경우(dev) 모두에 대비해 `STATIC_DIR`을 동적으로 찾습니다.
   - Vite로 빌드된 프론트엔드 정적 파일(`nexus-view/dist/*`)을 서빙하며, 알 수 없는 경로는 `index.html`로 폴백(Fallback)시킵니다.

3. **좀비 방지 하트비트 스레드 (Graceful Shutdown Monitor)**
   - 백그라운드 스레드 `monitor_heartbeat()`가 계속 돌면서, 클라이언트(브라우저 창)가 `/api/heartbeat` 호출을 15초 이상 멈췄을 때 즉시 `os._exit(0)`를 호출하여 서버를 깔끔하게 스스로 죽이는(자폭) 역할을 수행합니다.

4. **REST API 엔드포인트 (`SSEHandler`)**
   - `/api/files`, `/api/drives`: 사용자의 파일 시스템 드라이브와 폴더 구조를 JSON 형식으로 내려줍니다.
   - `/api/read-file`: 사용자가 특정 파일을 클릭했을 때 UTF-8 문자열로 읽어서 프론트엔드에 전달합니다. (퀵 뷰 및 활성 뷰어에 사용됨).
   - `/api/shutdown`: 사용자가 고의로 강제 종료 버튼을 눌렀을 때 작동하는 명시적인 종료 호출입니다.
   - `/api/install-skills`, `/api/install-gemini-cli`: 시스템/프로젝트 내부로 필요한 툴을 자동 다운로드/설치/복사합니다.

5. **웹소켓(WebSocket) 기반 PTY 통신**
   - 8001번 포트(또는 동적 할당 포트)에서 비동기 `websockets` 서버가 열려, 프론트엔드의 각 터미널 슬롯(`xterm.js`)과 PTY 세션(cmd.exe / bash)을 1:1로 묶어줍니다.
   - `winpty` 모듈을 이용하여 윈도우 환경에서도 터미널 텍스트/ANSI 코드가 깨지지 않고 안전하게 스트리밍되게 처리합니다.

6. **SSE(Server-Sent Events) 스트리밍**
   - 하이브 마인드 에이전트들이 기록한 작업 로그(`sessions.jsonl`) 파일을 0.5초마다 지속적으로 감시(`stat().st_size`)하여, 파일에 새로운 줄이 생기면 곧장 `/stream` 주소로 프론트엔드에 라이브로 쏴줍니다.

7. **PyWebView 네이티브 데스크탑 앱 래핑 [NEW]**
   - 기존 크롬(Chrome) 브라우저의 App Mode에 의존하던 방식을 탈피하여, `pywebview` 라이브러리를 활용한 완전한 네이티브 OS 데스크탑 윈도우 창으로 실행됩니다.
   - 백그라운드 서버 구동과 동시에 WebView2 (Edge Chromium 기반) 또는 기본 OS 웹뷰가 뜨면서 프론트엔드를 감싸며, 윈도우를 닫으면 내부적으로 하트비트 스레드가 서버를 종료합니다.
