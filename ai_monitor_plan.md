<!--
FILE: ai_monitor_plan.md
DESCRIPTION: 정리 단계 실행 계획 — telegram_bridge 분할(1500줄 규칙 예방) +
             ty/psycopg3 도입 검토(사실 수집 → 권고안). A+B+C(8f0443f까지) 완료 후속.

REVISION HISTORY:
- 2026-07-16 Claude: 신규. A+B(a34b698)+C(bd1ecbe)+Vite8(8f0443f) 완료 → 교체.
  사용자 승인 순서: A+B → C → 정리 → D(메타버스 재논의). 이번이 '정리'.
-->

# 구현 계획 — 정리 단계: telegram_bridge 분할 + ty/psycopg3 검토

> **근거**: telegram_bridge.py 1455줄 — 상한(1500) 이하지만 권장 분할선(1200) 초과.
> ty/psycopg3는 2026-07 툴체인 정비의 검토 대기 항목 (Vite8은 8f0443f로 완료).

## 핵심 사실 (정찰 실측)
- `vibe-coding.spec` datas가 `('scripts','scripts')` + `_appseed/scripts` 디렉토리 통째 포함 —
  scripts/ 신규 파일은 spec 수정 불필요 (v3.7.215~218 누락 사고 조건 아님).
- telegram_bridge는 `infra/daemons.py:69`가 스크립트 경로 spawn — 모듈 import 참조자 없음.
  진입점(`scripts/telegram_bridge.py` main)만 유지하면 분할 안전.
- 가변 전역(TERMINAL_CLI_MAP/GROUP_CHAT_ID)을 AgentBot과 BotManager가 공유 —
  분할 시 소유 모듈을 하나로 정하고 타 모듈은 모듈 속성 경유로 읽기/쓰기.

---

## 태스크

### [x] Task 1: telegram_bridge 분할 — 완료 (350+1135줄, 컴파일/임포트/심볼 대조 통과)
- **파일**: `scripts/telegram_agent_bot.py`(신규), `scripts/telegram_bridge.py`(축소)
- **방법**: AgentBot 클래스 + CLI 매핑/GROUP_CHAT_ID 전역을 telegram_agent_bot.py로 이동
  (~1080줄). telegram_bridge.py에는 BotManager + 싱글턴 락 + main 잔류 (~420줄).
  BotManager의 `global TERMINAL_CLI_MAP` 갱신은 `telegram_agent_bot.TERMINAL_CLI_MAP`
  모듈 속성 대입으로 전환. dotenv 로드는 agent_bot 모듈 상단(GROUP_CHAT_ID env 읽기 전).
- **검증**: 두 파일 각 1500줄 이하 + `python -c "import telegram_bridge"` 컴파일/임포트 통과.

### [x] Task 2: ty/psycopg3 도입 검토 — 완료 (권고: psycopg3 보류·ty 로컬만, 사용자 결정 대기)
- **방법**: psycopg2 사용 지점 전수(import 방식·psycopg3 비호환 API) + 타입체크 현황 실측
  → 도입 비용/이득 권고안 보고. 실제 전환은 사용자 결정 후 별도 태스크.
- **검증**: 권고안에 파일 수·비호환 API 목록·CI 영향 포함.

### [x] Task 3: 회귀 + 커밋 — 완료 (py_compile + 3.12 임포트 스모크 + 데몬 spawn 경로 불변 확인)
- **방법**: 분할 후 py_compile + import smoke. Conventional Commits 3단 본문 커밋.

---

## 의존성: Task 1·2 병렬 가능, Task 3 ← Task 1.

## 완료 정의
- telegram_bridge.py가 권장선 이하로 축소, 데몬 spawn 경로/동작 불변.
- ty/psycopg3 결정에 필요한 사실이 권고안 1건으로 정리됨.
- 다음: D(메타버스 재논의) — 사용자와 재논의 후 착수.
