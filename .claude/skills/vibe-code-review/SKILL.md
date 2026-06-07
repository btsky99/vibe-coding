---
name: vibe-code-review
description: >
  코드 품질, 성능, 가독성을 3가지 관점에서 검토합니다. 보안 심층 점검은 /vibe-security를 사용하세요.
  Use when: "코드 리뷰", "리팩터링", "최적화", 배포 전 검토, PR 리뷰 요청 시.
allowed-tools: Agent
user-invocable: true
---

<!--
FILE: .claude/skills/vibe-code-review/SKILL.md
DESCRIPTION: 코드 리뷰 요청 시 code-reviewer subagent로 위임하는 래퍼 스킬.
             메인 컨텍스트 다이어트 + 3관점 분석 격리가 목적.

REVISION HISTORY:
- 2026-06-07 Claude: subagent 래퍼로 전환 (이전: 메인에서 직접 분석)
  - .claude/agents/code-reviewer.md 와 매핑
  - 라우팅 정책: .claude/agents/README.md 참조
-->

# 코드 리뷰 — Subagent 위임 래퍼

당신은 **즉시 Agent 도구를 호출**합니다. 메인에서 코드를 직접 읽지 않습니다.

## 호출 사양

```
Agent(
  subagent_type: "code-reviewer",
  description: "코드 리뷰 (3관점)",
  prompt: """
    작업 디렉토리: <호출 시점의 cwd — pwd로 확인. 절대 경로 하드코딩 금지>
    검토 대상: <사용자가 지정한 파일/디렉토리. 미지정 시 `git diff` 변경분>
    사용자 요청 원문: <전달>

    출력: 한국어
    검토 관점: 성능 / 코드 품질 / 가독성 (3관점)
    결과 형식:
      🔴 Critical: 즉시 수정 필요
      🟡 Warning: 배포 전 수정 권장
      🔵 Info: 검토 권장
      ✅ Good: 잘 된 점
    카운트 요약 1줄 + 항목별 파일:줄 위치 명시.
    보안 심층 점검은 별도 vibe-security 사용 (이 리뷰에서는 제외).
  """
)
```

## Subagent 결과 수신 후 (메인 보고 형식)

1. **카운트 1줄**: `🔴 N / 🟡 N / 🔵 N / ✅ N`
2. **핵심 발견 3~5개** 요약 (전체 항목 나열 금지, 가장 임팩트 큰 것만)
3. **"수정 진행할까?"** 대기 — 사용자 승인 시 메인이 직접 편집 수행

## 다음 단계 안내
- 수정 후 회귀 방지: `/vibe-tdd`
- 배포 전 보안: `/vibe-security`
