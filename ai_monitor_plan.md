<!--
FILE: ai_monitor_plan.md
DESCRIPTION: 아픽스 콘솔 구축 계획 — btsky.pe.kr 을 개인 전용 총괄 관제판으로 전환하고
             공개 제품 허브를 www 로 분리한다. 모든 프로젝트·노드를 한 화면에서 관제.

REVISION HISTORY:
- 2026-08-08 Claude: 신규. vibe-brainstorm 승인 설계 반영.
                     이전 계획(중앙 대화 PG)은 미착수 → Phase 10으로 흡수 보존.
-->

# 아픽스 콘솔 — btsky.pe.kr 전면 개편

**상태: Phase 0~6 완료 (2026-08-09 새벽) · 콘솔 라이브**
설계 메모리: `project_apix_console`, `project_apix_central_db`, `project_seoul_vps`

## 목표

**메인은 공개 허브, 관리 정보는 그 안의 관리자 전용 페이지.** 개발 중인 모든 프로젝트
(vibe-coding · CipherTrader · OnS · finbee · APIS)와 모든 노드(PC 3대 · 레노버 · 탭 ·
VPS)의 상태를 한 화면에서 본다.

**완료 판정**: 밖에서 폰으로 `btsky.pe.kr/console/` 에 들어가 구글 로그인 한 번 하면,
각 노드가 살아 있는지 · 무슨 작업이 돌고 있는지 · 어디서 터졌는지가 **수집 시각과 함께**
보인다. 로그인 없는 사람에게는 공개 메인만 보인다.

## 최종 도메인 배치 (2026-08-09 확정 — **초기안에서 반전됨**)

| 주소 | 무엇 | 어디 | 접근 |
|---|---|---|---|
| `btsky.pe.kr/` | **공개 메인 허브** | 아픽스 서버가 직접 서빙 | 공개 |
| `btsky.pe.kr/console/` | 🎛️ 아픽스 콘솔 | 아픽스 서버 | 🔒 구글 로그인 (btsky99만) |
| `www.btsky.pe.kr` | → apex 301 | 아픽스 서버 | — (전파 대기 중) |
| `ons.btsky.pe.kr` | OnS | Vercel — **손대지 않음** | 공개 |
| `admin`·`status` | 레거시 | → apex 301 | — |

> 🔴 **초기에 "apex 전체 = 콘솔"로 만들었다가 되돌렸다.** 요구는 "메인은 공개(지금 화면
> 그대로), 관리 정보만 그 안에 관리자 전용 페이지"였다. apex 를 통째로 잠그지 말 것.
>
> 🔴 **메인을 GitHub Pages 에 얹지 않는다.** 도메인을 옮길 때마다 GitHub 인증서 재발급을
> 기다려야 하고 그동안 사이트가 통째로 죽는다(2026-08-08 실측 약 2시간). 서버가 직접
> 서빙하면 certbot 1분. 가용성을 남의 큐에 맡기지 않는다.

## 설계 고정 사항 (변경 금지 — 이유는 아래 근거 참조)

- **관제 데이터 전송은 HTTPS 인제스트**(노드 → 서버 POST). SSH 터널을 쓰지 않는다.
  근거: 관제는 작고 단방향이고 주기적이다. 터널은 노드마다 상주 데몬 + 좀비 정리가
  필요해(`project_apix_central_db` Critic 블로커) 탭 같은 약한 노드에서 먼저 무너진다.
  외부 메시 VPN 을 배제한 이유였던 "제3자 의존 회피"는 **내 서버로 직접 붙는 HTTPS 에는 해당 없음**.
  실시간 양방향이 필요한 **대화**만 Phase 10에서 SSH 터널로 간다.
- **콘솔 코드는 `apix-console` private 리포**. `vibe-coding` 은 public 이라
  노드 목록·엔드포인트 구조가 그대로 공개된다.
- **`/api/*` 는 무인증으로 열지 않는다.** 여는 길은 로그인 게이트 뒤뿐 (Phase 0 사고).
- **인제스트 토큰은 노드별로 따로 발급.** 한 대 유출 시 그 한 대만 폐기한다.
- **모든 값에 수집 시각을 함께 표시**하고, 낡으면 회색+⚠️ 로 강등한다.
  근거: `feedback_observability_first` — 노드가 죽어도 마지막 값이 남아 "정상"으로
  보이는 관제판은 장애보다 나쁘다. 값 없음과 값 낡음을 같은 색으로 그리지 않는다.
- **`vibe-coding` 리포에 시크릿을 절대 넣지 않는다.** 전부 `/opt/apix/apix.env` (600, root).

## 🙋 사용자 수동 작업 (내가 대신 못 하는 것)

