<!--
FILE: ai_monitor_plan.md
DESCRIPTION: 설치 버전(배포 EXE) 범용화 — 개발 전용 파일 제거 + 버그 수정
REVISION HISTORY:
- 2026-03-24 Claude: 배포 범용화 계획 수립
-->

# 설치 버전 범용화 — 개발 전용 파일 제거

## 목표
설치 버전(EXE)은 **대시보드 GUI + 터미널 + PostgreSQL** 만 포함하는 범용 도구.
하이브 마인드/오케스트레이션/AI 지침서/스킬은 개발 환경 전용.

## 제거 대상 (EXE 번들에서)
- `CLAUDE.md`, `RULES.md`, `GEMINI.md`, `AGENTS.md`, `PROJECT_MAP.md` — 이 프로젝트 전용 지침서
- `scripts/` — 하이브 훅, 메모리, 디스패처 등 개발용 스크립트
- `.claude/skills/`, `.gemini/skills/` — 이 프로젝트 전용 스킬
- `chromadb`, `pysqlite3` — 미사용 hidden import

## 유지 대상 (EXE 번들에)
- `src/`, `api/`, `bin/` — 코어 모듈
- `vibe-view/dist/` — 프론트엔드
- `pty-server/` — 터미널
- winpty 바이너리 — 터미널 필수
- PostgreSQL 포터블 — DB 필수

---

## 태스크 목록

### Phase 1: 빌드 설정 정리

[x] Task 1: vibe-coding.spec에서 개발 전용 datas 제거
    파일: `.ai_monitor/vibe-coding.spec`
    방법: - datas에서 제거: `.gemini/skills`, `GEMINI.md`, `CLAUDE.md`, `RULES.md`, `PROJECT_MAP.md`, `scripts`
          - hiddenimports에서 제거: `chromadb`, `pysqlite3` (사용 안 함)
          - 유지: `src`, `bin`, `vibe-view/dist`, `api`, `pty-server`(없으면 추가)
    검증: spec 파일 문법 확인

[x] Task 2: build-release.yml에서 개발 전용 번들 제거
    파일: `.github/workflows/build-release.yml`
    방법: - "Bundle skills" 스텝에서 제거: xcopy .gemini\skills, xcopy .claude\skills, copy GEMINI.md, copy CLAUDE.md, copy RULES.md
          - xcopy scripts도 제거 (EXE 내부에 scripts 불필요)
          - Build exe 명령에서 --add-data 제거: skills, .gemini/skills, .claude/skills, scripts, GEMINI.md, CLAUDE.md, RULES.md, PROJECT_MAP.md, AGENTS.md
          - console 빌드도 동일하게 적용
    검증: yml 문법 확인
    의존: Task 1과 독립

[x] Task 3: server.py — frozen 모드에서 스킬/스크립트 복사 로직 비활성화
    파일: `.ai_monitor/server.py`
    방법: - /api/superpowers/install-project (line 2315~): frozen 모드일 때 scripts/CLAUDE.md/GEMINI.md 복사 시도하되, 파일 없으면 조용히 skip (현재 코드가 .exists() 체크하므로 자연스럽게 skip됨 — 확인만)
          - /api/superpowers/install (line 4156~): frozen 모드에서 .gemini/skills 경로 없으면 에러 대신 "설치 버전에서는 스킬이 포함되지 않습니다" 안내 메시지 반환
          - SCRIPTS_DIR (line 932): frozen 모드에서 scripts 폴더 없으면 None으로 설정 + 사용처에서 None 체크 추가
    검증: frozen 모드 시뮬레이션 (SCRIPTS_DIR 경로 없을 때 서버 정상 기동)

### Phase 2: 버그 수정

[x] Task 4: hive_hook.py SyntaxError 수정
    파일: `scripts/hive_hook.py`
    방법: - line 685의 `try: pass` → `except/finally` 블록 없는 문제
          - 해결: try/pass 블록 전체 제거 (Self-Reflect 제거 주석만 남기고 try/pass 삭제)
    검증: `python -m py_compile scripts/hive_hook.py` 통과

[x] Task 5: generate_project_map.py에서 삭제된 config_api.py 참조 제거
    파일: `scripts/generate_project_map.py`
    방법: - line 54의 `"api/config_api.py": "Discord 설정 관리 API"` 딕셔너리 항목 삭제
    검증: 해당 라인 없음 확인

### Phase 3: 검증

[x] Task 6: 전체 빌드 검증
    방법: - `python -m py_compile .ai_monitor/server.py` 통과
          - `python -m py_compile scripts/hive_hook.py` 통과
          - 프론트엔드 빌드: cd .ai_monitor/vibe-view && npm run build
          - spec 파일 문법 확인
    검증: 모든 컴파일/빌드 통과
    의존: Task 1~5 완료 후
