# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## 프로젝트 개요

**Vibe Coding**은 AI 멀티 에이전트 하이브 마인드 대시보드입니다. Claude, Gemini, Codex 등 여러 AI 에이전트를 통합 터미널 UI에서 오케스트레이션하며, PostgreSQL 18 기반 실시간 협업 시스템입니다. Windows 자체 호스팅(PyWebView) 방식으로 동작합니다.

- **공통 하네스 계약**: [docs/HARNESS_V2.md](./docs/HARNESS_V2.md)

## 최우선 준수 사항

**반드시 `RULES.md`를 먼저 읽고 모든 규칙을 절대적으로 준수할 것.** 핵심 요약:

- **한글 필수**: 모든 주석, 커밋 본문, 대화 출력은 한글로 작성
- **표준 헤더**: 모든 파일 상단에 FILE/DESCRIPTION/REVISION HISTORY 템플릿 포함 (Python: `"""`, JS/TS: `/* */`, MD/HTML: `<!-- -->`)
- **PostgreSQL-first**: 로깅은 반드시 PostgreSQL `pg_logs` 테이블에 기록 (`.jsonl`/SQLite 금지)
- **Git worktree**: 새 기능 구현 시 격리된 worktree에서 작업
- **커밋 메시지**: Conventional Commits 형식 + 한글 본문(Why/What/Impact 필수), 제목 한 줄만 작성 금지
- **불필요한 문서 생성 금지**: `docs/` 내 1:1 설명 문서 대신 `PROJECT_MAP.md`에서 중앙 관리

## 빌드 및 실행

```bash
# 개발 모드 설치 및 실행
pip install -e .
vibe-coding          # CLI (콘솔 출력 있음)
vibe-coding-gui      # GUI (콘솔 없이)

# 서버 직접 실행
python .ai_monitor/server.py

# PyInstaller EXE 빌드
pyinstaller vibe-coding.spec --noconfirm

# Windows 인스톨러 빌드
ISCC.exe vibe-coding-setup.iss

# 테스트
pytest tests/
```

## 작업 전 하이브 동기화 (필수)

```bash
# 공유 메모리 확인 (다른 에이전트의 기술 결정 사항)
python scripts/memory.py list

# 하이브 상태 분석
python scripts/analyze_hive.py

# 현재 단계 확인
cat ai_monitor_plan.md
```

작업 완료 후:
```bash
# 로그 기록
python scripts/hive_bridge.py
# 지식 공유
python scripts/memory.py
```

## 아키텍처

```
React/TS 프론트엔드 (.ai_monitor/dist/)
  ↕ HTTP + SSE + WebSocket (포트 9000-9007)
Python HTTP 서버 (.ai_monitor/server.py, ~5400줄)
  ↕ API 모듈 (.ai_monitor/api/)
  ↕ 데이터 계층 (.ai_monitor/src/pg_store.py)
PostgreSQL 18 (포트 5433, 내장/포터블)
  + Node.js PTY 서버 (.ai_monitor/pty-server/)
```

**서버** (`server.py`): 중앙 오케스트레이터. 라우팅, SSE 스트리밍, WebSocket PTY 멀티플렉싱, 정적 파일 서빙 담당. Flask 유사 구조(Python stdlib).

**API 모듈** (`.ai_monitor/api/`): 도메인별 분리된 REST 핸들러.
- `agent_api.py` — CLI 에이전트 실행/중지/상태 (claude, gemini, codex)
- `hive_api.py` — 하이브 마인드 헬스체크, 스킬 체인, 오케스트레이션
- `tasks_api.py` — 태스크 큐 CRUD + 원자적 체크아웃
- `dispatcher_api.py` — 멀티 LLM 자동 태스크 분배
- `memory_api.py` — 공유 지식 기반 (PostgreSQL hive_memory)
- `git_api.py` — worktree + 커밋 통합
- `pty_api.py` — 터미널 세션 관리
- `files_api.py` — 파일 읽기/쓰기/탐색
- `vibe_api.py` — UI 상태 + 진행률

**데이터 계층** (`.ai_monitor/src/`):
- `pg_store.py` — PostgreSQL 스키마 정의 + CRUD (pg_logs, pg_messages, hive_memory, hive_tasks, hive_sessions, hive_skill_chains, task_comments, agent_heartbeats)
- `db_helper.py` — 트랜잭션 헬퍼
- `file_store.py` — 레거시 JSONL/SQLite 폴백

**프론트엔드** (React/TypeScript, Vite 빌드 → `.ai_monitor/dist/`):
- `App.tsx` — 레이아웃 오케스트레이터, 폴링 코디네이터
- `AgentPanel.tsx` (~2900줄) — 핵심 패널. 자가 치유, 스킬 체인, 사고 추적
- `TerminalSlot.tsx` — xterm.js + WebSocket PTY 연결
- 상태 관리: React hooks (Redux 없음, prop drilling)

**에이전트 간 통신**: PostgreSQL NOTIFY/LISTEN 기반 비동기 방식. `task_comments` 테이블로 소통, `agent_heartbeats`로 상태 추적, `hive_tasks`의 원자적 체크아웃으로 동시 작업 방지.

## 패키지 구조

`.ai_monitor/` 디렉토리가 `ai_monitor` Python 패키지로 매핑됨 (pyproject.toml의 `package-dir` 설정). 패키지: `ai_monitor`, `ai_monitor.api`, `ai_monitor.src`.

Python >= 3.11, 주요 의존성: pywebview, psycopg2-binary, watchdog, python-dotenv, rich, python-telegram-bot, pywin32 (Windows).

## 에이전트 역할 분담

- **Gemini**: 전체 설계 및 오케스트레이션
- **Claude**: 정밀 로직 구현 및 프론트엔드 최적화
- `task_logs.jsonl`과 `hive_tasks` 테이블로 진행 상황 공유

## 작업 완료 리포트 (필수)

단위 작업 완료 시 반드시 간결하게 출력:
- **수정/생성된 파일:** (경로 나열)
- **원인 (Why):** (1줄 요약)
- **수정 내용 (How):** (1~2줄 요약)
