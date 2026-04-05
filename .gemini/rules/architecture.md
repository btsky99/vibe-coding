## 아키텍처 (Gemini 관점)

이 프로젝트는 PostgreSQL 18을 백엔드로 하는 **멀티 에이전트 하이브 마인드** 시스템입니다.

```
React/TS 프론트엔드 (.ai_monitor/vibe-view/ → dist/)
  ↕ HTTP + SSE + WebSocket (포트 9000-9007)
Python HTTP 서버 (.ai_monitor/server.py)
  ↕ API 모듈 (.ai_monitor/api/)
  ↕ 데이터 계층 (.ai_monitor/src/pg_store.py)
PostgreSQL 18 (포트 5433, 내장/포터블)
  + Node.js PTY 서버 (.ai_monitor/pty-server/)
```

### 서버 구성 및 모듈
Gemini는 시스템의 전반적인 구조와 흐름을 이해하고, 각 모듈의 역할을 파악하여 오케스트레이션을 수행합니다.

- `server.py` — 중앙 라우팅 및 SSE/WebSocket 관리
- `api/agent_api.py` — 에이전트 생명주기 관리
- `api/hive_api.py` — 하이브 상태 및 스킬 체인 오케스트레이션
- `api/tasks_api.py` — 원자적 태스크 체크아웃 및 큐 관리
- `api/memory_api.py` — PostgreSQL 기반 공유 지식 저장소
- `src/pg_store.py` — 데이터베이스 스키마 및 쿼리 (Truth of Source)

### 데이터 흐름
모든 에이전트 간의 통신과 상태 공유는 **PostgreSQL 18**을 통해 이루어집니다.
- `pg_logs`: 모든 에이전트의 활동 기록
- `hive_tasks`: 작업 할당 및 상태 추적
- `agent_heartbeats`: 실시간 에이전트 활성 상태 감시
- `task_comments`: 에이전트 간 협업 대화 (ITCP)

### 패키징
- `.ai_monitor/` 폴더가 핵심 패키지이며, `pyproject.toml`을 통해 관리됩니다.
- Gemini는 전체 빌드 파이프라인(`auto_release.py`)과 버전 관리(`auto_version.py`)를 감독합니다.
