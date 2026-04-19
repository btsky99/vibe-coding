---
name: platform-check
description: >
  Vibe Coding 플랫폼 레이어 상태를 진단한다. docs/PLATFORM_LAYERS.md를
  참조해 Layer 1/2 경계 위반을 탐지하고, project_id 스코프 일관성을 확인한다.
  Use when: "플랫폼 상태", "레이어 확인", "project_id 감사", "레이어 진단" 요청 시.
allowed-tools: Read, Grep, Bash
user-invocable: true
---

당신은 Vibe Coding 플랫폼 진단 프로토콜을 실행합니다.

## 배경

Vibe Coding은 "하네스/하이브/옵시디언을 내장한 멀티에이전트 IDE"로,
프로젝트를 열면 **Layer 1(공통 런타임)** 이 자동으로 활성화되고
그 위에 **Layer 2(프로젝트별 확장)** 이 얹힙니다.
상위 문서: [docs/PLATFORM_LAYERS.md](docs/PLATFORM_LAYERS.md)

## 절차

### 1단계 — Layer 1 project_id 스코프 점검
PostgreSQL의 Layer 1 테이블(`hive_memory`, `zettel_notes`, `zettel_links`,
`hive_tasks`, `hive_sessions`, `pg_logs`, `agent_*`, `active_session_context`,
`hive_skill_chains`, `hive_state`, `office_*`, `pg_messages`, `task_comments`)에서:
- [ ] 모든 테이블에 `project_id` 컬럼이 존재하는가?
- [ ] 값이 정규 슬러그로 통일되어 있는가? (이 리포: `D--vibe-coding`)
- [ ] empty/null 값이 남아있는가?

진단 쿼리 (`.ai_monitor/src/pg_store.py`의 `_layer1_project_id_tables` 참조):
```sql
SELECT table_name, column_name
FROM information_schema.columns
WHERE table_schema='public'
  AND column_name IN ('project','project_id')
ORDER BY table_name;
```

구 컬럼 `project`가 남아있으면 즉시 보고.

### 2단계 — Layer 2 확장 스캔
- [ ] `.vibe/skills/` 디렉토리가 존재하는가?
- [ ] `.claude/skills/` 와 이름 충돌이 있는가?
- [ ] 각 `SKILL.md`가 frontmatter(`name`, `description`)를 갖추었는가?

점검 API: `GET /api/vibe/skills` (서버 실행 중일 때)

### 3단계 — 레이어 혼재 탐지
`docs/PLATFORM_LAYERS.md` §"현재 리포의 레이어 혼재 자가 진단"에 나열된
6개 지점이 해소되었는지 확인:
- `scripts/harness_verify.py` — PROJECT_ROOT 하드코딩?
- `.ai_monitor/api/vibe_api.py` — Layer 1 로직 섞임?
- (기타 지점 참조)

## 보고 양식

```markdown
## 플랫폼 진단 리포트 (YYYY-MM-DD)

### Layer 1 상태
- project_id 컬럼 커버리지: N/16 테이블
- 정규 슬러그 통일: OK / 예외 M건
- empty/null: 0건 / 총합

### Layer 2 확장
- .vibe/skills: N개
- .claude/skills: M개
- 충돌: [...]

### 경계 위반
- [ ] 없음  또는  [!] N건 (상세)

### 권장 조치
- ...
```

## 제한

- DB 쓰기 없음 (읽기/진단만)
- 서버 종속 기능(예: `/api/vibe/skills` 호출)은 서버 실행 중이어야 동작
- 에이전트 중립: Claude/Gemini/Codex 누가 실행해도 결과 동일해야 함
