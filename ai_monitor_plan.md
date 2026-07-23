<!--
FILE: ai_monitor_plan.md
DESCRIPTION: 텔레그램 그룹방 허브화 구현 계획 — 설정저장 버그·메시지 유실·문서전송 부재 해소.

REVISION HISTORY:
- 2026-07-23 Claude: 신규. 텔레그램 허브화 브레인스토밍 승인(B안) → 계획.
                     이전 계획(LAN 브리지 Phase 3)은 완료(커밋 098845f, Phase 4 fb1225d) → 교체.
-->

# 텔레그램 그룹방 허브화

승인: 2026-07-23 (vibe-brainstorm, B안 = 버그수정 + 문서전송 + 분할).

## 배경 (왜 하는가)

사용자가 T1~T8 봇을 한 방에 모아 **봇끼리 대화하는 채팅방**을 만들려다 실패했다.
원인은 코드가 아니라 텔레그램의 원천 제약이다 — 공식 FAQ 원문:

> "bots will not be able to see messages from other bots regardless of mode"

따라서 **봇 간 대화는 구현 불가**이며, 이미 존재하는 구조를 살리는 방향으로 간다:
에이전트는 ITCP(PostgreSQL `pg_messages`)로 대화하고, 브릿지가 그것을 그룹방에
미러링한다(`telegram_bridge.py:157 _poll_itcp_to_group` — 이미 구현됨).

**역할 분리: 대화하는 곳 = PostgreSQL, 보는 곳 = 텔레그램.**

현재 부족한 것: ①설정 저장 시 그룹 ID가 날아가는 지뢰 ②4000자 초과 메시지 유실
③파일/문서 전송 기능 전무(`sendDocument` 구현 0건).

---

## 태스크

### [ ] Task 1: `.env` 저장 시 `TELEGRAM_GROUP_CHAT_ID` 삭제 버그 수정
- **파일**: `.ai_monitor/api/telegram_api.py` (L86~104)
- **문제**: L92 `elif not stripped.startswith("TELEGRAM_")` 가 `TELEGRAM_` 접두 라인을
  전부 버린 뒤, 복원은 `TELEGRAM_BOT_T1~T8`만 한다. 대시보드에서 텔레그램 설정을
  저장하는 순간 `TELEGRAM_GROUP_CHAT_ID`가 소멸 → `send_to_group`이 전부 무동작
  (`telegram_agent_bot.py:226` `if GROUP_CHAT_ID:` 가드에 걸려 **조용히** 스킵).
- **방법**: 제거 조건을 `TELEGRAM_BOT_T`로 좁힌다. `TELEGRAM_BOT_T*`만 재작성 대상으로
  걸러내고, 그 외 `TELEGRAM_*` 라인(GROUP_CHAT_ID 및 미래 키)은 `existing_lines`에 보존.
- **검증**: tmp 경로에 GROUP_CHAT_ID 포함 `.env` 사본 생성 → 저장 로직 통과 →
  `TELEGRAM_GROUP_CHAT_ID`가 값 그대로 남는지 assert. 실제 `.env` 미변경.
- **의존성**: 없음

### [ ] Task 2: 긴 메시지 분할 헬퍼 `_split_message` 신설
- **파일**: `scripts/telegram_helpers.py` (`_truncate` 아래)
- **문제**: `_truncate(text, 4000)`가 초과분을 **버린다**(L57~59). `_safe_send`가 항상
  이걸 통과시켜(`telegram_agent_bot.py:213`) 긴 응답·리포트가 소리 없이 유실된다.
  스트리밍 경로에만 분할이 있고(L479~488) 범용 헬퍼는 없다.