| # | 무엇 | 언제 |
|---|---|---|
| M1 | hosting.kr DNS: `btsky.pe.kr` A레코드를 GitHub 4개 → `158.247.205.192` 로 교체 | Phase 2, **www 확인 후** |
| M2 | GitHub OAuth App 생성 (Client ID/Secret 발급) | Phase 3 |
| M3 | Google Cloud Console: 리디렉션 URI 추가 + **client secret 확보** | Phase 3 |
| M4 | Google Cloud Console: 승인된 JavaScript 원본에 `https://www.btsky.pe.kr` 추가 | Phase 1 직후 |

> M4 배경: 공개 허브의 구글 로그인(`web/auth.js`, GIS)은 **승인된 원본**에 등록된
> 도메인에서만 뜬다. apex 만 등록돼 있어 www 이전 직후 로그인 버튼이 동작하지 않는다.
> 이 로그인은 실인증이 아닌 프로토타입이라 사이트 자체는 멀쩡하다 — 급한 항목은 아니다.

---

## Phase 0 — 뚫린 상태 API 차단 ✅ 완료

```
[x] Task 0: /api/status 외부 차단
    파일: scripts/remote/vps-web-deploy.sh
    내용: nginx snippet 에 allow 127.0.0.1 / deny all. 서버 즉시 적용 완료.
    검증: 외부 403 · 루프백 200 실측 확인 (PHASE0_OK).
    부수: 검증부가 평문 http 로 재서 정상인데도 404를 뱉던 결함 동시 수정.
          certbot 이후 80 블록은 return 404 뿐 — 콘텐츠는 전부 443 에 있다.
```

## Phase 1 — 공개 허브를 www 로 이전 ❌ **폐기 (2026-08-09 방향 전환)**

> 이 Phase 의 전제("메인은 콘솔, 공개 허브는 www")가 뒤집혔다. 메인은 공개 허브로
> 남고 **아픽스 서버가 직접 서빙**한다. www 는 apex 로 301 하는 별칭일 뿐이다.
> 아래 기록은 **다운타임 실측치를 남기기 위해** 보존한다 — 다음에 도메인을 옮길 때
> 같은 값을 예산으로 잡을 것.

```
[-] Task 1: (폐기) CNAME 교체 + Pages 커스텀 도메인 변경 — f37fd39
    파일: web/CNAME
    방법: btsky.pe.kr → www.btsky.pe.kr. 커밋·푸시로 Pages 워크플로 재배포 후
          gh api PUT repos/btsky99/vibe-coding/pages 로 cname 갱신.
    🔴 순서 불변식: 이 작업이 apex A레코드 변경보다 **반드시 먼저**다. 반대로 하면
       GitHub 이 도메인 검증 실패로 Pages 인증서를 폐기해 www 까지 같이 죽는다.
    검증: gh api ...pages 의 https_certificate.state = approved (수분 대기).

    🔴 발급 창 = 실제 공개 다운타임 (2026-08-08 21:43~ 실측):
       cname 을 www 로 바꾼 직후 state=dns_changed 이고, 이때 www:443 은
       기본 `*.github.io` 인증서를 제시한다 → 브라우저 신뢰 실패.
       apex 는 이미 www 로 301 하므로 **사이트 전체가 그 창 동안 안 열린다**.
       이 구간에는 gh api PUT 도 404("certificate has not finished being issued")
       로 거부되므로 재촉할 수단이 없다 — 기다리는 것 외에 할 일 없음.
       다음에 도메인을 또 옮긴다면 이 다운타임을 미리 계산에 넣을 것.
    후속: approved 되면 https_enforced=true 로 올린다(현재 false).

[x] Task 2: 내부 절대경로·메타태그 정리   (의존: Task 1)
    파일: web/index.html, web/site.js, web/*/index.html
    방법: og:url·canonical·하드코딩된 https://btsky.pe.kr 를 www 로 교체.
          상대경로(./)는 그대로 둔다.
    검증: grep 으로 'btsky.pe.kr' 중 www 아닌 잔재 0건.
    ✅ 2026-08-08 실측: 리포 전체에서 `//btsky.pe.kr` 코드 참조 0건
       (남은 언급은 이 계획서·HIVEMIND.md 의 서술문뿐).
```

## Phase 2 — apex 를 아픽스 서버로

```
[x] Task 3: apex A레코드 전환   (의존: Task 1 검증 통과 · 🙋 M1)
    파일: 없음 (운영 작업)
    검증: dig btsky.pe.kr 이 158.247.205.192 단독. www 는 계속 Pages 정상.

