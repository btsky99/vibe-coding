<!--
FILE: .claude/agents/README.md
DESCRIPTION: Subagent 위임 라우팅 정책. 어느 vibe-* 스킬이 어느 subagent로 위임되는지 매핑.
             신규 subagent 추가 절차도 포함.

REVISION HISTORY:
- 2026-06-07 Claude: [신규] vibe-code-review/security/debug 3개 스킬을 subagent 래퍼로 전환하며 라우팅 표 추가.
                    외부 프로젝트 적용은 2차 PR(skills-install 세팅 프롬프트)에서 진행.
-->

# Subagent 라우팅 정책

이 디렉토리의 `<name>.md` 파일은 Claude Code subagent 정의다. 메인 컨텍스트와 격리된 작업 컨텍스트에서 실행되어 메인의 토큰 부담을 줄이고 도메인 특화 작업을 격리한다.

---

## 라우팅 매핑 (vibe-* 스킬 → subagent)

| Slash 스킬 | Subagent | 위임 사유 |
|-----------|----------|----------|
| `/vibe-code-review` | `code-reviewer` | 3관점(성능/품질/가독성) 분석을 메인에서 분리, 토큰 절약 |
| `/vibe-security` | `security-auditor` | OWASP Top 10 스캔 격리, grep 부담 분리 |
| `/vibe-debug` | `debugger` | 4단계 분석 격리 + Edit 권한 격리 (수정은 사용자 승인 후 메인이 수행) |

**위임 흐름:** 사용자가 `/vibe-*` 호출 → 스킬이 `Agent(subagent_type=..., prompt=...)` 즉시 호출 → subagent 결과 수신 → 메인이 핵심만 요약 보고 → 사용자 승인 시 메인이 후속 작업(편집/배포 등) 수행.

---

## 위임 안 하는 스킬 (메인 컨텍스트 유지)

| Slash 스킬 | 메인 유지 사유 |
|-----------|----------|
| `/vibe-brainstorm` | A/B/C 질의응답 양방향 대화, subagent 위임 시 흐름 끊김 |
| `/vibe-write-plan` | 사용자 확인 받으며 파일 작성 |
| `/vibe-execute-plan` | `ai_monitor_plan.md` 의존, 순차 실행 추적 |
| `/vibe-orchestrate` | 통합 컨트롤 타워, 다른 스킬 호출 |
| `/vibe-heal` | 반복 오류 패턴 분석, 메인 히스토리 필요 |
| `/vibe-release` | 버전 증가/커밋/푸시 — 메인 권한 필요 |
| `/vibe-tdd` | RED-GREEN-REFACTOR 순차 진행 |
| `/vibe-zettel` | 옵시디언 sync 컨텍스트 필요 |
| `/vibe-harness-init` | 설정 변경 작업 |

---

## 신규 Subagent 추가 절차

1. `.claude/agents/<name>.md` 작성 (frontmatter `name`/`description`/`tools`/`model` 포함, 한국어 출력 명시)
2. 위 라우팅 매핑 표 갱신
3. 대응 `.claude/skills/vibe-<name>/SKILL.md` 본문에 `Agent(subagent_type="<name>", prompt=...)` 호출 패턴 추가
4. `PROJECT_MAP.md`의 subagent 카운트 갱신 (자동 생성 시 반영되도록 `scripts/generate_project_map.py` 보강 권장)

---

## 외부 프로젝트 적용 (2차 PR 예고)

이 라우팅 정책을 다른 프로젝트(예: D:/ons, D:/clim)에서도 그대로 쓰려면 별도 작업 필요:
- 신규 세팅 프롬프트 ⑨ `skills-install` 추가 — `install_hive_hooks.py` 패턴 복제
- vibe-coding 저장소의 `.claude/skills/`, `.claude/agents/`를 외부 프로젝트로 동기화
- 외부 프로젝트 세팅 시 "프로젝트 세팅" 버튼 한 번 누르면 자동 적용

상세: 1차 PR 완료 후 별도 `vibe-brainstorm` 세션에서 설계.
