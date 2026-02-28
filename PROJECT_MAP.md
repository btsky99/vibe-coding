# 🗺️ Vibe-Coding 프로젝트 맵 (PROJECT_MAP.md)

이 파일은 프로젝트의 전체 구조와 각 파일의 역할을 정의합니다. 모든 에이전트는 작업 시 이 맵을 최신 상태로 유지해야 합니다.

## 🏗️ 전체 구조

### 1. 코어 서버 (`.ai_monitor/`)
- `server.py`: FastAPI 기반 중앙 통제 서버. 에이전트 로그 중계 및 DB 관리. (v3.6.0: 파일 관리 API 안정화)
- `_version.py`: 시스템 버전 정보 (`v3.6.0`).
- `vibe-coding.spec`: PyInstaller 빌드 설정 파일.
- `installer.iss`: Inno Setup 인스톨러 생성 스크립트.
- **`data/`**: (개발 모드) SQLite DB 및 로그 파일 저장소.
- **`vibe-view/`**: React/TypeScript 기반 모니터링 대시보드 프론트엔드. (v3.6.0: VS Code 스타일 사이드바 UI 복원)

### 2. 통합 브릿지 및 메모리 (`scripts/`)
- `memory.py`: 에이전트 간 공유 메모리(SQLite) 관리 헬퍼. 배포 버전 경로 대응 및 인코딩 패치 완료.
- `vector_memory.py`: 로컬 벡터 DB(ChromaDB) 기반 장기 기억 엔진. (v3.5.7 이후 비활성)
- `hive_bridge.py`: 에이전트 작업 로그를 서버로 전송하는 통신 브릿지.
- `hive_watchdog.py`: 시스템 상태 감시 및 자가 복구 엔진.
- `auto_version.py`: 빌드 시 버전 번호를 자동으로 증가시키는 유틸리티.

### 3. 사용자 인터페이스 및 배포
- `run_vibe.bat`: 시스템 실행 배치 파일.
- `repair_env.bat`: 환경 복구 도구.
- `dist/vibe-coding-v3.6.0.exe`: 빌드된 독립 실행 파일.

## 🕒 최근 주요 변경 사항
- **[2026-03-01] v3.6.0 VS Code 스타일 사이드바 UI 완벽 복원 (Gemini CLI)**:
  - **호버 액션 버튼**: 사이드바 파일/폴더 호버 시 우측에 (경로 복사, 이름 변경, 삭제, 새 파일/폴더) 버튼 그룹 노출.
  - **인라인 편집(Inline Rename)**: 파일 이름 클릭 시 즉시 수정 가능한 input 박스 전환 (VS Code UX).
  - **컨텍스트 메뉴 확장**: 우클릭 메뉴에 경로 복사 및 이름 변경 항목 추가.
  - **트리/플랫 뷰 통합**: 모든 뷰 모드에서 일관된 파일 관리 경험 제공.
- **[2026-02-28] v3.5.8 배포 버전 경로 버그 수정 (Claude)**:
  - server.py `_load_task_logs_into_thoughts()`: frozen 모드에서 DATA_DIR 미정의 시 APPDATA 직접 참조.
  - hive_bridge.py: CWD 상대경로 → `__file__` 기준 절대경로 + frozen APPDATA 지원.
  - memory.py: `VECTOR_AVAILABLE` 미정의 NameError 버그 수정.
- **[2026-02-27] v3.5.7 벡터 DB 제거**:
  - ChromaDB 의존성 제거 및 ThoughtTrace 단순화.
- **[2026-02-27] v3.5.5 파일 탐색기 컨텍스트 메뉴 도입**:
  - 다크 네온 스타일 우클릭 메뉴 및 기본 파일 관리 기능 추가.

---
**마지막 업데이트**: 2026-03-01
**관리 에이전트**: Gemini CLI (Master Orchestrator)
