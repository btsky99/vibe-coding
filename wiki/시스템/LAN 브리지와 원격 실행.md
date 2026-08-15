---
title: LAN 브리지와 원격 실행
type: 시스템
sources:
  - .ai_monitor/api/agent_api.py:983
  - .ai_monitor/api/agent_api.py:1017
  - .ai_monitor/api/agent_api.py:1036
  - .ai_monitor/api/agent_api.py:1294
  - .ai_monitor/api/lan_api.py:1
  - .ai_monitor/api/lan_api.py:87
  - .ai_monitor/api/lan_api.py:97
  - .ai_monitor/api/lan_api.py:142
  - .ai_monitor/api/lan_api.py:159
  - .ai_monitor/api/lan_api.py:178
  - .ai_monitor/api/lan_api.py:185
  - .ai_monitor/api/lan_api.py:221
  - .ai_monitor/api/lan_api.py:296
  - .ai_monitor/api/lan_api.py:330
  - .ai_monitor/api/lan_api.py:341
  - .ai_monitor/api/lan_api.py:481
  - .ai_monitor/api/lan_api.py:536
  - .ai_monitor/lan_bridge.py:1
  - .ai_monitor/lan_bridge.py:76
  - .ai_monitor/lan_bridge.py:104
  # …외 24건 (본문 각 항목에 경로 표기)
  - session_memory  # ~/.claude/projects/<슬러그>/memory/ · 2장
related: []
confidence: high
updated: 2026-08-15
---

# LAN 브리지와 원격 실행

## 한 줄

LAN 원격실행이 yolo(권한 전면 스킵) 대신 deny 프로파일로 격리하기 위한 통로.

> 자동 합성 (코드 주석 44건 · 파일 5개 · 세션 메모리 2장 · 추출 55d5cf1).
> 🔴 **여기를 고치기 전에** 원본(주석 또는 사고 장부)을 먼저 고칠 것 — 다음 빌드에 덮어써진다.

## 🧠 세션에서 굳은 것 (세션 메모리)

> 원본은 `~/.claude/projects/<슬러그>/memory/` 다. **여기가 아니라 원본을 고칠 것** — 다음 빌드에 덮어써진다.

### 🧠 feedback_metaverse_quality

**오피스 메타버스 시각 품질은 Gather Town 레벨이 기준. 프리미티브 + 픽셀아트 혼합 금지**

오피스/메타버스 화면을 만들 때 품질 기준은 **Gather Town 수준**이다. 사용자가
레퍼런스로 보여준 스크린샷(pokemon/stardew valley 풍 탑다운 픽셀 오피스)이 기준선.

**Why:** 2026-04-09 세션에서 OfficeWorld(DOM 동그라미) → OfficeCanvas(Phaser +
부분 LimeZu) 전환을 시도했는데, 사용자가 최종 결과물에 "이건 어니아 영 아니야 ㅠㅠ
내일 다시 만들자"로 반응. 마지막 커밋 `9091da5`는 체크포인트로 유지되지만 품질
만족 못 함. 원인:
1. 프리미티브(내가 그린 사각형)와 LimeZu 픽셀아트를 혼합 → 시각적 부조화
2. 대표실/회의실/탕비실은 여전히 프리미티브 유지, 코딩 부서만 LimeZu
3. LimeZu Room_Builder의 진짜 벽/벽지 미활용 — "방"이 아니라 "바닥에 그린 구역"
4. Interiors 에셋 수백 개 중 4~5개만 사용 (desk_plain, chair_side, plant_large)
5. 조급한 단계별 진행 — "빨리 보여주기"에 매달려 기반 설계 스킵
6. 코딩 부서 3x3 레이아웃이 답답. 통로/공간감 부재

**How to apply:**
- **금지**: 프리미티브(Phaser Graphics 사각형/원)와 픽셀아트 스프라이트를 한 화면에
  섞지 마라. 한 개라도 남으면 전체가 어색해짐. 전부 스프라이트 아니면 전부 프리미티브.
- **필수**: LimeZu 등 타일셋을 쓸 때는 **Room_Builder의 진짜 벽 타일**로 방을 만들어야
  한다. 바닥 tint만으로는 "방"이 아님. 벽 + 문 + 창문 = 방.
- **필수**: 에셋 통합 전 **전체 시트 스캔**부터. Interiors_free_16x16.png 같은 큰
  시트는 어떤 스프라이트가 있는지 먼저 목록화. 그 다음에 "이 오브젝트에 이 스프라이트"
  매핑. 몇 개 크롭해서 붙이고 끝내지 말 것.
- **필수**: 탑다운 RPG 오피스는 **통로/빈 공간/러그**로 공간감을 만들어야 한다. 책상을
  3x3 그리드에 억지로 끼워넣지 말 것.
- **Playwright로 계속 검증**: 각 변경마다 캡처해서 직접 확인 (이건 이번에 잘 했음)
- **레퍼런스 기준선 유지**: Gather Town 스크린샷을 계속 비교하면서 "이 정도 안 나오면
  멈추지 않음" 원칙. 어중간한 타협 금지.

**Next session starting point:**
- LimeZu 에셋은 `D:\vibe-coding\Modern_Interiors_Free_v2.2` + 프로젝트 내
  `.ai_monitor/vibe-view/public/assets/limezu/` 에 이미 로드됨
