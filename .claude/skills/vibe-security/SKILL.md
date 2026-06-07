---
name: vibe-security
description: >
  OWASP Top 10 기반 보안 취약점을 4단계로 점검합니다. 배포 전 필수 보안 검토.
  Use when: "보안 점검", "취약점 확인", "OWASP", "해킹 가능해?", "보안 리뷰", 배포 전 보안 검토 요청 시.
allowed-tools: Agent
user-invocable: true
---

<!--
FILE: .claude/skills/vibe-security/SKILL.md
DESCRIPTION: 보안 점검 요청 시 security-auditor subagent로 위임하는 래퍼 스킬.
             메인 컨텍스트 다이어트 + OWASP Top 10 스캔 격리가 목적.

REVISION HISTORY:
- 2026-06-07 Claude: subagent 래퍼로 전환 (이전: 메인에서 직접 grep + 체크리스트)
  - .claude/agents/security-auditor.md 와 매핑
  - 라우팅 정책: .claude/agents/README.md 참조
-->

# 보안 점검 — Subagent 위임 래퍼

당신은 **즉시 Agent 도구를 호출**합니다. 메인에서 직접 grep/스캔하지 않습니다.

## 호출 사양

```
Agent(
  subagent_type: "security-auditor",
  description: "OWASP Top 10 보안 점검 (4단계)",
  prompt: """
    작업 디렉토리: <호출 시점의 cwd — pwd로 확인. 절대 경로 하드코딩 금지>
    점검 대상: <사용자가 지정한 범위. 미지정 시 전체 변경분 + 외부 노출 엔드포인트>
    사용자 요청 원문: <전달>

    출력: 한국어
    절차: 4단계 점검 프로토콜
      1단계: 공격 표면 파악 (API 엔드포인트 + 입력 지점 + 인증 경계)
      2단계: OWASP Top 10 스캔 (A01~A10)
      3단계: 민감 정보 노출 검사 (하드코딩 키/토큰, .env, .gitignore)
      4단계: 결과 보고

    결과 형식:
      🔐 보안 점검 결과
      🔴 Critical (즉시 수정): N건 + [A0X] 파일:줄 + 1줄 사유
      🟡 Warning (배포 전 수정): N건
      🔵 Info (검토 권장): N건
      ✅ 통과: OWASP Top 10 중 X개 이상 없음
  """
)
```

## Subagent 결과 수신 후 (메인 보고 형식)

1. **카운트 1줄**: `🔴 N / 🟡 N / 🔵 N`
2. **Critical 항목 즉시 노출** — 전부 나열 (보안은 누락 시 위험)
3. **Warning/Info는 상위 3개씩** 요약
4. **"Critical 수정 진행할까?"** 대기 — 사용자 승인 시 메인이 편집

## 다음 단계 안내
- Critical 수정 후 재점검: 다시 `/vibe-security`
- 수정 코드 품질 검증: `/vibe-code-review`
