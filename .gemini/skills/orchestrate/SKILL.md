---
name: orchestrate
description: 통합 오케스트레이터. 하이브 컨텍스트 로드 + 요청 분석 + 스킬 체인 자동 실행 + 자기치유.
---

<!--
FILE: .gemini/skills/orchestrate/SKILL.md
DESCRIPTION: Gemini용 통합 오케스트레이터 스킬.
             Claude의 .claude/commands/vibe-orchestrate.md와 동일한 프로토콜.
             Claude와 Gemini가 동일한 워크플로우를 공유합니다.

REVISION HISTORY:
- 2026-03-05 Claude: [통합] 구 master + orchestrate 합병
  - vibe-orchestrate.md와 동일한 5단계 프로토콜 적용
  - 자기치유(vibe-heal) 연동 추가
  - 중복 제거: orchestration 그룹과 master 그룹 통합
-->

# 🎯 통합 오케스트레이터 (Hive Control Tower)

> **Claude의 `.claude/commands/vibe-orchestrate.md`와 동일한 프로토콜을 따릅니다.**
> Gemini와 Claude가 같은 워크플로우를 사용하여 하이브 협업을 유지합니다.

**핵심 원칙:**
- 사용자는 목표만 말한다. 나머지는 내가 판단하고 실행한다.
- 에러가 나면 자기치유(`vibe-heal`)한다. "완료" 보고는 검증 후에만 한다.
- 모든 실행 결과는 대시보드에 narrative(이야기)로 남긴다.

---

## 0단계: 하이브 컨텍스트 로드 (필수 — 가장 먼저)

```bash
# 1. 장기 기억 및 사용자 선호도 숙지 (필독)
cat memory.md

# 2. 공유 메모리 로드
python scripts/memory.py list

# 3. Git 상태 시각화 및 워크트리 확인 (Mandatory)
python scripts/git_visualizer.py
```

- **[판단]**: `memory.md`의 '사용자 선호도'와 '자주 발생하는 실수'를 확인하여 이번 작업에서 동일한 실수를 반복하지 않도록 주의하십시오.
- 현재 위치가 메인 브랜치라면 `using-git-worktrees` 스킬을 사용하여 반드시 워크트리를 생성한 후 작업하십시오.
- task_logs.jsonl 최근 확인으로 다른 에이전트 작업 충돌 감지
- ai_monitor_plan.md 확인하여 기존 계획 이어서 진행 여부 판단

---

## 1단계: 요청 분석 및 스킬 체인 결정

| 카테고리 | 키워드 예시 | 스킬 체인 |
|----------|------------|----------|
| **버그/오류** | 오류, 에러, 안 돼, 고쳐줘, 버그 | `vibe-debug` → `vibe-code-review` → *(필요시)* `vibe-release` |
| **새 기능** | 만들어줘, 추가해줘, 구현해줘 | `vibe-brainstorm` → `vibe-write-plan` → `vibe-execute-plan` |
| **코드 품질** | 리팩터링, 정리, 개선, 최적화 | `vibe-code-review` → `vibe-execute-plan` |
| **빌드/배포** | 빌드, 배포, 릴리즈 | `vibe-release` |
| **반복 오류** | 또 같은 에러, 계속 안 돼 | `vibe-heal` → `vibe-debug` → `vibe-code-review` |
| **단순 질문** | 뭐야, 어디야, 설명 | 직접 답변 |

---

## 2단계: 체인 계획 저장

```bash
python scripts/skill_orchestrator.py plan "<요청>" "<skill1>" "<skill2>" ...
```

---

# 3. 스킬 체인 자동 실행

각 스킬 실행 전후로 상태 업데이트 및 **메시지 채널 공지**:

```bash
# 1. 오케스트레이터 상태 업데이트
python scripts/skill_orchestrator.py update <step번호> running

# 2. 파일 수정이 필요한 경우 잠금 획득 (필수)
python scripts/lock_manager.py acquire <파일경로1> <파일경로2> ...

# 3. 메시지 채널을 통해 하이브 전체에 공지
python scripts/send_message.py Gemini Claude message "🚀 [진행 중] <step명> 스킬을 시작합니다. (파일 잠금 획득)"

# [스킬 실행 및 코드 수정]

# 4. 파일 수정 완료 후 잠금 해제 (필수)
python scripts/lock_manager.py release <파일경로1> <파일경로2> ...

# 3.1단계: RULES.md 검증 (Mandatory — 코드 변경 시 필수)
```
코드 수정이나 파일 생성이 포함된 경우, 완료 전 반드시 검증기를 실행합니다:

```bash
python scripts/rules_validator.py <수정된_파일_경로1> <수정된_파일_경로2> ...
```

- **[결과 처리]**:
  - ✅ **Pass**: 4단계(자기치유/완료)로 진행.
  - ❌ **Fail**: **[자기 성찰]** 실패 사유(헤더 누락, 한글 주석 부족 등)를 분석하여 즉시 스스로 수정한 후 다시 검증합니다. 3회 실패 시 `vibe-heal` 스킬로 전환합니다.

# 3.2단계: 오케스트레이터 완료 처리
python scripts/skill_orchestrator.py update <step번호> done "<구체적 결과 요약>"

# 3.3단계: 완료 보고 전송
python scripts/send_message.py Gemini Claude message "✅ [완료] <step명>: <결과 요약>"
```

**summary 형식 예시:**
- `[오류 발견] server.py:145 TypeError — NoneType.len() / 수정 완료`
- `[문법 검사 완료] 문법 오류 없음 / 미사용 변수 2건 정리`
- `[자기치유] 반복 패턴 'X' 감지 → 원인 수정 완료`

---

## 4단계: 자기치유 루프

에러/실패 발생 시:
1. `vibe-heal` 스킬 호출
2. 실패 시 `vibe-debug`로 재시도
3. 2회 실패 시 사용자에게 보고 후 중단

---

## 5단계: 완료 처리

```bash
python scripts/skill_orchestrator.py done
python scripts/hive_bridge.py "[에이전트]" "[완료 내용]"
```

### 메타러닝 (작업 완료 후 자동 수행)

1. 반복 패턴 감지되면 `references/` 문서 업데이트
2. 완전히 새로운 워크플로우 발견 시 → 신규 스킬 파일 생성 제안

---

## 사용 가능한 스킬 목록

| 스킬 | 설명 |
|------|------|
| `vibe-debug` | 버그 4단계 분석·수정 |
| `vibe-heal` | 반복 패턴 자기치유 |
| `vibe-tdd` | RED→GREEN→REFACTOR |
| `vibe-brainstorm` | 요구사항 정제 + 설계 승인 |
| `vibe-write-plan` | 마이크로태스크 계획 작성 |
| `vibe-execute-plan` | 계획 순서대로 실행 |
| `vibe-code-review` | 코드 품질/보안/성능 검토 |
| `vibe-release` | 빌드 + 릴리즈 파이프라인 |
