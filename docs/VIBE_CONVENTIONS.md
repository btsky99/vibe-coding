<!--
FILE: docs/VIBE_CONVENTIONS.md
DESCRIPTION: .vibe/ 디렉토리 규약 — Layer 2 확장(프로젝트별 스킬/에이전트/규칙)을
             Vibe Coding 플랫폼이 자동 로드하기 위한 표준 정의.
             Platform Phase 3의 기반 문서.

REVISION HISTORY:
- 2026-04-19 Claude: 최초 작성 — Phase 3-1 규약 단계
  - .vibe/skills/ 포맷 스펙 (Claude Code skills와 호환)
  - .claude/ 병합 규칙 (중복 시 .vibe/ 우선)
  - 스캐너 API 계약
-->

# 📦 `.vibe/` 컨벤션

> **"`.vibe/`는 멀티 에이전트(Claude / Gemini / Codex) 공통 Layer 2 확장이다.
> `.claude/`는 Claude CLI 전용이며, 두 디렉토리는 병합 로드된다."**

이 문서는 Vibe Coding 플랫폼이 프로젝트 루트의 `.vibe/` 디렉토리에서
**무엇을**, **어떤 포맷으로**, **어떻게** 로드할지를 정의한다.

상위 아키텍처: [docs/PLATFORM_LAYERS.md](./PLATFORM_LAYERS.md) (Layer 2)

---

## 🎯 왜 `.vibe/` 인가

| 디렉토리 | 성격 | 읽는 주체 | 수명 |
|---------|-----|---------|------|
| `.claude/` | Claude CLI 전용 훅·스킬 (Anthropic 규약) | Claude CLI + Vibe 서버 | Claude CLI 의존 |
| **`.vibe/`** | 플랫폼 공통 확장 (Claude/Gemini/Codex 공용) | Vibe 서버(+각 CLI가 선택적 참조) | Vibe Coding 자체 |
| `sprint_contracts/`, `feature_list.json` | Layer 1 스키마를 따르는 프로젝트 데이터 | Vibe 서버, 하네스 | 하네스 규약 |

`.claude/`에만 의존하면 Claude CLI가 바뀌거나 다른 에이전트가 참여할 때 이식이 어렵다.
`.vibe/`는 **에이전트 중립** 영역.

---

## 📁 디렉토리 구조

```
<project-root>/
└── .vibe/
    ├── skills/
    │   └── <skill-name>/
    │       └── SKILL.md        # 필수. 슬래시 커맨드/프롬프트 템플릿
    ├── agents/                  # Phase 4 예정 — 현재 미구현
    │   └── <agent-name>.md
    └── rules/                   # Phase 4 예정 — 현재 미구현
        └── <rule-name>.md
```

**Phase 3 범위:** `.vibe/skills/`만. `agents/`, `rules/`는 후속.

---

## 📄 `SKILL.md` 포맷

Claude Code `.claude/skills/<name>/SKILL.md`와 **동일한 YAML frontmatter 스펙**을 사용한다.
파서 재사용 + Claude CLI가 같은 스킬을 직접 실행 가능하다는 덤.

### 예시

```markdown
---
name: platform-check
description: >
  Vibe Coding 플랫폼 레이어 상태를 진단한다. PLATFORM_LAYERS.md를 참조해
  Layer 1/2 경계 위반을 탐지하고, project_id 스코프 일관성을 확인한다.
  Use when: "플랫폼 상태", "레이어 확인", "project_id 감사" 요청 시.
allowed-tools: Read, Grep, Bash
user-invocable: true
---

당신은 Vibe Coding 플랫폼 진단 프로토콜을 실행합니다.

## 절차
1. ...
```

### Frontmatter 필드

| 필드 | 필수 | 타입 | 설명 |
|------|-----|------|------|
| `name` | ✅ | string | 슬래시 커맨드 이름. 디렉토리명과 일치 권장 |
| `description` | ✅ | string (멀티라인 허용) | 어떤 상황에서 호출할지. "Use when:" 포함 권장 |
| `allowed-tools` | ⬜ | comma list | 스킬 실행 중 허용할 도구 (Read, Write, Bash 등) |
| `user-invocable` | ⬜ | bool (기본 true) | UI 슬래시 팝업 노출 여부 |
| `origin` | (자동) | string | 스캐너가 `vibe` / `claude` 값을 부여 — 저자가 쓸 필요 없음 |

### Body

