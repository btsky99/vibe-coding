---
name: vibe-orchestrate
description: >
  Vibe Coding 통합 컨트롤 타워. 하이브 컨텍스트 로드 + 요청 분석 + 스킬 체인 자동 실행 + 자기치유.
  Use when: 복합 작업, 여러 스킬이 필요한 요청, 무엇부터 시작할지 모를 때, 전체 워크플로우 실행 시.
allowed-tools:
  - Read
  - Write
  - Edit
  - Bash
  - Glob
  - Grep
---

<!--
FILE: .claude/commands/vibe-orchestrate.md
DESCRIPTION: Vibe Coding 통합 오케스트레이터.
             구 vibe-master + 구 vibe-orchestrate 통합 버전.
             모든 개발 요청의 단일 진입점.

REVISION HISTORY:
- 2026-03-05 Claude: [통합] vibe-master + vibe-orchestrate 합병
  - 하이브 컨텍스트 로드(0단계) 추가
  - 충돌 감지 및 에이전트 조율 통합
  - 자기치유 루프(4단계) 강화
  - 메타러닝 및 지식 업데이트(5단계) 추가
-->

당신은 지금 **Vibe Coding 통합 오케스트레이터 프로토콜**을 실행합니다.

# 🎯 통합 오케스트레이터 (Hive Control Tower)

**핵심 원칙:**
- 사용자는 목표만 말한다. 나머지는 내가 판단하고 실행한다.
- 에러가 나면 자기치유(`vibe-heal`)한다. "완료" 보고는 검증 후에만 한다.
- 모든 실행 결과는 대시보드에 narrative(이야기)로 남긴다.

---

## 0단계: 하이브 컨텍스트 로드 (필수 — 가장 먼저)

```bash
# 공유 메모리에서 기술 결정 사항 로드
python scripts/memory.py list

# Phase 2: 수정 예정 파일에 대한 충돌(LOCK) 감지
# check_conflict()는 messages.jsonl 최근 20줄에서 다른 에이전트의 LOCK을 자동 탐지
python -c "
import sys; sys.path.insert(0, 'scripts')
from hive_bridge import check_conflict
# 예시 — 실제 수정 파일명으로 교체:
# conflict = check_conflict('수정할파일.py', my_agent='Claude')
# if conflict: print(f'[경고] {conflict}가 작업 중! 조율 필요')
print('[OK] 충돌 없음 — 작업 진행 가능')
"
```

- **충돌 감지**: 수정할 파일을 다른 에이전트가 작업 중이면 → 조율 우선
- **경고/충돌** 있으면 해당 에이전트 태스크 정리 후 진행
- ai_monitor_plan.md 확인하여 기존 계획 이어서 진행 여부 판단

---

## 1단계: 요청 분석 및 스킬 체인 결정

사용자 요청을 아래 표로 분류합니다:

| 카테고리 | 키워드 예시 | 스킬 체인 |
|----------|------------|----------|
| **버그/오류** | 오류, 에러, 안 돼, 고쳐줘, 버그, 깨짐 | `vibe-debug` → `vibe-code-review` → *(필요시)* `vibe-release` |
| **새 기능** | 만들어줘, 추가해줘, 구현해줘, 새로 | `vibe-brainstorm` → `vibe-write-plan` → `vibe-execute-plan` |
| **코드 품질** | 리팩터링, 정리, 개선, 최적화, 리뷰 | `vibe-code-review` → `vibe-execute-plan` |
| **빌드/배포** | 빌드, 배포, 릴리즈, 업로드, push | `vibe-release` |
| **설계/계획** | 계획, 설계, 어떻게, 방법, 구조 | `vibe-brainstorm` → `vibe-write-plan` |
| **반복 오류** | 또 같은 에러, 계속 안 돼, 반복 | `vibe-heal` → `vibe-debug` → `vibe-code-review` |
| **단순 질문** | 뭐야, 어디야, 확인해줘, 설명 | 직접 답변 (스킬 체인 없음) |

---

## 2단계: 체인 계획 저장 (대시보드 연동 필수)

```bash
# 체인 계획 등록 (터미널 번호는 환경변수 TERMINAL_ID에서 자동 읽음)
python scripts/skill_orchestrator.py plan "<요청 내용>" "<skill1>" "<skill2>" ...

# 예시: "로그인 버그 고쳐줘"
python scripts/skill_orchestrator.py plan "로그인 버그 고쳐줘" "vibe-debug" "vibe-code-review"
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

**각 스킬 실행 전에 상태 업데이트 → Skill 도구 실행 → 결과 검증 → 다음 단계.**
중간에 사용자 확인 요청 금지.

```bash
# Phase 2: 파일 수정 전 LOCK 선언 (다른 에이전트 충돌 방지)
python -c "import sys; sys.path.insert(0,'scripts'); from hive_bridge import lock_file; lock_file('Claude','수정할파일.py')"

# 스킬 N 시작 (Phase 3: messages.jsonl에 "작업 중" 자동 게시)
python scripts/skill_orchestrator.py update <step번호> running

# [Skill 도구로 해당 스킬 실행]

