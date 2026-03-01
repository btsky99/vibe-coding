---
description: "AI 오케스트레이터. 요청을 분석하여 최적의 스킬 체인을 자동 수립하고 순서대로 실행합니다."
---

<!--
FILE: skills/claude/vibe-orchestrate.md
DESCRIPTION: Vibe Coding AI 오케스트레이터 스킬.
             사용자 요청을 분석하여 필요한 스킬을 자동으로 판별하고
             체인 형태로 순서대로 실행합니다.
             skill_orchestrator.py와 연동하여 실행 상태를 추적합니다.

REVISION HISTORY:
- 2026-03-01 Claude: 최초 구현 — A안+B안 통합 오케스트레이터
  - 요청 분석 → 스킬 체인 자동 수립
  - skill_chain.json에 실행 계획 저장 (대시보드 연동)
  - Skill 도구로 각 스킬 순서대로 자동 실행
-->

당신은 지금 **Vibe Coding 오케스트레이터 프로토콜**을 실행합니다.

# 🎯 AI 오케스트레이터

**핵심 원칙: 사용자가 무엇을 원하는지 분석하여, 필요한 스킬들을 자동으로 연결·실행합니다.**

---

## 1단계: 요청 분석 및 카테고리 판별

사용자 요청을 다음 카테고리로 분류합니다:

| 카테고리 | 키워드 예시 | 스킬 체인 |
|----------|------------|----------|
| **버그/오류** | 오류, 에러, 안 돼, 고쳐줘, 버그, 깨짐 | `vibe-debug` → `vibe-tdd` → *(선택)* `vibe-release` |
| **새 기능** | 만들어줘, 추가해줘, 구현해줘, 새로 | `vibe-brainstorm` → `vibe-write-plan` → `vibe-execute-plan` |
| **코드 품질** | 리팩터링, 정리, 개선, 최적화, 리뷰 | `vibe-code-review` → `vibe-execute-plan` |
| **빌드/배포** | 빌드, 배포, 릴리즈, 업로드, push | `vibe-release` |
| **설계/계획** | 계획, 설계, 어떻게, 방법, 구조 | `vibe-brainstorm` → `vibe-write-plan` |
| **단순 질문** | 뭐야, 어디야, 확인해줘, 설명 | 직접 답변 (스킬 체인 없음) |

---

## 2단계: 스킬 체인 계획 수립 및 저장

### 계획 파일 저장 (대시보드 연동 필수)

아래 명령으로 실행 계획을 skill_chain.json에 저장합니다:

```bash
# 체인 계획 시작 (plan 커맨드에 요청 내용과 스킬 목록 전달)
python scripts/skill_orchestrator.py plan "<요청 내용>" "<skill1>" "<skill2>" "<skill3>"

# 예시: "로그인 버그 고쳐줘"
python scripts/skill_orchestrator.py plan "로그인 버그 고쳐줘" "vibe-debug" "vibe-tdd"
```

---

## 3단계: 스킬 체인 자동 실행

**각 스킬을 Skill 도구로 순서대로 호출합니다. 중간에 사용자에게 확인하지 않습니다.**

### 실행 전 발표 (필수)

```
🎯 오케스트레이터 실행 시작
━━━━━━━━━━━━━━━━━━━━━━━━━
📋 요청: [사용자 요청]
🔗 체인: [스킬1] → [스킬2] → [스킬3]
━━━━━━━━━━━━━━━━━━━━━━━━━
```

### 스킬 실행 순서

각 스킬 실행 전에 상태를 업데이트합니다:

```bash
# 스킬 N 시작 시
python scripts/skill_orchestrator.py update <step번호> running

# 스킬 N 완료 시 (summary는 핵심 결과 한 줄 요약)
python scripts/skill_orchestrator.py update <step번호> done "<핵심 결과 요약>"
```

그 다음 Skill 도구로 해당 스킬을 실행합니다.

---

## 4단계: 각 스킬 완료 후 재판단

각 스킬 완료 후 다음을 판단합니다:

1. **다음 스킬이 여전히 필요한가?**
   - 버그 수정 후 테스트가 모두 통과했다면 → `vibe-tdd` 생략 가능
   - 이미 배포된 상태라면 → `vibe-release` 생략 가능

2. **새로운 스킬이 필요해졌는가?**
   - 디버그 중 새 기능 필요 발견 → `vibe-brainstorm` 추가
   - 코드 수정 후 빌드 필요 → `vibe-release` 추가

---

## 5단계: 완료 보고

모든 스킬 체인 완료 후:

```bash
# 전체 완료 처리
python scripts/skill_orchestrator.py done
```

그리고 사용자에게 보고합니다:

```
✅ 오케스트레이터 완료
━━━━━━━━━━━━━━━━━━━━━━━━━
[vibe-debug  ✅] 버그 원인: null 체크 누락
[vibe-tdd    ✅] 테스트 3개 추가, 전체 통과
[vibe-release ✅] v3.6.6 빌드 완료 및 배포
━━━━━━━━━━━━━━━━━━━━━━━━━
총 소요: 약 N분
```

---

## 사용 가능한 스킬 목록

| 스킬 | 설명 | 언제 사용 |
|------|------|----------|
| `vibe-debug` | 버그 4단계 분석·수정 | 오류, 예외, 동작 이상 |
| `vibe-tdd` | RED→GREEN→REFACTOR 테스트 | 버그 수정 후, 새 기능 후 |
| `vibe-brainstorm` | 요구사항 정제 + 설계 승인 | 새 기능, 복잡한 변경 |
| `vibe-write-plan` | 마이크로태스크 계획 작성 | 설계 완료 후 |
| `vibe-execute-plan` | 계획 순서대로 실행 | 계획 작성 완료 후 |
| `vibe-code-review` | 코드 품질/보안/성능 검토 | 리팩터링, 배포 전 |
| `vibe-release` | 빌드 + 릴리즈 전체 파이프라인 | 배포, 빌드 요청 |

---

## ⚠️ 오케스트레이터 원칙

1. **자동 실행**: 각 스킬 사이에 사용자 확인 요청 금지
2. **재판단 허용**: 스킬 결과에 따라 체인 조정 가능
3. **단순 질문 예외**: 개발 작업이 아닌 질문은 직접 답변
4. **실패 시 즉시 보고**: 스킬 실패 시 원인 분석 후 중단 또는 재시도 판단
5. **skill_orchestrator 연동 필수**: 모든 실행 상태를 JSON으로 추적
