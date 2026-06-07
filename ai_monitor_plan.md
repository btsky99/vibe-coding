# 바이브 코딩 — 스킬 정리 + Subagent 위임 (1차 PR)

> 2026-06-07 브레인스토밍 승인. 옵션 B(스킬 → subagent 래퍼).
> 메모리: `project_skill_subagent_routing.md`

---

## 목표
1. `.claude/commands/` ↔ `.claude/skills/` **중복 제거** (시스템 reminder 두 번 표시 해소)
2. `vibe-code-review`/`vibe-security`/`vibe-debug` **3개 스킬을 subagent 래퍼로 전환** (메인 컨텍스트 다이어트)
3. 라우팅 정책 **문서화** (CLAUDE.md + agents/README.md + PROJECT_MAP.md)

## 비범위 (다음 PR)
- Plan mode 통합 — vibe-brainstorm/vibe-write-plan vs 네이티브 Plan mode 역할 분담
- 워크트리 4개 leftover 삭제 — 활성 여부만 확인 후 메모리 기록, 삭제는 별개 PR

---

## 마이크로태스크

### [x] Task 1: `.claude/commands/` 디렉토리 통째 삭제
- **파일**: `.claude/commands/*.md` 10개 (vibe-brainstorm, vibe-code-review, vibe-debug, vibe-execute-plan, vibe-heal, vibe-orchestrate, vibe-release, vibe-security, vibe-tdd, vibe-write-plan)
- **방법**: `rm -rf .claude/commands/` 한 줄 실행
- **검증**:
  - `ls .claude/commands/ 2>&1` → "No such file or directory"
  - `ls .claude/skills/` → 12개 그대로 유지 확인
- **예상 시간**: 5분

### [x] Task 2: 워크트리 활성 여부 확인 (삭제 보류)
- **파일**: 없음 (조사만)
- **방법**:
  1. `git worktree list` 실행
  2. `.claude/worktrees/clever-sutherland/`, `confident-matsumoto-790504/`, `inspiring-jepsen-f44ea4/`, `nice-curie/` 4개의 활성 여부 확인
  3. 결과를 메모리 `project_skill_subagent_routing.md`에 한 줄 추가 ("워크트리 4개 현황: 활성 N개 / 비활성 M개, 삭제는 별개 PR")
- **검증**: 메모리 파일에 워크트리 현황 줄 추가됨
- **예상 시간**: 10분
- **의존성**: 없음 (Task 1과 병렬 가능)

### [x] Task 3: `vibe-code-review/SKILL.md` 재작성
- **파일**: `.claude/skills/vibe-code-review/SKILL.md`
- **방법**: 본문을 다음 구조로 단순화 (frontmatter 유지)
  ```
  당신은 즉시 Agent 도구를 호출합니다.
    subagent_type: code-reviewer
    description: "코드 리뷰 (3관점)"
    prompt: |
      현재 디렉토리: D:\vibe-coding
      검토 대상: <사용자가 지정한 파일/디렉토리, 미지정 시 git diff 변경분>
      출력: 한국어, 3관점(성능/품질/가독성), 🔴/🟡/🔵/✅ 카운트

  subagent 결과 수신 후:
  - 🔴/🟡/🔵 카운트 1줄 보고
  - 핵심 발견 3~5개 요약
  - "수정 진행할까?" 대기 (메인이 편집 수행)
  ```
- **검증**:
  - `wc -l .claude/skills/vibe-code-review/SKILL.md` ≤ 60줄
  - frontmatter `name`, `description`, `user-invocable: true` 유지
  - 본문에 `subagent_type="code-reviewer"` 명시
- **예상 시간**: 15분
- **의존성**: 없음

### [x] Task 4: `vibe-security/SKILL.md` 재작성
- **파일**: `.claude/skills/vibe-security/SKILL.md`
- **방법**: Task 3과 동일 패턴
  - `subagent_type="security-auditor"`
  - prompt에 4단계 OWASP 점검 요청 + 한국어 출력 + cwd 명시
  - 결과 수신 후 🔴/🟡/🔵 카운트 보고 + Critical 항목 즉시 노출
- **검증**:
  - `wc -l` ≤ 60줄
  - `subagent_type="security-auditor"` 명시
  - frontmatter 유지
