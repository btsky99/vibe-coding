## 아키텍처

```
React/TS 프론트엔드 (.ai_monitor/vibe-view/ → dist/)
  ↕ HTTP + SSE + WebSocket (포트 9000-9007)
Python HTTP 서버 (.ai_monitor/server.py)
  ↕ API 모듈 (.ai_monitor/api/)
  ↕ 데이터 계층 (.ai_monitor/src/pg_store.py)
PostgreSQL 18 (포트 5433, 내장/포터블)
  + Node.js PTY 서버 (.ai_monitor/pty-server/)
```

### 서버 (`server.py`)
중앙 오케스트레이터. 라우팅, SSE 스트리밍, WebSocket PTY 멀티플렉싱, 정적 파일 서빙. Flask 유사 구조(Python stdlib).

### API 모듈 (`.ai_monitor/api/`)
- `agent_api.py` — CLI 에이전트 실행/중지/상태
- `hive_api.py` — 하이브 마인드 헬스체크, 스킬 체인
- `tasks_api.py` — 태스크 큐 CRUD + 원자적 체크아웃
- `dispatcher_api.py` — 멀티 LLM 자동 태스크 분배
- `memory_api.py` — 공유 지식 기반 (PostgreSQL hive_memory)
- `git_api.py` — worktree + 커밋 통합
- `pty_api.py` — 터미널 세션 관리
- `files_api.py` — 파일 읽기/쓰기/탐색
- `vibe_api.py` — UI 상태 + 진행률

### 데이터 계층 (`.ai_monitor/src/`)
- `pg_store.py` — PostgreSQL 스키마 + CRUD
- `db_helper.py` — 트랜잭션 헬퍼
- `file_store.py` — 레거시 JSONL/SQLite 폴백

**project_id 가드 의무 (Phase 2-4):** DB 쓰기 함수는 `pg_store.py`에 집중한다. `project_id` 컬럼이 있는 테이블에 INSERT/UPDATE 하는 함수는 진입부에서 `assert_project_id(project_id, '<함수명>')`을 호출해 빈 값 유입을 dev 모드에서 경고한다. 우회 INSERT(`api/office_api.py` 등)는 점진적으로 pg_store로 흡수한다.

### 프론트엔드 (React/TypeScript, Vite)
- `App.tsx` — 레이아웃, 폴링 코디네이터
- `AgentPanel.tsx` — 핵심 패널. 자가 치유, 스킬 체인
- `TerminalSlot.tsx` — xterm.js + WebSocket PTY
- 상태 관리: React hooks (Redux 없음)

### 에이전트 간 통신
PostgreSQL NOTIFY/LISTEN 기반. `task_comments`로 소통, `agent_heartbeats`로 상태 추적, `hive_tasks` 원자적 체크아웃.

### 패키지 구조
`.ai_monitor/` → `ai_monitor` 패키지 (pyproject.toml `package-dir`). Python >= 3.11.
