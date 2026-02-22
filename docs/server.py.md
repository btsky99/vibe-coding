# 📄 `server.py` 파일 상세 문서

- **원본 파일 경로**: `.ai_monitor/server.py`
- **파일 역할**: 하이브 마인드의 파이썬 백엔드(Backend)로, 프론트엔드 React 클라이언트에 정적 파일, 파일 시스템 접근 API, 실시간 터미널 웹소켓 세션, SSE 로그 스트림 등을 제공합니다.

## 🛠️ 주요 기능 (Key Features)

1. **정적 파일 서비스 및 라우팅**
   - PyInstaller로 빌드될 경우(frozen)와 스크립트로 직접 실행될 경우(dev) 모두에 대비해 `STATIC_DIR`을 동적으로 찾습니다.
   - Vite로 빌드된 프론트엔드 정적 파일(`nexus-view/dist/*`)을 서빙하며, 알 수 없는 경로는 `index.html`로 폴백(Fallback)시킵니다.

2. **좀비 방지 하트비트 스레드 (Graceful Shutdown Monitor)**
   - 백그라운드 스레드 `monitor_heartbeat()`가 계속 돌면서, 클라이언트(브라우저 창)가 `/api/heartbeat` 호출을 15초 이상 멈췄을 때 즉시 `os._exit(0)`를 호출하여 서버를 깔끔하게 스스로 죽이는(자폭) 역할을 수행합니다.

3. **REST API 엔드포인트 (`SSEHandler`)**
   - `/api/files`, `/api/drives`: 사용자의 파일 시스템 드라이브와 폴더 구조를 JSON 형식으로 내려줍니다.
   - `/api/read-file`: 사용자가 특정 파일을 클릭했을 때 UTF-8 문자열로 읽어서 프론트엔드에 전달합니다. (퀵 뷰 및 활성 뷰어에 사용됨).
   - `/api/shutdown`: 사용자가 고의로 강제 종료 버튼을 눌렀을 때 작동하는 명시적인 종료 호출입니다.
   - `/api/install-skills`, `/api/install-gemini-cli`: 시스템/프로젝트 내부로 필요한 툴을 자동 다운로드/설치/복사합니다.

4. **웹소켓(WebSocket) 기반 PTY 통신**
   - 8001번 포트(또는 동적 할당 포트)에서 비동기 `websockets` 서버가 열려, 프론트엔드의 각 터미널 슬롯(`xterm.js`)과 PTY 세션(cmd.exe / bash)을 1:1로 묶어줍니다.
   - `winpty` 모듈을 이용하여 윈도우 환경에서도 터미널 텍스트/ANSI 코드가 깨지지 않고 안전하게 스트리밍되게 처리합니다.

5. **SSE(Server-Sent Events) 스트리밍**
   - 하이브 마인드 에이전트들이 기록한 작업 로그(`sessions.jsonl`) 파일을 0.5초마다 지속적으로 감시(`stat().st_size`)하여, 파일에 새로운 줄이 생기면 곧장 `/stream` 주소로 프론트엔드에 라이브로 쏴줍니다.

6. **크롬 앱 모드(App Mode) 윈도우 팝업**
   - 백그라운드 서버가 구동될 때 `open_app_window()` 함수를 호출하여 브라우저 주소창이나 탭이 없는 깔끔한 데스크톱 앱처럼 크롬(또는 엣지)을 띄웁니다.
