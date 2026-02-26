"""
FILE: docs/VIBE_PROJECT_GUIDE.md
DESCRIPTION: Vibe-Coding (AI Monitor) 프로젝트의 전체 구조, 철학 및 운영 가이드
REVISION HISTORY:
- 2026-02-26 Gemini-1: 프로젝트 분석을 통한 종합 가이드 문서 생성 및 docs 폴더 이동 관리
"""

# 🚀 Vibe-Coding: 하이브 마인드 AI 모니터 가이드

이 문서는 다중 AI 에이전트(Gemini, Claude)가 협업하는 **하이브 마인드(Hive Mind)** 환경을 구축하고 모니터링하는 **Vibe-Coding (AI Monitor)** 프로젝트의 전체 안내서입니다.

---

## 🧠 1. 핵심 철학: 하이브 마인드 (Hive Mind)
본 프로젝트는 개별 AI 에이전트가 독립적으로 작업하는 것을 넘어, 지식을 공유하고 서로의 사고 과정을 감시하며 보완하는 **단일 지능체계**를 지향합니다.

- **SSOT (Single Source of Truth)**: 모든 에이전트의 로그와 공유 메모리는 중앙 DB(`hive_mind.db`, `shared_memory.db`)에서 관리됩니다.
- **장기 기억 (Long-term Memory)**: Vector DB(`chromadb`)를 활용하여 과거의 결정 사항과 코드 패턴을 시맨틱 검색으로 로드합니다.
- **자가 치유 (Self-Healing)**: `hive_watchdog.py`가 시스템의 건강 상태를 체크하고 오류를 자동 복구합니다.

---

## 🏗️ 2. 전체 시스템 구조 (System Architecture)

### ⚙️ 코어 시스템 (`.ai_monitor/`)
시스템의 심장부로, 데이터 처리와 서버 기능을 담당합니다.
- `server.py`: FastAPI 기반 중앙 허브 서버.
- `config.json`: 시스템 전역 설정 파일.
- **`data/`**: 하이브 마인드의 기억 저장소 (SQLite, JSONL, Vector DB).
- **`vibe-view/`**: React 기반의 실시간 모니터링 대시보드 (HUD).

### 🛠️ 통합 브릿지 & 유틸리티 (`scripts/`)
에이전트와 시스템을 연결하는 핵심 로직들입니다.
- `hive_bridge.py`: 에이전트 작업 로그 전송 브릿지.
- `memory.py` & `vector_memory.py`: 공유 지식 및 장기 기억 관리.
- `hive_watchdog.py`: 시스템 상태 모니터링 및 자가 치유.
- `agent_protocol.py`: 에이전트 간 협업(RFC) 프로토콜.
- **`utils/`**: 아이콘 변환 및 기타 보조 유틸리티 스크립트.

### 📂 지능형 스킬 시스템
에이전트가 상황에 따라 로드하는 전문 워크플로우입니다.
- `.gemini/skills/`: Gemini 전용 전문 스킬 (Master, Brainstorming 등).
- `.claude/commands/`: Claude 전용 인터랙티브 명령 셋.

---

## ⚙️ 3. 주요 운영 워크플로우

1. **분석 및 계획**: 마스터 스킬이 요청을 분석하고 본 가이드를 기반으로 전략 수립.
2. **실행 (TDD)**: 테스트 코드를 먼저 작성하고 기능을 구현.
3. **동기화**: 작업 완료 후 `hive_bridge.py`로 로그를 남기고 지식베이스 업데이트.
4. **검증**: `verify_ui.js` 또는 린팅 도구를 통해 최종 품질 확인.

---

## 🔮 4. 미래 로드맵 (Future Roadmap)

- **단계 1: 지능형 장기 기억 고도화**: 벡터 DB 검색 성능 최적화 및 에이전트 컨텍스트 자동 주입.
- **단계 2: 사고 과정 시각화 (ThoughtTrace)**: 프론트엔드에서 노드 그래프 형식으로 AI의 판단 근거 시각화.
- **단계 3: 에이전트 협업 RFC**: 에이전트가 스스로 다른 에이전트에게 작업을 요청하고 피드백을 받는 시스템 공식화.

---
**최종 업데이트**: 2026-02-26
**관리 에이전트**: Gemini-1 (Master)
