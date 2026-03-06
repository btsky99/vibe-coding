# 🗺️ 바이브 코딩 (Vibe Coding) 프로젝트 맵 (PROJECT_MAP.md)

이 파일은 하이브 마인드의 전체 구조와 각 파일의 핵심 역할을 정의합니다. (2026-03-06 Gemini-1 고도화)

## 🧠 프로젝트 인프라 (Infrastructure)
- **`PROJECT_MAP.md`**: (필독) 프로젝트 전체 지도 및 파일 역할 가이드.
- **`RULES.md`**: (필독) 에이전트 행동 수칙, 한글 주석/커밋 표준, 하이브 마인드 운영 원칙.
- **`ai_monitor_plan.md`**: 하이브 마인드 고도화 및 신규 기능 구현 로드맵.
- **`memory.md`**: 프로젝트 장기 기억 및 주요 기술적 결정 사항 보관소.

## 🛰️ 하이브 마인드 및 오케스트레이션 (Hive Mind)
- **`scripts/hive_bridge.py`**: [Postgres-First] 모든 에이전트의 작업/사고 로그를 PostgreSQL 18로 통합 전송하는 핵심 브릿지.
- **`scripts/orchestrator.py`**: 하이브 마스터 조율기. 에이전트 상태 감시 및 사고 과정(Thought)을 Postgres `JSONB`로 기록.
- **`scripts/analyze_hive.py`**: [신규] PostgreSQL 18 데이터를 분석하여 에이전트 기여도 및 사고 연쇄 보고서 생성.
- **`scripts/pg_manager.py`**: PostgreSQL 18 서버 관리 및 확장 기능(Vector, MQ, Search) 제어.
- **`.ai_monitor/server.py`**: 하이브 대시보드 백엔드. Postgres 연동 API 및 실시간 SSE 스트리밍 제공.

## 📂 핵심 스크립트 (Core Scripts)
- **`scripts/auto_version.py`**: 배포 시 버전 자동 업데이트 및 동기화 도구.
- **`scripts/terminal_agent.py`**: 사용자 터미널 조율 및 에이전트 실행 헬퍼.
- **`scripts/memory.py`**: 공유 메모리(`shared_memory.db`) 관리 및 시맨틱 검색 인터페이스.

## 🏗️ 빌드 및 설치 (Build & Installer)
- **`vibe-coding.spec`**: PyInstaller 실행 파일 빌드 설정.
- **`vibe-coding-setup.iss`**: Inno Setup 인스톨러 생성 스크립트.
- **`run_vibe.bat`**: 하이브 서버 및 대시보드 실행 배치 파일.

---
> **[AI 에이전트 주의]** 하이브의 모든 정보는 이제 PostgreSQL 18을 원천 데이터로 사용합니다.
