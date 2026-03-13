---
name: vibe-orchestrate
description: >
  Vibe Coding 통합 컨트롤 타워. 하이브 컨텍스트 로드 + 요청 분석 + 스킬 체인 자동 실행 + 자기치유.
  Use when: 복합 작업, 여러 스킬이 필요한 요청, 무엇부터 시작할지 모를 때, 전체 워크플로우 실행 시.
allowed-tools: Read, Write, Edit, Bash, Glob, Grep
user-invocable: true
---

<!--
FILE: .claude/skills/vibe-orchestrate/SKILL.md
DESCRIPTION: Vibe Coding 통합 오케스트레이터.
             모든 개발 요청의 단일 진입점.

REVISION HISTORY:
- 2026-03-13 Claude: [Skills 2.0] .claude/commands → .claude/skills 마이그레이션
                     vibe-security 스킬 목록 추가
- 2026-03-05 Claude: [통합] vibe-master + vibe-orchestrate 합병
-->

당신은 지금 **Vibe Coding 통합 오케스트레이터 프로토콜**을 실행합니다.

# 🎯 통합 오케스트레이터 (Hive Control Tower)

**핵심 원칙:**
- 사용자는 목표만 말한다. 나머지는 내가 판단하고 실행한다.
- 에러가 나면 자기치유(`vibe-heal`)한다. "완료" 보고는 검증 후에만 한다.
- 모든 실행 결과는 대시보드에 narrative(이야기)로 남긴다.

> 명령 레퍼런스: `$CLAUDE_SKILL_DIR/skill-chain-guide.md` 참조

---

## 0단계: 하이브 컨텍스트 로드 (필수 — 가장 먼저)

```bash
python scripts/memory.py list
```

- **충돌 감지**: 수정할 파일을 다른 에이전트가 작업 중이면 → 조율 우선
- ai_monitor_plan.md 확인하여 기존 계획 이어서 진행 여부 판단

---

## 1단계: 요청 분석 및 스킬 체인 결정

| 카테고리 | 키워드 예시 | 스킬 체인 |
|----------|------------|----------|
| **버그/오류** | 오류, 에러, 안 돼, 고쳐줘, 버그 | `vibe-debug` → `vibe-code-review` → *(필요시)* `vibe-release` |
| **새 기능** | 만들어줘, 추가해줘, 구현해줘 | `vibe-brainstorm` → `vibe-write-plan` → `vibe-execute-plan` |
| **코드 품질** | 리팩터링, 정리, 개선, 최적화 | `vibe-code-review` → `vibe-execute-plan` |
| **빌드/배포** | 빌드, 배포, 릴리즈, push | `vibe-release` |
| **설계/계획** | 계획, 설계, 어떻게, 구조 | `vibe-brainstorm` → `vibe-write-plan` |
| **반복 오류** | 또 같은 에러, 계속 안 돼 | `vibe-heal` → `vibe-debug` → `vibe-code-review` |
| **보안 점검** | 보안, 취약점, OWASP, 해킹 | `vibe-security` → `vibe-code-review` |
| **단순 질문** | 뭐야, 어디야, 확인해줘 | 직접 답변 (스킬 체인 없음) |

---

## 2단계: 체인 계획 저장 (대시보드 연동 필수)

```bash
python scripts/skill_orchestrator.py plan "<요청 내용>" "<skill1>" "<skill2>" ...
```

실행 시작 선언:
```
🎯 오케스트레이터 실행 시작
━━━━━━━━━━━━━━━━━━━━━━━━━
📋 요청: [사용자 요청]
🔗 체인: [스킬1] → [스킬2] → [스킬3]
━━━━━━━━━━━━━━━━━━━━━━━━━
```

---

## 3단계: 스킬 체인 자동 실행

```bash
python scripts/skill_orchestrator.py update <step번호> running
# [Skill 도구로 해당 스킬 실행]
python scripts/skill_orchestrator.py update <step번호> done "<핵심 결과 요약>"
```

### summary 작성 규칙

| 스킬 | summary 형식 |
|------|-------------|
| `vibe-debug` | `[오류 발견] server.py:145 TypeError — NoneType.len() / 수정 완료` |
| `vibe-code-review` | `[문법 검사 완료] 문법 오류 없음 / 미사용 변수 2건 정리` |
| `vibe-security` | `[보안 점검] OWASP A03 SQL Injection 위험 1건 수정 완료` |
| `vibe-tdd` | `[테스트] 신규 3건 추가 — 전체 12건 통과` |
| `vibe-release` | `[배포 완료] v3.7.5 빌드 성공 / installer 생성 완료` |
| `vibe-heal` | `[자기치유] 반복 패턴 'X' 감지 → 원인 수정 완료` |

---

## 4단계: 자기치유 루프 (에러 발생 시 자동 전환)

1. **즉시 `vibe-heal` 호출** (격리 컨텍스트에서 실행)
2. vibe-heal 실패 → `vibe-debug`로 재시도
3. 2회 실패 → 사용자에게 에러 내용 보고 후 중단

---

## 5단계: 완료 처리

```bash
python scripts/skill_orchestrator.py done
python scripts/hive_bridge.py "claude" "<결과 요약>"
```

완료 보고 형식:
```
✅ 오케스트레이터 완료
━━━━━━━━━━━━━━━━━━━━━━━━━
[스킬명  ✅] [상태] 결과 요약
━━━━━━━━━━━━━━━━━━━━━━━━━
```

---

## 사용 가능한 스킬 목록

| 스킬 | 설명 | 언제 사용 |
|------|------|----------|
| `vibe-debug` | 버그 4단계 분석·수정 | 오류, 예외, 동작 이상 |
| `vibe-heal` | 반복 패턴 자기치유 (fork 격리) | 같은 에러 반복 |
| `vibe-tdd` | RED→GREEN→REFACTOR | 버그 수정 후, 새 기능 후 |
| `vibe-brainstorm` | 요구사항 정제 + 설계 승인 | 새 기능, 복잡한 변경 |
| `vibe-write-plan` | 마이크로태스크 계획 작성 | 설계 완료 후 |
| `vibe-execute-plan` | 계획 순서대로 실행 | 계획 작성 완료 후 |
| `vibe-code-review` | 코드 품질/보안/성능 검토 | 리팩터링, 배포 전 |
| `vibe-release` | 빌드 + 릴리즈 파이프라인 | 배포, 빌드 요청 |
| `vibe-security` | OWASP 보안 취약점 점검 | 보안 점검, 배포 전 |