- Phaser + React 통합 파이프라인 완성됨 (OfficeCanvas.tsx 패턴)
- 캐릭터 idle 애니메이션 + depth 레이어링 공식 확립 ("앉아있는 느낌")
- 내일은 `OfficeCanvas.tsx`를 처음부터 다시 쓰거나 신규 파일로 시작. 방 레이아웃 설계
  → 벽/바닥 타일맵 → 방별 가구 큐레이션 → 캐릭터 순서로.

출처: 세션 메모리 `feedback_metaverse_quality.md` · type=feedback

### 🧠 project_pty_pool_isolation

**2-5.3a + 2-5.3b TTL 워커 + 2-5.3c 탭 배지 모두 완료. Platform Phase 2 마무리.**

#### 2-5.3c 완료 (2026-05-03)
- ✅ C.1 GET /api/pty/sessions/summary — { project_id: { agent_count, total } } 집계 응답
- ✅ C.2 pty_api.py handle_get L156-166 자동 패스스루로 추가 매핑 불필요
- ✅ C.3 useVibeData ptySessionsSummary state + 10s 폴링
- ✅ C.4 TopMenuBar 탭 우상단 absolute 배지 (agent_count > 0만 노출, slugifyProjectPath로 path → project_id 매핑)
- ✅ C.5 App.tsx props 1줄 배선
- ✅ C.6 tsc 0 errors + vite build 38s

→ Phase 2-5.3 (탭별 PTY 세션 풀 분리) 3개 PR 모두 완료. Platform Phase 2 마무리 + Phase 3-3(UI 병합) 진입 가능.

#### 2-5.3b 완료 (2026-05-03)
- ✅ B.1 lastInputAt/lastOutputAt 필드 + 갱신 지점 4곳 (legacy/persistent onData + 두 ws.on('message'))
- ✅ B.2 isSessionIdleForCleanup() — attached/yolo/O*/legacy(detachedAt 없음) 면제
- ✅ B.3 setInterval 스윕 워커 (PTY_TTL_SWEEP_MS) + .unref()로 이벤트 루프 비차단
- ✅ B.4 GET /api/pty/sessions 응답 last_input_at, last_output_at, idle_seconds 필드
- ✅ B.5 SIGTERM/SIGINT/exit + cleanupAllSessions에서 stopTtlSweepWorker
- ✅ B.6 단위 8/8 + 부팅 검증 (TTL=8s/idle=4s/sweep=2s 환경변수에서 워커 시작 로그 확인)
- ✅ B.7 ai_monitor_plan.md + 본 메모리 갱신

##### 환경변수 기본값
- `PTY_TTL_MS` = 60분 (3,600,000ms)
- `PTY_IDLE_THRESHOLD_MS` = 10분 (600,000ms)
- `PTY_TTL_SWEEP_MS` = 5분 (300,000ms)

##### 면제 정책 (코드 = 명세)
1. attached=true → 면제 (사용자가 보고 있음)
2. yolo=true → 면제 (장기 실행 의도)
3. slotId.startsWith('O') → 면제 (오피스 풀 별도)
4. detachedAt 없음 → 면제 (legacy 핸들러 / spawn만 되고 detach 안 한 세션)

#### 2-5.3a 완료 (2026-05-03 커밋 14982ab)
- ✅ Node 키 헬퍼 (sessionKey/parseSessionKey/_resolvePidFromQuery/displayId)
- ✅ WebSocket 핸들러 #1/#2 sessionId 복합 키 변경
- ✅ GET /api/pty/sessions — ?project_id= 필터 + 통합 응답 분기
- ✅ /api/pty/output|interrupt|terminate|write — _resolveSessionKey 도입
- ✅ /api/pty/office/spawn + office/sessions — sessionKey 적용
- ✅ DELETE /api/pty/sessions 신설 — ?project_id= 필수, O* 제외
- ✅ pty_api.py — _extract_project_id, _node_delete, handle_delete
- ✅ server.py do_DELETE — /api/pty/ 라우팅
- ✅ TerminalSlot.tsx — wsParams project_id
- ✅ useVibeData.ts — withProjectId 적용
- ✅ 빌드 OK (47s, 2185 modules)
- ✅ A.12 백엔드 격리 curl 검증: project_id 필터로 누설 없음 확인
  - D--vibe-coding 필터 → T1(claude)+T2(codex) 2건 정상
  - fake-project 필터 → 빈 응답 (다른 프로젝트 세션 누설 X)
- ✅ A.14 커밋 14982ab (1차) + 73d8ead (Codex PTY heartbeat 2차)

#### 후속 PR 진입점 (ai_monitor_plan.md 참조)
- **2-5.3b TTL 정리 워커**: B.1~B.8 (lastInputAt/Output 필드 + 60분 TTL + 5분 스윕)
- **2-5.3c 탭별 활성 에이전트 수 배지**: C.1~C.8 (/api/pty/sessions/summary + TopMenuBar 배지)

Phase 2-5.3 — 탭별 PTY 세션 풀 분리. 멀티 프로젝트 탭 환경에서 각 탭이 독립적인 T1~T8 PTY 세션을 갖게 한다.

