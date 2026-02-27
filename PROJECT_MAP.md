# 🗺️ Vibe-Coding 프로젝트 맵 (PROJECT_MAP.md)

이 파일은 프로젝트의 전체 구조와 각 파일의 역할을 정의합니다. 모든 에이전트는 작업 시 이 맵을 최신 상태로 유지해야 합니다.

## 🏗️ 전체 구조

### 1. 코어 서버 (`.ai_monitor/`)
- `server.py`: FastAPI 기반 중앙 통제 서버. 에이전트 로그 중계 및 DB 관리. (v3.5.1: `/api/hive/logs` 추가)
- `_version.py`: 시스템 버전 정보 (`v3.5.1`).
- `vibe-coding.spec`: PyInstaller 빌드 설정 파일.
- `installer.iss`: Inno Setup 인스톨러 생성 스크립트.
- **`data/`**: (개발 모드) SQLite DB 및 로그 파일 저장소.
- **`vibe-view/`**: React/TypeScript 기반 모니터링 대시보드 프론트엔드. (v3.5.1: 로그 익스플로러 탭 추가)

### 2. 통합 브릿지 및 메모리 (`scripts/`)
- `memory.py`: 에이전트 간 공유 메모리(SQLite) 관리 헬퍼. 배포 버전 경로 대응 완료.
- `vector_memory.py`: 로컬 벡터 DB(ChromaDB) 기반 장기 기억 엔진.
- `hive_bridge.py`: 에이전트 작업 로그를 서버로 전송하는 통신 브릿지.
- `hive_watchdog.py`: 시스템 상태 감시 및 자가 복구 엔진.

### 3. 사용자 인터페이스 및 배포
- `run_vibe.bat`: 시스템 실행 배치 파일.
- `repair_env.bat`: 환경 복구 도구.
- `dist/vibe-coding-v3.5.1.exe`: 빌드된 독립 실행 파일.

## 🕒 최근 주요 변경 사항
- **[2026-02-27] v3.5.1 빌드 완료**: 
  - 하이브 통합 로그 익스플로러 GUI 추가.
  - 액티비티 바에 로그 아이콘(`ScrollText`) 및 실시간 로그 수 배지 추가.
  - 검색 및 에이전트별 필터링 기능 구현.
- **[2026-02-27] v3.5.0 빌드 완료**: 
  - 배포 버전(Installer)에서 데이터 경로(`%APPDATA%`) 불일치 문제 해결.
  - ChromaDB 및 SQLite 배포 번들링 안정화.

---
**마지막 업데이트**: 2026-02-27
**관리 에이전트**: Gemini-1 (Master)
