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
- [ ] **Task 10: Codex CLI 설치 및 초기 설정 스크립트 작성**
    - 파일: `scripts/install_codex.py`
    - 방법: `npm install -g @codex/cli` 명령을 서브프로세스로 실행하고 설치 확인.
    - 검증: `codex --version` 실행 결과 확인.
- [ ] **Task 11: 통합 에이전트 런처 개발**
    - 파일: `scripts/agent_launcher.py` (신규)
    - 방법: `agent`, `mode`를 인자로 받아 `vibe-coding`, `claude`, `codex`를 적절한 플래그(`-y`, `--yolo`)로 실행하는 Python 래퍼 구현.
    - 검증: `python scripts/agent_launcher.py claude yolo` 실행 시 YOLO 모드로 시작되는지 확인.
- [ ] **Task 12: 미션 컨트롤 UI에 Codex 링 및 모드 토글 추가**
    - 파일: `.ai_monitor/mission_control_ui.py`
    - 방법: `AgentRing` 인스턴스에 `Codex` 추가 및 상단에 글로벌 [NORMAL | YOLO] 모드 전환 스위치 구현.
    - 검증: UI에서 Codex 링이 보이고 모드 전환 시 시각적 피드백 확인.
- [ ] **Task 13: 대시보드 및 배치 파일 연동**
    - 파일: `run_vibe.bat`, `run_claude.bat`
    - 방법: 배치 파일에서 `agent_launcher.py`를 호출하도록 수정하여 모드 설정이 반영되도록 함.
    - 검증: `run_vibe.bat` 실행 시 현재 설정된 모드로 에이전트가 자동 시작되는지 확인.

---
**지휘관님, Phase 5 계획이 수립되었습니다. 승인하시면 작업을 시작합니다.**
