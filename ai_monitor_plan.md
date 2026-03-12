<!--
FILE: ai_monitor_plan.md
DESCRIPTION: 하이브 마인드 고도화 및 신규 기능 구현 로드맵
REVISION HISTORY:
- 2026-03-11 Claude: PostgreSQL 자동 설치 A안 태스크 추가
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
- [x] **Task 14: 로그 아키텍처의 완전한 통합 (PostgreSQL)**
    - [x] **Task 14-1: PostgreSQL 로그 테이블 및 실시간 알림 트리거 생성**
    - [x] **Task 14-2: 통합 로거의 PostgreSQL 핸들러 구현**
    - [x] **Task 14-3: server.py를 PostgreSQL LISTEN 기반 SSE로 전환**
    - [x] **Task 14-4: 미션 컨트롤 UI의 데이터 소스 전환 및 검증**
- [x] **Task 15: 하이브 브레인(Hive Brain) 토론 모드 구현**
    - [x] **Task 15-1: 하이브 토론 상태 관리 및 스키마 확장**
        - 파일: `scripts/pg_manager.py`
        - 방법: `hive_debates` (주제, 상태, 참여자, 최종합의) 및 `hive_debate_messages` (의견, 라운드, 찬반) 테이블 추가.
        - 검증: 토론 주제 생성 및 메시지 삽입 쿼리 정상 작동 확인.
    - [x] **Task 15-2: 하이브 토론 엔진 클래스 구현 (scripts/hive_debate.py)**
        - 파일: `scripts/hive_debate.py` (신규)
        - 방법: `DebateEngine` 클래스 구현. 라운드 기반 토론 진행 (의견 수집 -> 비판 -> 최종 합의) 로직 작성.
        - 검증: `python scripts/hive_debate.py "New Feature Design"` 명령으로 목업 토론 세션 실행 확인.
    - [x] **Task 15-3: 에이전트 프로토콜 통합 (scripts/agent_protocol.py)**
        - 파일: `scripts/agent_protocol.py`
        - 방법: `DebateParticipant` 클래스 구현. 에이전트 페르소나·라운드별 의견 유형·프롬프트 생성·의견 게시 체인 구축.
        - 검증: `python scripts/agent_protocol.py debate 3 claude critique "..."` 실행 시 비판적 의견 정상 게시 확인.
    - [x] **Task 15-4: 미션 컨트롤 UI에 하이브 토론 시각화 HUD 추가**
        - 파일: `.ai_monitor/mission_control_ui.py`
        - 방법: `DebateHUD` 위젯 구현. 진행 중 토론 주제·라운드·상태를 실시간 표시.
        - 검증: UI 사이드바에 토론 정보 출력 확인.
- [x] **Task 16: 에이전트 권한 및 리소스 제어(Sandbox) 강화**
    - 내용: `safety_guard.py` 로직 강화. 시스템 파괴 명령, 권한 남용, 민감 파일 접근( .env, .ssh 등) 차단 패턴 대폭 확장 및 리소스 모니터링 연동 완료.
- [x] **Task 17: 하이브 지식 기억(Memory) 및 지식 그래프 시각화**  
    - 내용: `pg_thoughts` 스키마 고도화(계보 추적용 parent_id 추가) 및 DB 연동 일관성 확보 완료. `memory.md`와 사고 데이터를 분석하여 기술적 결정 계보를 시각화하는 컴포넌트 개발 예정.


---
**지휘관님, Phase 6 (초지능 고도화 4대 과제) 계획이 수립되었습니다.**