<!--
FILE: docs/HARNESS_DESIGN.md
DESCRIPTION: 하네스 설계 근거 — 컨텍스트 계측 실태, 세션 리사이클 상태머신,
             안전 불변식. 코드만 봐서는 알 수 없는 "왜 이렇게 만들었나"의 정본.

REVISION HISTORY:
- 2026-08-14 Claude: docs/DISCORD_HARNESS_INTEGRATION_PLAN.md에서 분리 신설.
  Discord 커넥터를 전면 제거하며 계획서를 폐기했으나, 그 안의 계측 실태·리사이클
  설계·안전 불변식은 커넥터와 무관하게 살아 있고 규칙(.claude/rules/context-limits.md)과
  코드(src/session_recycle.py)가 인용 중이라 근거만 옮겼다.
-->

# 하네스 설계 근거

이 문서는 **계획서가 아니라 근거 기록**이다. 구현은 이미 끝났고, 여기 남은 것은
"왜 그렇게 만들었나"와 "무엇을 실측했나"뿐이다. 새 기능 계획은 `ai_monitor_plan.md`에 쓴다.

---

## 1. 컨텍스트 계측 실태 (2026-08-05 실측, 2026-08-14 보강)

자동 리사이클을 얹기 전에 계측 원천을 실측했다. **결과가 설계를 바꿨다.**

| CLI | 원천 | 상태 | 자동 트리거 |
|-----|------|------|-------------|
| claude | `~/.claude/projects/*/*.jsonl` | 정상 — `/api/context-usage` | 가능 |
| codex | `~/.codex/sessions/**/rollout-*.jsonl` | API 부재 → `src/codex_context.py` 신설 | 가능(단일 슬롯 한정) |
| antigravity | `/api/antigravity-context-usage` | **죽은 계측** | **불가 — 제외** |

- codex는 `last_token_usage.input_tokens / model_context_window`가 정답이다.
  `total_token_usage`는 세션 누적이라 실측에서 11164%가 나온다(오용 금지).
- antigravity API는 폐기 경로 `~/.gemini/tmp/<folder>/chats/`를 읽는다. 실제 대화는
  `~/.gemini/antigravity-cli/conversations/*.db`(SQLite)에 있다.
  → `AUTO_TRIGGER_CLIS`에서 제외하고 수동만 허용한다. agy용 파서를 만들면
  이 표와 `session_recycle.AUTO_TRIGGER_CLIS`를 **함께** 갱신할 것.

### 🔴 계측의 근본 함정 — 화석 (2026-08-14 실측)

세션 파일은 대화가 끝나도 사라지지 않는다. **끝난 세션의 사용률은 영원히 그 값에
멈춘 채로 "현재값"처럼 보인다.** 실측: 853,206/1,000,000 = 85.3%가 7시간째 고정.

이것이 위험한 이유는 자동 처형과 결합할 때다. 화석을 근거로 터미널을 죽이면 새
세션은 첫 응답을 받기 전에 다시 죽고, 그래서 usage가 영영 0이라 계측은 계속 화석을
가리킨다 — **자기영속 루프**가 되어 스스로 멈추지 않는다.

방어선 둘:
1. **결속** — `src/session_binding.py`가 세션 파일을 PTY 슬롯에 묶는다
   (`first_ts >= slot.started`, 그리고 `mtime`이 슬롯의 `last_output_at`보다
   미래면 남의 대화로 거부). 확정 못 하면 아무도 죽이지 않는다.
2. **나이(stale)** — 마지막 쓰기가 2시간(claude)/6시간(codex)을 넘으면 처형 대상에서 뺀다.

계측 원천이 하나라도 "어느 터미널의 값인가"를 모르면 **자동 처형에 쓰지 않는다.**
CLI 전역 계측(`recycle_api.measure_context`)의 용도는 UI 표시와 GUARD 입력뿐이다.

---

## 2. 세션 리사이클 (Phase 6)

컨텍스트가 임계에 닿은 세션을 마감 기록으로 봉인하고 새 컨텍스트로 갈아끼운다.

**상태머신: GUARD → SEAL → DRAIN → SWAP → REANCHOR**

