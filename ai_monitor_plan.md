# AI 오케스트레이터 스킬 체인 DB 전환 계획

**작성일:** 2026-03-01
**작성자:** Claude (vibe-write-plan)
**목표:** skill_chain.json → skill_chain.db(SQLite) 전환 + 터미널별 스킬 실행 추적 UI

---

## 설계 요약

- **DB 파일**: `.ai_monitor/data/skill_chain.db` (신규, 오케스트레이터 전용)
- **터미널 구분**: `--terminal N` 플래그로 1~8번 터미널에 체인 귀속
- **표기 방식**: `N-M` (터미널N, 스킬번호M) → 예: `1-3 → 1-4 → 1-5`
- **스킬 번호 고정**: 1=debug, 2=tdd, 3=brainstorm, 4=write-plan, 5=execute, 6=review, 7=release

---

## 태스크 목록

### [x] Task 1: skill_orchestrator.py — JSON→SQLite 전환 + --terminal 플래그
### [x] Task 2: hive_api.py — skill-chain 엔드포인트 DB 쿼리로 변경
### [x] Task 3: server.py — skill-chain 엔드포인트 DB 쿼리로 변경
### [x] Task 4: OrchestratorPanel.tsx — 스킬 레지스트리 + 터미널별 N-M 표기 UI

---

---

# [신규] CLI 오케스트레이터 자율 에이전트 시스템

**작성일:** 2026-03-04
**작성자:** Claude (vibe-write-plan)
**목표:** 대시보드에서 지시 입력 → Claude Code CLI / Gemini CLI 자동 제어 → 자율 실행 (OpenHands 스타일, 도커 없이)

---

## 설계 요약

```
[사용자] 대시보드 AgentPanel에 지시 입력
    ↓
[라우터] 키워드 분석 → Claude Code CLI / Gemini CLI / 체인 결정
    ↓
[엔진] scripts/cli_agent.py → subprocess로 CLI 비대화형 실행
    - Claude Code: claude -p "지시내용"
    - Gemini CLI: echo "지시내용" | gemini
    ↓
[스트림] 실시간 출력 → SSE /api/events/agent → 대시보드 실시간 표시
    ↓
[완료] 프로세스 종료 감지 → agent_runs.jsonl 저장 → 다음 태스크 체인 가능
```

## 새 파일 구조

```
scripts/
└── cli_agent.py                    ← NEW: CLI 오케스트레이터 핵심 엔진

.ai_monitor/
├── api/
│   └── agent_api.py                ← NEW: 에이전트 REST API
├── server.py                       ← MODIFY: agent_api 임포트 + SSE 추가
├── data/
│   └── agent_runs.jsonl            ← 자동 생성: 실행 히스토리
└── vibe-view/src/
    ├── App.tsx                     ← MODIFY: AgentPanel 탭 추가
    └── components/panels/
        └── AgentPanel.tsx          ← NEW: 자율 에이전트 UI 패널
```

---

## 태스크 목록

### [x] Task 5: scripts/cli_agent.py — CLI 오케스트레이터 핵심 엔진

**파일:** `scripts/cli_agent.py` (신규 생성)

**방법:**
1. `CLIAgent` 클래스 구현
   - `route_task(task: str) -> str`: 키워드 기반 CLI 선택 로직
     - 코드/구현/수정/버그/파일 → `claude`
     - 설계/분석/검토/브레인스토밍 → `gemini`
     - 기본값 → `claude`
   - `run(task: str, cli: str, output_queue: Queue) -> dict`: 비대화형 실행
     - Claude Code: `subprocess.Popen(['claude', '-p', task], stdout=PIPE, stderr=STDOUT)`
     - Gemini CLI: `subprocess.Popen(['gemini'], stdin=PIPE, stdout=PIPE, stderr=STDOUT)` + `communicate(input=task)`
     - 출력을 줄 단위로 읽어 `output_queue`에 실시간 Push
   - `stop()`: 실행 중 프로세스 강제 종료 (`process.terminate()`)
   - `save_run(task, cli, output, status)`: `agent_runs.jsonl`에 결과 저장

2. 전역 상태 (모듈 레벨)
   - `_current_process`: 현재 실행 중인 subprocess
   - `_output_queue`: SSE 스트리밍용 Queue
   - `_run_status`: 'idle' | 'running' | 'done' | 'error'

3. 라우팅 키워드 테이블 (한글 + 영문 지원)
   ```python
   CLAUDE_KEYWORDS = ['코드', '구현', '수정', '버그', '파일', 'code', 'fix', 'implement', 'write']
   GEMINI_KEYWORDS = ['설계', '분석', '검토', '브레인', 'design', 'analyze', 'review', 'plan']
   ```

**검증:** `python scripts/cli_agent.py "간단한 hello.py 만들어줘"` 실행 → 터미널에 출력 확인

---

### [x] Task 6: .ai_monitor/api/agent_api.py — 에이전트 REST API
**의존성:** Task 5 완료 후

**파일:** `.ai_monitor/api/agent_api.py` (신규 생성)

**방법:**
엔드포인트 4개 구현:

1. **POST `/api/agent/run`**
   ```json
   요청: { "task": "지시내용", "cli": "auto" }
   응답: { "status": "started", "cli": "claude", "run_id": "uuid" }
   ```
   - `cli_agent.route_task()` 호출 → CLI 결정
   - 백그라운드 스레드에서 `cli_agent.run()` 실행
   - 이미 실행 중이면 `{ "error": "already_running" }` 반환

2. **POST `/api/agent/stop`**
   ```json
   응답: { "status": "stopped" }
   ```
   - `cli_agent.stop()` 호출

3. **GET `/api/agent/status`**
   ```json
   응답: { "status": "idle|running|done|error", "cli": "claude", "task": "..." }
   ```

