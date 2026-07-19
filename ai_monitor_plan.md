<!--
FILE: ai_monitor_plan.md
DESCRIPTION: LAN 브리지 P2P 협업 Phase 1 구현 계획 — 같은 네트워크의 다른 바이브코딩과
             자동발견 + 페어링 + 파일전송. 채팅은 Phase 2.

REVISION HISTORY:
- 2026-07-19 Claude: 신규. 이전 계획(heartbeat 데몬)은 v3.7.264까지 완료 → 교체.
  브레인스토밍 승인 완료 (memory: project_lan_bridge.md).
-->

# LAN 브리지 P2P 협업 — Phase 1 구현 계획

> 승인: 2026-07-19 브레인스토밍 (project-lan-bridge, A안). 범위: 자동발견 + 페어링 + 파일전송 + 방화벽자동등록 + LanPanel(파일UI). **채팅은 Phase 2로 제외.**
> 원칙: 기존 서버 `127.0.0.1` 불변 — 새 `lan_bridge.py`(`0.0.0.0:9020`)만 LAN 노출. 전부 신규 소파일(1500줄 이하). project_id 비의존(이식성).

---

## 태스크 목록

### [ ] Task 1: lan_peers.py — 페어링/신뢰 저장 + HMAC 토큰
파일: `.ai_monitor/src/lan_peers.py` (신규, ~120줄)
방법:
- 저장소 `data_dir/lan_peers.json` (PC 전역 — DB 아님, 신뢰는 기기 단위라 프로젝트 격리와 무관).
- `generate_pair_code()` → 6자리 숫자. `add_peer(peer_id, name, shared_key)`, `list_peers()`, `is_trusted(peer_id)`.
- `make_token(peer_id)` / `verify_token(peer_id, token)` — HMAC-SHA256(shared_key, nonce+ts). 재전송 방지 위해 ts 윈도우(±120초) 검증.
검증: `python -c "from src import lan_peers; ..."` 단위 — 코드생성→페어링저장→토큰 발급/검증 왕복 PASS, 잘못된 키는 reject.

### [ ] Task 2: lan_discovery.py — UDP 자동발견
파일: `.ai_monitor/src/lan_discovery.py` (신규, ~150줄)
방법:
- announce 스레드: `255.255.255.255:9021`로 주기(3초) 브로드캐스트 `{app:'vibe-coding', peer_id, name:<hostname>, http_port:9020}`.
- listen 스레드: 9021 수신 → 피어 레지스트리(dict, last_seen). TTL 10초 초과 시 오프라인. 자기 자신(peer_id 일치) 제외.
- `start(peer_id, http_port)`, `get_peers()` (온라인만), `stop()`.
검증: 같은 PC에서 announce+listen 동시 기동 → 자기 제외 확인. 2번째 프로세스 띄우면 서로 목록에 뜨는지.

### [ ] Task 3: lan_bridge.py — 브리지 프로세스 골격
파일: `.ai_monitor/lan_bridge.py` (신규, ~180줄)  · 의존: Task 1, 2
방법:
- `office_server.py` 구조 복제: `ThreadedHTTPServer(('0.0.0.0', PORT), Handler)`, `find_free_port(9020)`.
- 기동 시 lan_discovery.start(). 라우트:
  - `GET /lan/ping` — 헬스체크(인증 불요, 발견 확인용)
  - `POST /lan/pair` — 페어링 코드 검증 → shared_key 교환 → lan_peers.add_peer
- CLI 인자: `--peer-id`, `--data-dir` (app_boot에서 주입).
검증: `python lan_bridge.py --peer-id test` 기동 → 다른 PC(또는 localhost)에서 `GET /lan/ping` 200.

### [ ] Task 4: 🔴 방화벽 자동등록 (블로커)
파일: `.ai_monitor/lan_bridge.py` (Task 3에 함수 추가) 또는 `src/lan_firewall.py` 분리
방법:
- 기동 직전 `netsh advfirewall firewall add rule name="VibeCoding-LAN" dir=in action=allow protocol=TCP localport=9020` + UDP 9021.
- 이미 규칙 있으면 skip(멱등). 관리자 권한 없어 실패 시 → stderr + 상태플래그 `firewall_ok=False`로 lan_api가 프론트에 "수동 허용 필요" 안내.
검증: 규칙 추가 후 `netsh advfirewall firewall show rule name="VibeCoding-LAN"` 존재 확인. 권한 없을 때 크래시 안 하고 경고만.