- **예상 시간**: 15분
- **의존성**: 없음

### [x] Task 5: `vibe-debug/SKILL.md` 재작성
- **파일**: `.claude/skills/vibe-debug/SKILL.md`
- **방법**: Task 3과 동일 패턴 + **수정 권한 가드 추가**
  - `subagent_type="debugger"`
  - prompt에 4단계 분석 요청 + 에러/스택 트레이스 전달 + cwd 명시
  - prompt 끝에 명시: **"근본 원인만 보고. 수정은 사용자 승인 받고 메인이 수행 — Edit 도구 직접 호출 금지."**
  - 결과 수신 후: 원인 1줄 + 가설 검증 결과 + "이대로 수정할까?" 대기
- **검증**:
  - `wc -l` ≤ 70줄 (수정 가드 한 줄 추가로 약간 김)
  - prompt에 "Edit 도구 직접 호출 금지" 문구 포함
  - `subagent_type="debugger"` 명시
- **예상 시간**: 15분
- **의존성**: 없음

### [x] Task 6: `.claude/agents/README.md` 신규 작성
- **파일**: `.claude/agents/README.md` (신규)
- **방법**: 다음 구조의 마크다운 작성 (200줄 이내)
  ```
  # Subagent 라우팅 정책
  표준 헤더(FILE/DESCRIPTION/REVISION HISTORY)

  ## 위임 매핑
  | 스킬 | Subagent | 위임 사유 |
  | vibe-code-review | code-reviewer | 메인 컨텍스트 다이어트, 3관점 분석 격리 |
  | vibe-security    | security-auditor | OWASP Top 10 스캔 격리 |
  | vibe-debug       | debugger | 4단계 분석 격리, Edit 권한 격리 |

  ## 위임 안 하는 스킬 (메인 유지)
  brainstorm/write-plan/execute-plan/orchestrate/heal/release/tdd/zettel/harness-init
  사유: 양방향 대화/파일 의존/외부 sync 컨텍스트 필요

  ## 신규 subagent 추가 절차
  1. .claude/agents/<name>.md 작성 (description + tools + model)
  2. 위 매핑 표 갱신
  3. 대응 vibe-* 스킬 본문에 라우팅 추가
  ```
- **검증**:
  - 파일 존재, 200줄 이내
  - 표 3행 모두 포함
  - 표준 헤더 포함
- **예상 시간**: 15분
- **의존성**: Task 3~5 완료 후 (스킬 본문과 일치성 확인 위해)

### [x] Task 7: `CLAUDE.md` 세부 규칙 섹션에 한 줄 추가
- **파일**: `CLAUDE.md`
- **방법**: "🗂️ 세부 규칙" 섹션 목록에 한 줄 삽입
  ```
  - [.claude/agents/README.md](./.claude/agents/README.md) — Subagent 위임 라우팅 정책
  ```
  위치: `.claude/rules/file-limits.md` 줄 다음
- **검증**:
  - `grep "agents/README.md" CLAUDE.md` 매칭 1건
  - 파일 1500줄 이하 유지
- **예상 시간**: 5분
- **의존성**: Task 6 완료 후

### [x] Task 8: `PROJECT_MAP.md` 스킬 카운트 갱신
- **파일**: `PROJECT_MAP.md`
- **방법**:
  1. `commands/` 관련 줄이 있으면 제거 또는 "삭제됨" 표기
  2. `skills/` 카운트를 12개로 명시
  3. `agents/` 섹션 추가 (3개: code-reviewer/security-auditor/debugger)
- **검증**:
  - `grep -E "skills.*12|agents.*3" PROJECT_MAP.md` 매칭
  - commands 잔재 없음
- **예상 시간**: 10분
- **의존성**: Task 1 완료 후

### [x] Task 9: 수동 검증 — 스킬 1개 실제 호출 (2026-06-07: orchestrator 호출 시 reminder에서 vibe-* 중복 없음 확인)
- **파일**: 없음 (실행 검증)
- **방법**:
  1. 메인 세션에서 `/vibe-code-review` 호출 시도 (이번 변경의 git diff 대상)
  2. 시스템 reminder에서 `vibe-code-review`가 **1번만** 표시되는지 확인 (중복 해소 검증)
  3. 스킬 실행 시 `code-reviewer` subagent로 위임되는지 확인
  4. 결과를 메인이 요약 보고하는지 확인
