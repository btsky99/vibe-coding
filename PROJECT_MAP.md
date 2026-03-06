# 🗺️ 바이브 코딩 (Vibe Coding) 프로젝트 맵 (PROJECT_MAP.md)

이 파일은 하이브 마인드의 전체 구조와 각 파일의 핵심 역할을 정의합니다. (2026-03-06 Gemini-1 초지능 고도화)

## 🧠 프로젝트 인프라 (Infrastructure)
- **`PROJECT_MAP.md`**: (필독) 프로젝트 전체 지도 및 파일 역할 가이드.
- **`RULES.md`**: (필독) 에이전트 행동 수칙, 한글 주석/커밋 표준, 하이브 마인드 운영 원칙.
- **`ai_monitor_plan.md`**: 하이브 마인드 고도화 및 신규 기능 구현 로드맵.
- **`ActivityBar.tsx`**: 좌측 액티비티 바 — HiveEngineStatus(3단계 LED 링 + 자가 치유 dot) 최상단 통합. globalPipelineStage/hiveHealth 수신.
- **`App.tsx`**: 최상위 레이아웃 — globalPipelineStage(agentTerminals 파생) + isHealingActive(hiveHealth 파생) + onNavigateToAgent를 ActivityBar에 전달.
- **`TerminalSlot.tsx`**: 터미널 슬롯 — 모니터링 뷰 슬림화(max-h 160px, 헤더 h-5). 파이프라인 단계는 ActivityBar LED로 통합.
- **`memory.md`**: 프로젝트 장기 기억 및 주요 기술적 결정 사항 보관소.

## 🛸 하이브 "초지능" 고도화 엔진 (Super Intelligence)
- **`scripts/heal_daemon.py`**: [Step 1] 에러 실시간 감시 및 자율 수리(Self-Healing) 엔진.
- **`scripts/knowledge_sync.py`**: [Step 2] 전역 코드 및 지식 임베딩(Vector DB) 통합 엔진.
- **`scripts/hive_debate.py`**: [Step 3] Gemini vs Claude 끝장 토론 및 최적 설계 도출 엔진.
- **`scripts/auto_release.py`**: [Step 4] 빌드, 패키징, 릴리즈 자동화(Autonomous Release) 엔진.

## 🛰️ 하이브 마인드 및 오케스트레이션 (Hive Mind Core)
- **`scripts/hive_bridge.py`**: [Postgres-First] 작업/사고 로그 통합 전송 브릿지.
- **`scripts/orchestrator.py`**: 하이브 마스터 조율기. 사고 과정(Thought) JSONB 기록.
- **`scripts/analyze_hive.py`**: Postgres 데이터를 분석하여 하이브 상태 분석 보고서 생성.
- **`scripts/pg_manager.py`**: PostgreSQL 18 서버 관리 및 확장 기능 제어.

## 🏗️ 빌드 및 설치 (Build & Installer)
- **`vibe-coding.spec`**: PyInstaller 실행 파일 빌드 설정.
- **`vibe-coding-setup.iss`**: Inno Setup 인스톨러 생성 스크립트.
- **`run_vibe.bat`**: 하이브 서버 및 대시보드 실행 배치 파일.

---
> **[AI 에이전트 주의]** 모든 초지능 엔진은 PostgreSQL 18 인프라 위에서 자율적으로 작동합니다.
