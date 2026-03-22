<!--
FILE: ai_monitor_plan.md
DESCRIPTION: 프로젝트 전체 보안/성능/품질 고도화 + 멀티-LLM 자율 협업 로드맵
REVISION HISTORY:
- 2026-03-22 Gemini: P7 코덱스 가이드 및 CLI 강화 완료
- 2026-03-18 Claude: P5 cmux 기반 vibe CLI + 알림 시스템 고도화 계획 추가
- 2026-03-17 Claude: P4 멀티-LLM 자율 협업 시스템 구축 계획 추가
- 2026-03-16 Claude: P0 보안 5건 + P1 성능/안정성 5건 전부 완료
- 2026-03-16 Claude: P0 보안 + P1 성능/안정성 + P2 코드품질 고도화 계획 수립
-->

# 📋 프로젝트 보안/성능/품질 고도화 + 자율 협업 (v3.7.82)

**작성일:** 2026-03-17
**목표:** P0~P3 완료 → P4 멀티-LLM 자율 협업 시스템 구축

---

## 🔴 P0: 보안 수정 (Critical) — ✅ 전부 완료

[x] Task 1: SQL 인젝션 수정 — server.py parameterized query 전환
[x] Task 2: SQL 인젝션 수정 — hive_bridge.py parameterized query 전환
[x] Task 3: 커맨드 인젝션 수정 — /api/launch
[x] Task 4: 경로 순회 수정 — 파일 접근 API 보안 강화
[x] Task 5: psycopg2 의존성 등록

## 🟡 P1: 성능/안정성 개선 — ✅ 전부 완료

[x] Task 6~10: 에러 핸들링, API_BASE 통합, bare except 정리, PG 포트 통합, ISS 통합

## 🔵 P3: 하이브 인텔리전스 — ✅ 전부 완료

[x] Task 11~14: Red Team, Living Doc, Consensus, Drift Detection

---

## 🟣 P4: 멀티-LLM 자율 협업 시스템 (v3.7.82~)

**목표:** Claude(T1) + Gemini(T2) + Codex(T3)가 자율적으로 작업 분배/실행/검증

[x] Task 15: 자율 태스크 디스패처 (auto_dispatcher.py) 구현
[x] Task 16: 서버 디스패처 API 추가
[x] Task 17: /api/heartbeat Content-Type 수정
[x] Task 18: /api/shutdown 엔드포인트 구현
[x] Task 19: T2/T3에 ITCP 작업 지시 전송
[x] Task 20: 대시보드 디스패처 UI 패널 추가
[x] Task 21: 자동 디스패치 트리거 — UserPromptSubmit 연동
[x] Task 22: 에이전트 자동 피드백 루프

---

## 🟢 P5: cmux 기반 vibe CLI + 알림 시스템 고도화 (v3.7.89~)