[x] Task 4: 인증서 발급 + 리다이렉트 규칙   (의존: Task 3)
    파일: apix-console/deploy/nginx-apix.conf (신규)
    방법: certbot -d btsky.pe.kr -d admin.btsky.pe.kr (기존 인증서에 SAN 추가).
          admin/* → https://btsky.pe.kr 301.
          apex 의 알려진 제품 경로(/vibe-coding /crypto /crypto-coin /finbee /ons
          /resources /portal)만 화이트리스트로 www 301 → 루프 방지.
    🔴 /.well-known/acme-challenge 는 로그인 게이트 예외로 고정. 빠뜨리면 갱신이
       조용히 실패해 90일 뒤 사이트가 통째로 죽는다.
    검증: 옛 링크 3개가 www 로 301. certbot renew --dry-run 통과.
```

## Phase 3 — 로그인 게이트

```
[x] Task 5: apix-console private 리포 생성
    파일: (신규 리포) apix-console/  — 로컬 클론 D:/apix-console
    방법: gh repo create --private. 구조 = console/(프론트) collector/(수집)
          deploy/(nginx·systemd·설치 스크립트).
    ✅ 2026-08-08 실측: visibility=PRIVATE, 3커밋(5df0320→bb880c8), 1094줄.
       vibe-coding 리포에 콘솔 코드 없음.

[x] Task 6: oauth2-proxy 설치   (의존: Task 5 · 🙋 M2 · 🙋 M3)
    파일: apix-console/deploy/oauth2-proxy.service, deploy/apix.env.example
    방법: 바이너리 설치 + 127.0.0.1:4180 상주. 구글·깃허브 두 provider 등록.
          🔴 이메일 화이트리스트에 내 계정만. 기본 정책은 deny.
          시크릿은 /opt/apix/apix.env (600, root) — 리포에는 example 만.
    검증: 로그아웃 상태에서 콘솔 접근 시 로그인으로, 타 계정 로그인 시 거부.

[x] Task 7: nginx auth_request 연결   (의존: Task 6)
    파일: apix-console/deploy/nginx-apix.conf
    방법: 콘솔 화면과 /api/* 전부 게이트 뒤로. 미인증 GET / 은 www 로 302.
          /ingest/* 와 /.well-known/* 는 게이트 예외(각각 토큰 인증 / 인증서 갱신).
    🔴 검증은 반드시 --resolve 로 실제 소스 IP를 바꿔가며 HTTPS 로 한다 (Phase 0 교훈).
    검증: 미인증 /api/status → 302 또는 401 (200 절대 금지). 인증 후 200.
```

## Phase 4 — 콘솔 뼈대 + 서버 자체 헬스

```
[x] Task 8: 콘솔 셸 UI   — 화면 검증 완료(2026-08-09)
    파일: apix-console/console/index.html, console/app.js, console/style.css
    방법: 정적 HTML+JS (1코어 서버라 빌드 도구·프레임워크 없음).
          공통 카드 컴포넌트에 **수집 시각 뱃지**를 내장 — 개별 패널이 빼먹을 수 없게.
    검증: 데이터 없음/낡음/정상 3가지 상태가 눈으로 구분된다.
    ✅ 2026-08-09 브라우저 실접속: /console/ 에서 4패널 렌더, CSS·JS 상대경로 정상.
       (앞선 세션의 경고 "코드가 있다를 화면이 맞다로 세지 말 것" — 이제 실제로 봤다.)

[x] Task 9: 서버 헬스 패널   (의존: Task 8) — 완료
    파일: apix-console/collector/server_health.py (vps_status_api.py 승계)
    방법: 기존 항목 + 인증서 만료일 + 서비스 재시작 급증 감지.
    ✅ 백엔드 실측(2026-08-08 22:15): apix-collector active, 127.0.0.1:9101 응답
       200 — collected_at·age_sec·services[].restarts 정상 포함.
    ✅ 화면 실측: vibe-seoul 메모리/디스크 막대, 서비스 7종 상태, 역터널 4개,
       인증서 89일 남음까지 표시. 서비스 강제 중단 테스트는 미실시(운영 중이라 보류).
```

## Phase 5 — 중앙 PG + 인제스트

```
[x] Task 10: 스키마
    파일: apix-console/collector/schema.sql
    방법: apix_nodes(노드·토큰해시·라벨) / apix_heartbeats / apix_projects /
          apix_tasks / apix_events(릴리즈·사고·커밋 공용). 전부 append-only 지향.
          🔴 노드 식별은 node_id 별도 컬럼 — agent_id('claude:T1')에 PC 구분자가 없다.
          전용 계정 최소 권한. 기존 DB·listen_addresses·방화벽 건드리지 않는다.
    검증: 두 번 실행해도 같은 결과(멱등). 다른 DB 접근 불가.

[x] Task 11: 인제스트 API   (의존: Task 10)
    파일: apix-console/collector/ingest.py (127.0.0.1:9101)
    방법: POST /ingest/heartbeat|tasks|events. Bearer 토큰 → 노드 해석.
          토큰은 해시로만 저장. 노드별 rate limit + 페이로드 크기 상한.
          PG 커넥션 풀 상한 고정 (브릿지와 동시 폭주 방지 — 1코어 1.9GB).
    검증: 잘못된 토큰 401, 큰 페이로드 413, 정상 202. 서버 재시작 후에도 동작.
```

## Phase 6 — 노드 푸시 (이 PC 1대부터)

```
[x] Task 12: 푸시 클라이언트
    파일: scripts/apix_push.py (vibe-coding — 시크릿은 env 로 분리)
    방법: 5분 주기. 하트비트(호스트·CPU·메모리·앱 버전·활성 슬롯) 전송.
          🔴 서버가 죽어도 조용히 실패하고 로컬에 영향 0 (예외 삼키되 로컬 로그 1줄).
    검증: 서버를 끄고 돌려도 앱 정상. 켜면 콘솔에 이 PC가 뜬다.

[x] Task 13: 스케줄 등록   (의존: Task 12)
    파일: infra/daemons.py 등록 또는 작업 스케줄러
    검증: 앱 재시작 후에도 하트비트가 계속 올라온다.
```

## Phase 7 — 작업 진행상황 · 프로젝트 보드

```
[x] Task 14: 작업 데이터 push   (의존: Task 11, 12)   ✅ 2026-08-09 검증
    파일: scripts/apix_sources.py(수집·신규) + scripts/apix_push.py(전송·커서)
    방법: hive_tasks · 체크포인트 · 커밋 · 사고의 **변경분만** 전송.
          커서 ~/.apix/cursor.json — 서버가 202 로 받아준 지점만 기록.
    검증 실측: 태스크 상태 변경 → 콘솔 /api/projects 에 반영(open 3→2, age 10초).
          프로젝트 4(pc-yjscom) · 이벤트 40건(commit 8 · ckpt 13 · incident 13).
    🔴 이 PC 에서 잡히는 프로젝트는 4개(vibe-coding·apix-console·k-quant·ons).
       crypto-bot·finbee 는 노드가 달라 Task 18 에서 붙는다 — 누락이 아니다.

[ ] Task 15: 프로젝트별 보드   (의존: Task 14)
    파일: apix-console/console/panels/projects.js
    방법: 프로젝트별 카드 — 마지막 활동·진행 태스크·마지막 커밋·담당 노드.
          CipherTrader 처럼 git 이 없는 노드는 이벤트만으로 표시.
    검증: 5개 프로젝트가 전부 뜨고, 조용한 프로젝트는 조용하다고 표시된다.
```

## Phase 8 — 릴리즈/CI + 사고 장부

```
[ ] Task 16: GitHub 폴러
    파일: apix-console/collector/github_poller.py (cron 5분)
    방법: 최신 릴리즈·워크플로 실패를 apix_events 로. 토큰 사용(rate limit 회피).
    검증: 일부러 실패한 워크플로가 콘솔에 뜬다.

[ ] Task 17: 사고·교훈 패널   (의존: Task 14)
    파일: apix-console/console/panels/incidents.js
    검증: incident.py record 직후 콘솔에 나타난다.
```

## Phase 9 — 노드 확산

```
[ ] Task 18: na2js · qeuhlak · lenovo · 탭 · CipherTrader 노드에 푸시 배포
    방법: 노드별 개별 토큰 발급. 노드마다 검증 후 다음으로.
    검증: 콘솔 노드 목록에 전부 살아 있고, 한 대를 끄면 그 한 대만 회색이 된다.
```

## Phase 10 — 중앙 대화 PG (별건 · 콘솔 이후)

관제와 목적이 다르다(실시간 양방향). 승인된 설계는 `project_apix_central_db` 에 있고
아래 태스크 목록은 그 계획을 **그대로 보존**한 것이다.

**상태: Task 19~28 백엔드 전부 완료 (2026-08-09) — 커밋 `cfb062f` · `19bb67f`**

```
[x] Task 19: vps-knowledge-db.sh — hive_knowledge DB + 최소권한 계정 + permitopen 키
[x] Task 20: node_identity.py — node_id(uuid4) + node_ref('{node}/claude:T1')
[x] Task 21: pg_central.py — 미설정 시 None 반환(예외 금지), 스키마는 연결 후에만 생성
[x] Task 22: 무동작 회귀 — 설정 없는 사용자에게 변화 0 (이게 통과해야 다음)
[x] Task 23: tunnel_daemon.py — find_free_port + 지수 백오프, PC당 1개 공유
[x] Task 24: 좀비 터널 정리 — '자기 것만 죽인다' 패턴 (v3.7.244 전례)
[x] Task 25: 메시지 송수신 + 커서 — append-only, created_at 은 서버 now()
[x] Task 26: central_api.py — 대화만. 원격 실행은 절대 넣지 않는다
[x] Task 27: LISTEN 실시간 수신 — office_api 패턴(autocommit), 끊기면 폴링 강등
[x] Task 28: E2E — 노드 A T1 ↔ 노드 B T3 왕복 + 서버 없이 앱 부팅 정상
```

**실측 검증(2026-08-09)**: 터널 127.0.0.1:5436 → VPS 5433 연결 성공 · 에코 차단과
커서 전진 왕복 통과 · INSERT 후 NOTIFY 도달 **0.25초** · HTTP 5종 실호출 정상 ·
전체 테스트 407 통과.

### 남은 것 (백엔드 완료 후)

```
[x] Task 29: 프론트 대화 UI — /api/central/{status,messages,poll,send} 소비
              status의 enabled/connected 를 분리 표시(회색 하나로 합치지 말 것)
[x] Task 30: 2대 실왕복 — 이 PC(노드 A) ↔ VPS(노드 B) 완료. 아래 검증 범위 참조
[x] Task 31: purge_old 주기 실행 배선 — 30일 보존이 코드에만 있고 아무도 부르지 않는다
[ ] Task 32: 신규 노드 온보딩 절차 — 키 발급→permitopen 등록→config 주입을 스크립트 1개로
              (지금은 수작업. 다른 PC를 붙이려면 이게 먼저다)
```

### Task 30 실왕복 결과 (2026-08-09)

노드 A = 이 PC(`e818a01f…`) / 노드 B = 서울 VPS(`a68e0ef3…`, `/tmp/nodeB` 샌드박스에
현행 `pg_central`·`node_identity`·`pg_base` 를 올려 **실제 클라이언트 코드로** 기동).

- B → A 발신 → A의 리스너에 **NOTIFY 0.46초** 도달 → `fetch_new` 수신(발신자·본문 일치)
- A → B 답신 → B의 커서가 해당 id까지 전진(수신 확정)
- 검증 후 `agent_messages`·`message_cursors` 전량 삭제, VPS 샌드박스 제거
  (config.json에 DB 비밀번호가 들어가므로 남기지 않는다)

🔴 **검증 범위의 한계**: 노드 B는 VPS 자신이라 PG에 **로컬로 직접** 붙었다. 즉 B쪽은
`tunnel_daemon`을 타지 않았다 — 터널 경로는 A(이 PC)에서만 검증됐다. **다른 PC에서
터널을 뚫는 경로는 여전히 미검증**이며, 그건 Task 32(온보딩)를 해야 확인할 수 있다.

🔴 **다른 PC 접근 경로는 아픽스 서버 역터널뿐이다.** 외부 메시 VPN 은 2026-08-09 전면
폐기했다(제3자 의존 회피 = 아픽스 서버를 세운 이유). 역터널(22001/22002/22004)은 살아
있으나 이 PC 키로는 각 노드 로그인이 거부됐다 — Task 32 온보딩에서 키를 정리해야 한다.

🔴 **부채**: `tests/test_tunnel_daemon.py`(미추적)는 08-08에 쓰인 옛 API 대상이라
`_ssh_command` · `live_tunnel_port` 등이 지금 모듈에 없다(9 fail / 5 error).
터널 재작성 때 같이 안 고쳤다. 현행 API로 다시 쓰거나 버릴 것.

---

## 의존성 요약

```
Task 0 ✅
Task 1 → Task 2
       ↘ Task 3(🙋M1) → Task 4
Task 5 → Task 6(🙋M2,M3) → Task 7 → Task 8 → Task 9
                                  ↘ Task 10 → Task 11 → Task 12 → Task 13
                                                              ↘ Task 14 → Task 15
                                                                        ↘ Task 17
                                              Task 16
Task 18 (Task 13 검증 후)
Task 19~28 (콘솔 안정 후)
```

🔴 **Task 1 검증이 통과하기 전에는 Task 3(apex A레코드)로 넘어가지 않는다.**
순서를 뒤집으면 www 까지 죽는다.

## 완료 후 기록할 지식

- `project_apix_console` 신규 — 도메인 배치·게이트 구조·인제스트 계약·실측 함정
- `project_seoul_vps` 갱신 — 도메인 배치 변경, 메모리 예산 실측
- `project_btsky_web_deploy` 갱신 — apex 가 더 이상 Pages 가 아님
- 사고 발생 시 `incident.py record` — 특히 인증서·리다이렉트 루프 계열

---

# Phase 11 — 아픽스 통합 대화 화면 (Task 32~47)

**상태: Task 32~46 구현 완료 (2026-08-09) · Task 47(배포)만 남음**
커밋: `cbec4bd`(백엔드 32~37) · `24a7419`(38~43 2분할·단일버스) · `7b367f1`(44~46 이름·멘션)
검증: 전체 테스트 465 통과 · tsc 0 · vite build 성공 · 호스트명 yjscom→seq 1 자동 배정 실측 ·
명부 등록 성공 · before_id 페이징 겹침 0.
🔴 **앱 재시작 후에 적용된다** — 서버 프로세스가 옛 코드를 들고 있어 `/api/central/nodes`가 없다.
🔴 **2대 실왕복 미검증** — na2js는 중앙 대화 미설정. 배포 후 확인.
설계 근거: 대화 UI 가 `ChatSlot` / `LanPanel 채팅` / `CentralPanel` 3곳에 흩어져 있고
패널은 한 번에 하나만 보여서, LAN·중앙 대화가 **사실상 못 쓰는 상태**였다.

## 이 Phase 의 불변식 (어기면 기능이 조용히 깨진다)

1. **`node_id`(uuid32)를 바꾸지 않는다.** `node_identity.py` 주석의 불변식 —
   형식을 바꾸면 중앙 DB 에 쌓인 참조가 전부 파싱 불가가 된다. `1-1` 은 표시 층일 뿐이다.
2. **중앙 대화 폴러는 앱 전체에 하나뿐이다.** `fetch_new(advance=True)` 가 커서를 밀기
   때문에, 슬롯마다 폴링하면 한 슬롯이 읽은 메시지를 나머지가 **영영 못 본다**.
3. **`slot_name` 의 정본은 config.json 하나다.** pty-server 메모리에도 두면 재연결
   전까지 라우팅이 옛 이름을 본다.
4. **중앙에 원격 실행 UI 를 만들지 않는다.** `central_api.py` 헤더의 설계 고정 사항 —
   공용 지점에 실행 통로가 생기면 DB 계정 하나가 전 노드 RCE 권한이 된다.
5. **오른쪽 창에 LAN 채팅을 섞지 않는다.** 중앙 대화는 같은 망에서도 0.46 초로 동작한다
   (실측). 두 소스를 합치면 중복·순서 꼬임만 남는다.

## 제외 (이미 되어 있거나 의도적으로 안 함)

- `purge_old` 주기 배선 — Task 31 에서 완료, 보존 **30일 유지**
- LAN 채팅/파일 전송 통합 — LAN 브리지는 파일·원격 실행 전용으로 존치
- `node_seq` 를 사람에게 묻는 것 — 번호는 이미 확정됐다(1=메인 2=크립토 3=na2js).
  호스트명 매핑으로 **자동 배정**하고, 질문은 네 번째 PC 가 붙을 때만 뜨는 폴백으로 둔다

---

## Phase 11-A — 백엔드 (Task 32~37)

### Task 32: node_seq 읽기/쓰기 + **호스트명 기본 배정** — PC 주소의 저장소
    파일: .ai_monitor/src/node_identity.py
    방법: get_node_seq()/set_node_seq() 를 get/set_node_label 과 같은 패턴으로 추가.
          config.json 키는 node_seq(int), 범위 1~99.
          🔴 **번호는 이미 확정돼 있다(사용자 지정) — 묻지 말고 호스트명으로 배정한다.**
              _DEFAULT_SEQ = {'yjscom': 1, <크립토 개발 PC 호스트명>: 2, 'na2js': 3}
          get_node_seq() 는 ① config 값 ② 호스트명 매핑 ③ 0(미지의 새 PC) 순으로 본다.
          매핑에 걸리면 그 값을 config 에 1회 기록해 이후 호스트명이 바뀌어도 안 흔들린다.
    완료 조건: pytest 4건 — 매핑된 호스트명은 config 없이도 번호가 나옴, config 값이
          매핑보다 우선, 미지 호스트명은 0, 범위 밖 저장 거부.

### Task 33: node_registry 테이블 + upsert — uuid→번호 명부
    파일: .ai_monitor/src/pg_central.py
    방법: _SCHEMA_SQL 에 node_registry(node_id PK, node_seq INT, node_label TEXT,
          updated_at) 추가. register_node_ref() 는 자기 행을 upsert 하되, **같은
          node_seq 에 다른 node_id 가 이미 있으면 저장하지 않고 (False, 사유) 반환**.
          list_node_refs() 는 전체 명부 반환.
    완료 조건: 같은 seq 를 두 uuid 로 등록 시도 → 두 번째가 거부되고 경고 로그.
    의존: Task 32

### Task 34: list_recent 에 before_id — '이전 50개' 의 서버측
    파일: .ai_monitor/src/pg_central.py
    방법: list_recent(limit, before_id=0). before_id>0 이면 WHERE id < %s 를 덧붙인다.
          커서(message_cursors)는 **건드리지 않는다** — 과거 조회는 수신이 아니다.
    완료 조건: before_id 로 두 번 호출해 겹치지 않는 두 구간이 나오는지 확인.
    의존: Task 33 (같은 파일 — 순차 수정)

### Task 35: 명부·과거조회 라우트 노출
    파일: .ai_monitor/api/central_api.py
    방법: GET /api/central/nodes → {nodes:[{node_id,node_seq,node_label}]}.
          GET /api/central/messages 에 before_id 쿼리 추가.
          중앙 미설정/서버 다운에서도 200 + 빈 배열(이 파일의 기존 계약 유지).
          server.py 의 GET_ROUTES 에 등록 — 🔴 구현하고 라우트 등록을 빠뜨려
          죽어 있던 전례가 있다.
    완료 조건: curl 로 두 라우트 200 확인 + 중앙 끈 상태에서도 200.
    의존: Task 33, 34

### Task 36: 부팅 시 자기 노드 명부 등록
    파일: .ai_monitor/src/central_listener.py
    방법: 리스너 기동 경로에서 register_node_ref() 1회 호출. node_seq 가 0(미설정)이면
          호출하지 않는다 — 0번으로 명부를 오염시키지 않는다.
    완료 조건: 앱 재시작 후 /api/central/nodes 에 이 PC 가 보임.
    의존: Task 33

### Task 37: 이름 라우팅 정본을 config 로 이전
    파일: .ai_monitor/api/message_api.py
    방법: 현재 pty 세션의 slot_name 으로 매칭하는 부분을, config.json 의
          slot_names{터미널ID: 이름} 를 **먼저** 보고 없을 때만 pty 값으로 폴백.
    완료 조건: config 에만 이름이 있고 pty 는 빈 상태에서 그 이름으로 메시지 도달.

---

## Phase 11-B — 프론트 준비 (Task 38~41)

### Task 38: TerminalSlot 헤더 분리 — 규칙 2 대비 선행 분할
    파일: .ai_monitor/vibe-view/src/components/TerminalSlot.tsx →
          .../components/terminal/TerminalSlotHeader.tsx (신규)
    방법: 현재 1171줄이라 2분할·이름편집을 그대로 얹으면 **1500줄 규칙을 넘긴다**.
          헤더(h-7 영역, 배지·모델·프로젝트 표시)를 통째로 새 파일로 옮기고 props 로
          받는다. 이 태스크에서는 **동작을 1도 바꾸지 않는다**(순수 이동).
    완료 조건: 두 파일 모두 1500줄 이하, tsc 오류 0, 화면 변화 없음.

### Task 39: useCentralBus 훅 — 앱 전체 단일 폴러
    파일: .ai_monitor/vibe-view/src/hooks/useCentralBus.ts (신규)
    방법: status/poll/messages 폴링과 메시지 배열(상한 150), 명부(uuid→'아픽스 3-1
          (na2js)') 변환, send(), loadOlder(before_id), 안읽음 카운트를 한곳에 소유.
          🔴 불변식 2 — 이 훅은 App 에서 **한 번만** 마운트한다.
    완료 조건: 훅 단독 렌더 시 3초 폴링 1회만 발생(네트워크 탭/로그로 확인).
    의존: Task 35

### Task 40: CentralPanel 을 표시 전용으로 분리
    파일: .ai_monitor/vibe-view/src/components/panels/CentralPanel.tsx
    방법: 내부 useState/fetch 8곳을 제거하고 props(messages, status, onSend,
          onLoadOlder)로 받는다. 패널 자체는 기존 위치에서 계속 동작해야 한다
          (훅을 App 에서 주입).
    완료 조건: 중앙 패널이 이전과 동일하게 동작하며 자체 폴링이 0.
    의존: Task 39

### Task 41: SideBus 컴포넌트 — 오른쪽 '서로 대화' 창
    파일: .ai_monitor/vibe-view/src/components/terminal/SideBus.tsx (신규)
    방법: 접기/펼치기, 접힘 시 안읽음 뱃지, 폭 드래그 + localStorage 저장,
          **스크롤이 맨 아래일 때만** 자동 추적, 상단 '이전 50개 더 보기'.
          발신 입력도 포함(나도 버스 참여). 표시명은 훅이 준 변환 결과를 그대로 쓴다.
    완료 조건: 접었다 펴도 폭 유지, 과거 읽는 중 새 메시지가 와도 화면이 안 밀림.
    의존: Task 39, 40

---

## Phase 11-C — 통합 (Task 42~45)

### Task 42: App 에 버스 마운트 + 슬롯 전달
    파일: .ai_monitor/vibe-view/src/App.tsx
    방법: useCentralBus() 를 최상위에서 1회 호출하고 결과를 TerminalSlot·CentralPanel
          양쪽에 내려보낸다.
    완료 조건: 터미널 3개를 켜도 /api/central/poll 호출이 3초당 1회.
    의존: Task 39, 40

### Task 43: TerminalSlot 본문 좌우 2분할
    파일: .ai_monitor/vibe-view/src/components/TerminalSlot.tsx
    방법: 본문 flex 영역을 좌(기존 ChatSlot, 상한 300 현행 유지) / 우(SideBus) 로 나눈다.
          접힘이 기본값 — 처음 켰을 때 화면이 좁아지는 인상을 주지 않는다.
    완료 조건: 접힘/펼침 모두에서 xterm 높이 계산이 깨지지 않음(h-full 유지).
    의존: Task 38, 41, 42

### Task 44: 헤더 이름 인라인 편집
    파일: .../terminal/TerminalSlotHeader.tsx, .ai_monitor/vibe-view/src/App.tsx
    방법: displayName 클릭 → 인라인 input → 저장 시 /api/config/update 로
          slot_names 갱신. 표시는 '아픽스 1-1 · 프론트' 형식, 이름 없으면 주소만.
    완료 조건: 이름 저장 후 앱 재시작해도 유지되고, 그 이름으로 메시지가 도달.
    의존: Task 37, 38

### Task 45: 미지 PC 폴백 안내 — 3대에서는 뜨지 않는다
    파일: .ai_monitor/vibe-view/src/components/terminal/TerminalSlotHeader.tsx
    방법: 🔴 지정된 3대(1·2·3)는 Task 32 의 호스트명 매핑으로 자동 배정되므로 **아무것도
          묻지 않는다**. 이 안내는 매핑에 없는 **네 번째 PC**가 붙었을 때만 뜨는 폴백이다.
          node_seq 가 0 일 때만 '이 PC 번호를 정하세요' 1회 노출, 저장 후 재노출 없음.
          중앙을 안 쓰는 사용자에게는 아예 뜨지 않는다.
    완료 조건: 기존 3대에서는 한 번도 안 뜸 + 호스트명을 바꾼 테스트 환경에서만 1회 노출.
    의존: Task 32, 35

---

## Phase 11-D — 마무리 (Task 46~47)

### Task 46: 멘션 파싱 — @1-1 과 @프론트 둘 다
    파일: .ai_monitor/vibe-view/src/hooks/useCentralBus.ts
    방법: 발신 직전 본문 앞의 @토큰을 명부(주소)와 slot_names(이름) 양쪽에서 찾아
          to_node/to_agent 로 변환. 못 찾으면 **그냥 브로드캐스트로 보낸다** —
          오타 하나로 메시지가 사라지는 편이 더 나쁘다(central_api send 의 기존 판단).
    완료 조건: @1-1 / @프론트 / @없는이름 세 경우 모두 의도대로.
    의존: Task 39

### Task 47: 통합 검증 + 배포
    파일: (검증 전용)
    방법: pytest 전체 · tsc · vite build · 로컬 EXE smoke.
          3대 중 2대(메인 ↔ na2js)로 실왕복 확인 — 한쪽에서 보낸 게 다른 쪽
          오른쪽 창에 뜨고 발신자가 '아픽스 3-1' 로 보이는지.
          이후 /vibe-release 로 배포 — 나머지 PC 는 자동 업데이트로 반영된다.
    완료 조건: 전체 테스트 통과 + 2대 실왕복 성공 + 릴리즈 발행.
    의존: Task 32~46 전부

---

## Phase 11 의존성 요약

```
Task 32 → 33 → 34 → 35 → 39 → 40 → 41 → 43
            ↘ 36        ↘ 42 ↗        ↗
Task 37 ─────────────→ 44 ←── 38 ──→ 43
Task 32,35 ─────────→ 45
Task 39 ────────────→ 46
전부 → Task 47
```

🔴 **Task 38(헤더 분리)을 Task 43 보다 먼저 한다.** 순서를 뒤집으면 TerminalSlot 이
1500줄을 넘긴 상태로 커밋되어 규칙 2 위반이 누적된다.

## Phase 11 완료 후 기록할 지식

- `project_apix_addressing` 신규 — 3층 이름(uuid 불변 / seq 수동 / slot_name 자유),
  단일 폴러 불변식(커서를 여러 곳에서 밀면 메시지 유실), seq 충돌 거부 규칙
- `project_apix_node_onboarding` 갱신 — 표시명이 pc-na2js/cipher/na2js 로 제각각이던
  문제가 주소 체계로 해소됨
- `feedback_office_classic_separation` 폐기 — "오피스/클래식 혼용 금지"는 사용자가
  2026-08-09 에 해제했다(대화 UI 일원화가 새 방침)
