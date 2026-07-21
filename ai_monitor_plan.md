<!--
FILE: ai_monitor_plan.md
DESCRIPTION: LAN 브리지 Phase 3 — 원격 Claude 에이전트 실행 구현 계획.

REVISION HISTORY:
- 2026-07-22 Claude: 신규. LAN 브리지 Phase 3(원격 에이전트 실행) 브레인스토밍 승인 → 계획.
                     이전 계획(라이브 프로젝트 전환)은 완료(v3.7.268) → 교체.
-->

# LAN 브리지 Phase 3 — 원격 Claude 에이전트 실행

승인: 2026-07-22 (vibe-brainstorm). 같은 LAN 페어링 PC에 태스크 전송 → 상대 승인 → 상대가
claude 에이전트 실행 → 결과 폴링 반환. 설계 메모리: `project_lan_bridge.md` Phase 3.

## 아키텍처 불변식 (반드시 준수)
- **브리지 = 순수 릴레이 + 메모리 버퍼**. 실행·DB 없음 (채팅 아키텍처와 동일 원칙).
- **server.py(lan_api) = 오케스트레이션 + 실행(agent_api 재사용) + DB(lan_exec_log)**.
- **실행 엔진 신규 금지** — `agent_api.handle_run`({task,cli,cwd}) 재사용 ([[feedback-no-duplicates]]).
- **3중 보안 게이트**: ① 페어링 HMAC 토큰(기존) ② 상대 독립토글 `lan_remote_exec_enabled` 기본 OFF
  ③ 승인 팝업(exec_trust=auto면 스킵). 감사로그는 auto여도 항상 기록.
- 데이터 흐름(요청자 A → 대상 B):
  ```
  A: UI → /api/lan/exec → 브리지 exec-send → [B 브리지] /lan/exec-recv (토큰인증)
  B: exec_trust=auto? → 즉시승인 : 승인큐 적재
  B: server가 pending drain → 승인팝업 → 승인 시 agent_api.handle_run 실행
  B: 실행 출력 → B브리지 로컬 exec-emit → [A 브리지] /lan/exec-output (토큰인증, 역방향 푸시)
  A: server가 output drain → UI 폴링 표시
  ```

---

## Phase 3A — 신뢰/릴레이 백엔드 (lan_peers, lan_bridge)

[ ] Task 1: 피어별 exec_trust 저장 추가
    파일: .ai_monitor/src/lan_peers.py
    방법: add_peer에 `exec_trust: 'ask'`(기본) 추가. 신규 메서드 get_exec_trust(peer_id)→'ask'|'auto',
          set_exec_trust(peer_id, mode). list_peers() 반환에 exec_trust 노출(shared_key는 계속 은닉).
    검증: set→get 왕복 후 lan_peers.json에 exec_trust 저장 확인. 기존 페어는 default 'ask' 폴백.
    의존성: 없음 (독립 시작 가능)

[ ] Task 2: 브리지 STATE 확장 + 송신 함수
    파일: .ai_monitor/lan_bridge.py
    방법: STATE에 exec_inbox(deque, 대상측 수신 태스크), exec_output(dict[exec_id→deque], 요청자측
          수신 출력) 추가. send_exec(peer_id, exec_id, task) — send_chat 복제, body_hash=sha256(task),
          POST /lan/exec-recv. send_exec_output(peer_id, exec_id, chunk, done) — 역방향 POST /lan/exec-output.
          MAX_EXEC_BYTES 상한(태스크 16KB / 출력청크 64KB).
    검증: 함수 단위 — 미페어링 peer거부, 오프라인 거부 반환값 확인.
    의존성: 없음

[ ] Task 3: 브리지 라우트 추가
    파일: .ai_monitor/lan_bridge.py
    방법: 로컬전용(_is_local): /lan/exec-send{peer_id,task}→send_exec, /lan/exec-emit{peer_id,exec_id,chunk,done}
          →send_exec_output, /lan/exec-pending-drain(대상 승인큐 비우기), /lan/exec-output-drain{exec_id}
          (요청자 출력 비우기), /lan/exec-trust{peer_id,mode}→set_exec_trust.
          인증필요(토큰): /lan/exec-recv(태스크 수신→exec_trust 조회, auto면 approved 표시, else pending 적재),
          /lan/exec-output(출력 역방향 수신→exec_output 버퍼). exec-recv 토큰서명=body_hash(task).
    검증: 2브리지 로컬 기동 — exec-send→exec-recv 토큰통과, 위조토큰 거부, pending-drain으로 태스크 회수.
    의존성: Task 1, 2 완료 후

