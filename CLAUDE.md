# Vibe Coding - Claude Code 프로젝트 가이드

## 프로젝트 구조
- `.ai_monitor/` - 메인 프로젝트 (Python 백엔드 + Nexus View 프론트엔드)
- `.ai_monitor/server.py` - SSE 로그 서버 + WebSocket PTY 서버
- `.ai_monitor/src/view.py` - Textual TUI 콘솔 뷰어
- `.ai_monitor/updater.py` - 자동 업데이트 모듈
- `.ai_monitor/nexus-view/` - React + Vite 프론트엔드
- `.ai_monitor/venv/` - Python 가상환경
- `.github/workflows/build-release.yml` - CI/CD 파이프라인

## 마스터 컨트롤 프로토콜

### 1단계: 요청 의도 분석
요청을 다음 카테고리로 분류하여 처리:
- **에러/버그 수정**: 로그 분석 우선, 근본 원인 파악 후 수정
- **새 기능 구현**: 설계 검토 후 구현, `ai_monitor_plan.md` 참조
- **빌드/배포**: CI 워크플로우 및 PyInstaller spec 파일 확인
- **문서/Git**: Conventional Commits 사용, CHANGELOG 반영

### 2단계: 개발 표준

#### Python
- 가상환경: `.ai_monitor/venv/`
- 린팅: `ruff` 사용
- 타입 힌팅 적극 활용
- 비동기 처리 시 이벤트 루프 블로킹 주의 (특히 GUI 연동)
- 테스트: `pytest` 기반

#### React / 프론트엔드 (nexus-view)
- Server/Client 컴포넌트 분리
- TailwindCSS 사용, 매직 넘버 지양
- 로컬 상태 우선, 전역 상태는 최소화
- Vite 빌드 최적화 유지

#### CI/CD
- GitHub Actions: `.github/workflows/build-release.yml`
- CI 실패 시 각 단계 로그 우선 분석
- 시크릿은 GitHub Secrets로 관리
- PyInstaller로 exe 빌드 (server.py → vibe-coding.exe, src/view.py → vibe-coding_console.exe)
- Inno Setup으로 인스톨러 생성

#### 커밋 표준
- Conventional Commits: `feat:`, `fix:`, `docs:`, `refactor:` 접두사
- 구체적 메시지: "fix(logger): handle empty log file error" 형태
- `git log -n 5`로 기존 스타일 확인 후 일관성 유지

### 3단계: 자동 후처리
코드 수정 완료 후 자동 수행:
1. **문서 동기화**: 변경 사항에 맞게 `ai_monitor_plan.md` 진행 상태 최신화
2. **코드 품질 검증**: 프로젝트 표준 준수 여부 점검
3. **최종 보고**: 결과와 검증/문서 업데이트 내역 간결하게 보고

## GitHub
- 저장소: `btsky99/vibe-coding` (private)
- 자동 업데이트: `updater.py`에서 GitHub Releases API 사용