| 파일 | 역할 |
|------|------|
| `src/session_recycle.py` | 상태머신 — 순수 로직(금지 7종 GUARD 포함) |
| `src/session_binding.py` | 세션↔슬롯 결속 + 터미널별 점유율 + stale 판정 |
| `src/brief_limits.py` | 재정박·브리프 글자 상한 + 중간 절단 (규칙 9의 유일 강제 지점) |
| `src/codex_context.py` | codex 컨텍스트 파서 |
| `api/recycle_api.py` | HTTP 계층 + 실제 deps 주입 |
| `infra/daemons.py` | `run_recycle_watcher` 60초 폴링 + `plan_terminal_recycles` 처형 판정 |
| `tests/test_session_recycle.py`, `tests/test_session_binding.py` | 회귀 |

설계 원칙:
- 재정박 프롬프트에 **규칙 본문을 넣지 않는다** — 새 세션이 CLAUDE.md와
  `.claude/rules/`를 자동 로드하므로 경로만 적는다. 본문을 복사하면 컨텍스트를
  회수하려고 만든 장치가 컨텍스트를 다시 채운다(자기모순).
- 저장 실패는 세션을 파괴하지 않는다(불변식 5).
- 실패 시 재정박 프롬프트를 `_local/reanchor-<T>.md`로 건져 수동 복구를 남긴다.

### 구현 중 발견한 결함 (재발 방지)

**① SEAL이 자기 판정을 오염시킴 (2026-08-05)** — `seal()`이 부르는
`set_session_checkpoint`가 `updated_at = NOW()`를 찍는다. 그래서 SEAL 직후
`user_active()`의 "나이" 판정이 항상 0초 → 항상 True → **DRAIN이 매번 20초를
꽉 채우고 실패, 자동 리사이클이 구조적으로 100% 불발**이었다. 가짜 deps를 쓰는
단위 테스트로는 잡히지 않는 통합 결함.
→ SEAL 성공 시각을 기준선으로 잡고 "기준선 이후의 새 쓰기"만 활동으로 판정.

**② 계측 단위와 처형 단위의 불일치 (2026-08-09 / 2026-08-14, 2회)** — 계측은
CLI 단위인데 처형은 터미널 단위였다. 처음엔 매핑이 아예 없어 `terminal_id or 'T1'`로
폴백해 **항상 T1이 죽었고**, 그 수정이 이번엔 `agent==cli`인 슬롯을 **전부** 죽이는
팬아웃이 됐다. 같은 자리에서 두 번 났다.
→ 세션↔슬롯 결속으로 터미널별 계측을 만들고, 처형 판정을 순수 함수
`plan_terminal_recycles`로 분리했다. **무한 루프 안에 있던 것이 두 번 다 회귀
테스트를 막은 진짜 원인이다** — 판정 로직은 루프 밖으로 뺄 것.

---

## 3. 안전 불변식

편의 기능보다 우선하며 구현 중 완화하지 않는다.

1. 토큰·비밀값을 PostgreSQL 일반 컬럼, API 응답, 로그에 평문 노출하지 않는다.
   Windows에서 Unix `chmod 0600`을 보안 보장으로 간주하지 않는다.
2. 외부에서 전달된 경로는 항상 등록된 project root 아래로 정규화한다.
3. 외부 요청만으로 삭제·배포·secret 조회를 자동 승인하지 않는다.
4. 사용자에게 전달하는 오류에서 토큰·로컬 민감 경로·원문 환경변수를 제거한다.
5. **체크포인트 저장 실패 시 현재 세션을 파괴하지 않는다.**
   (`.claude/rules/context-limits.md`가 인용 — 상한 초과는 차단이 아니라 축약인 근거)
6. 대상을 확정하지 못하면 아무것도 죽이지 않는다 — 추측 배정 금지.
7. 외부 서비스 장애나 rate limit이 로컬 agent 프로세스를 종료시키지 않는다.

---

## 4. 비목표

- 대시보드는 **런처 + 기록 열람판**이다. 관제 기능 신규 개발은 영구 중단
  (`project_orchestration_board_reality` 참조).
- 모든 자연어 메시지를 shell 명령으로 직접 실행하지 않는다.
- 쿼터 데이터만으로 진행 중인 사용자 작업을 강제 종료하지 않는다.
- 프로젝트마다 별도 오케스트레이터와 별도 DB를 무조건 생성하지 않는다.
