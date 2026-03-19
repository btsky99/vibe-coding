---
name: dispatcher
description: >
  멀티 LLM 디스패처 관리 스킬. 에이전트 간 태스크 분배, 상태 모니터링, 크로스 검증을 수행합니다.
  auto_dispatcher.py를 활용하여 Claude/Gemini/Codex 에이전트에 역량 기반 최적 매칭으로 작업을 할당합니다.
  Use when: 태스크 분배, 에이전트 배정, 작업 보내줘, 디스패치, 팬아웃, 에이전트 상태,
  누가 뭐 하고 있어, 검증 요청, 크로스 리뷰, 멀티 에이전트, 병렬 작업, 하이브 상태 요청 시.
---

<!--
FILE: .gemini/skills/dispatcher/SKILL.md
DESCRIPTION: Gemini용 멀티 LLM 디스패처 관리 스킬.
             Claude의 .claude/skills/vibe-dispatcher/SKILL.md와 동일한 프로토콜.
             Claude와 Gemini가 같은 디스패처 워크플로우를 공유합니다.

REVISION HISTORY:
- 2026-03-19 Claude: 최초 작성 — skill-creator 기반 멀티 LLM 디스패처 스킬 생성
-->

> **Claude의 `.claude/skills/vibe-dispatcher/SKILL.md`와 동일한 프로토콜을 따릅니다.**
> Gemini와 Claude가 같은 디스패처 워크플로우를 사용하여 하이브 협업을 유지합니다.

당신은 **하이브 마인드 디스패처 오퍼레이터** 역할을 수행합니다.
사용자의 요청을 분석하여 적절한 에이전트에 작업을 분배하고, 하이브 전체 상태를 관리합니다.

# 디스패처 관리 프로토콜

## 핵심 원칙

- **역량 기반 매칭**: 키워드가 아닌 에이전트 역량 프로필 점수로 최적 에이전트를 선택한다.
- **크로스 검증**: 작성자 ≠ 검증자. 한 에이전트의 결과는 반드시 다른 에이전트가 검증한다.
- **이중 전달**: MUX(즉시) + ITCP(비동기) 병행. 하나가 실패해도 다른 채널로 도달한다.
- **수동 ITCP 금지**: 반드시 `auto_dispatcher.py`를 통해 분배한다. 직접 `itcp.send()` 호출하지 않는다.

---

## 1단계: 요청 분석

사용자의 요청에서 다음을 판단합니다:

| 판단 항목 | 방법 |
|----------|------|
| **작업 내용** | 사용자 메시지에서 핵심 태스크 추출 |
| **태스크 유형** | 키워드로 자동 감지 (bug_fix, feature, security, perf 등 11가지) |
| **대상 에이전트** | 사용자 지명 시 해당 에이전트, 미지명 시 자동 선택 |
| **단일 vs 병렬** | 독립 작업 여러 개면 fan-out, 한 건이면 dispatch |
| **긴급도** | 키워드(급해, 긴급, ASAP, critical)로 우선순위 판단 |

---

## 2단계: 디스패치 실행

### 단일 태스크 분배

```bash
python scripts/auto_dispatcher.py dispatch "태스크 설명" [--type TYPE] [--to AGENT] [--priority PRIO]
```

### 병렬 다중 분배 (Fan-Out)

```bash
python scripts/auto_dispatcher.py fan-out "태스크1" "태스크2" "태스크3"
```

### 사전 점수 확인 (분배 전 미리보기)

```bash
python scripts/auto_dispatcher.py score "태스크 설명"
```

---

## 3단계: 모니터링

### 현황 조회

```bash
python scripts/auto_dispatcher.py status
```

### 에이전트 간 메시지 확인

```bash
python scripts/itcp.py history --limit 20 --channel task
```

### 하이브 전체 상태

```bash
python scripts/orchestrator.py summary
```

---

## 4단계: 크로스 검증

작업 완료 후 결과를 검증 요청:

```bash
python scripts/auto_dispatcher.py verify TASK_ID "결과 요약" --author gemini
```

검증 결과 보고 (내가 검증자일 때):

```bash
python scripts/auto_dispatcher.py report-verify TASK_ID "검증 의견" --verdict approved --reviewer gemini
```

verdict 옵션: `approved` | `rejected` | `needs_revision`

---

## 5단계: 결과 보고

디스패치 결과를 사용자에게 보고할 때 이 형식을 사용:

```
📡 디스패처 실행 결과
━━━━━━━━━━━━━━━━━━━━━━━━━
🆔 Task: TASK-20260319-abc123
📋 유형: research (자동 감지)
🎯 할당: Gemini (T2) — 적합도 0.90
🔍 검증: Claude (T1)가 크로스 검증 예정
⚡ 우선순위: medium
📡 전달: MUX + ITCP 이중 전송 완료
━━━━━━━━━━━━━━━━━━━━━━━━━
```

---

## 에이전트 역량 요약 (의사결정 참고)

내가 직접 처리하는 것이 나은지, 다른 에이전트에 보내는 것이 나은지 판단할 때:

| 작업 | 최적 에이전트 | 이유 |
|------|-------------|------|
| 웹 조사, 트렌드 분석 | **Gemini (나)** | research 0.95 |
| 아키텍처 설계 | **Gemini (나)** | architecture 0.90 |
| 문서화 | **Gemini (나)** | documentation 0.90 |
| 코드 리뷰, 보안 분석 | **Claude** | security 0.95, code_review 0.95 |
| 빠른 코드 생성, 테스트 | **Codex** | testing 0.90, 샌드박스 병렬 실행 |
| 디버깅, 정밀 로직 | **Claude** | debugging 0.90, precision_logic 0.90 |

> 내가 잘하는 작업(조사, 설계, 문서화)은 직접 수행하되, 검증만 다른 에이전트에 요청한다.
> 내가 약한 작업(정밀 코드 수정, 보안 분석)은 적극적으로 Claude/Codex에 위임한다.

---

## 주의사항

- `auto_dispatcher.py`가 자동 감지한 유형이 부정확하면 `--type`으로 직접 지정한다.
- 사용자가 터미널 번호로 지정하면: T1=claude, T2=gemini, T3=codex.
- 크로스 검증은 기본 활성화. 사소한 작업(문서 오타 수정 등)에만 `--no-verify` 사용.
- Fan-Out은 **독립 작업**에만 사용. 순서 의존성이 있으면 하나씩 dispatch하고 결과를 기다린다.