- **검증**:
  - 시스템 reminder 중복 0건
  - subagent 위임 성공 (Agent 도구 호출 로그)
  - 메인 컨텍스트가 가벼움 (전체 diff를 메인이 직접 읽지 않음)
- **예상 시간**: 10분
- **의존성**: Task 1~7 모두 완료 후

### [x] Task 10: 커밋 (Conventional Commits + 한글 본문)
- **파일**: 없음 (git 작업)
- **방법**:
  ```
  refactor(skills): commands/ 중복 제거 + 3개 스킬을 subagent 래퍼로 전환

  ## 변경 이유 (Why)
  .claude/commands/와 .claude/skills/가 같은 이름으로 양쪽 등록되어
  시스템 reminder에 중복 표시. vibe-code-review/security/debug는
  메인 컨텍스트를 많이 잡아먹어 다른 작업 여유 부족.

  ## 변경 내용 (What)
  - .claude/commands/ 디렉토리 삭제 (10개 파일)
  - vibe-code-review/SKILL.md — code-reviewer subagent 위임 래퍼로
  - vibe-security/SKILL.md — security-auditor subagent 위임 래퍼로
  - vibe-debug/SKILL.md — debugger subagent 위임 래퍼로 (Edit 가드 추가)
  - .claude/agents/README.md — 라우팅 매핑 표 신규
  - CLAUDE.md — 세부 규칙에 agents/README.md 한 줄 추가
  - PROJECT_MAP.md — 스킬/subagent 카운트 갱신

  ## 영향 범위 (Impact)
  3개 스킬의 동작 방식 변경 — 사용자 슬래시 호출 인터페이스는 그대로,
  내부적으로 subagent에 위임. 다른 스킬(brainstorm/write-plan 등)은 무영향.
  ```
- **검증**:
  - `git log -1 --format=%B` 본문 3섹션 포함
  - pre-commit hook 통과
  - `git status` 클린
- **예상 시간**: 5분
- **의존성**: Task 1~9 모두 완료 후

---

## 의존성 그래프
```
Task 1 (commands 삭제) ─┐
Task 2 (워크트리 확인) ─┤
Task 3 (code-review)   ─┤
Task 4 (security)      ─┼─→ Task 6 (agents README) ─→ Task 7 (CLAUDE.md)
Task 5 (debug)         ─┤
                        └─→ Task 8 (PROJECT_MAP)
Task 1~8 완료 → Task 9 (수동 검증) → Task 10 (커밋)
```
- Task 1~5는 **병렬 실행 가능** (서로 다른 파일)
- Task 6은 Task 3~5 완료 후
- Task 7은 Task 6 완료 후
- Task 8은 Task 1 완료 후
- Task 9는 Task 1~7 모두 완료 후
- Task 10은 Task 1~9 모두 완료 후

## 총 예상 시간
약 1시간 45분 (병렬 실행 시 1시간 이내)

---

## 검증 체크리스트 (전체 완료 후)
- [ ] `ls .claude/commands/` → 디렉토리 없음
- [ ] `ls .claude/skills/` → 12개 유지
- [ ] 3개 스킬이 60~70줄 이내
- [ ] `.claude/agents/README.md` 존재 + 표 3행
- [ ] `CLAUDE.md` 세부 규칙에 agents/README.md 줄 추가됨
- [ ] `PROJECT_MAP.md` 스킬 12개 / agents 3개 명시
- [ ] 시스템 reminder에서 `vibe-code-review` 1번만 표시
- [ ] subagent 위임 실제 동작 확인
- [ ] 커밋 메시지 본문 3섹션
- [ ] `git status` 클린

## 롤백 계획
문제 발생 시:
1. `git restore .claude/commands/ .claude/skills/ CLAUDE.md PROJECT_MAP.md` — 작업 디렉토리 원복
2. 커밋 이후 문제 발견 시 `git revert <commit>` — 새 revert 커밋으로 안전 롤백
3. 메모리는 그대로 유지 (다음 재시도 참고용)