---

## Phase 3B — 서버 오케스트레이션 + DB + 실행 (pg_lan, lan_api)

[ ] Task 4: 감사로그 테이블 + CRUD
    파일: .ai_monitor/src/pg_lan.py (+ 테이블 생성은 lan_messages와 동일 위치)
    방법: lan_exec_log 테이블(id, exec_id, direction 'in'|'out', peer_id, task, status
          'received'|'approved'|'rejected'|'running'|'done'|'error', result_summary, project_id, ts).
          save_lan_exec(...), update_lan_exec_status(exec_id, status, summary), get_lan_exec_log(...).
          기존 assert_project_id 가드 + _sql_text 바인딩 패턴 준수. 테이블은 lan_messages를 만드는
          곳(pg_lan import 시 ensure 또는 postgres_runtime BOOTSTRAP)과 동일 방식으로 생성.
    검증: save→update→get 왕복, project_id 빈값 dev경고 발생 확인.
    의존성: 없음 (Phase 3A와 병렬 가능)

[ ] Task 5: 원격실행 마스터 게이트 + 전송/승인 API
    파일: .ai_monitor/api/lan_api.py
    방법: handle_post에 추가 —
          /api/lan/exec{peer_id,task}: 요청자측. exec_id 생성(uuid) → 브리지 exec-send 프록시 →
            save_lan_exec(direction='out',status='running').
          /api/lan/exec/approve{exec_id,trust?}: 대상측. trust='auto'면 set_exec_trust 프록시 →
            agent_api.handle_run(task) 실행 시작 → update status='approved'/'running'.
          /api/lan/exec/reject{exec_id}: status='rejected' + 브리지에 거부 통지.
          handle_get에 추가 —
          /api/lan/exec/pending: 대상측. **여기서 lan_remote_exec_enabled 게이트** — OFF면 빈 배열
            즉시 반환(브리지 pending-drain도 스킵). ON이면 exec-pending-drain → 각 건 save_lan_exec
            (direction='in',status='received') → 미승인 목록 반환. auto인 건은 자동 approve 경로로.
          /api/lan/exec/output?exec_id&since: 요청자측. exec-output-drain → UI에 청크 반환.
    검증: 게이트 OFF일 때 pending 항상 빈배열(우회불가). ON일 때 pending 회수→approve→run 흐름.
    의존성: Task 3, Task 4 완료 후

[ ] Task 6: 실행 출력 캡처 → 브리지 역방향 전송 (최고 위험)
    파일: .ai_monitor/api/lan_api.py (+ agent_api 연동 지점 확인)
    방법: agent_api.handle_run은 subprocess로 stream-json 출력 → 이 출력을 exec_id에 묶어
          브리지 /lan/exec-emit로 청크 푸시하는 브리지(중계) 스레드/콜백 필요. handle_run의
          출력 스트림 노출 방식을 먼저 조사 — run_id로 출력 버스(_bus_append?)를 폴링 가능하면
          그것을 exec_id에 매핑해 폴링→emit. done 시 update_lan_exec_status('done', 요약).
          **출력 민감정보 최소화**: lan_exec_log.result_summary는 절단/요약만 저장(Critic).
    검증: A에서 태스크 전송→B승인→B에서 claude 실행→A가 output 폴링으로 출력 수신 확인(E2E).
    의존성: Task 5 완료 후. ⚠️ handle_run 출력노출 구조 선(先)조사 — 불명확하면 별도 checkpoint.

---

## Phase 3C — 프론트엔드 (LanPanel)

