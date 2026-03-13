# 🔐 OWASP Top 10 체크리스트 (2021)

이 파일은 vibe-security 스킬의 보조 체크리스트입니다.
점검 시 각 항목을 순서대로 확인하세요.

---

## A01 — 접근 제어 취약점 (Broken Access Control)

| 항목 | 확인 방법 | 위험도 |
|------|----------|--------|
| 인증 없이 관리자 기능 접근 가능 | 로그아웃 상태에서 /admin 접근 시도 | 🔴 Critical |
| IDOR (다른 사용자 리소스 접근) | /api/user/1 → /api/user/2 변경 시도 | 🔴 Critical |
| 디렉토리 탐색 공격 | `../../../etc/passwd` 경로 시도 | 🔴 Critical |

## A02 — 암호화 실패 (Cryptographic Failures)

| 항목 | 확인 방법 | 위험도 |
|------|----------|--------|
| 비밀번호 평문 저장 | DB에서 password 컬럼 직접 조회 | 🔴 Critical |
| API 키 코드 하드코딩 | `grep -rn "api_key\s*=" .` | 🔴 Critical |
| HTTP (비암호화) 사용 | 프로덕션 URL 확인 | 🟡 Warning |

## A03 — 인젝션 (Injection)

| 항목 | 확인 방법 | 위험도 |
|------|----------|--------|
| SQL Injection | f-string/% 포맷 쿼리 직접 삽입 | 🔴 Critical |
| Command Injection | `subprocess(shell=True, input=user_input)` | 🔴 Critical |
| XSS (저장형) | DB에 저장된 HTML이 이스케이프 없이 출력 | 🟡 Warning |
| XSS (반사형) | URL 파라미터가 이스케이프 없이 출력 | 🟡 Warning |

## A04 — 보안 설계 실패

| 항목 | 확인 방법 | 위험도 |
|------|----------|--------|
| 에러 메시지 내부 정보 노출 | 500 에러 시 스택 트레이스 노출 여부 | 🟡 Warning |
| 민감 데이터 과다 수집 | API 응답에 불필요한 필드 포함 | 🔵 Info |

## A05 — 보안 설정 오류

| 항목 | 확인 방법 | 위험도 |
|------|----------|--------|
| DEBUG 모드 프로덕션 활성화 | `DEBUG=True` 설정 확인 | 🟡 Warning |
| CORS 전체 허용 (`*`) | CORS 설정 확인 | 🟡 Warning |
| 기본 계정/비밀번호 사용 | admin/admin, postgres/postgres 등 | 🔴 Critical |

## A06 — 취약한 컴포넌트

| 항목 | 확인 방법 | 위험도 |
|------|----------|--------|
| 알려진 취약 버전 라이브러리 | `pip audit` 또는 `npm audit` 실행 | 🟡 Warning |

## A07 — 인증 실패

| 항목 | 확인 방법 | 위험도 |
|------|----------|--------|
| 로그인 시도 제한 없음 | 브루트포스 가능 여부 | 🟡 Warning |
| 세션 만료 없음 | 세션/토큰 만료 시간 설정 확인 | 🟡 Warning |

## A09 — 로깅 및 모니터링 실패

| 항목 | 확인 방법 | 위험도 |
|------|----------|--------|
| 로그인 실패 기록 없음 | 인증 실패 로그 확인 | 🔵 Info |
| 보안 이벤트 알림 없음 | 이상 접근 알림 여부 | 🔵 Info |

---

## 이 프로젝트 특수 주의사항 (Vibe Coding)

1. **PostgreSQL 연결**: `psycopg2.connect()` 시 파라미터화 쿼리 필수
2. **PTY/터미널**: 사용자 입력이 shell 명령으로 직접 전달되는 경로 주의
3. **GitHub 토큰**: `.ai_monitor/data/github_token.txt` — .gitignore 포함 확인
4. **API 키**: `.env` 파일 사용, 절대 코드에 하드코딩 금지
