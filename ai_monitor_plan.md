<!--
FILE: ai_monitor_plan.md
DESCRIPTION: 하이브 마인드 고도화 및 신규 기능 구현 로드맵
REVISION HISTORY:
- 2026-03-09 Gemini: Phase 6 (하이브 초지능 고도화 4대 과제) 기획 추가
-->
# AI Mission Control (Windows Native) Implementation Plan

## 🎯 Goal
Build a high-performance, native Windows "Mission Control" center inspired by CMUX.
- **Minimal Widget:** System tray icon showing agent status (Pulsing colors).
- **Sidebar HUD:** A slide-in, semi-transparent native window (PySide6) showing real-time hive logs and agent status rings.
- **Terminal Status:** A thin status line at the bottom of the terminal.

## 🛠️ Tech Stack
- **UI:** PySide6 (Qt for Python)
- **Data:** Real-time monitoring of `.ai_monitor/data/task_logs.jsonl` and `hive_mind.db`.
- **Communication:** Local server API (`server.py`) + Watchdog for file changes.

## 📝 Task Breakdown

### Phase 1: Foundation & Dependencies
- [x] **Task 1: Add PySide6 to requirements.txt**
- [x] **Task 2: Create Mission Control Core Script**

### Phase 2: Minimal Widget (Tray Icon)
- [x] **Task 3: Implement Tray Icon Status Logic**
- [x] **Task 4: Implement Tray Pulse Animation**

### Phase 3: Sidebar HUD (Slide-in UI)
- [x] **Task 5: Create Sidebar Window UI**
- [x] **Task 6: Implement Agent Status Rings**
- [x] **Task 7: Real-time Hive Log Streaming**

### Phase 4: Terminal Integration
- [x] **Task 8: Create Terminal Status Bar Helper**
- [x] **Task 9: Hook into run_vibe.bat**

### Phase 5: Agent Expansion & Execution Modes (Current)
- [x] **Task 10: Codex CLI 설치 및 초기 설정 스크립트 작성**
    - 파일: `scripts/install_codex.py`
    - 방법: `npm install -g @openai/codex` 명령을 서브프로세스로 실행하고 설치 확인.
    - 검증: `codex --version` 실행 결과 확인.
- [x] **Task 11: 통합 에이전트 런처 개발**
    - 파일: `scripts/agent_launcher.py` (신규)
    - 방법: `agent`, `mode`를 인자로 받아 `vibe`, `claude`, `codex`를 적절한 플래그(`--yolo`, `--dangerously-skip-permissions`)로 실행하는 Python 래퍼 구현.
    - 검증: `python scripts/agent_launcher.py claude yolo` 실행 시 YOLO 모드로 시작.
- [x] **Task 12: 미션 컨트롤 UI에 Codex 링 및 모드 토글 추가**
    - 파일: `.ai_monitor/mission_control_ui.py`
    - 방법: `AgentRing` 인스턴스에 `Codex`(주황) 추가 및 상단에 `ModeToggle` 위젯(NORMAL/YOLO 버튼) 구현.
    - 검증: UI에서 Codex 링이 보이고 모드 전환 시 버튼 색상 피드백 및 config.json 저장 확인.
- [x] **Task 13: 대시보드 및 배치 파일 연동**
    - 파일: `run_vibe.bat`, `run_claude.bat`
    - 방법: 배치 파일에서 `agent_launcher.py`를 호출하도록 수정하여 저장된 모드가 자동 반영되도록 함.
    - 검증: `run_vibe.bat` 실행 시 현재 설정된 모드로 에이전트가 자동 시작.

### Phase 6: 하이브 초지능 고도화 4대 과제 (Super Intelligence)
- [ ] **Task 14: 로그 아키텍처의 완전한 통합 (PostgreSQL)**
    - [ ] **Task 14-1: PostgreSQL 로그 테이블 및 실시간 알림 트리거 생성**
        - 파일: `scripts/pg_manager.py` (또는 신규 `scripts/init_log_db.sql`)
        - 방법: `hive_logs` 테이블 생성 및 로그 삽입 시 `NOTIFY`를 호출하는 트리거 SQL 작성/실행 로직 추가.
        - 검증: `psql`에서 직접 로그 삽입 시 `LISTEN` 채널에 신호 오는지 확인.
    - [ ] **Task 14-2: 통합 로거의 PostgreSQL 핸들러 구현**
        - 파일: `scripts/logger.py`
        - 방법: `psycopg2` 또는 `asyncpg`를 사용하여 로그를 DB에 저장하는 클래스 구현. 비동기 큐 처리로 성능 최적화.
        - 검증: `python scripts/logger.py "Test Log"` 실행 후 DB에 기록 확인.
    - [ ] **Task 14-3: server.py를 PostgreSQL LISTEN 기반 SSE로 전환**
        - 파일: `server.py`
        - 방법: 기존 `.jsonl` 파일 감시 루프를 제거하고, DB `LISTEN` 채널을 구독하는 비동기 SSE 엔드포인트 구현.
        - 검증: `/stream/logs` 호출 시 실시간 데이터 수신 확인.
    - [ ] **Task 14-4: 미션 컨트롤 UI의 데이터 소스 전환 및 검증**
        - 파일: `.ai_monitor/mission_control.py`, `.ai_monitor/mission_control_ui.py`
        - 방법: UI에서 파일 대신 SSE 엔드포인트를 구독하여 로그 표시하도록 수정.
        - 검증: 에이전트 동작 시 UI HUD에 즉각적인 로그 스트리밍 확인.
- [ ] **Task 15: "하이브 토론(Hive Debate)" 모드 활성화 및 UI 연동**
    - 내용: `scripts/hive_debate.py`를 미션 컨트롤 UI와 연동. 복잡한 설계 결정 시 Gemini vs Claude 토론 과정을 HUD에 실시간 중계 및 사용자 승인(Approve) 기능 구현.
- [ ] **Task 16: 에이전트 권한 및 리소스 제어(Sandbox) 강화**
    - 내용: `safety_guard.py` 로직 강화. 프로세스 단위 리소스(CPU/Mem) 모니터링/제한 및 네트워크 통신 보호를 추가하여 YOLO 모드의 안전성 보장.
- [ ] **Task 17: 하이브 기억(Memory)의 지식 그래프 시각화**
    - 내용: `memory.md` 및 `pg_thoughts` 데이터를 분석하여 기술적 결정 계보를 보여주는 지식 그래프(Knowledge Graph) 컴포넌트를 대시보드에 렌더링.

---
**지휘관님, Phase 6 (초지능 고도화 4대 과제) 계획이 수립되었습니다.**