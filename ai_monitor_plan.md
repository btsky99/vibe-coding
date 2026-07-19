<!--
FILE: ai_monitor_plan.md
DESCRIPTION: LAN 브리지 Phase 2 구현 계획 — 신뢰 피어 간 실시간 채팅(HTTP 폴링 + PG 영구저장).

REVISION HISTORY:
- 2026-07-19 Claude: 신규. Phase 1(발견/페어링/파일전송, 8c89af2·9b7460f·보안 39af82a) 완료 → 교체.
  브레인스토밍 승인 (memory: project_lan_bridge.md Phase 2 섹션).
-->

# LAN 브리지 Phase 2 — 실시간 채팅 구현 계획

> 승인: 2026-07-19 브레인스토밍. HTTP 폴링(WebSocket 기각 — stdlib 부담) + PG `lan_messages` 영구저장.
> **핵심 아키텍처: 브리지=릴레이+메모리버퍼(project_id 무지·이식성), server.py(lan_api)=DB책임.**

---

## 태스크 목록

### [ ] Task 1: lan_messages 스키마 + CRUD
파일: `.ai_monitor/src/pg_schema.py` (ensure_schema에 테이블) + `.ai_monitor/src/pg_store.py`(또는 신규 `src/pg_lan.py`)
방법:
- `lan_messages` 테이블: `id SERIAL, from_peer TEXT, to_peer TEXT, content TEXT, ts TIMESTAMPTZ DEFAULT now(), project_id TEXT DEFAULT ''`. 인덱스 `(project_id, to_peer, from_peer, id)`.
- `save_lan_message(from_peer, to_peer, content, project_id)` — 진입부 `assert_project_id`. content는 파라미터 바인딩(_sql_text).
- `get_lan_messages(peer_id, since_id, project_id)` — 나↔peer_id 양방향 대화를 id>since_id로 증분 조회, id ASC.
검증: `python -c "..."` — 저장→조회 왕복, since 커서 증분 동작, project_id 빈값 가드 경고.

### [ ] Task 2: 브리지 채팅 라우트 (릴레이 + 버퍼)
파일: `.ai_monitor/lan_bridge.py`  · 의존: 없음(Phase1 토큰 재사용)
방법:
- 수신 버퍼 `STATE['chat_inbox'] = collections.deque(maxlen=500)`.
- `POST /lan/chat-recv` (인증필수) — verify_token(peer_id, token, body_hash=sha256(content), filename=''). content 8KB 상한(_body). 통과 시 deque에 `{from_peer, content, ts}` 적재.
- `GET /lan/chat-drain` (로컬전용) — deque 전체 pop 반환(비움). server가 폴링해 DB로 옮김.
- `send_chat(peer_id, content)` — 신뢰·온라인 확인 → 상대 `:9020/lan/chat-recv`로 토큰 POST.
검증: 2브리지에서 send_chat → 상대 chat-drain에 메시지 1건. 미인증(토큰 없이) chat-recv 거부.

### [ ] Task 3: lan_api 채팅 라우트 (DB 책임)
파일: `.ai_monitor/api/lan_api.py`  · 의존: Task 1, 2
방법:
- `POST /api/lan/chat-send {peer_id, content}` — 브리지 send_chat 위임 + 성공 시 내 발신분 `save_lan_message(self_id, peer_id, content)` 저장.
- `GET /api/lan/chat?peer_id=&since=` — ① 브리지 `/lan/chat-drain` 호출 → 받은 수신분을 `save_lan_message(from_peer, self_id, ...)` 저장 ② `get_lan_messages(peer_id, since)` 조회 반환.
- self_id는 브리지 /lan/status에서 획득(또는 status 캐시).
검증: `curl .../api/lan/chat-send` → 브리지 전달 + DB row. `curl .../api/lan/chat?peer_id=X&since=0` → drain+저장+조회 JSON.

### [ ] Task 4: LanPanel 채팅 UI
파일: `.ai_monitor/vibe-view/src/components/panels/LanPanel.tsx`  · 의존: Task 3
방법:
- 전송대상(sendPeer) 선택 시 하단에 채팅영역: 메시지 목록(from/시각) + 입력창 + 전송.
- `since` 커서로 `/api/lan/chat` 2초 폴링(신규만 append). content는 **텍스트 노드로 렌더(escape)** — XSS 방지(dangerouslySetInnerHTML 금지).
- 전송: `/api/lan/chat-send` → 낙관적 append 또는 다음 폴링 반영.
검증: Playwright — 채팅영역 렌더, 입력→전송, 메시지가 escape되어 표시.

### [ ] Task 5: E2E + 커밋
파일: (검증 스크립트, scratchpad)  · 의존: Task 1~4
방법: 2브리지 + 로컬 lan_api 모의로 송신→수신→DB저장→조회 왕복. 빌드(tsc+vite). 통과 시 conventional commit(백엔드/프론트 분리 가능).
검증: 채팅 1왕복이 양쪽 DB에 정확히 1건씩 + since 증분 무중복. 미인증 거부.

---

## 의존성 그래프
- Task 1, 2 (병렬) → Task 3 → Task 4 → Task 5

## 완료 정의 (Phase 2 DoD)
신뢰 피어 간 텍스트 메시지 송수신, PG 영구저장(재시작 후 이력 유지), since 증분 폴링 무중복,
chat-recv 토큰 인증 + content 8KB 상한, 프론트 XSS escape. WebSocket 없음(HTTP 폴링).
