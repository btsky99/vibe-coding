<!--
FILE: ai_monitor_plan.md
DESCRIPTION: 아픽스 서버(서울 VPS) 중앙 대화 PG 1차 구현 계획 — 노드 ID + append-only 대화.

REVISION HISTORY:
- 2026-08-08 Claude: 신규. vibe-brainstorm 승인 설계 반영.
                     이전 계획(슬롯별 프로젝트 전환)은 완료(2026-07-24) → 교체.
-->

# 아픽스 서버 중앙 대화 PG — 1차

**상태: 계획 승인 대기**
승인: 2026-08-08 (vibe-brainstorm). 설계 메모리: `project_apix_central_db`.

## 목표

여러 PC의 클로드가 한 DB로 **대화를 주고받는다**. 지식 공유는 2차.
완료 판정: 다른 PC의 `T1`과 `T3`가 메시지를 왕복하고, **서버가 꺼져 있어도 앱은 멀쩡하다**.

## 설계 고정 사항 (변경 금지 — 이유는 설계 메모리 참조)

- **연결은 SSH 터널.** Tailscale을 쓰지 않는다 — 제3자 의존 회피가 이 서버를 만든 목적이다.
- 서버의 `listen_addresses`(127.0.0.1)·방화벽(22/tcp)·기존 서비스를 **건드리지 않는다**.
- 로컬 `pg_base.py`를 건드리지 않는다. 원격은 **별도 모듈**로 격리한다.
- 노드 ID는 로컬 식별자를 바꾸지 않는다. 중앙으로 나갈 때만 `{node}/claude:T1`로 감싼다.
- 대화 테이블은 **append-only**(UPDATE 없음). 읽음 표시는 커서 테이블로 한다.

## 재사용할 기존 자산 (새로 만들지 말 것)

| 기존 | 용도 |
|---|---|
| `src/server_utils.py: find_free_port` | 터널 로컬 포트 자동 탐색 |
| `infra/pty_process.py: kill_orphan_pty_servers` | '자기 것만 죽이는' 좀비 정리 패턴 |
| `infra/daemons.py: start_all_daemons` / `DaemonEnv` | 터널 데몬 등록 지점, config 경로 |
| `infra/proc.py` | 콘솔 숨김 subprocess 래퍼 (인라인 CREATE_NO_WINDOW 금지) |

---

## Phase 1 — 서버 셋업

```
[ ] Task 1: 서버 셋업 스크립트 작성
    파일: scripts/remote/vps-knowledge-db.sh (신규)
    방법: hive_knowledge DB + 전용 계정(최소 권한, 슈퍼유저 금지) 생성.
          터널 전용 SSH 키를 authorized_keys에 등록하되
          permitopen="127.0.0.1:5433",no-pty,no-agent-forwarding,no-X11-forwarding 부착.
          전부 멱등(이미 있으면 건너뜀). listen_addresses/방화벽 변경 코드는 넣지 않는다.
    검증: 두 번 실행해도 결과가 같고 에러가 없다.

[ ] Task 2: 서버에 적용 + 수동 접속 확인   (의존: Task 1)
    파일: 없음 (운영 작업)
    방법: ssh로 스크립트 전달 실행 → 개발 PC에서 터널을 손으로 띄우고 psql 접속.
    검증: psql로 hive_knowledge 접속 성공 + 전용 계정이 다른 DB엔 접근 불가.
          기존 서비스(nginx/RustDesk/vibe-bridge) 정상 확인.
```

## Phase 2 — 노드 정체성

```
[ ] Task 3: 노드 ID 도입
    파일: .ai_monitor/src/node_identity.py (신규)
    방법: config.json에 node_id(uuid4, 최초 1회 생성) + node_label 저장.
          node_ref('claude:T1') -> '{node_id}/claude:T1' 헬퍼 제공.
          🔴 로컬 agent_id를 바꾸지 않는다 — 중앙 전송 시에만 감싼다.
    검증: tests/test_node_identity.py — 재호출/재시작해도 같은 ID, 라벨 변경이 ID를 안 바꿈.
```

## Phase 3 — 중앙 연결 (가장 중요한 검증 지점)