- **방법**: `_split_message(text, limit=3900, max_parts=4) -> list[str]`
  - 줄 경계 우선 분할, 한 줄이 limit 초과 시 그 줄만 강제 분할
  - 코드펜스(```) 내부에서 잘리면 조각마다 펜스를 닫고 다시 열어 포맷 보존
  - `max_parts` 초과분은 Task 4에서 파일로 전환하므로 여기선 조각 리스트만 반환
- **검증**: 단위 테스트 ①짧은 텍스트 1조각 ②경계값 ③줄바꿈 없는 초장문
  ④코드펜스 짝 맞음 ⑤조각 합이 원문을 보존(유실 0)
- **의존성**: 없음 (Task 1과 병행 가능)

### [ ] Task 3: 파일/문서 전송 신설 + 보안 가드
- **파일**: `scripts/telegram_agent_bot.py`, `scripts/telegram_helpers.py`
- **현황**: `sendDocument`/`InputFile` 사용 **0건** — 텍스트 전용.
- **방법**:
  - `AgentBot._safe_send_document(chat_id, path, caption)` +
    `send_document_to_group/private` 래퍼 (`app.bot.send_document`)
  - **🔴 보안 가드 (필수)**: 경로를 자유롭게 받으면 `.env`(봇 토큰 보관처)를 텔레그램으로
    유출시킬 수 있다. `telegram_helpers.is_sendable_path(path, project_root)` 신설:
    ① `resolve()` 후 project_root 하위 확인(`..`/심볼릭 탈출 차단)
    ② 차단 패턴 — `.env*`, `*.key`, `*.pem`, `id_rsa*`, `credentials*`, `.oci/`, `*.pid`
    ③ 크기 상한 45MB (봇 업로드 한도 50MB 여유)
  - 거부 시 전송하지 않고 사유를 텍스트로 회신
- **검증**: `is_sendable_path` 단위 테스트 — `.env` 거부, `../` 탈출 거부, 프로젝트 내
  일반 파일 허용, 초대용량 거부
- **의존성**: 없음

### [ ] Task 4: `_safe_send`에 분할 + 자동 파일 전환 적용
- **파일**: `scripts/telegram_agent_bot.py` (L211 `_safe_send`)
- **방법**: `_truncate` 단일 호출을 3경로로 교체
  1. limit 이하 → 기존대로 1건
  2. 초과 & 조각 ≤ max_parts → `_split_message` 순차 전송 (조각 사이 `sleep(0.3)`으로
     그룹 전송 레이트 회피)
  3. 조각 초과 → 전문을 임시 `.txt`로 저장해 **Task 3 문서 전송**으로 첨부 + 앞부분 미리보기
- **불변식**: 어떤 경로로도 **내용이 조용히 사라지지 않는다** (현 `... (잘림)` 소실 제거)
- **검증**: 3경로 각각 태우기 + Markdown 파싱 실패 폴백이 분할 후에도 동작하는지
- **의존성**: **Task 2, 3 완료 후**

### [ ] Task 5: ITCP→그룹 미러링 가독성 개선
- **파일**: `scripts/telegram_bridge.py` (L157~248)
- **방법**:
  - L211 `_truncate(content, 3800)`, L229~232 `formatted`를 Task 4 경로에 태워 유실 제거
  - 헤더 포맷 정리 — `발신봇 → 수신자 [채널] 타입`이 한눈에
  - 동일 발신자 연속 메시지는 헤더 생략(스팸 감소) — 직전 발신자 캐시 1개
- **검증**: `scripts/send_message.py`로 ITCP 메시지 발행 → 그룹방 도착 확인(유실·중복 0)
- **의존성**: **Task 4 완료 후**

---

## 범위 밖 (이번에 하지 않음)

- **포럼 토픽(T1~T8 스레드 분리)** — 그룹을 포럼으로 전환 + `message_thread_id` 배관이
  전 경로에 필요. 효용 대비 변경폭이 커 별건.
- **자비스 이전** — 같은 봇 토큰으로 두 PC가 폴링하면 충돌하므로 최종형은 상시 가동
  서버(자비스)가 브릿지를 전담해야 한다. 인스턴스 확보 전이라 보류.
- **양방향 명령 확장** — `/t1~/t8`, `/run`, `/auto` 등 9종이 이미 있어 불필요.

## 완료 기준

- [ ] 대시보드에서 텔레그램 설정을 저장해도 그룹방이 계속 동작
- [ ] 4000자 초과 응답이 잘리지 않고 전부 도착(분할 또는 파일)
- [ ] 프로젝트 내 문서를 텔레그램으로 전송 가능, `.env`/키 파일은 거부
- [ ] T1~T8 에이전트 대화가 그룹방에 유실 없이 보임
