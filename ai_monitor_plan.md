# AI 오케스트레이터 스킬 체인 DB 전환 계획

**작성일:** 2026-03-01
**작성자:** Claude (vibe-write-plan)
**목표:** skill_chain.json → skill_chain.db(SQLite) 전환 + 터미널별 스킬 실행 추적 UI

---

## 설계 요약

- **DB 파일**: `.ai_monitor/data/skill_chain.db` (신규, 오케스트레이터 전용)
- **터미널 구분**: `--terminal N` 플래그로 1~8번 터미널에 체인 귀속
- **표기 방식**: `N-M` (터미널N, 스킬번호M) → 예: `1-3 → 1-4 → 1-5`
- **스킬 번호 고정**: 1=debug, 2=tdd, 3=brainstorm, 4=write-plan, 5=execute, 6=review, 7=release

---

## 태스크 목록

### [x] Task 1: skill_orchestrator.py — JSON→SQLite 전환 + --terminal 플래그

**파일:** `scripts/skill_orchestrator.py`

**방법:**
1. `CHAIN_FILE` 제거 → `DB_FILE = DATA_DIR / "skill_chain.db"` 추가
2. `_ensure_db()` 함수: `skill_chains` 테이블 자동 생성
   ```sql
   CREATE TABLE IF NOT EXISTS skill_chains (
     id          INTEGER PRIMARY KEY AUTOINCREMENT,
     session_id  TEXT NOT NULL,
     terminal_id INTEGER NOT NULL DEFAULT 0,
     request     TEXT,
     skill_num   INTEGER,
     skill_name  TEXT,
     step_order  INTEGER,
     status      TEXT DEFAULT 'pending',
     summary     TEXT DEFAULT '',
     started_at  TEXT,
     updated_at  TEXT
   )
   ```
3. `cmd_plan()`: `--terminal N` 플래그 파싱 → terminal_id 저장
   - 각 스킬을 skill_num(전역 번호)과 step_order(이 세션의 순서)와 함께 INSERT
4. `cmd_update()`: terminal_id 기준으로 현재 세션 레코드 UPDATE
5. `cmd_done()`: terminal_id 기준 세션 완료 처리 + skill_results.jsonl 저장 유지
6. `cmd_reset()`: terminal_id 기준 DELETE 또는 status='idle' UPDATE
7. `cmd_status()`: DB에서 터미널별 최신 세션 조회 후 JSON 출력

**스킬 번호 매핑 (상수):**
```python
SKILL_REGISTRY = [
  {"num": 1, "name": "vibe-debug",        "short": "debug"},
  {"num": 2, "name": "vibe-tdd",          "short": "tdd"},
  {"num": 3, "name": "vibe-brainstorm",   "short": "brainstorm"},
  {"num": 4, "name": "vibe-write-plan",   "short": "write-plan"},
  {"num": 5, "name": "vibe-execute-plan", "short": "execute"},
  {"num": 6, "name": "vibe-code-review",  "short": "review"},
  {"num": 7, "name": "vibe-release",      "short": "release"},
]
```

**검증:** `python scripts/skill_orchestrator.py plan --terminal 1 "테스트" vibe-debug vibe-tdd` 실행 후 DB 확인

---

### [x] Task 2: hive_api.py — skill-chain 엔드포인트 DB 쿼리로 변경

**파일:** `.ai_monitor/api/hive_api.py`
**의존성:** Task 1 완료 후

**수정 위치:**
1. `/api/orchestrator/skill-chain` (GET, line ~211) — JSON 파일 읽기 → DB 쿼리
2. `/api/orchestrator/skill-chain/update` (POST, line ~596) — JSON → DB UPDATE

**응답 구조:**
```json
{
  "skill_registry": [{"num":1,"name":"vibe-debug","short":"debug"}, ...],
  "terminals": {
    "1": {
      "session_id": "...", "request": "...", "status": "running",
      "steps": [
        {"label":"1-3","skill_num":3,"skill_name":"vibe-brainstorm","status":"done","summary":""},
        {"label":"1-4","skill_num":4,"skill_name":"vibe-write-plan","status":"running","summary":""},
        {"label":"1-5","skill_num":5,"skill_name":"vibe-execute-plan","status":"pending","summary":""}
      ]
    }
  }
}
```

**검증:** curl `http://localhost:3333/api/orchestrator/skill-chain` 응답 구조 확인

---

### [x] Task 3: server.py — skill-chain 엔드포인트 DB 쿼리로 변경

**파일:** `.ai_monitor/server.py`
**의존성:** Task 1 완료 후 (Task 2와 병렬 가능)

**수정 위치:**
1. GET `/api/orchestrator/skill-chain` (line ~1534)
2. POST `/api/orchestrator/skill-chain/update` (line ~3404)

hive_api.py와 동일한 DB 쿼리 로직 적용

**검증:** Task 2와 동일

---

### [x] Task 4: OrchestratorPanel.tsx — 스킬 레지스트리 + 터미널별 N-M 표기 UI

**파일:** `.ai_monitor/vibe-view/src/components/panels/OrchestratorPanel.tsx`
**의존성:** Task 2, 3 완료 후

**방법:**
1. 타입 확장 (SkillRegistry, TerminalStep, TerminalChain 인터페이스 추가)
2. **상단 스킬 레지스트리** 위젯:
   - 원형 번호 ①~⑦ + 스킬 약칭 배지
3. **터미널별 체인 섹션**:
   - 활성 터미널만 표시 (steps가 있는 것만)
   - `T1 [18:56]  1-③ → 1-④ → 1-⑤`  (✅🔄⏳)
4. 기존 단일 체인 위젯은 하위 호환 fallback으로 축소

**검증:** `npx tsc --noEmit` 오류 없음 + 브라우저에서 오케스트레이터 탭 확인

---

## 실행 순서

```
Task 1 (skill_orchestrator.py)
    ↓
Task 2 (hive_api.py) ── 병렬 가능
Task 3 (server.py)   ──┘
    ↓
Task 4 (OrchestratorPanel.tsx)
```

---

## 비고

- `skill_chain.json` 파일은 삭제하지 않고 보존 (배포 버전 호환성)
- `skill_results.jsonl` 히스토리 저장 기능 유지
- `--terminal` 미지정 시 `terminal_id = 0` (unknown) 으로 처리
