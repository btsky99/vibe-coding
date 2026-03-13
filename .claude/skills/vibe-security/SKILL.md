---
name: vibe-security
description: >
  OWASP Top 10 기반 보안 취약점을 4단계로 점검합니다. 배포 전 필수 보안 검토.
  Use when: "보안 점검", "취약점 확인", "OWASP", "해킹 가능해?", "보안 리뷰", 배포 전 보안 검토 요청 시.
allowed-tools: Read, Bash, Grep, Glob
user-invocable: true
---

<!--
FILE: .claude/skills/vibe-security/SKILL.md
DESCRIPTION: Vibe Coding 보안 점검 스킬 (Skills 2.0 신규).
             OWASP Top 10 기반 4단계 보안 점검.
             배포 전 필수 실행 스킬.

REVISION HISTORY:
- 2026-03-13 Claude: [신규] Skills 2.0 형식으로 vibe-security 생성
  - OWASP Top 10 체크리스트 기반 4단계 점검
  - owasp-checklist.md 보조파일 연동
-->

당신은 지금 **Vibe Coding 보안 점검 프로토콜**을 실행합니다.

# 🔐 보안 점검 프로토콜 (OWASP Top 10)

**핵심 원칙: 배포 전 반드시 보안 점검. 취약점은 발견 즉시 수정.**

> 상세 체크리스트: `$CLAUDE_SKILL_DIR/owasp-checklist.md` 참조

---

## 4단계 점검 프로세스

### 1️⃣ 공격 표면 파악
```bash
# API 엔드포인트 목록 확인
grep -rn "def do_GET\|def do_POST\|@app.route\|router\." --include="*.py" --include="*.ts" .

# 외부 입력 처리 지점 확인
grep -rn "request\.\|params\.\|body\.\|query\." --include="*.py" --include="*.ts" .
```

- 외부에서 접근 가능한 모든 엔드포인트 목록화
- 사용자 입력을 받는 모든 지점 식별
- 인증이 필요한 경로 vs 공개 경로 구분

---

### 2️⃣ OWASP Top 10 취약점 스캔

#### A01 — 접근 제어 취약점 (Broken Access Control)
```bash
# 인증 없이 접근 가능한 민감 엔드포인트 확인
grep -rn "admin\|delete\|update\|private" --include="*.py" .
```
- [ ] 모든 민감 API에 인증 확인 로직 존재
- [ ] 다른 사용자 데이터 접근 차단 (IDOR 방지)

#### A02 — 암호화 실패 (Cryptographic Failures)
```bash
# 평문 저장 패턴 확인
grep -rn "password\|token\|secret\|key" --include="*.py" --include="*.ts" . | grep -v "test\|#"
```
- [ ] 비밀번호 해시 처리 (bcrypt/argon2)
- [ ] API 키, 토큰이 코드에 하드코딩되지 않음
- [ ] HTTPS 강제 사용

#### A03 — 인젝션 (Injection)
```bash
# SQL 쿼리 문자열 연결 패턴 확인
grep -rn "f\".*SELECT\|f\".*INSERT\|f\".*DELETE\|\+.*SQL" --include="*.py" .
```
- [ ] SQL: 파라미터화 쿼리 사용 (f-string 직접 삽입 금지)
- [ ] 명령 실행: shell=True 사용 여부 확인
- [ ] XSS: 사용자 입력 HTML 이스케이프 처리

#### A04 — 보안 설계 실패 (Insecure Design)
- [ ] 민감 데이터 최소화 원칙 준수
- [ ] 에러 메시지에 내부 정보 노출 없음

#### A05 — 보안 설정 오류 (Security Misconfiguration)
```bash
# CORS, 디버그 모드, 기본 계정 확인
grep -rn "DEBUG\|CORS\|allow_all\|*" --include="*.py" . | head -20
```
- [ ] 프로덕션에서 DEBUG=False
- [ ] CORS 화이트리스트 명시
- [ ] 불필요한 포트/서비스 비활성화

#### A06 ~ A10 — 추가 점검
- [ ] A06: 취약한 컴포넌트 사용 여부 (`pip list` → CVE 확인)
- [ ] A07: 인증 실패 — 로그인 시도 제한, 세션 만료
- [ ] A08: 데이터 무결성 — 역직렬화 취약점
- [ ] A09: 로깅 부재 — 보안 이벤트 로깅 여부
- [ ] A10: SSRF — 외부 URL 요청 시 검증

---

### 3️⃣ 민감 정보 노출 검사

```bash
# API 키, 비밀번호 하드코딩 검사
grep -rn "api_key\s*=\s*['\"].\|password\s*=\s*['\"].\|secret\s*=\s*['\"]." \
  --include="*.py" --include="*.ts" --include="*.json" . \
  | grep -v ".env\|test\|example\|#"

# .env 파일이 .gitignore에 포함되어 있는지 확인
cat .gitignore | grep -E "\.env|secrets|token"
```

---

### 4️⃣ 결과 보고 및 수정

결과 형식:
```
🔐 보안 점검 결과
━━━━━━━━━━━━━━━━━━━━━━━━━
🔴 Critical (즉시 수정): N건
  - [A03] server.py:145 SQL Injection 위험 — f-string 쿼리 직접 삽입
🟡 Warning (배포 전 수정 권장): N건
  - [A05] DEBUG 모드 활성화 상태
🔵 Info (검토 권장): N건
  - [A09] 보안 이벤트 로깅 미흡
✅ 통과: OWASP Top 10 중 X개 항목 이상 없음
━━━━━━━━━━━━━━━━━━━━━━━━━
```

**Critical 항목이 있으면 즉시 수정 후 재점검.**
수정 완료 후 vibe-code-review로 검증 권장.
