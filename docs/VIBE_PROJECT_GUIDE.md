"""
FILE: docs/VIBE_PROJECT_GUIDE.md
DESCRIPTION: Vibe-Coding (AI Monitor) 프로젝트의 전체 구조, 철학 및 운영 가이드 (v5.0 최신화)
REVISION HISTORY:
- 2026-03-19 Gemini: PostgreSQL 18 기반 아키텍처 및 Multi-LLM 자율 협업 체계 반영
- 2026-02-26 Gemini-1: 최초 작성
"""

# 🚀 Vibe-Coding: 하이브 마인드 AI 모니터 가이드

이 문서는 다중 AI 에이전트(Gemini, Claude, Codex)가 협업하는 **하이브 마인드(Hive Mind)** 환경을 구축하고 모니터링하는 **Vibe-Coding (AI Monitor)** 프로젝트의 통합 안내서입니다.

---

## 🧠 1. 핵심 철학: 하이브 마인드 (Hive Mind)
본 프로젝트는 개별 AI 에이전트의 독립적인 작업을 넘어, 지능을 결합하고 사고 과정을 실시간으로 공유하는 **단일 초지능 체계**를 지향합니다.

- **Postgres-First (SSOT)**: 모든 로그, 사고 과정(Thoughts), 공유 메모리는 PostgreSQL 18(Port 5433)에서 중앙 집중 관리됩니다.
- **자율 오케스트레이션**: `auto_dispatcher.py`와 `orchestrator.py`가 에이전트의 역량과 부하를 분석하여 태스크를 자동으로 분배합니다.
- **실시간 MUX 통신**: cmux 스타일의 터미널 멀티플렉서(`vibe_mux.py`)를 통해 에이전트 간 텍스트 직접 주입 및 제어가 가능합니다.
- **자가 치유 (Self-Healing)**: `hive_watchdog.py`가 시스템 상태를 감시하고 장애 발생 시 자동으로 복구합니다.

---

## 🏗️ 2. 전체 시스템 구조 (System Architecture)

### ⚙️ 코어 서버 시스템 (`.ai_monitor/`)
시스템의 중추로, 데이터 영속성과 에이전트 중계를 담당합니다.
- `server.py`: HTTP/WebSocket/SSE 기반의 중앙 제어 서버.
- **`api/`**: 도메인별 REST API 핸들러 (hive, vibe, agent, git, mcp 등).
- **`src/`**: PostgreSQL 스토어(`pg_store.py`) 및 핵심 비즈니스 로직.
- **`bin/pgsql/`**: 포터블 PostgreSQL 18 바이너리 및 데이터.
- **`vibe-view/`**: React + Vite 기반의 차세대 모니터링 대시보드 (Mission Control).

### 🛠️ 자율 협업 도구 (`scripts/`)
에이전트의 능력을 확장하고 협업을 조율하는 스크립트군입니다.
- `auto_dispatcher.py`: 멀티 에이전트 태스크 디스패처.
- `vibe_cli.py` & `vibe_mux.py`: cmux 호환 CLI 및 터미널 제어 도구.
- `hive_bridge.py`: PostgreSQL 기반 통합 로깅 및 협업 브릿지.
- `itcp.py`: 에이전트 간 통신 프로토콜 (Inter-Terminal Communication Protocol).

### 📂 지능형 스킬 시스템 (`.gemini/skills/`, `.claude/skills/`)
각 에이전트가 상황에 맞춰 로드하여 실행하는 전문 워크플로우 단위입니다.

---

## 📡 3. 주요 API 및 인터페이스

상세한 API 명세는 **[API_SPEC.md](./API_SPEC.md)** 문서를 참조하십시오.

- **Hive API**: 태스크 관리, 사고 과정 기록, 메시징.
- **Vibe API**: 실시간 알림, 에이전트 진행률 및 상태 업데이트.
- **MUX API**: 터미널 제어 및 텍스트 주입.
- **Dispatcher API**: 자율 태스크 분배 및 협업 제어.

---

## 🔮 4. 로드맵 및 향후 과제

- **P6 완료**: cmux 스타일 터미널 MUX 및 에이전트 간 직접 소통 체계 구축.
- **P7 예정**: 지식 그래프 기반의 자율적 문제 해결 엔진 (Self-Solving Engine).
- **P8 예정**: 완전 자율 하이브리드 에이전트 팀 (Fully Autonomous Hybrid Team).

---
**최종 업데이트**: 2026-03-19
**관리 에이전트**: Gemini (Hive Mind Architect)