### [ ] Task 5: 파일 송수신 라우트
파일: `.ai_monitor/lan_bridge.py` (Task 3 확장)  · 의존: Task 3
방법:
- `POST /lan/recv-file` (인증필수: verify_token) — 헤더 파일명 → **sanitize(경로분리·`..` 제거)** → 고정 수신폴더 `data_dir/lan_inbox/<peer_name>/` 저장.
- 송신은 lan_api가 트리거 → 브리지 `send_file(peer_id, path)`가 상대 `:9020/lan/recv-file`로 POST(토큰 첨부).
검증: 2 인스턴스 간 파일 1개 전송 → inbox에 sanitize된 이름으로 도착. `../../etc` 류 파일명이 폴더 밖으로 안 나가는지.

### [ ] Task 6: lan_api.py — server.py용 제어 API
파일: `.ai_monitor/api/lan_api.py` (신규, ~150줄)  · 의존: Task 3, 5
방법:
- `/api/lan/status`(브리지 살아있나+firewall_ok), `/api/lan/peers`(발견목록), `/api/lan/pair`(코드 입력→브리지 위임), `/api/lan/send`(파일 전송 트리거).
- 프론트 → 로컬서버(127.0.0.1) → lan_api → 브리지(로컬 9020) 중계. handle_get/handle_post(office_api 시그니처 관례).
검증: 브리지 켠 상태에서 `curl 127.0.0.1:<서버>/api/lan/status` → 200 + firewall_ok 필드.

### [ ] Task 7: server.py dispatch 연결 (1줄급)
파일: `.ai_monitor/server.py`  · 의존: Task 6
방법: `_g_lan`/`_p_lan` 위임 함수 + GET/POST prefix 테이블에 `('/api/lan/', _g_lan)` / `('/api/lan/', _p_lan)` 추가. `('/api/office/', _g_office)` 패턴 그대로.
검증: dispatch 유닛(route_table 테스트) — `/api/lan/status`가 lan_api로 라우팅되는지.

### [ ] Task 8: app_boot 브리지 기동 (토글, 기본 꺼짐)
파일: `.ai_monitor/infra/daemons.py` (+ app_boot 호출부)  · 의존: Task 3, 4
방법: `launch_lan_bridge(data_dir, peer_id)` — `subprocess.Popen([sys.executable, lan_bridge.py, ...])` + `child_procs.append` 불변식 준수. config 플래그 `lan_bridge_enabled`(기본 False)일 때만. peer_id는 config에 없으면 1회 생성 저장.
검증: 플래그 True로 앱 부팅 → 9020 리스닝. (설치본 EXE는 `sys.executable`=앱EXE 함정 — frozen 분기 필요.)

### [ ] Task 9: LanPanel.tsx — 파일 UI
파일: `vibe-view/src/components/LanPanel.tsx` (신규, ~200줄)  · 의존: Task 6
방법: 피어 목록(온/오프라인 점) + 페어링(코드 표시/입력) + 파일 드롭존 → `/api/lan/send`. firewall_ok=False면 상단 경고 배너. 폴링은 App.tsx 코디네이터 관례.
검증: Playwright — 패널 렌더, 피어목록 로드, 방화벽 경고 노출 조건.

### [ ] Task 10: App.tsx 탭 추가 + E2E + 커밋
파일: `vibe-view/src/App.tsx`  · 의존: Task 9
방법: LanPanel 탭/라우트 등록(기존 TasksPanel 방식). dist 재빌드.
검증: 2 인스턴스(또는 localhost 2프로세스)로 발견→페어링→파일전송 E2E 1회. 통과 시 conventional commit.

---

## 의존성 그래프
- Task 1, 2 (독립·병렬) → Task 3 → Task 4·5 → Task 6 → Task 7 → Task 8
- Task 6 → Task 9 → Task 10 (프론트 체인)

## 완료 정의 (Phase 1 DoD)
같은 LAN 2대에서 ①자동으로 서로 발견 ②페어링 코드 1회로 신뢰 ③파일 1개 왕복 전송 성공 ④방화벽 자동등록(실패 시 안내). 채팅 없음(Phase 2).
