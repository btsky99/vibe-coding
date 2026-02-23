# 📄 `server.py` 파일 상세 문서

> **버전: v2.6.0 - [Claude] 임베딩 기반 의미 검색 도입 (fastembed + 한국어 다국어 모델)**
> **메인 문서:** [README.md](README.md)

- **원본 파일 경로**: `.ai_monitor/server.py`
- **파일 역할**: 하이브 마인드의 파이썬 백엔드(Backend)로, 프론트엔드 React 클라이언트에 정적 파일, 파일 시스템 접근 API, 실시간 터미널 웹소켓 세션, SSE 로그 스트림 등을 제공합니다.

## 🛠️ 주요 기능 및 최근 개선 사항 (Key Features & Recent Improvements)

1. **임베딩 기반 의미 검색 [v2.6.0]**
   - `fastembed` + `paraphrase-multilingual-MiniLM-L12-v2` 모델 (한국어 포함 50개 언어, PyTorch 불필요)
   - 메모리 저장 시(`/api/memory/set`, `MemoryWatcher._upsert`) 자동으로 float32 벡터 생성 → `embedding BLOB` 컬럼 저장
   - 검색 시(`GET /api/memory?q=`) 코사인 유사도 기반 의미 검색 우선, 임베딩 없는 항목은 키워드 LIKE 폴백
   - `?threshold=0.45` (유사도 최소값), `?top=20` (반환 개수) 파라미터 지원
   - 결과에 `_score` 필드(유사도 0~1)를 포함하여 UI에서 신뢰도 표시 가능
   - 기존 DB 자동 마이그레이션 (`ALTER TABLE memory ADD COLUMN embedding BLOB`)

2. **MemoryWatcher — 에이전트 메모리 자동 동기화 [v2.5.0]**
   - `MemoryWatcher` 백그라운드 스레드가 서버 시작 시 자동으로 실행됩니다.
   - **감시 대상**
     - Claude Code: `~/.claude/projects/*/memory/*.md`
     - Gemini CLI: `~/.gemini/tmp/{프로젝트}/logs.json`, `chats/session-*.json`
   - 15초마다 mtime 폴링 → 변경된 파일만 `shared_memory.db` 에 UPSERT
   - 터미널 번호(T1, T2…)는 최초 감지 순서로 자동 부여 (`author: claude-code:terminal-1` 등)
   - 에이전트 추가 토큰 소모 없이 자연스러운 메모리 저장 → 하이브 공유 메모리 자동 반영
   - Nexus View UI의 메모리 패널에서 "1번 터미널: MCP UI 작업 중" 형태로 확인 가능

2. **MCP 관리자 API 추가 [v2.4.0]**
   - `GET /api/mcp/catalog` — 8개의 큐레이션된 MCP 서버 목록 반환 (context7, github, memory, fetch, playwright, sequential-thinking, sqlite, brave-search)
   - `GET /api/mcp/installed?tool=claude|gemini&scope=global|project` — 지정한 설정 파일의 `mcpServers` 키 목록 반환
   - `POST /api/mcp/install` — `mcpServers`에 엔트리 추가 (환경변수 필요 시 플레이스홀더 삽입)
   - `POST /api/mcp/uninstall` — `mcpServers`에서 해당 키 삭제
   - `_mcp_config_path(tool, scope)` 헬퍼로 Claude/Gemini × Global/Project 4가지 경로를 관리

2. **실행 안정성 강화 및 버그 수정 [v2.3.1]**
   - **import 구조 전면 최적화**: 함수 내부에 흩어져 있던 지역 `import` 문들을 파일 상단으로 통합하여, 특정 API 호출 시 발생하던 `UnboundLocalError`를 근본적으로 해결했습니다.
   - **pywebview 6.1 API 준수**: `create_window()`에서 지원하지 않는 `icon` 인자를 제거하고 `webview.start(icon=...)` 단계로 이동시켜 실행 시 발생하는 `TypeError`를 해결했습니다.
   - **Windows 인코딩(CP949) 호환성 확보**: `subprocess.run` 호출 시 `encoding='utf-8'`을 명시하여, 한글 경로 또는 Git 로그 출력 시 발생하던 `UnicodeDecodeError`를 방지했습니다.

2. **에이전트 작업 충돌 방지 (Lock System)**
...
   - 락 획득/해제 시 `task_logs.jsonl`에 자동으로 이벤트를 로깅하여 넥서스 뷰 대시보드에 실시간 표시합니다.

2. **배포 버전(Frozen EXE) 안정성 및 디버깅 지원 [NEW]**
   - **자가 진단 에러 로그**: `--noconsole` 모드에서 실행 시 에러가 발생하면 `data/server_error.log` 파일에 모든 트레이스백을 자동으로 기록하여 크래시 원인을 분석할 수 있게 합니다.
   - **빌드 구조 개선**: PyInstaller 빌드 시 `src` 폴더를 명시적으로 포함하여 임포트 오류를 원천 차단했습니다.
   - **콘솔 모드 제공**: `vibe-coding_console.exe`를 통해 서버의 모든 동작 로그를 실시간으로 확인하며 디버깅할 수 있는 환경을 별도로 제공합니다.

3. **정적 파일 서비스 및 라우팅**
...
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