[ ] Task 7: 태스크 전송 UI
    파일: .ai_monitor/vibe-view/src/components/LanPanel.tsx
    방법: 페어링된 온라인 피어 선택 + 태스크 입력창 + '실행 요청' 버튼 → POST /api/lan/exec.
          기존 파일드롭/채팅 UI 옆에 '원격 실행' 섹션. exec_id 보관해 출력 폴링에 사용.
    검증: 빌드 PASS(npm run build). 피어 선택→전송 시 네트워크 요청 발생.
    의존성: Task 5 완료 후 (API 계약 확정)

[ ] Task 8: 승인 팝업 + 자동승인 체크박스
    파일: .ai_monitor/vibe-view/src/components/LanPanel.tsx
    방법: /api/lan/exec/pending 주기 폴링(예: 3초) → 대기건 있으면 모달 — 요청자명 + 태스크 **전문**
          표시(Critic: 요약금지, XSS escape) + [승인][거부] + "이 PC 앞으로 자동승인" 체크박스
          (체크 시 approve에 trust='auto'). 승인 TTL 카운트다운 표시.
    검증: 빌드 PASS. 2대 실사용에서 팝업 표시→승인→trust 저장 확인.
    의존성: Task 5 완료 후

[ ] Task 9: 실행 출력 뷰
    파일: .ai_monitor/vibe-view/src/components/LanPanel.tsx
    방법: 전송한 exec_id에 대해 /api/lan/exec/output?since 폴링 → 출력 스트림 표시(터미널 유사),
          done 시 폴링 종료. [취소] 버튼 → /api/lan/exec/reject 또는 exec-cancel.
    검증: 빌드 PASS. E2E에서 원격 출력이 실시간 누적 표시.
    의존성: Task 6, Task 7 완료 후

---

## Phase 3D — 게이트/안전장치/배포

[ ] Task 10: 마스터 토글 UI + 기본 OFF
    파일: LanPanel.tsx + config 기본값
    방법: config.json lan_remote_exec_enabled 기본 false. LanPanel에 '원격 실행 수락' 토글
          (/api/config/update). OFF면 이 PC는 pending을 절대 회수 안 함(Task 5 게이트와 짝).
          첫 ON 시 명확한 경고 문구("이 PC가 페어링된 PC의 태스크를 실행합니다").
    검증: OFF 상태에서 상대가 태스크 보내도 팝업/실행 없음 확인.
    의존성: Task 5, Task 8 완료 후

[ ] Task 11: 승인 TTL + 실행 타임아웃 + 취소
    파일: lan_bridge.py + lan_api.py
    방법: pending 항목 TTL(예 5분) 경과 시 자동 거부(자리비움 대비). 실행 타임아웃(예 30분) —
          초과 시 agent_api stop + status='error'. /lan/exec-cancel 라우트로 요청자/대상 양측 취소.
    검증: TTL 경과 후 pending 자동소멸, 타임아웃 시 프로세스 종료 확인.
    의존성: Task 5, Task 6 완료 후

[ ] Task 12: 회귀/배포 점검
    파일: — (검증 전용)
    방법: lan_bridge.py는 이미 spec datas 개별등록됨(신규 루트 .py 없음 → spec 무변경 예상).
          route_table 자기검증, 기존 파일/채팅 회귀 없음 확인. wc -l로 lan_bridge.py/lan_api.py
          1500 제한 점검(초과 시 분리). E2E 2대(발견→페어링→원격실행→출력)까지 최종 검증.
    검증: 파일/채팅 기존 기능 정상 + 원격실행 E2E PASS + 1500 제한 OK.
    의존성: 전체 완료 후

---

## 🔴 리스크 / 선조사 항목
- **Task 6(출력 캡처)이 최고 난도** — `agent_api.handle_run`의 출력 스트림 노출 방식이 불명확하면
  먼저 조사 후 checkpoint 기록. run_id 출력버스 폴링이 가능한지가 관건.
- lan_exec_log 테이블 생성 위치 확정 필요(lan_messages가 어디서 CREATE 되는지 선확인).
- 다른 네트워크 불가(UDP+사설IP) — 이번 스코프 명시적 제외.
- 와이어 프로토콜 신규 라우트라 구버전 브리지와 혼용 시 exec만 미동작(파일/채팅은 정상) — 무방.
