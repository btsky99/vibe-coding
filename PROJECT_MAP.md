# 🗺️ Vibe-Coding 프로젝트 맵 (PROJECT_MAP.md)

<!--
FILE: PROJECT_MAP.md
DESCRIPTION: 프로젝트 전체 구조와 각 파일의 역할 정의. 모든 에이전트는 작업 시 이 맵을 최신 상태로 유지해야 함.

REVISION HISTORY:
- 2026-02-25 Gemini-1: 최초 작성, 하이브 마인드 v3.0 구조 반영
- 2026-03-01 Claude: scripts/ 신규 파일 추가, skills/ 구조 반영, v3.6.10 상태 업데이트
-->

이 파일은 프로젝트의 전체 구조와 각 파일의 역할을 정의합니다. 모든 에이전트는 작업 시 이 맵을 최신 상태로 유지해야 합니다.

## 🏗️ 전체 구조

### 1. 코어 서버 (`.ai_monitor/`)
- `server.py`: http.server 기반 중앙 통제 서버. SSE 로그 스트림 + WebSocket PTY + REST API 50+ 개. (3690줄)
- `_version.py`: 시스템 버전 정보 (`v3.6.10`).
- `updater.py`: GitHub Releases 기반 자동 업데이트 모듈.
- `vibe-coding.spec`: PyInstaller 빌드 설정 파일.
- `installer.iss`: Inno Setup 인스톨러 생성 스크립트.
- **`data/`**: (개발 모드) SQLite DB 및 로그 파일 저장소.
  - `shared_memory.db` — 에이전트 간 공유 메모리 (embedding 포함)
  - `hive_mind.db` — 하이브 마인드 태스크/세션 DB
  - `task_logs.jsonl` — 실시간 작업 로그
  - `task_logs_archive.jsonl` — 아카이브된 로그
  - `messages.jsonl` — 에이전트 간 채팅 메시지
  - `tasks.json` — 태스크 보드 데이터
  - `sessions.jsonl` — 에이전트 세션 기록
  - `skill_chain.json` — 오케스트레이터 현재 스킬 체인 상태
  - `skill_results.jsonl` — 스킬 실행 결과 영구 기록
  - `skill_analysis.json` — 스킬 사용 통계 분석
  - `hive_health.json` — 하이브 헬스 상태
  - `locks.json` — 에이전트 락 상태
  - `projects.json` — 최근 프로젝트 목록
  - `vector_db/` — ChromaDB 벡터 DB (현재 비활성)
- **`vibe-view/`**: React/TypeScript 기반 모니터링 대시보드 프론트엔드.
  - `src/App.tsx`: 메인 앱 컴포넌트. 9개 탭(explorer/search/orchestrate/hive/messages/tasks/memory/git/mcp). (3289줄)
  - `src/types.ts`: TypeScript 타입 정의 (166줄)
  - `src/components/ThoughtTrace.tsx`: ThoughtTrace 패널 컴포넌트
  - `src/components/VibeEditor.tsx`: 코드 에디터 컴포넌트

### 2. 통합 브릿지 및 메모리 (`scripts/`)
- `memory.py`: 에이전트 간 공유 메모리(SQLite) 관리 헬퍼. `python scripts/memory.py list` 로 하이브 메모리 조회.
- `hive_bridge.py`: 에이전트 작업 로그를 서버(task_logs.jsonl)로 전송하는 통신 브릿지.
- `hive_watchdog.py`: 시스템 상태 감시 및 자가 복구 엔진. 서버 자동 재시작 포함 (restart_server()).
- `hive_hook.py`: Claude Code UserPromptSubmit 훅. 세션 스냅샷 저장 + 미읽음 메시지 수신.
- `gemini_hook.py`: Gemini CLI UserPromptSubmit 훅. 세션 스냅샷 저장 + 양방향 메시지 연결.
- `orchestrator.py`: AI 오케스트레이터 기본 모듈. 요청 분석 및 스킬 선택.
- `skill_orchestrator.py`: 스킬 체인 상태 추적 + 대시보드 연동. `plan/update/done` 명령 지원.
- `skill_analyzer.py`: 스킬 사용 패턴 분석 엔진.
- `skill_manager.py`: 스킬 설치/관리 모듈.
- `agent_protocol.py`: 에이전트 간 표준 프로토콜 정의.
- `send_message.py`: 에이전트 간 메시지 전송 CLI. `python scripts/send_message.py <from> <to> <type> <msg>`
- `megaphone.py`: 브로드캐스트 메시지 전송 도구.
- `task.py`: 태스크 보드 관리 CLI.
- `auto_version.py`: 빌드 시 버전 번호 자동 증가 유틸리티.
- `vector_memory.py`: 로컬 벡터 DB(ChromaDB) 기반 장기 기억 엔진. (v3.5.7 이후 비활성)
- `utils/`: 공통 유틸리티 함수 모음.

### 3. 스킬 시스템
- `.gemini/skills/`: Gemini CLI용 하이브 마인드 공통 스킬 지침
  - `brainstorming/`, `code-review/`, `execute-plan/`, `master/`
  - `pattern-vibe/`, `pattern-view/`, `release/`, `systematic-debugging/`, `tdd/`, `write-plan/`
- `skills/claude/`: Claude Code용 스킬 지침
  - (Claude Code `~/.claude/commands/` 또는 프로젝트 `.claude/commands/`에서 로드)

### 4. 사용자 인터페이스 및 배포
- `run_vibe.bat`: 시스템 실행 배치 파일.
- `repair_env.bat`: 환경 복구 도구.
- `dist/`: 빌드된 독립 실행 파일 저장소.

## 🕒 최근 주요 변경 사항
- **[2026-03-01] v3.6.10 세션 자동 저장 + 양방향 메시지 연결 (Claude)**:
  - `scripts/hive_hook.py`: Claude Code 세션 스냅샷 자동 저장 + 미읽음 메시지 폴링
  - `scripts/gemini_hook.py`: Gemini 세션 스냅샷 + Claude↔Gemini 양방향 메시지 연결
- **[2026-03-01] v3.6.9 하이브 마인드 3가지 기능 추가 (Claude)**:
  - `hive_watchdog.py`: 서버 자동 재시작 `restart_server()` 추가
  - `hive_hook.py`: Gemini↔Claude 메시지 폴링 `read_messages()` 추가
  - `skill_orchestrator.py`: 스킬 결과 영구 저장 → `skill_results.jsonl`
- **[2026-03-01] v3.6.8 파일 탐색기 VS Code 스타일 UI 복원 (Gemini CLI)**:
  - 호버 액션, 인라인 편집, 컨텍스트 메뉴 확장
- **[2026-02-28] v3.5.8 배포 버전 경로 버그 수정 (Claude)**:
  - server.py frozen 모드 DATA_DIR 버그, hive_bridge.py 절대경로 패치
- **[2026-02-27] v3.5.7 벡터 DB 제거 (Claude)**:
  - ChromaDB 의존성 제거, ThoughtTrace 단순화

---
**마지막 업데이트**: 2026-03-01
**관리 에이전트**: Claude (v3.6.10 기준 전체 동기화)
