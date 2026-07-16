<!--
FILE: ai_monitor_plan.md
DESCRIPTION: 로드맵 ③ 코덱스 래퍼 회상 주입 실행 계획 — handle_chat(대시보드/오피스 공용
             프롬프트 중계 지점)에서 cli=='codex'일 때만 회상 v2 요약을 stdin 전달분에 접두.

REVISION HISTORY:
- 2026-07-16 Claude: 신규. 로드맵 ②(안티그래비티 회상 주입, db089a6) 완료 → 교체. A안 승인됨.
-->

# 구현 계획 — 로드맵 ③ 코덱스 래퍼 회상 주입

> **근거**: 2026-07-14 합의 로드맵 (`project_claude_loop_100` 메모리). ①(a165156)·②(db089a6)
> 실측 검증 완료 → ③ 코덱스는 훅 시스템이 없어 **대시보드 프롬프트 중계 시점 래퍼 주입이 상한선**.
> **북극성**: 에이전트 확장이 아니라 자가치유 루프 실효율 완성 (`project_ultimate_goal`).

## 핵심 사실 (정찰 실측, 2026-07-16)
- 중계 지점: `.ai_monitor/api/agent_api.py:1004 handle_chat` (POST /api/agent/chat) —
  클래식 ChatSlot.tsx + 오피스 useOfficeChat.ts **공용**. 오피스 Phase 5 통로 이미 존재.
- 코덱스 전달: `stdin=PIPE`(agent_api.py:1100-1103) — 메시지 앞 접두 주입 안전.
- 재사용 부품: `src/recall_client.smart_recall_summary(query, limit, caller)` — 2초 상한
  + 3단 폴백 + 예외 전부 삼킴. ②에서 caller 계측(memory_api.py:295) + heal_report
  에이전트별 분해 완비 → `caller='codex'`만 넘기면 계측 자동.
- [제약] 서버 프로세스 자신은 `VIBE_SERVER_PORT` env 미보유(daemons.py:115는 자식에게만
  주입) → recall_client가 포트 스캔(보통 9000 즉답, 최악 0.3초×20). handler.server의
  실제 바인드 포트로 setdefault해 스캔 생략.
- [불변식] claude(hive_hook)/antigravity(BeforeAgent 훅)는 이미 회상 주입됨 —
  handle_chat에서는 **codex만** 주입 (이중 주입 금지).
- agent_api.py 현재 1373줄 — +~25줄로 1500 한계 무위반.

---

## 태스크

### [x] Task 1: handle_chat에 코덱스 회상 주입
- **파일**: `.ai_monitor/api/agent_api.py`
- **방법**:
  1. 모듈 헬퍼 `_codex_recall_prefix(message: str, server_port: int) -> str` 신설 —
     `os.environ.setdefault('VIBE_SERVER_PORT', str(server_port))` 후
     `from src.recall_client import smart_recall_summary` (지연 import, 훅 스타일)로
     `smart_recall_summary(message[:120], limit=5, caller='codex')` 호출.
     요약이 비면 `''` 반환. 어떤 예외도 삼킴(채팅 중계 중단 금지).
  2. `handle_chat`에서 stdin 쓰기 직전(`use_stdin_pipe` 블록):
     `cli == 'codex'`이고 prefix가 있으면
     `relay = f"[하이브 회상 — 과거 지식]\n{prefix}\n---\n{message}"` 를 stdin에 쓴다.
  3. `history` 및 `_bus_append`에는 **원문 message 유지** (UI/텔레그램에 회상 블록 노출 금지).
- **검증**: `wc -l` ≤ 1500. 주입은 stdin 한 곳만(원문/주입본 분리 육안 확인).

### [x] Task 2: 회귀 + 실측 검증
- **의존**: Task 1 완료 후.
- **방법**: `pytest tests/` 전체(기존 127개 무파괴 확인). 서버 재기동 후 실측:
  코덱스 슬롯(T3)에 메시지 전송 → `pg_logs`에서 `agent='recall' AND metadata->>'caller'='codex'`
  이벤트 확인 + heal_report 에이전트별 분해에 codex 행 등장 확인.
  (서버 미가동/코덱스 CLI 부재 시: recall-smart를 caller='codex'로 직접 POST해 계측 경로만 확증)

### [x] Task 3: 마무리 — 커밋 + 메모리 갱신
- **의존**: Task 2 완료 후.
- **방법**: Conventional Commits 3단 본문 커밋(`feat(agent): 로드맵 ③ 코덱스 회상 주입`).
  `project_claude_loop_100.md` 메모리에 ③ 완료 기록(주입 지점 = handle_chat,
  3에이전트 회상 경로 수렴 완성). `python scripts/hive_bridge.py` + checkpoint 기록.

---

## 의존성 요약
- Task 1 → Task 2 → Task 3 순차.

## 완료 정의
- 대시보드/오피스 채팅에서 코덱스로 보내는 모든 메시지에 회상 v2가 접두 주입됨
  (서버 warm 시 벡터 회상, 불통 시 v1 폴백, 요약 없으면 무주입).
- pg_logs 회상 이벤트에 caller='codex'가 기록되어 heal_report 에이전트별 분해에 노출.
- claude/antigravity 채팅 경로는 무변경 (이중 주입 없음).
- 이로써 3에이전트(claude 훅 / antigravity 훅 / codex 래퍼) 회상 경로 수렴 — 클로드 루프 100% 로드맵 종결.

## 남은 로드맵
- ③ 완료 후: 메타버스 재개 여부 재논의 (2026-07-14 합의).