**Why:** Phase 2-5.1/2-5.2에서 탭 바 + ?project_id= 쿼리 인프라가 깔렸지만, PTY 풀은 여전히 평탄(slot0~31). 프로젝트별 격리 없이는 탭 전환 시 컨텍스트가 섞임.

**How to apply:** PTY 관련 신규/수정 작업은 반드시 `sessionKey(pid, slot)` 헬퍼를 거쳐 풀 접근. `ptySessions.get('slot3')` 같은 직접 키 접근 금지.

#### 확정 설계

##### 풀 키 구조 (Q1=A)
- 복합 키: `{project_id}:slot{0-7}`
- 헬퍼: `sessionKey(pid, slot)`, `parseSessionKey(key)` (Node)
- `?project_id=` 누락 시 `_default` 폴백 (후방 호환)

##### 탭 전환 정책 (Q2=C)
- 기본: detach 유지 (프로세스/출력 버퍼 살림, socket만 분리)
- TTL 정리: **60분** + 5분마다 스윕
- idle 판정: `agent_status == 'idle'` AND `마지막 출력 후 10분 무변화` AND `마지막 키 입력 후 10분 무변화`
- **yolo=true 면제** — 사용자가 명시적으로 켠 장기 실행 의도 존중

##### 변경 범위 (Q3=C)
3개 PR 분리:
- **2-5.3a**: Node 풀 키 + WebSocket URL + 프론트 + 프로젝트 제거 핸들러 (회귀 핵심)
- **2-5.3b**: TTL 정리 워커 (lastInputAt/lastOutputAt 필드 + setInterval)
- **2-5.3c**: UI 탭별 활성 에이전트 수 배지 (plan A-2/A-3)

##### 변경 파일
- `.ai_monitor/pty-server/pty-server.js` (~120줄)
- `.ai_monitor/api/pty_api.py` (~10줄, 패스스루라 거의 무변경)
- `.ai_monitor/vibe-view/src/components/TerminalSlot.tsx` (~20줄)
- `.ai_monitor/vibe-view/src/hooks/useVibeData.ts` (~10줄)

##### 비범위 / 명시 제약
- **오피스 세션**(`/api/pty/office/spawn`, UUID 키)은 별도 풀 — 본 정책 미적용
- **프로젝트 rename 비지원** — config.json 편집 후 앱 재시작 필요. 슬러그 바뀌면 기존 풀 고립.
- 프로젝트 제거 시: `DELETE /api/pty/sessions?project_id={pid}` 일괄 종료 핸들러 신설

##### 위험도
🟡 중간 — PTY 동작 변경은 회귀 위험. 단독 PR 권장. 시작 첫 단계로 `Grep "slot[0-9]" .ai_monitor/vibe-view/src` 전수조사.

#### 의존성
- Phase 2-5.1 (탭 바 UI) ✅ 커밋 eb238ac
- Phase 2-5.2 (?project_id= 쿼리 인프라) ✅ 커밋 eb238ac
- 본 작업 완료 후 → Platform Phase 2 마무리, Phase 3-3(UI 병합) 진행 가능

출처: 세션 메모리 `project_pty_pool_isolation.md` · type=project

## 코드에 박힌 지식

## `.ai_monitor/api/agent_api.py`

### _build_chat_cmd `[WHY]`

에이전트별 CLI 명령 구성 (cokacdir 패턴).
[에이전트별 명령]
- claude: claude --verbose --output-format stream-json [--resume SID] [--dangerously-skip-permissions] -p "메시지"
→ -p는 프롬프트 텍스트를 인자로 받으므로 반드시 -p message 순서로 배치.
stdin=DEVNULL 사용 (stdin 파이프 불필요).
- gemini: gemini -m gemini-3.1-pro [--resume SID] [-y]
- codex:  codex --full-auto [--resume SID]
Args:
cli: 에이전트 종류 ("claude" | "antigravity" | "codex")
session_id: 기존 세션 ID (--resume용, None이면 새 세션)
yolo: YOLO 모드 (권한 자동 승인)
message: 전달할 메시지 (claude -p 인자로 직접 전달)
settings_path: --settings로 주입할 권한 프로파일 절대경로 (claude 전용).
[WHY] LAN 원격실행이 yolo(권한 전면 스킵) 대신 deny 프로파일로 격리하기 위한 통로.
상대경로를 주면 claude가 cwd 기준 해석 후 미발견 시 exit 1 — 반드시 절대경로.

출처: `.ai_monitor/api/agent_api.py:983`

### _build_chat_cmd `[제약]`

[2026-06-11] Antigravity(agy) 전환 — 'gemini-3.1-pro' 모델 지정 제거 (6/18 종료로
존재하지 않는 모델, agy 기본 모델 사용). --resume → --conversation, -y → 권한 스킵.
[제약] agy TUI는 파이프 stdin 채팅을 보장하지 않음 (실측: -p 파이프 캡처 결함과 동일 계열)

출처: `.ai_monitor/api/agent_api.py:1017`

### _codex_recall_prefix `[WHY]` `[불변식]` `[제약]`

