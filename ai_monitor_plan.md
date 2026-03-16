<!--
FILE: ai_monitor_plan.md
DESCRIPTION: 프로젝트 전체 보안/성능/품질 고도화 로드맵
REVISION HISTORY:
- 2026-03-16 Claude: P0 보안 5건 + P1 성능/안정성 5건 전부 완료
- 2026-03-16 Claude: P0 보안 + P1 성능/안정성 + P2 코드품질 고도화 계획 수립
-->

# 📋 프로젝트 보안/성능/품질 고도화 (v3.7.79)

**작성일:** 2026-03-16
**목표:** P0 보안 취약점 수정 → P1 성능/안정성 개선 → P2 코드 품질 향상

---

## 🔴 P0: 보안 수정 (Critical) — ✅ 전부 완료

[x] Task 1: SQL 인젝션 수정 — server.py parameterized query 전환
    run_pg_sql() / run_pg_sql_csv()에 params 인자 추가, log_to_pg() / thought_to_pg() 전환

[x] Task 2: SQL 인젝션 수정 — hive_bridge.py parameterized query 전환
    _run_psql()에 params 인자 추가, log_task() / log_thought() 전환

[x] Task 3: 커맨드 인젝션 수정 — /api/launch
    경로 검증(is_dir) + 셸 메타문자 차단 + 모델명 안전문자 검증 추가

[x] Task 4: 경로 순회 수정 — 파일 접근 API 보안 강화
    _validate_file_path() 헬퍼 추가 — 6개 API 엔드포인트 적용
    (/api/read-file, /api/image-file, /api/save-file, /api/files/delete, /api/file-rename, /api/files/create)

[x] Task 5: psycopg2 의존성 등록
    requirements.txt에 psycopg2-binary==2.9.9 추가

## 🟡 P1: 성능/안정성 개선 — ✅ 전부 완료

[x] Task 6: 프론트엔드 에러 핸들링 — .catch(() => {}) 제거
    15개 파일, 57개 인스턴스 → console.error 로깅 교체

[x] Task 7: API_BASE 중복 제거 — constants.ts 통일
    9개 파일의 로컬 API_BASE 정의 삭제, constants.tsx import로 통일

[x] Task 8: server.py bare except 정리
    34개 bare except → 에러 로깅 추가 (PG/FILE/일반 카테고리별)

[x] Task 9: PG 포트 하드코딩 통합 — 환경변수 VIBE_PG_PORT
    13개 파일의 5433 하드코딩 → os.environ.get('VIBE_PG_PORT', '5433') 통일

[x] Task 10: ISS 파일 통합 — 중복 제거
    .ai_monitor/installer.iss 삭제, CI → vibe-coding-setup.iss 통일, #ifndef 파라미터 지원

---

## 변경 요약
- **server.py**: parameterized SQL, 경로 검증, bare except 로깅, PG_PORT 환경변수
- **hive_bridge.py**: parameterized SQL, PG_PORT 환경변수
- **scripts/ 11개 파일**: PG_PORT 환경변수 통일
- **프론트엔드 15개 파일**: 에러 핸들링 + API_BASE 통일
- **requirements.txt**: psycopg2-binary 추가
- **vibe-coding-setup.iss**: CI 파라미터 오버라이드 지원
- **.github/workflows/build-release.yml**: ISS 경로 통일
