# 🗺️ 프로젝트 하이브 마인드 맵 (Project Map)

이 문서는 AI Monitor(vibe-coding) 프로젝트의 전체 구조와 파일별 역할을 정의합니다. 모든 에이전트는 파일 수정 시 이 지도를 최신 상태로 유지해야 합니다.

## 📁 루트 디렉토리 (Root)
- `ai_monitor_plan.md`: 프로젝트 전체 개발 로드맵 및 단계별 목표.
- `PROJECT_MAP.md`: (본 문서) 프로젝트 구조 및 파일 역할 정의서.
- `RULES.md`: AI 에이전트 간 협업 및 작업 수행을 위한 절대 원칙 (2026-02-25 표준 주석 규칙 강화).
- `GEMINI.md`: 프로젝트 헌법 및 하이브 마인드 운영 지침.
- `CLAUDE.md`: Claude 전용 구현 가이드 및 스타일 가이드.

## ⚙️ 코어 엔진 (`.ai_monitor/`)
- `server.py`: 에이전트 간 메시지 중계 및 데이터 관리를 담당하는 FastAPI 서버.
  - **기능 추가**: 자가 치유(Self-Healing) 엔진 통합, 건강 상태 체크 및 스킬 생성 API.
- `config.json`: 시스템 설정 및 환경 변수 관리.
- **`data/`**: 데이터베이스 및 로그 저장소.
  - `hive_health.json`: (NEW) 시스템 건강 상태 실시간 진단 데이터.
  - `skill_analysis.json`: (NEW) 작업 로그 기반 스킬 추출 데이터.

## 🌐 대시보드 프론트엔드 (`.ai_monitor/vibe-view/`)
- `src/App.tsx`: 대시보드 메인 컴포넌트 및 레이아웃.
  - **기능 추가**: 실시간 HUD, 스킬 주입 안전장치, 원클릭 경로 주입(Pinning), 시각적 Diff 뷰어.
- `src/main.tsx`: React 애플리케이션 엔트리 포인트.

## 🛠️ 통합 및 브릿지 스크립트 (`scripts/`)
- `hive_bridge.py`: 에이전트의 작업 로그를 서버로 전송하는 통신 브릿지.
- `hive_watchdog.py`: (NEW) 24/7 자가 치유 엔진. DB 및 메모리 자동 복구.
- `skill_analyzer.py`: (NEW) 작업 패턴 분석 및 스킬 자동 생성기.

## 📂 하이브 스킬 시스템 (`.gemini/skills/`)
- `master/`: 중앙 컨트롤 타워 및 지능형 오케스트레이션 지침 (TDD/디버깅 연동).
- `brainstorming/`: (NEW) 6단계 브레인스토밍 절차 및 승인 워크플로우.

---
**마지막 업데이트:** 2026-02-26 - [Gemini-1] 하이브 에볼루션 v4.0 (자가 치유 및 지식 자동화) 적용