코덱스 중계분에 접두할 회상 v2 요약 — 실패/무관련이면 '' (주입 생략).
[WHY] 코덱스는 훅 시스템이 없어 자동 회상 주입이 구조적으로 불가 —
대시보드/오피스 공용 중계 지점(handle_chat)이 유일한 주입 통로 (로드맵 ③).
hive_hook(claude)·antigravity_hook(BeforeAgent)과 같은 recall_client 경로를
재사용해 3에이전트 회상이 한 곳(recall-smart)으로 수렴한다.
[제약] 서버 자신은 VIBE_SERVER_PORT env 미보유(daemons.py:115는 자식에게만 주입)
→ 자기 바인드 포트를 setdefault해 recall_client의 포트 스캔(최악 0.3초×20) 생략.
[불변식] 어떤 실패도 채팅 중계를 중단시키지 않는다 — 전부 삼키고 '' 반환.
recall_client 자체도 2초 상한 + 3단 폴백 내장 (hive_hook과 동일 계약).

출처: `.ai_monitor/api/agent_api.py:1036`

### handle_chat_stop `[WHY]`

Windows: taskkill /T /F로 프로세스 트리 종료
[WHY] os.system은 항상 cmd.exe를 새로 띄워 채팅 stop마다 검은 창이 번쩍인다.
_proc.run(콘솔 숨김 주입)으로 콘솔 없이 조용히 트리 킬.

출처: `.ai_monitor/api/agent_api.py:1294`

## `.ai_monitor/api/lan_api.py`

### 모듈 상단 `[WHY]`

실제 LAN 통신은 lan_bridge.py 프로세스가 하고, 여기서는 로컬 프록시만 한다.
브리지 포트는 data_dir/lan_bridge_port 파일에서 얻는다(파일 부재=브리지 꺼짐).
- 2026-07-19 Claude: 신규 — LAN 브리지 Phase 1 Task 6. project_id 비의존(이식성).
- 2026-07-22 Claude: Phase 3 Task 5/6 — 원격 에이전트 실행 전송/승인 API + 출력캡처 스레드.
마스터 게이트 lan_remote_exec_enabled(기본 OFF) + 3중 보안. 실행=agent_api 재사용.
[WHY 프록시 구조] 프론트 → 로컬서버(lan_api) → 브리지(로컬 9020~). 프론트가 브리지에 직접
붙지 않는 이유: 브리지 포트가 동적이라 프론트가 모르고, 기존 UI는 전부 로컬서버 경유라
경로 일관성 유지. 브리지 꺼짐/살아있음도 여기서 running 플래그로 흡수.

출처: `.ai_monitor/api/lan_api.py:1`

### 모듈 상단 `[WHY]`

── 자동 공유(auto-share) 안전장치 유틸 ──────────────────────────────
[WHY] 클로드 자율 판단 발송은 오발송/프라이버시 사고 위험이 커, 서버측에서 강제하는
방어선(민감필터·dedup·레이트리밋)을 프론트/스킬이 우회 못하게 여기 고정한다.
설계: memory project_lan_auto_share.md (A안, 마스터 토글 기본 OFF).

출처: `.ai_monitor/api/lan_api.py:87`

### 모듈 상단 `[제약]`

[제약] 레이트리밋은 프로세스 메모리(단일 lan_api 프로세스 전제). 재시작 시 리셋 — 스팸
억제가 목적이라 영속화 불필요. dedup은 파일로 영속(재시작 후에도 재발송 방지).

출처: `.ai_monitor/api/lan_api.py:97`

### _save_seen `[제약]`

[제약] 무한 증가 방지 — 최근 500개만 유지. 오래된 해시는 재발송 가능해지지만
실사용상 같은 산출물을 500건 뒤에 다시 보낼 일은 드물어 수용.

출처: `.ai_monitor/api/lan_api.py:142`

### _pick_online_peer `[불변식]`