```
[ ] Task 4: 중앙 PG 커넥션 모듈
    파일: .ai_monitor/src/pg_central.py (신규)
    방법: config.json central_db{host,port,user,password,dbname} 로드.
          설정이 없으면 get_central_conn()이 None을 반환하고 끝난다(예외 금지).
          🔴 중앙 스키마(agent_messages, message_cursors) 생성은 **연결이 성립한 뒤에만**.
             pg_schema.py에 넣지 않는다 — 설정 없는 사용자의 로컬 DB가 오염된다.
    검증: tests/test_pg_central.py — 설정 없음 -> None, 잘못된 설정 -> None(예외 없음).

[ ] Task 5: 무동작 회귀 검증   (의존: Task 4)
    파일: tests/test_central_optional.py (신규)
    방법: central_db 설정이 없는 상태에서 서버 부팅 경로가 평소와 동일한지 확인.
          로컬 DB에 중앙 테이블이 생기지 않았는지 명시적으로 단언.
    검증: 🔴 설정 없는 사용자에게 아무 변화가 없다. 이게 통과해야 Phase 4로 간다.
```

## Phase 4 — SSH 터널

```
[ ] Task 6: 터널 데몬
    파일: .ai_monitor/infra/tunnel_daemon.py (신규)
    방법: ssh -N -L <로컬>:127.0.0.1:5433 을 infra.proc로 기동.
          로컬 포트는 find_free_port로 탐색(5434 고정 금지 — 멀티 인스턴스 충돌).
          죽으면 지수 백오프 재연결. PID+포트를 런타임 파일에 기록.
          🔴 PC당 1개 공유 — 이미 살아있는 터널이 있으면 그 포트를 재사용한다.
    검증: 터널 프로세스를 강제 종료 -> 자동 재연결. 서버가 꺼져 있어도 앱은 정상.

[ ] Task 7: 좀비 터널 정리 + 데몬 등록   (의존: Task 6)
    파일: .ai_monitor/infra/tunnel_daemon.py, .ai_monitor/infra/daemons.py
    방법: 부팅 시 PID 파일 기준으로 고아 ssh 프로세스 정리
          (kill_orphan_pty_servers의 '자기 것만 죽인다' 패턴을 따른다 — 다른 인스턴스/
           사용자의 ssh를 죽이면 안 된다). start_all_daemons에 등록.
    검증: 🔴 앱 비정상 종료 후 재시작 시 ssh 좀비 0개.
          전례: v3.7.244 좀비 node PTY가 _MEI를 잠가 앱이 안 켜진 사고.
```

## Phase 5 — 대화

```
[ ] Task 8: 메시지 송수신 + 커서
    파일: .ai_monitor/src/pg_central.py   (의존: Task 3, 4)
    방법: send_message(to_node,to_agent,content) / fetch_new(node_id) 구현.
          created_at은 서버 now() 사용(PC 시계를 믿지 않는다).
          읽음은 message_cursors(node_id,last_seen_id) UPSERT — 메시지 행은 불변 유지.
          노드별 rate limit + 보존 30일 정리.
    검증: 같은 DB에 두 노드 ID로 왕복. 커서가 중복 수신을 막는지 확인.

[ ] Task 9: API 라우트   (의존: Task 8)
    파일: .ai_monitor/api/central_api.py (신규), .ai_monitor/server.py (라우팅 1줄)
    방법: GET /api/central/messages (커서 이후), POST /api/central/messages.
          중앙 미설정이면 503이 아니라 빈 목록 + disabled 플래그(프론트가 조용히 숨김).
          🔴 대화만 — 원격 '실행'은 이 경로에 절대 넣지 않는다(LAN 브리지 3중 게이트 우회 금지).
    검증: 설정 유/무 양쪽에서 200 응답.

[ ] Task 10: 실시간 수신 (NOTIFY)   (의존: Task 8)
    파일: .ai_monitor/infra/tunnel_daemon.py 또는 신규 리스너 스레드
    방법: LISTEN agent_msg. office_api.py의 기존 LISTEN 스레드 패턴을 그대로 따른다
          (autocommit 필수). 연결 끊기면 폴링으로 자동 강등.
    검증: 다른 노드가 INSERT하면 수 초 내 수신.

[ ] Task 11: E2E 검증   (의존: Task 9, 10)
    파일: tests/test_central_e2e.py (신규)
    방법: 노드 A의 claude:T1 -> 노드 B의 claude:T3 왕복. 서버 다운 시 로컬 정상 동작.
    검증: 왕복 성공 + 서버 없이도 앱 부팅 정상.
```

---

## 의존성 요약

```
Task 1 → Task 2 ─┐
Task 3 ──────────┼→ Task 8 → Task 9 ─┐
Task 4 → Task 5 ─┘         ↘ Task 10 ┴→ Task 11
Task 6 → Task 7
```

Phase 3(Task 5)이 통과하기 전에는 Phase 4 이후로 진행하지 않는다.

## 완료 후 기록할 지식

- `project_apix_central_db` 갱신 — 실제 구현 결과, 터널 재연결 실측, 지연 측정치
- 사고가 나면 `incident.py record` — 특히 좀비/포트 충돌 계열
