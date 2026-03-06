# 🧠 하이브 마인드 장기 기억 (memory.md)

<!--
FILE: memory.md
DESCRIPTION: 프로젝트의 핵심 기술적 결정, 사용자 선호도, 아키텍처 원칙 및 과거의 실수/해결책 기록소.
             모든 에이전트는 작업 시작 전(0단계) 이 파일을 반드시 숙지해야 함.

REVISION HISTORY:
- 2026-03-06 Gemini: 최초 작성. 하이브 고도화 4단계(장기 기억) 반영 및 핵심 규칙 통합.
-->

이 파일은 프로젝트의 '영혼'과 같습니다. 기술적인 지식뿐만 아니라 사용자의 취향과 작업 스타일을 기록하여 에이전트의 지능을 연속적으로 유지합니다.

## 🌟 1. 사용자 선호도 및 작업 스타일 (User Preferences)
- **언어**: 모든 출력, 주석, 답변은 반드시 **상세한 한국어**여야 함.
- **도구 활용**: `rules_validator.py`를 통한 자체 검증을 선호함.
- **디자인**: 시각적으로 풍부한 대시보드 및 터미널 출력(이모지 활용 등)을 선호함.
- **엄격성**: 레거시 코드를 방치하거나 규칙을 어기는 것을 매우 싫어함.

## 🏗️ 2. 핵심 아키텍처 및 결정 사항 (Technical Decisions)
- **오케스트레이션**: `skill_orchestrator.py`가 상태를 총괄하며, `lock_manager.py`로 파일 충돌을 방지함.
- **Git 전략**: `git_visualizer.py`를 통해 워크트리 상태를 상시 확인하며, 메인 브랜치 직접 수정 금지.
- **주석 표준**: 모든 파일 상단에 `FILE:`, `DESCRIPTION:`, `REVISION HISTORY:` 템플릿이 필수임.
- **데이터 저장**: 실시간 로그는 `.ai_monitor/data/` 하위의 `.jsonl` 및 `.db` 파일에 저장됨.

## ⚠️ 3. 자주 발생하는 실수 및 방어책 (Common Mistakes & Guardrails)
- **[실수]** Python `re.findall`에서 전역 플래그(`(?s)`)를 중간에 사용하는 오류.
  - **[방어]** 반드시 플래그를 정규식 맨 앞에 위치시킬 것.
- **[실수]** `PROJECT_MAP.md`에 신규 파일을 등재하지 않는 망각.
  - **[방어]** `rules_validator.py`가 이를 체크하므로 항상 실행할 것.
- **[실수]** 다른 에이전트가 작업 중인 파일을 건드려 충돌 발생.
  - **[방어]** 작업 전 반드시 `lock_manager.py acquire`로 소유권을 확보할 것.

## 🔗 4. 지식 간의 관계 (Knowledge Graph)
- `server.py` → `dashboard.py` (SSE 스트림 의존성)
- `skill_orchestrator.py` → `skill_chain.db` (상태 영속화)
- `rules_validator.py` → `RULES.md` (검증 기준 정의)

---
**마지막 업데이트**: 2026-03-06
**관리 에이전트**: Gemini (Hive Mind System Architect)
