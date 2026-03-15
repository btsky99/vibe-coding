---
name: vibe-heal
description: >
  자기치유 스킬. 반복 오류 패턴을 감지하고 근본 원인을 수정하여 재발을 방지합니다.
  Use when: 같은 에러가 반복, "또 같은 에러", "계속 안 돼", "자꾸 터져", 반복 오류 패턴 감지 시.
allowed-tools: Read, Write, Edit, Bash, Glob, Grep
user-invocable: true
context: fork
agent: general-purpose
---

<!--
FILE: .claude/skills/vibe-heal/SKILL.md
DESCRIPTION: Vibe Coding 자기치유(Self-Healing) 스킬.
             task_logs.jsonl에서 반복 오류 패턴을 감지하고
             근본 원인을 수정하여 같은 에러가 반복되지 않도록 합니다.
             Skills 2.0: context: fork — 격리된 서브에이전트에서 실행하여 메인 컨텍스트 보호.

REVISION HISTORY:
- 2026-03-13 Claude: [Skills 2.0] context: fork 적용, known-patterns.md 보조파일 추가
- 2026-03-05 Claude: [신규] 자기치유 스킬 생성
-->

당신은 지금 **Vibe Coding 자기치유 프로토콜**을 실행합니다.

# 🧬 자기치유 프로토콜 (Self-Healing)

**핵심 원칙: 같은 에러가 2번 이상 반복되는 것은 스킬/코드/구조의 문제다. 증상이 아닌 패턴을 제거한다.**

> 이 스킬은 격리된 컨텍스트(fork)에서 실행됩니다. 치유 작업이 메인 컨텍스트를 오염시키지 않습니다.
> 알려진 반복 패턴 목록: `$CLAUDE_SKILL_DIR/known-patterns.md` 참조

---

## 1단계: 반복 패턴 감지

```bash
# 최근 task_logs에서 반복 요청/오류 패턴 확인
python scripts/claude_watchdog.py --analyze 2>/dev/null || true
```

직접 분석 기준:
- **동일 오류 메시지** 2회 이상 → 즉시 치유 대상
- **동일 파일 수정** 3회 이상 → 구조적 문제 의심
- **동일 요청 키워드** 3회 이상 → 스킬 부재 또는 스킬 오작동

감지된 패턴 보고:
```
🔍 반복 패턴 감지:
  - "X 오류" — 최근 N회 반복 (파일: Y)
  - "Z 수정 요청" — N회 반복
```

---

## 2단계: 근본 원인 분류

| 원인 유형 | 증상 | 치유 방법 |
|-----------|------|----------|
| **코드 결함** | 특정 파일/함수에서 반복 오류 | 해당 코드 구조 수정 |
| **스킬 누락** | 반복 요청인데 전용 스킬 없음 | 신규 스킬 파일 생성 |
| **지식 부재** | 매번 같은 정보를 새로 찾음 | references/ 업데이트 |

---

## 3단계: 자동 치유 실행

### A. 코드 결함인 경우
- `vibe-debug` 스킬을 호출하여 근본 원인 수정
- 수정 후 동일 조건으로 재현 테스트
- 한글 주석에 "자기치유 수정" 표시 필수

### B. 스킬 누락인 경우
- 반복 패턴에 맞는 신규 스킬 파일 초안 작성
- `.claude/skills/vibe-[이름]/SKILL.md` 생성 (Skills 2.0 형식)
- `.gemini/skills/[이름]/SKILL.md` 동기화 생성
- `known-patterns.md`에 패턴 추가

### C. 지식 부재인 경우
- `.gemini/skills/master/references/` 관련 파일 업데이트
- 재사용 가능한 해결책을 명확한 패턴으로 문서화

---

## 4단계: 치유 결과 검증

검증 기준:
- ✅ 에러 메시지가 사라졌는가
- ✅ 기존 기능이 정상 동작하는가
- ✅ 치유 내용이 `known-patterns.md`에 문서화되었는가

---

## 5단계: 하이브 메모리 업데이트

```bash
python scripts/memory.py set "heal:[패턴명]" "[치유 방법 요약]"
```

치유 보고 형식:
```
🧬 자기치유 완료
━━━━━━━━━━━━━━━━━━━━━━━━━
감지된 패턴: [패턴 설명]
반복 횟수: N회
원인 유형: 코드 결함 / 스킬 누락 / 지식 부재
치유 방법: [수행한 조치]
재발 방지: [추가된 스킬/문서/수정 내용]
━━━━━━━━━━━━━━━━━━━━━━━━━
```

---

## ⚠️ 자기치유 원칙

1. **패턴 우선**: 개별 증상이 아닌 반복 패턴에 집중
2. **최소 변경**: 치유에 필요한 최소한의 수정만
3. **검증 필수**: 치유 후 반드시 동작 확인 후 완료 보고
4. **지식화**: 모든 치유는 `known-patterns.md`에 기록하여 다음 에이전트가 활용