YAML frontmatter 뒤 빈 줄을 두고 마크다운 본문.
본문은 에이전트에게 주입될 **프롬프트 템플릿**으로 해석된다.

---

## 🔀 `.claude/` 병합 규칙

Vibe 서버는 두 디렉토리를 **병합**해 단일 스킬 목록을 제공한다.

```
final_skills = { s.name: s for s in scan(.claude/skills) }
for s in scan(.vibe/skills):
    final_skills[s.name] = s    # 같은 이름이면 .vibe/ 우선
```

### 우선순위 근거
1. `.vibe/`는 프로젝트 저자가 **명시적으로** 올린 것 → 의도가 더 강함
2. `.claude/`는 Claude CLI 기본 스킬(다수가 vibe-* 프리픽스)과 겹칠 수 있음
3. 충돌이 발견되면 스캐너가 경고 로그 1회 출력 (조용히 덮어쓰지 않음)

### 병합 결과에 `origin` 부여
스캐너는 각 스킬에 `origin: "claude" | "vibe"` 필드를 추가한다.
UI는 이 값을 배지로 표시해 "어디서 왔는지" 사용자가 알 수 있게 한다.

---

## 🔌 스캐너 API 계약

**엔드포인트:** `GET /api/vibe/skills`

**쿼리 파라미터:**
- `project_root` (선택, 기본값: 현재 활성 프로젝트) — 절대 경로

**응답 (200 OK):**
```json
{
  "project_root": "D:\\vibe-coding",
  "skills": [
    {
      "name": "vibe-brainstorm",
      "description": "모든 기능 구현 전 필수 단계...",
      "allowed_tools": ["Read", "Write", "Bash"],
      "user_invocable": true,
      "origin": "claude",
      "path": ".claude/skills/vibe-brainstorm/SKILL.md"
    },
    {
      "name": "platform-check",
      "description": "Vibe Coding 플랫폼 레이어 상태를 진단한다...",
      "allowed_tools": ["Read", "Grep", "Bash"],
      "user_invocable": true,
      "origin": "vibe",
      "path": ".vibe/skills/platform-check/SKILL.md"
    }
  ],
  "conflicts": []
}
```

**응답 (에러):**
- 404: project_root가 존재하지 않음
- 400: project_root가 절대 경로가 아님

**멱등성:** 서버는 매 요청마다 디스크 스캔(캐시 없음, Phase 3에선). 프로젝트가 크면 Phase 5에서 캐시 도입.

---

## 🚨 금지 사항

| # | 금지 | 이유 |
|---|-----|------|
| 1 | `.vibe/skills/<name>/SKILL.md` 이외 파일에 의존 | 스캐너는 `SKILL.md`만 읽음. 보조 리소스는 스킬 본문에서 `Read`로 접근 |
| 2 | Claude CLI 전용 기능을 `.vibe/skills/`에서 가정 | `.vibe/`는 에이전트 중립이어야 함. Gemini/Codex 실행도 염두에 둘 것 |
| 3 | frontmatter 없이 SKILL.md 작성 | 스캐너가 무시하고 WARN 출력 |
| 4 | `name` 필드 값과 디렉토리명 불일치 | 혼란 유발. 스캐너가 WARN 출력 (에러는 아님) |
| 5 | `.vibe/` 경로에 민감 정보 (토큰, 키) 커밋 | Layer 2 확장은 프로젝트에 커밋되는 공개 자산 |

---

## 🔍 하네스 검증 (Phase 3-5)

`scripts/harness_verify.py`는 `.vibe/` 디렉토리가 존재할 때 다음을 검사한다:

- `SKILL.md`에 YAML frontmatter가 있는가
- `name`, `description` 필수 필드가 있는가
- 디렉토리명과 `name` 필드가 일치하는가 (일치 안 하면 WARN)

실패는 에러가 아닌 경고. `.vibe/`는 **선택**이므로 프로젝트에 없어도 무방.

---

## 📚 관련 문서

- 상위: [docs/PLATFORM_LAYERS.md](./PLATFORM_LAYERS.md) — 3-Layer 모델 전체
- 하네스: [docs/HARNESS_V2.md](./HARNESS_V2.md)
- 구현 계획: [ai_monitor_plan.md](../ai_monitor_plan.md) §Platform Phase 3

---

**작성일:** 2026-04-19
**상태:** Phase 3-1 완료. 3-2(서버 스캐너) 구현 대기.