온라인이면서 페어링된(신뢰) 피어를 고른다.
반환: (peer_dict, reason). peer_dict None이면 reason에 실패 사유.
[불변식] online ∩ trusted 만 대상 — 발견됐지만 미페어링 피어로는 절대 안 보냄."""

출처: `.ai_monitor/api/lan_api.py:159`

### 모듈 상단 `[WHY]` `[제약]`

── 원격 실행 러너 (Phase 3 Task 6) ──────────────────────────────────
[WHY 재사용] agent_api의 명령 빌더(_build_chat_cmd)와 콘솔숨김 popen(_proc.popen)을
그대로 재사용 — claude 실행법 중복 금지([[서버와 라우팅]]). 다른 점은 출력 목적지:
handle_chat은 SSE로 브라우저에 보내지만, 여기선 브리지 exec-emit로 요청자에게 역방향 릴레이.
[제약] handle_run(싱글턴+SSE)은 caller가 출력을 폴링할 수 없어 부적합 → 전용 캡처 스레드.

출처: `.ai_monitor/api/lan_api.py:178`

### _extract_stream_text `[제약]`

claude stream-json 1줄 → 표시용 텍스트.
[2026-08-14] api/connector_relay.py에서 이관 — Discord 커넥터 계층을 걷어내며
유일하게 남은 소비자가 여기가 됐다. 원래 '중복 금지'로 relay에 두고 빌려
썼는데, 빌려주던 쪽이 사라졌으니 소비자가 소유한다.
[제약] agent_api.handle_chat의 파싱과 형식이 같아야 한다 — 같은 claude
stream-json을 읽는다. 한쪽 출력 형식이 바뀌면 양쪽을 같이 고칠 것.

출처: `.ai_monitor/api/lan_api.py:185`

### _run_remote_exec `[제약]`

[대상측] 승인된 태스크를 격리된 작업공간에서 claude로 실행하며 출력을 역방향 푸시.
[보안 — 2026-07-30 전면 교체] 이전 구현은 `yolo=True`(--dangerously-skip-permissions) +
`cwd=_project_root`였다. 3중 게이트가 '누가 요청하나'만 막고 '무엇을 건드리나'는 무제한이라,
페어링된 PC가 수신 PC의 프로젝트 루트를 통째로 편집할 수 있었다. 지금은:
① target_dir이 화이트리스트(lan_exec_allowed_dirs) 이하인지 검증 — 미등록이면 실행 거부
② copy 모드면 worktree/사본에서 실행 → 원본이 클로드 시야에 없음
③ yolo 제거, deny 프로파일을 --settings로 주입
[제약] direct 모드는 완전 격리가 아니다 — deny는 Bash 접두 매칭이라 절대경로 Edit을 못 막는다
(src/lan_sandbox.SANDBOX_SETTINGS 주석 참조). 사용자가 명시적으로 등록한 폴더에만 허용된다.
출력 원문은 DB에 안 남기고 요약 절단본만(Critic).

출처: `.ai_monitor/api/lan_api.py:221`

### _run_remote_exec `[WHY]`

[WHY 변경목록 통지] copy 모드는 원본에 아무것도 반영되지 않는다. 무엇이 바뀌었고
사본이 어디 있는지 알려주지 않으면 원격 작업 결과가 사본에 갇혀 유실된다.
반영 여부는 사람이 결정하는 것이 Phase A 계약(자동 머지 금지).

출처: `.ai_monitor/api/lan_api.py:296`

### _start_exec `[제약]`

실행 러너를 데몬 스레드로 시작(승인 시 호출). HTTP 핸들러를 막지 않음.
[제약] target_dir은 요청자가 보낸 값 — 신뢰하지 않는다. 검증은 _run_remote_exec 진입부의
resolve_target이 담당한다(스레드 안에서 실패해도 요청자에게 사유가 emit되도록).

출처: `.ai_monitor/api/lan_api.py:330`

### _drain_chat_inbox `[불변식]`

브리지 수신버퍼를 1회성으로 비워 DB에 옮긴다. 1:1/그룹방 폴링이 공유하는 헬퍼.
[불변식] 브리지 chat-drain은 큐를 비우는 1회성 호출이다. 1:1 폴링과 방 폴링이 각자
다르게 저장하면 먼저 호출한 쪽이 상대 메시지를 잘못된 스코프로 저장해버린다 →
저장 로직을 여기 하나로 모아 어느 쪽이 먼저 폴링해도 결과가 같게 만든다.

출처: `.ai_monitor/api/lan_api.py:341`

### handle_post `[WHY]`

[WHY 여기서 막나] 폴더 없이 보내면 상대가 '폴더 거부'로 응답할 뿐이라 왕복 낭비 +
사용자에게는 그냥 실패로 보인다. 요청자 쪽에서 먼저 걸러 원인을 명확히 알린다.

출처: `.ai_monitor/api/lan_api.py:481`

### handle_post `[WHY]`

[WHY] 클로드 자율 판단 발송의 서버측 관문. 입력 {files:[path...], summary, peer_id?}.
마스터 토글 OFF면 no-op — 우회 불가하게 여기서 강제한다.

출처: `.ai_monitor/api/lan_api.py:536`

## `.ai_monitor/lan_bridge.py`

### 모듈 상단 `[WHY]`

127.0.0.1 불변) 같은 네트워크의 다른 바이브코딩과 자동발견·페어링·파일전송한다.
LAN에 노출되는 유일한 표면 = 이 파일의 인증된 라우트뿐.
- 2026-07-19 Claude: 신규 — LAN 브리지 Phase 1 Task 3~5. office_server 구조 복제.
- 2026-07-22 Claude: 원격 VPN 지원 — 통신 대상 IP 해석을 _resolve_target으로 통합
(발견 우선 → 페어링 저장주소 폴백). 페어링 때 양측이 http_port를 교환해 상대 주소를 저장.
[보안 불변식] 라우트는 2계층:
① 로컬 전용(127.0.0.1만) — pair-begin/pair-connect/send/status. 외부가 내 파일전송을
트리거하지 못하게 client_address로 강제 차단.
② 인증 필요(외부 피어 대상) — pair-request/recv-file. HMAC 토큰(lan_peers) 검증 통과만.
[WHY 별도 프로세스] 기존 server.py를 0.0.0.0으로 열면 모든 API가 LAN 노출 → 위험.
브리지만 노출하고 노출 표면을 이 파일로 국한한다.

출처: `.ai_monitor/lan_bridge.py:1`

### 모듈 상단 `[제약]`

[Phase2] 채팅 수신 버퍼 — server(lan_api)가 chat-drain으로 꺼내 DB에 옮길 때까지의 전달버퍼.
[제약] 영구성은 DB(lan_messages)가 책임. 이 큐는 drain 전 재시작 시 유실 가능(전달버퍼 한정).

출처: `.ai_monitor/lan_bridge.py:76`

### _bind_server `[WHY]`

preferred부터 순차로 실제 bind를 시도(TOCTOU 없는 확정 바인딩). fixed면 그 포트만.
[WHY] find_free_port(bind-test-후-close)는 두 프로세스가 거의 동시에 뜨면 같은 포트를
free로 오판(race). 실제 서버 소켓을 직접 bind해 성공한 포트를 확정한다.

출처: `.ai_monitor/lan_bridge.py:104`

### ensure_firewall `[WHY]`

netsh로 인바운드 허용 규칙 등록. 관리자 권한 없으면 False(크래시 금지).
[WHY] 규칙을 매번 delete→add — find_free_port로 HTTP 포트가 바뀔 수 있어 stale 규칙을
남기지 않고 항상 현재 포트를 반영(멱등). delete는 규칙이 없으면 실패하나 무시.
[블로커] 이게 없으면 Windows Defender가 인바운드를 막아 '됐다는데 연결 안 됨' 사고.

출처: `.ai_monitor/lan_bridge.py:121`

### sanitize_filename `[불변식]`

수신 파일명을 안전화 — 경로 분리자·상위참조·제어문자·Windows 예약명 제거.
[보안] '../../etc/passwd', 'C:\\evil', 절대경로가 inbox 밖으로 못 나가게. 빈 결과는 대체명.
[불변식] 멱등이어야 함 — send_file이 sanitize된 이름으로 토큰을 서명하고, recv-file이
unquote→sanitize한 결과와 정확히 일치해야 인증 통과(재적용해도 같은 값).

출처: `.ai_monitor/lan_bridge.py:150`

### _resolve_target `[WHY]` `[불변식]`

peer_id → {ip, http_port, name, ...}. 발견(같은 LAN, UDP 브로드캐스트) 우선, 없으면
페어링 때 저장한 고정 주소로 폴백.
[WHY] 발견은 255.255.255.255 브로드캐스트라 서브넷/VPN을 못 넘는다
(lan_discovery 의도된 경계). 다른 네트워크 통신은 페어링 저장주소가 유일 경로. 같은 LAN이면
발견이 우선이라 DHCP로 IP가 바뀌어도 흡수(저장주소는 페어링 시점 고정이라 stale 가능).
[불변식] 반환 dict는 최소 ip·http_port 키 보유 — 5개 send_* 함수가 이 계약에 의존.

출처: `.ai_monitor/lan_bridge.py:167`

### _chat_body_hash `[WHY]`

채팅 토큰 서명용 해시. scope를 서명이 덮게 하되 1:1은 기존 규약을 그대로 유지한다.
[WHY 비대칭] scope를 무조건 해시에 넣으면 구버전 피어와 1:1 채팅까지 깨진다(구버전은
sha256(content)를 계산). room일 때만 확장해 하위호환을 보존한다 — 구버전에게 room 메시지를
보내면 인증 실패로 거부되는데, 그게 올바른 동작이다(구버전엔 그룹방 개념이 없음).
[보안] scope 강등/승격(room↔peer 바꿔치기) 시 해시가 달라져 토큰이 무효 → scope가 서명에
묶인다. exec의 target_dir이 서명 밖이라 바꿔치기 가능했던 것과 같은 계열의 함정이다.

출처: `.ai_monitor/lan_bridge.py:213`

### broadcast_chat `[WHY]` `[불변식]` `[제약]`

페어링된 모든 피어에게 그룹방 메시지를 팬아웃.
[WHY 서버 없는 방] 중앙 릴레이가 없으므로 '방'은 각자가 자기 피어 전원에게 뿌려서 성립한다.
A가 B·C에 뿌리고 B가 A·C에 뿌리면 셋 다 전부 보게 된다.
[제약 — 반드시 알 것] 방의 완전성은 **페어링의 완전성**에 종속된다. B와 C가 서로 페어링되지
않았다면 B의 메시지는 C에게 닿지 않는다(A만 봄). 3대 완전 참여엔 3쌍 페어링이 모두 필요.
[불변식] 오프라인 피어는 실패로 집계하되 전체를 실패시키지 않는다 — 한 대가 꺼져 있다고
나머지에게 안 가면 방이 사실상 죽는다.

출처: `.ai_monitor/lan_bridge.py:253`

### _read_config `[WHY]`

data_dir/config.json 읽기 — 매 호출 새로 읽는다(토글 변경 즉시 반영, 재시작 불필요).
[WHY 캐시 없음] lan_api._config와 동일 계약. 토글을 끈 뒤에도 캐시가 살아 있으면
'껐는데 계속 동작한다'는 최악의 보안 실패 모드가 된다.

출처: `.ai_monitor/lan_bridge.py:279`

### query_exec_dirs `[WHY]`

상대가 원격실행에 허용한 작업 폴더 목록을 조회(요청자 → 대상).
[WHY 네트워크 조회] 경로를 손으로 입력하게 하면 오타 한 글자에 '폴더 거부'만 돌아와
원인을 알 수 없다. 상대가 공개한 목록에서 고르게 해 실패 경로를 UI에서 제거한다.
[보안] 노출되는 것은 상대가 **명시적으로 등록한** 폴더의 경로/라벨/모드뿐이다. 디스크
탐색 기능이 아니므로 임의 경로 열람으로 확장되지 않는다.

출처: `.ai_monitor/lan_bridge.py:337`

### send_exec_output `[불변식]`

실행 출력 청크를 요청자에게 역방향 전송. body_hash=sha256(exec_id:chunk:done)로 서명.
[불변식] 대상측 server가 agent_api 실행 출력을 청크로 잘라 여기로 밀어 넣는다.
done=True 청크가 종료 신호(빈 chunk 가능). 요청자 브리지의 /lan/exec-output이 버퍼링.

출처: `.ai_monitor/lan_bridge.py:366`

### _exec_recv `[불변식]`

[불변식] 브리지는 target_dir을 판정하지 않는다 — 화이트리스트 검증은 lan_api 러너 책임.
여기서 걸러버리면 '왜 조용히 안 되는지'가 감사로그에 안 남는다.

출처: `.ai_monitor/lan_bridge.py:729`

### _exec_dirs_recv `[제약]`

페어링된 상대에게 내가 허용한 작업 폴더 목록을 응답.
[보안] ① 토큰 인증 필수 ② 마스터 토글(lan_remote_exec_enabled) OFF면 목록조차 주지 않음
— 꺼둔 PC가 폴더 구성을 노출할 이유가 없고, 요청자 UI가 'OFF'를 즉시 알 수 있다.
[제약] 브리지는 project_id를 모르지만 config.json은 data_dir 파일이라 읽어도 이식성에
영향 없다(lan_peers.json과 동일 계층).

출처: `.ai_monitor/lan_bridge.py:739`

### main `[WHY]`

[WHY] 브리지 HTTP 포트는 동적(9020부터 스캔) → server.py의 lan_api가 어느 포트로
프록시할지 알 방법이 없다. 확정 포트를 파일에 남겨 lan_api가 읽게 한다(파일 부재=브리지 꺼짐).

출처: `.ai_monitor/lan_bridge.py:853`

## `.ai_monitor/src/lan_sandbox.py`

### 모듈 상단 `[WHY]` `[제약]`

모드별 작업공간(copy=사본/direct=원본) 준비 + deny 권한 프로파일 생성.
LAN 원격실행(api/lan_api.py)과 자율 데몬(infra/heartbeat_daemon.py)이 공용한다.
- 2026-07-30 Claude: 신설. 원격실행이 --dangerously-skip-permissions로 수신 PC의 프로젝트
루트를 무제한 편집할 수 있던 구멍(3중 게이트는 '누가'만 막고 '무엇을'은
무제한이었음)을 막기 위한 격리 계층. heartbeat의 deny 프로파일을 정본으로 흡수.
[WHY 별도 모듈] lan_api(원격실행)와 heartbeat_daemon(자율실행)이 같은 문제를 각자 풀면
프로파일이 갈라져 한쪽만 강화되는 사고가 난다. 여기가 정본이고 양쪽이 import 한다.
[제약] project_id 비의존 — LAN 계층 전체가 이식성 전제([[회상과 지식 창고]]).

출처: `.ai_monitor/src/lan_sandbox.py:1`

### 모듈 상단 `[WHY]` `[제약]`

── 샌드박스 권한 프로파일 ───────────────────────────────────────────────────
[WHY] 파일로 배포하지 않고 상수→런타임 materialize — .ai_monitor/config/ 신규 디렉토리를
만들면 spec datas + CI --add-data 양쪽 갱신이 필요(v3.7.215~218 사고). data_dir은 이미
런타임 쓰기 경로라 frozen 모드에서도 안전.
[제약 — 반드시 알 것] deny 규칙은 Bash 접두 매칭이다. Edit/Write 도구는 이걸로 못 막는다.
따라서 direct 모드에서 절대경로 Edit로 cwd 밖을 고치는 것은 프로파일이 아니라
defaultMode(cwd 밖 자동승인 안 함) 성질에만 의존한다 = 완전 격리 아님.
완전 격리가 필요하면 copy 모드를 써야 한다.

출처: `.ai_monitor/src/lan_sandbox.py:23`

### 모듈 상단 `[WHY]`

copy 모드 복사 제외 — 비밀·대용량·재생성 가능 산출물.
[WHY] 사본 격리의 목적은 '원본 보호'지만, 사본에 .env/키가 실리면 원격 실행자가 비밀을
읽어가는 새 구멍이 된다. git 저장소면 worktree(추적 파일만)가 이 문제를 구조적으로 회피한다.

출처: `.ai_monitor/src/lan_sandbox.py:52`

### allowed_dirs `[WHY]`

설정의 허용 폴더 목록을 정규화해 반환. [{path, mode, label, exists}]
mode: 'copy'(사본에서 작업, 기본) | 'direct'(원본 폴더에서 직접 편집)
[WHY 기본 copy] 잘못 등록해도 원본이 안 깨지는 쪽이 안전한 기본값.

출처: `.ai_monitor/src/lan_sandbox.py:81`

### Workspace `[불변식]`

준비된 작업공간. cwd에서 claude를 실행하고, 끝나면 finish()로 정리/변경목록을 얻는다.
[불변식] is_copy=True인 경우에만 cwd != origin. direct 모드는 cwd == origin이라
cleanup이 원본을 지우면 안 된다 — finish()가 is_copy로 분기하는 이유.

출처: `.ai_monitor/src/lan_sandbox.py:161`

### finish `[WHY]`

변경목록을 뽑고 사본을 정리한다. keep=True면 사본을 남겨 사람이 직접 확인 가능.
[WHY keep 기본 True] 사본을 즉시 지우면 원격 작업 결과가 통째로 사라진다. Phase A는
'자동 반영' 없이 '사람이 보고 반영'이 계약이므로 산출물을 남기는 쪽이 기본.

출처: `.ai_monitor/src/lan_sandbox.py:189`

### _diff_by_stat `[제약]`

copy 모드 변경 감지 — (크기, mtime) 비교. git이 없는 폴더용 폴백.
[제약] 내용이 같은 크기로 바뀌고 mtime까지 보존된 경우는 놓친다. 해시 전수 비교는
대형 폴더에서 비용이 커서, '사람이 검토한다'는 Phase A 계약 하에 stat 비교로 충분하다고 판단.

출처: `.ai_monitor/src/lan_sandbox.py:247`

### prepare_workspace `[불변식]`

모드에 맞는 작업공간을 준비한다.
- direct: 원본 폴더 그대로 (사용자가 명시적으로 등록한 경우만)
- copy + git 저장소: `git worktree add --detach` — 추적 파일만 나타나므로 .env/키가
구조적으로 배제되고 복사 비용도 거의 없다(하드링크). copy 모드의 우선 경로.
- copy + 비-git: copytree(제외 패턴 + 용량 상한)
[불변식] 작업공간은 항상 data_dir/lan_workspaces/<exec_id> 이하에 만든다. 원본 안에
만들면 원격 작업이 원본 트리를 오염시키고 git status를 더럽힌다.

출처: `.ai_monitor/src/lan_sandbox.py:273`

## `.ai_monitor/vibe-view/src/components/panels/LanPanel.tsx`

### PENDING_TTL_MS `[불변식]`

[다중 실행] peer_id → 실행 1건. 백엔드는 exec_id별로 프로세스·작업공간이 분리돼 원래부터
병렬이었지만 UI가 단일 execId 슬롯이라 한 대씩만 몰 수 있었다. 피어별 맵으로 해소.
[불변식] 같은 피어에 동시 2건은 여전히 금지 — 이전 exec를 잊고 orphan 스트림을 남기는
문제(리뷰 W6)는 '피어당 1건'으로 막는다.

출처: `.ai_monitor/vibe-view/src/components/panels/LanPanel.tsx:58`

### PENDING_TTL_MS `[WHY]`

[WHY] PyWebView 네이티브 앱이라 <input type=file>은 경로를 못 주고(보안상 fakepath),
전송엔 실제 절대경로가 필요. 백엔드 tkinter 파일 다이얼로그(/api/browse-file)로 경로 획득.

출처: `.ai_monitor/vibe-view/src/components/panels/LanPanel.tsx:120`

### PENDING_TTL_MS `[불변식]`

[Phase3] 승인 대기 폴링(대상측) — 3초. 게이트 OFF면 enabled=false로 즉시 빈 목록.
[불변식] 브리지 pending-drain은 1회성(큐 비움)이라 서버가 매번 새로 준 것만 반환한다.
→ 프론트가 덮어쓰면 팝업이 3초 뒤 사라진다. 반드시 exec_id로 dedupe 누적(merge)하고,
승인/거부로만 제거. TTL(5분) 초과분은 자동 거부(자리비움 대비, Task 11).

출처: `.ai_monitor/vibe-view/src/components/panels/LanPanel.tsx:170`

### PENDING_TTL_MS `[WHY]`

[다중 실행] 진행 중인 모든 exec의 출력을 하나의 인터벌로 폴링한다.
[WHY 단일 인터벌] 실행별 useEffect를 두면 runs가 바뀔 때마다 effect가 재생성돼
폴링이 리셋되고, 브리지 exec-output-drain은 1회성이라 그 틈에 청크를 흘릴 수 있다.
deps=[]로 고정하고 최신 runs는 ref에서 읽는다.

출처: `.ai_monitor/vibe-view/src/components/panels/LanPanel.tsx:204`

### PENDING_TTL_MS `[WHY]`

[Phase A] 전송 대상이 바뀌면 그 PC의 허용 폴더를 다시 조회한다.
[WHY 매번 조회] 상대가 폴더를 추가/삭제하거나 토글을 끈 것을 이쪽이 알 방법이 없다.
캐시하면 '목록에 있는데 거부됨'이라는 설명 불가능한 실패로 이어진다.

출처: `.ai_monitor/vibe-view/src/components/panels/LanPanel.tsx:241`

## 확인법

```bash
python scripts/wiki_lint.py        # 이 페이지의 출처가 아직 살아 있는지
python scripts/wiki_build.py       # 원본 주석 변경분 재합성
```

<!-- tags: WHY, 불변식, 제약 -->
