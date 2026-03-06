# 🗺️ Vibe-Coding 프로젝트 맵 (PROJECT_MAP.md)

<!--
FILE: PROJECT_MAP.md
DESCRIPTION: 프로젝트 전체 구조와 각 파일의 역할 정의. 모든 에이전트는 작업 시 이 맵을 최신 상태로 유지해야 함.

REVISION HISTORY:
- 2026-03-05 Gemini-1: [합병] 구 master + orchestrate 스킬 통합 반영, v3.7.1 업데이트
- 2026-03-01 Claude: scripts/ 신규 파일 추가, skills/ 구조 반영, v3.6.10 상태 업데이트
- 2026-02-25 Gemini-1: 최초 작성, 하이브 마인드 v3.0 구조 반영
-->

이 파일은 프로젝트의 전체 구조와 각 파일의 역할을 정의합니다. 모든 에이전트는 작업 시 이 맵을 최신 상태로 유지해야 합니다.

## 🏗️ 전체 구조

### 1. 코어 서버 (`.ai_monitor/`)
- `server.py`: 중앙 통제 서버. SSE 로그 스트림 + WebSocket PTY + REST API.
- `_version.py`: 시스템 버전 정보 (`v3.7.1`).
- `updater.py`: 자동 업데이트 모듈.
- `installer.iss`: Inno Setup 인스톨러 생성 스크립트.
- **`data/`**: 실시간 DB 및 로그 저장소.
  - `shared_memory.db` — 에이전트 간 공유 메모리 (SQLite)
  - `hive_mind.db` — 하이브 마인드 태스크/세션 DB
  - `task_logs.jsonl` — 실시간 작업 로그
  - `skill_chain.json` — 오케스트레이터 현재 스킬 체인 상태
  - `skill_results.jsonl` — 스킬 실행 결과 영구 기록

### 2. 통합 브릿지 및 메모리 (`scripts/`)
- `memory.md`: **[신규]** 루트 폴더의 장기 기억 저장소. 사용자 선호도 및 기술적 결정 사항 영구 기록.
- `memory.py`: 공유 메모리(SQLite) 관리 헬퍼. `python scripts/memory.py list`
- `rules_validator.py`: **[신규]** RULES.md 준수 여부 자동 검증기.
- `lock_manager.py`: **[신규]** 에이전트 간 파일 수정 충돌 방지(Locking) 도구.
- `git_visualizer.py`: **[신규]** 에이전트 상황 판단용 Git 상태 시각화 도구.
- `setup_hive_pg.py`: **[신규]** 포터블 PostgreSQL 18 + pgvector + PGMQ 자동 설치 및 초기화 도구.
- `pg_manager.py`: **[신규]** 하이브 마인드 슈퍼 DB(PostgreSQL 5433) 통합 제어 매니저 (Vector, Search, MQ 활성화).

- `hive_bridge.py`: 에이전트 작업 로그 전송 브릿지.
- `hive_watchdog.py`: 시스템 자가 복구 엔진 (서버 자동 재시작).
- `orchestrator.py`: AI 오케스트레이터 기본 모듈.
- `skill_orchestrator.py`: 스킬 체인 상태 추적 + 대시보드 연동.
- `send_message.py`: 에이전트 간 메시지 전송 CLI.
- `task.py`: 태스크 보드 관리 CLI.

### 3. 스킬 시스템
- **`.gemini/skills/`**: Gemini CLI용 하이브 마인드 공통 스킬 지침
  - `orchestrate/` — **[통합]** 구 `master` + `orchestrate` 합병 (Hive Control Tower)
  - `brainstorming/`, `code-review/`, `debug/`, `execute-plan/`, `write-plan/`
  - `pattern-vibe/`, `pattern-view/`, `release/`, `tdd/`, `vibe-heal/`
- `skills/claude/`: Claude Code용 스킬 지침 (명령어/훅 연동)

### 4. 사용자 인터페이스 및 배포
- `run_vibe.bat`: 시스템 실행 배치 파일.
- `vibe-coding-setup-3.7.1.exe`: 최신 인스톨러.

## 🕒 최근 주요 변경 사항
- **[2026-03-05] v3.7.1 스킬 시스템 대통합 (Gemini CLI)**:
  - **`master` 스킬 삭제**: `orchestrate` 스킬로 기능 완전 통합.
  - UI(Mission Control) 명칭을 `orchestrate`로 통일.
  - 불필요한 예시 파일 및 구버전 설치 파일(v3.6.5, v3.7.0) 정리.
- **[2026-03-01] v3.6.10 세션 자동 저장 + 양방향 메시지 연결 (Claude)**:
  - `scripts/hive_hook.py`: Claude Code 세션 스냅샷 자동 저장
  - `scripts/gemini_hook.py`: Gemini 세션 스냅샷 + Claude↔Gemini 메시지 연결
- **[2026-03-01] v3.6.9 하이브 마인드 3가지 기능 추가 (Claude)**:
  - `hive_watchdog.py`: 서버 자동 재시작 `restart_server()` 추가
  - `skill_orchestrator.py`: 스킬 결과 영구 저장 → `skill_results.jsonl`

---
**마지막 업데이트**: 2026-03-05
**관리 에이전트**: Gemini (v3.7.1 기준 전체 동기화)