# 스킬 N 완료 — summary는 반드시 구체적으로 (Phase 3: "완료" 메시지 자동 게시)
python scripts/skill_orchestrator.py update <step번호> done "<핵심 결과 요약>"

# Phase 2: 파일 수정 완료 후 LOCK 해제
python -c "import sys; sys.path.insert(0,'scripts'); from hive_bridge import unlock_file; unlock_file('Claude','수정한파일.py')"
```

### summary 작성 규칙 (대시보드 narrative용)

사용자가 패널에서 "어떤 일이 일어났는지" 한눈에 알 수 있어야 합니다.

| 스킬 | summary 형식 |
|------|-------------|
| `vibe-debug` | `[오류 발견] server.py:145 TypeError — NoneType.len() / 수정 완료` |
| `vibe-debug` (정상) | `[정상] 오류 없음 — 코드 동작 이상 없음 확인` |
| `vibe-code-review` | `[문법 검사 완료] 문법 오류 없음 / 미사용 변수 2건 정리` |
| `vibe-tdd` | `[테스트] 신규 3건 추가 — 전체 12건 통과` |
| `vibe-execute-plan` | `[실행 완료] 5개 태스크 완료 — AgentPanel.tsx 수정` |
| `vibe-release` | `[배포 완료] v3.7.5 빌드 성공 / installer 생성 완료` |
| `vibe-heal` | `[자기치유] 반복 패턴 'X' 감지 → 원인 수정 완료` |

**규칙:**
- `[상태]` 접두어 필수 (오류 발견 / 정상 / 완료 / 실패 / 자기치유)
- 발견된 파일명과 줄 번호 포함
- 수정한 내용 한 줄 요약 포함
- 검사 결과(통과/오류 건수) 포함

---

## 4단계: 자기치유 루프 (에러 발생 시 자동 전환)

스킬 실행 중 에러/실패 발생 시:

1. **즉시 `vibe-heal` 호출** (사용자에게 알리되 중단하지 않음)
2. vibe-heal이 실패하면 → `vibe-debug`로 재시도
3. 2회 실패 시 → 사용자에게 에러 내용과 함께 보고 후 중단

**절대 금지:**
- 에러를 무시하고 "완료" 보고
- 빌드 성공만으로 "완료" 판단 (실제 동작 검증 필수)
- 검증 없이 다음 단계 진행

---

## 5단계: 완료 처리 및 메타러닝

```bash
# 전체 완료 처리
python scripts/skill_orchestrator.py done
```

### 사후 처리 (자동 수행)

1. **문서 동기화**: `CHANGELOG.md`, `PROJECT_MAP.md` 업데이트
2. **하이브 로깅**: `python scripts/hive_bridge.py` 결과 공유
3. **메타러닝**: 이번 작업에서 반복 패턴이 발견되었다면:
   - `.gemini/skills/master/references/` 관련 문서 업데이트
   - 새 패턴이 완전히 새로운 유형이면 → 신규 스킬 파일 생성 제안

완료 보고 형식:
```
✅ 오케스트레이터 완료
━━━━━━━━━━━━━━━━━━━━━━━━━
[vibe-debug       ✅] [오류 발견] server.py:145 TypeError 수정 완료
[vibe-code-review ✅] [문법 검사 완료] 문법 오류 없음 / 미사용 변수 1건 정리
[vibe-release     ✅] [배포 완료] v3.7.5 빌드 성공
━━━━━━━━━━━━━━━━━━━━━━━━━
```

---

## 사용 가능한 스킬 목록

| 스킬 | 설명 | 언제 사용 |
|------|------|----------|
| `vibe-debug` | 버그 4단계 분석·수정 | 오류, 예외, 동작 이상 |
| `vibe-heal` | 반복 패턴 자기치유 | 같은 에러 반복, 자동 복구 |
| `vibe-tdd` | RED→GREEN→REFACTOR | 버그 수정 후, 새 기능 후 |
| `vibe-brainstorm` | 요구사항 정제 + 설계 승인 | 새 기능, 복잡한 변경 |
| `vibe-write-plan` | 마이크로태스크 계획 작성 | 설계 완료 후 |
| `vibe-execute-plan` | 계획 순서대로 실행 | 계획 작성 완료 후 |
| `vibe-code-review` | 코드 품질/보안/성능 검토 | 리팩터링, 배포 전 |
| `vibe-release` | 빌드 + 릴리즈 파이프라인 | 배포, 빌드 요청 |


---

## 🔄 자기치유 감지 패턴 (자동 업데이트: 2026-03-06 22:45)

> 워치독이 `task_logs.jsonl`에서 자동 감지한 반복 요청 패턴입니다.
> 이 패턴들을 인지하고 작업 시 우선적으로 고려하세요.

- **`rgb`** (5회 반복): 'rgb' 관련 요청이 5회 반복되었습니다. 이 패턴을 스킬에 등록하면 다음 에이전트가 즉시 활용 가능합니다.
- **`그럼`** (4회 반복): '그럼' 관련 요청이 4회 반복되었습니다. 이 패턴을 스킬에 등록하면 다음 에이전트가 즉시 활용 가능합니다.