[x] Task 23: PostgreSQL에 vibe 알림/상태/로그 스키마 생성
[x] Task 24: api/vibe_api.py 신규 생성 — /api/vibe/* REST 핸들러
[x] Task 25: server.py에 vibe_api 라우팅 추가
[x] Task 26: scripts/vibe_cli.py 신규 생성 — cmux 호환 CLI
[x] Task 27: scripts/osc_parser.py 신규 생성 — OSC 시퀀스 파서
[x] Task 28: scripts/agent_detector.py 신규 생성 — 에이전트 프로세스 감지
[x] Task 29: cli_agent.py에 OSC 파서 통합
[x] Task 30: mission_control.py에 vibe_notification 채널 구독 추가
[x] Task 31: mission_control_ui.py에 링 플래시 + 배지 + 진행률 호 추가

---

## 🔵 P6: cmux-style 터미널 MUX — 에이전트 간 텍스트 직접 주입 (v3.7.90~)

[x] Task 32: scripts/vibe_mux.py — Named Pipe MUX 서버 + CLI
[x] Task 33: scripts/vibe_mux_agent.py — 터미널별 MUX 에이전트
[x] Task 34: server.py에 /api/mux/* REST 엔드포인트 추가
[x] Task 35: cli_agent.py에 MUX 에이전트 자동 등록
[x] Task 36: auto_dispatcher.py를 MUX 기반으로 업그레이드

---

## 🟢 P7: 코덱스(Codex) 가이드 통합 및 CLI 도구 강화 (v3.7.95~)

**목표:** 사용자가 코덱스(Codex) 에이전트를 쉽게 설치/실행/협업할 수 있도록 문서와 도구 제공

[x] Task 37: 통합 가이드 문서 생성 (`CODEX_GUIDE.md`)
[x] Task 38: `vibe_cli.py`에 `codex` 서브커맨드 구조 추가
[x] Task 39: `codex status` 및 `guide` 기능 구현
[x] Task 40: `codex start` 및 `msg` (ITCP 래퍼) 구현

---

## 🔴 P8: node-pty 기반 PTY 마이크로서비스 교체 (v3.7.108~)

**목표:** Python pywinpty PTY 핸들러를 Node.js node-pty 마이크로서비스로 교체하여
Gemini/Codex 터미널 연결 안정성을 근본 해결 (접근법 C: REST 브릿지)

**아키텍처:**
```
Frontend (TerminalSlot.tsx) ──WS──→ Node.js PTY Server (node-pty + ws + express)
Python server.py ──REST──→ Node.js PTY Server (/api/pty/sessions, /output, /interrupt)
```

**포트:** Node PTY Server = HTTP_PORT+1 (기존 WS_PORT 재사용, 프론트엔드 변경 0)

### Phase 1: Node.js PTY 서버 구축

[x] Task 41: Node.js PTY 서버 프로젝트 초기화
    파일: .ai_monitor/pty-server/package.json
    방법: node-pty, ws, express 의존성으로 package.json 생성 + npm install
    검증: node_modules에 node-pty 네이티브 빌드 성공 확인

[x] Task 42: PTY 서버 핵심 구현 — WebSocket PTY 핸들러
    파일: .ai_monitor/pty-server/pty-server.js
    방법: 기존 server.py:pty_handler() (4561-4709줄) 로직을 Node.js로 포팅
      - ws 라이브러리로 WebSocket 서버 (/pty/slot{N}?agent=...&cols=...&rows=...)
      - node-pty.spawn() → cmd.exe (Claude) / bash.exe (Gemini/Codex)
      - 에이전트별 시작 명령 (claude, gemini -y, codex --model ...)
      - 환경변수 주입 (TERMINAL_ID, HIVE_AGENT, PYTHONIOENCODING 등)
      - PTY→WS 출력 스트리밍 (pty.onData → ws.send)
      - WS→PTY 입력 전달 (ws.onmessage → pty.write)
      - JSON resize 메시지 처리 ({type:'resize',cols,rows} → pty.resize)
      - 세션 저장소 (Map: sessionId → {pty, agent, started, cwd, lastLine, ...})
      - 출력 버퍼 (배열 maxlen=400, ANSI 제거 후 저장)
    검증: node pty-server.js 실행 → wscat으로 WS 연결 → cmd.exe 쉘 응답 확인

[x] Task 43: PTY 서버 — 에이전트별 입력 처리 + 더블엔터
    파일: .ai_monitor/pty-server/pty-server.js
    방법: 기존 server.py:read_from_ws() (4796-4862줄) 로직 포팅
      - Gemini/Codex 더블엔터 (\r\r) 처리
      - IME 호환성 (\r\n → \r 정규화)
      - 백스페이스 버퍼 처리
      - 입력 버퍼링 + 자율 에이전트 라우팅 (빈 셸용, cli_agent.py 호출)
    의존성: Task 42 완료 후
    검증: Gemini/Codex TUI에서 입력 정상 처리 확인

[x] Task 44: PTY 서버 — REST API 엔드포인트
    파일: .ai_monitor/pty-server/pty-server.js
    방법: Express로 REST 엔드포인트 추가
      - GET /api/pty/sessions → 전체 세션 스냅샷 (agent, started, cwd, lastLine, mainModel, bgModel)
      - GET /api/pty/output/:id?since=N&limit=M → 출력 버퍼 조회
      - POST /api/pty/interrupt/:id → pty.write('\x03')
      - POST /api/pty/terminate/:id → pty.kill() + 세션 제거
      - 세션 로그 → Python 서버 /api/log로 HTTP POST
    의존성: Task 42 완료 후
    검증: curl로 각 REST 엔드포인트 응답 확인

### Phase 2: Python 서버 연동

[x] Task 45: server.py — Node PTY 서버 프로세스 관리
    파일: .ai_monitor/server.py
    방법:
      - Node PTY 서버를 subprocess.Popen으로 시작 (PTY_PORT, HTTP_PORT 환경변수 전달)
      - 개발 모드: node pty-server.js / 배포 모드: pty-server.exe 자동 감지
      - atexit + SIGTERM/SIGBREAK 핸들러에 node_pty_proc.terminate() 등록
      - 기존 websockets.serve() 호출 제거 (start_ws_server 함수)
      - 기존 pty_sessions, pty_output_buffers, pty_output_seq 글로벌 제거
      - 기존 pty_handler(), _append_pty_output(), _cleanup_all_pty_sessions() 제거
    의존성: Task 44 완료 후
    검증: server.py 시작 시 Node PTY 서버 자동 spawn + 종료 시 자동 kill 확인

[x] Task 46: pty_api.py — REST 프록시로 전환
    파일: .ai_monitor/api/pty_api.py
    방법:
      - _pty_sessions_getter 콜백 방식 → HTTP GET http://127.0.0.1:{PTY_PORT}/api/pty/sessions 호출
      - _pty_output_getter → HTTP GET http://127.0.0.1:{PTY_PORT}/api/pty/output/:id
      - handle_post interrupt/terminate → HTTP POST http://127.0.0.1:{PTY_PORT}/api/pty/...
      - set_pty_rest_url(url) 함수로 URL 주입 (기존 getter 패턴 대체)
      - 기존 프론트엔드 API URL (/api/pty/*) 유지 — 투명 프록시
    의존성: Task 45 완료 후
    검증: 프론트엔드에서 /api/pty/terminals 호출 시 Node 서버 데이터 반환 확인

[x] Task 47: agent_api.py — PTY 세션 조회 REST 전환
    파일: .ai_monitor/api/agent_api.py
    방법:
      - set_pty_sessions_getter() → set_pty_rest_url() 로 교체
      - handle_terminals() 내 pty_sessions 직접 참조 → HTTP GET /api/pty/sessions
      - server.py의 기타 pty_sessions 직접 참조 (2150, 2382, 2838, 3861, 3965줄) → REST 호출
    의존성: Task 46 완료 후
    검증: 대시보드 에이전트 패널에서 터미널 상태 정상 표시 확인

### Phase 3: 프론트엔드 최소 수정 + 통합 테스트

[x] Task 48: TerminalSlot.tsx — 프로토콜 호환성 확인 및 미세 조정
    파일: .ai_monitor/vibe-view/src/components/TerminalSlot.tsx
    방법:
      - WebSocket 프로토콜 동일 (raw text + JSON resize) → 변경 불필요 예상
      - 단, Node ws 라이브러리의 Binary/Text 프레임 차이 확인
      - 필요 시 ws.binaryType = 'arraybuffer' → 'blob' 조정
      - 연결 성공 메시지에 "[node-pty]" 태그 추가 (디버깅용)
    의존성: Task 47 완료 후
    검증: Claude 터미널 연결 + 명령 실행 정상 확인

[x] Task 49: 통합 테스트 — Claude/Gemini/Codex 3종 터미널 검증
    파일: (전체 시스템)
    방법:
      - Claude 터미널: cmd.exe → claude 실행 → 명령 입출력 확인
      - Gemini 터미널: bash.exe → gemini -y 실행 → TUI 입출력 확인
      - Codex 터미널: bash.exe → codex 실행 → TUI 입출력 확인
      - 터미널 리사이즈 동작 확인
      - 터미널 종료/재연결 확인
      - 대시보드 에이전트 패널 상태 표시 확인
      - /api/pty/interrupt, /api/pty/terminate 동작 확인
    의존성: Task 48 완료 후
    검증: 3종 에이전트 모두 터미널 출력 정상 연결 + 입력 처리 성공

[x] Task 50: 정리 — 미사용 Python PTY 코드 완전 제거 + 빌드 검증
    파일: .ai_monitor/server.py, .ai_monitor/requirements.txt
    방법:
      - server.py에서 pywinpty import 제거
      - requirements.txt에서 pywinpty==3.0.3 제거 (websockets도 불필요 시 제거)
      - .ai_monitor/winpty/ DLL 디렉토리 제거 (있을 경우)
      - /vibe-release로 빌드 + 배포 테스트
    의존성: Task 49 완료 후 (모든 테스트 통과 확인)
    검증: pywinpty 없이 서버 정상 시작 + 전체 기능 동작 확인

---

## 변경 요약
- **P0~P3 완료**: 보안/성능/하이브 인텔리전스 전부 완료.
- **P4 완료**: 멀티-LLM 자율 협업 시스템 전부 완료.
- **P5 완료**: cmux 기반 vibe CLI + 알림 시스템 고도화 완료.
- **P6 완료**: cmux-style 터미널 MUX 완료.
- **P7 완료**: 코덱스(Codex) 가이드 및 CLI 강화 완료.
- **P8 완료**: node-pty 기반 PTY 마이크로서비스 교체 완료.