4. **GET `/api/agent/runs`**
   ```json
   응답: [{ "id": "...", "task": "...", "cli": "claude", "status": "done", "ts": "..." }]
   ```
   - `agent_runs.jsonl` 최근 20개 읽어서 반환

**검증:** 서버 실행 후 `curl -X POST http://localhost:8005/api/agent/run -d '{"task":"테스트"}'` 성공

---

### [x] Task 7: .ai_monitor/server.py — agent_api 임포트 + SSE 엔드포인트 추가
**의존성:** Task 6 완료 후

**파일:** `.ai_monitor/server.py` (수정)

**방법:**

1. **임포트 추가** (파일 상단 api 임포트 섹션, 약 51-53번째 줄 근처)
   ```python
   import api.agent_api as agent_api
   ```

2. **SSE 엔드포인트 추가** — `/api/events/agent`
   - 기존 `/api/events/thoughts` SSE 패턴과 동일하게 구현
   - `cli_agent._output_queue`에서 줄 단위로 읽어 SSE 포맷으로 전송
   - 클라이언트 연결 종료 시 자동 정리

3. **라우팅 추가** — `do_POST`, `do_GET` 핸들러에
   ```python
   elif path == '/api/agent/run':    return agent_api.handle_run(self)
   elif path == '/api/agent/stop':   return agent_api.handle_stop(self)
   elif path == '/api/agent/status': return agent_api.handle_status(self)
   elif path == '/api/agent/runs':   return agent_api.handle_runs(self)
   ```

**검증:** 서버 재시작 후 `/api/agent/status` GET 요청 → `{"status": "idle"}` 응답 확인

---

### [x] Task 8: .ai_monitor/vibe-view/src/components/panels/AgentPanel.tsx — 자율 에이전트 UI
**의존성:** Task 7 완료 후

**파일:** `.ai_monitor/vibe-view/src/components/panels/AgentPanel.tsx` (신규 생성)

**방법:**
```
레이아웃:
┌─────────────────────────────┐
│ 🤖 Autonomous Agent         │
│ ┌──────────────────────┐    │
│ │ 지시 입력 textarea   │    │
│ └──────────────────────┘    │
│ [CLI: Auto▼]  [▶ 실행] [■ 중단] │
│─────────────────────────────│
│ 상태: 🟢 Running (claude)   │
│─────────────────────────────│
│ ▼ 실시간 출력               │
│  > 파일 분석 중...          │
│  > App.tsx 수정 완료        │
│─────────────────────────────│
│ ▼ 실행 히스토리 (최근 5개)  │
└─────────────────────────────┘
```

구현 세부:
1. **상태 관리**
   - `status`: 'idle' | 'running' | 'done' | 'error'
   - `outputLines`: string[] (실시간 출력)
   - `selectedCli`: 'auto' | 'claude' | 'gemini'
   - `taskInput`: string
   - `history`: 실행 히스토리 배열

2. **SSE 연결** (`useEffect`)
   - `/api/events/agent` SSE 구독
   - 수신 데이터 → `outputLines` 추가
   - `status` 업데이트 (started/done/error 이벤트)

3. **API 호출**
   - `handleRun()`: POST `/api/agent/run` → SSE 자동 시작
   - `handleStop()`: POST `/api/agent/stop`
   - `loadHistory()`: GET `/api/agent/runs`

4. **스타일**: 기존 패널과 동일한 다크테마 (`bg-black/20`, `text-white/80`)
   - 출력창: 터미널 스타일 (`font-mono`, `text-green-400`)
   - 실행 중 애니메이션 스피너

**검증:** `npx tsc --noEmit` 오류 없음 + 브라우저에서 패널 렌더링 확인

---

### [x] Task 9: .ai_monitor/vibe-view/src/App.tsx — AgentPanel 탭 추가
**의존성:** Task 8 완료 후

**파일:** `.ai_monitor/vibe-view/src/App.tsx` (수정)

**방법:**

1. **임포트 추가**
   ```typescript
   import AgentPanel from './components/panels/AgentPanel';
   ```

2. **ActivityBar 탭 추가** — 기존 탭 배열에 삽입
   ```typescript
   { id: 'agent', icon: <Bot />, label: 'Agent', title: 'Autonomous Agent' }
   ```
   - `lucide-react`의 `Bot` 아이콘 사용 (이미 설치됨)

3. **패널 렌더링 추가** — 탭 패널 스위치에
   ```typescript
   {activeTab === 'agent' && <AgentPanel />}
   ```

4. **배지** — 실행 중일 때 주황색 점 표시 (AgentPanel 콜백으로 수신)

**검증:** `npm run build` 성공 + 브라우저에서 Agent 탭 클릭 → AgentPanel 표시 확인

---

## 실행 순서

```
Task 5 (cli_agent.py)        ← 핵심 엔진, 독립 구현
    ↓
Task 6 (agent_api.py)        ← Task 5 의존
    ↓
Task 7 (server.py 수정)      ← Task 6 의존
    ↓
Task 8 (AgentPanel.tsx)      ← Task 7 의존 (API 완성 후 UI)
    ↓
Task 9 (App.tsx 탭 추가)     ← Task 8 의존
```

## 비고

- **도커 없음**: subprocess + 가상환경으로 격리 대체
- **API 키 없음**: Claude Code CLI / Gemini CLI가 각자 인증 처리
- **비대화형 모드 우선**: `claude -p` 플래그 사용 (안정성 우선, 대화형은 v2)
- **체인 실행**: Task 5 완성 후 `run_chain(tasks: list)` 함수로 확장 가능
- **기존 PTY 터미널 영향 없음**: 독립 subprocess 사용, WebSocket PTY와 충돌 없음
