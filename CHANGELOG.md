# 📜 변경 이력 (CHANGELOG)

## [2026-08-16] - 음성: 낭독을 edge-tts 로

낭독이 edge-tts 로 바뀌었습니다(선희·인준·현수). 마이크 누르고 말하기, 터미널별 분리, 채팅창 정리도 함께.

### 🔊 낭독 엔진 교체 + 정리
- **[Feature] edge-tts 로 낭독**: 한국어 3종(선희·인준·현수). 모델 0개·GPU 0·API 키 없음. 새 문장 0.7~1.1초, 같은 문장 재생은 캐시로 ~10ms. 로컬 후보 6종(MeloTTS·XTTS-v2·OmniVoice·VoxCPM2·Qwen3-TTS·Kokoro)은 실측에서 전부 탈락했고 Kokoro 는 한국어 목소리가 0개였다.
- **[Feature] 목소리 고르기 + 끄는 스위치**: 음성 설정에서 목소리·속도를 고르고 브라우저에 기억한다. 인터넷 목소리를 끄면 목록에서 빠진다.
- **[정리] 낭독 엔진을 하나로**: sherpa VITS·SAPI·CosyVoice 어댑터와 그 패키지·모델을 걷어냈다(약 151MB 회수). 되돌아갈 길은 브라우저 내장 합성기가 맡는다 — 망이 끊겨도 소리가 난다.
- **[UX] 읽기 전에 표·코드·경로를 걷어낸다**: "슬래시 에이피아이 슬래시"는 귀로 못 따라간다. 지우지 않고 낱말로 바꿔 조사가 뜨지 않게 했다.
- **[Fix] 설치본이 보이지 않는 오류창에서 멈추던 사고**: 안내 문구의 줄표(—)를 cp949 가 못 담아 print 가 예외를 냈고, GUI 빌드라 화면 없는 모달 대화상자로 떠서 앱이 영원히 멈췄다. 로그도 안 남았다. 표준 출력 인코딩을 안전하게 만들어 근본 차단.
- **파일**: `voice-server/`(engines·voice_server.py), `vibe-view/src/lib/`(voiceBus·browserVoice·speech), `boot.py`.

## [2026-07-24] - 터미널 슬롯마다 다른 프로젝트 실행

### 🗂️ 단일 앱 안에서 슬롯별 프로젝트 + 활성 슬롯 따라 패널 전환
- **[Feature] 슬롯별 프로젝트 오버라이드**: 각 터미널 슬롯이 서로 다른 프로젝트 cwd로 PTY를 띄운다. `currentPath` 전역 하나를 모든 슬롯이 공유하던 구조에서, `slotProjects` 맵으로 슬롯마다 프로젝트를 지정. 미지정 슬롯은 전역 프로젝트 상속(하위호환).
- **[UX] 명시적 활성화**: 슬롯 헤더의 📁 프로젝트 뱃지 클릭 → 그 슬롯 프로젝트가 사이드 패널(파일·Git·태스크·하이브) 전체를 지배. 활성 슬롯은 하이라이트. 암묵적 포커스는 Phase 2-5.2 race window 재발 위험이라 배제.
- **[안전] 실행 중 변경은 재시작 확인**: PTY cwd는 spawn 시 고정이라, 살아있는 터미널의 프로젝트를 바꾸려면 `confirm` 후 새 cwd로 재연결. `launchAgent(cwdOverride)`로 stale-closure 회피.
- **[영속] localStorage `hive_slot_projects`**: 앱 재시작 후 슬롯별 프로젝트 복원(WebView2 storage_path).
- **[백엔드 무변경]**: PTY는 이미 `/pty/slot{id}?cwd=` 슬롯별 cwd 수신, 서버 폴링은 `withProjectId(currentPath)`로 project_id 명시 전달 → 활성화 즉시 패널 재조회(기존 기계 재사용).
- **파일**: `App.tsx`(slotProjects/activeProjectSlot 상태·배선·FileExplorer 동기), `TerminalSlot.tsx`(slotProject cwd·헤더 UI·재시작 핸들러).

## [2026-07-24] - 크로스 프로젝트 로그 오염 차단

### 🚧 외부 프로젝트 로그가 vibe-coding 회상에 섞이던 누수 봉합 (b5ded87)
- **[Fix] caller project_id 4계층 관통**: `hive_bridge.log_task`가 project_id를 안 실어 보내고 `server.log_to_pg`가 무조건 자기 PROJECT_ID로 도장하던 것을, 훅→브리지→서버수신→DB기록 전 경로에 호출 프로젝트 슬러그를 관통. f1c0d4b가 세션 함수만 고치고 로그 경로를 빠뜨린 회귀를 봉합.
- **[정리] 과거 오염 로그 재태깅**: ons 작업이 `D--vibe-coding`으로 잘못 박힌 1105행을 파일 실존 판별로 안전 분류해 `D--ons`로 비파괴 재태깅(vibe-coding 자기 파일은 제외).

## [2026-07-24] - 텔레그램 그룹방 허브화 회귀 테스트 고정

### 🧪 조용한 실패 3종을 테스트로 못 박음
- **[Test] `tests/test_telegram_hub.py` 신규 (35케이스)**: 구현(c768e7b)은 있었으나 계획의 '검증' 항목이 비어 있던 것을 채움. 세 결함 모두 예외·로그 없이 **조용히** 실패했던 종류라 수동 확인으로는 재발을 못 잡는다.
- **[Task 1] `.env` 저장 시 `TELEGRAM_GROUP_CHAT_ID` 보존**: 토큰만 저장해도 그룹ID·PC라벨 생존, 비-텔레그램 라인 보존, 마스킹 토큰이 실토큰을 덮지 않음, 멱등(마커 누적 없음), `None`(미변경) vs `""`(의도적 비움) 구분.
- **[Task 2] `_split_message` 유실 0**: 줄 경계 분할은 재결합 시 원문과 정확히 일치, 줄바꿈 없는 초장문도 전량 보존, 코드펜스가 조각마다 짝을 이룸, `max_parts`가 내용을 잘라내지 않음(판단 기준일 뿐).
- **[Task 3] `is_sendable_path` 보안 가드**: `.env`/키/자격증명/로그·덤프 거부, `..` 탈출 거부(resolve 후 판정), 민감 디렉토리(`.ssh`/`.oci` 등) 거부, 용량 상한·빈 파일·디렉토리 거부.
- **[Task 4] `_safe_send` 3경로**: ①1건 ②분할(재결합=원문) ③.txt 첨부(전문 일치). **파일 전송이 실패해도 분할로 폴백**해 내용이 사라지지 않음, Markdown 파싱 실패 시 분할 후에도 plain 폴백 동작, 가드 거부 시 사유를 사용자에게 회신.
- **[검증 방식] 네트워크 미사용**: `app.bot`을 가짜 객체로 대체 — 봇 토큰·인터넷 없이 CI에서 그대로 실행된다. 옛 결함 로직을 재현해 테스트가 실제로 잡는지 확인함(옛 `_truncate` 경로에서 36,799자 유실 재현).
- **[Docs] `api/telegram_api.py`**: `telegram_config_post` docstring이 사고 원인이던 옛 동작("TELEGRAM_ 접두사를 모두 제거")을 그대로 설명하고 있어 현행 규칙으로 교정.

## [2026-07-22] - LAN 브리지 Phase 3: 원격 Claude 에이전트 실행

### 🎮 같은 LAN 페어링 PC 원격 제어
- **[Feature] 원격 에이전트 실행**: 페어링된 같은 네트워크 PC에 태스크 전송 → 상대 승인 → 상대가 Claude 에이전트 실행 → 결과를 요청자가 폴링 수신. `임의 셸 아님`(자연어 태스크→claude, 간접 실행).
- **[보안] 3중 게이트**: ① 페어링 HMAC 토큰(기존 재사용, body_hash 서명·nonce 재전송차단) ② 상대 독립 마스터토글 `lan_remote_exec_enabled` **기본 OFF**(파일/채팅과 별개 — 켠 PC만 수락, OFF면 pending 회수 자체를 안 함) ③ 승인 팝업(요청자+태스크 **전문** 표시).
- **[편의] 피어별 exec_trust(ask/auto)**: 첫 승인 팝업의 '이 PC 자동승인' 체크 시 이후 팝업 없이 실행(자율 목적). auto여도 감사로그는 항상 기록.
- **[아키텍처] 브리지=릴레이, server=실행+DB**: 브리지(lan_bridge.py)는 exec 릴레이+버퍼만, 실행은 lan_api가 `agent_api._build_chat_cmd`+`_proc.popen` 재사용(중복 없음), 감사는 PG `lan_exec_log`(server 책임 — 채팅과 동일 원칙).
- **[안전] TTL/타임아웃/취소**: 승인 대기 5분 TTL 자동거부(자리비움), 실행 30분 타임아웃 강제종료, 취소 라우트. 출력 원문 DB 미저장(요약 2000자 절단).
- **[제약] 같은 LAN 전용**: UDP 브로드캐스트+사설IP라 다른 네트워크 불가(VPN/릴레이는 별도 스코프).
- **파일**: lan_bridge.py(exec 라우트/버퍼), api/lan_api.py(/api/lan/exec/*+캡처스레드), src/lan_peers.py(exec_trust), src/pg_lan.py+pg_schema.py(lan_exec_log), LanPanel.tsx(전송/승인팝업/출력뷰/토글).

## [2026-07-19] - 라이브 프로젝트 전환 (무재시작)

### 🔀 프로젝트 라이브 전환
- **[Fix/Feature] server.py `_switch_project` + `POST /api/switch-project`**: '프로젝트 폴더 선택' 시 재시작 없이 DB 커넥션/컨텍스트/배너/패널을 전환. 근본원인 = PROJECT_CONTEXT_UNRESOLVED/DB커넥션/PROJECT_ROOT가 부팅 1회 고정, 런타임 재초기화 없음(폴더 선택해도 last_path만 저장돼 패널 빔+배너 잔존).
- **[안전] 전환 실패 시 이전 프로젝트로 롤백** — 반쪽 상태로 앱 불능 방지. DB 전환은 set_project_db가 단일/db-키잉 풀 커넥션을 새 DB로 유도(교차오염 없음).
- **[라이브 추종] zettel_sync.py watch_and_sync `resolve` 콜러블**: 매 사이클 vault/project_id 재해석 → 데몬 재시작 없이 전환 추종. 옛 스코프로 새 DB를 정리해 노트를 오삭제하던 위험 차단.
- **[프론트] App.tsx openFolder**: select-folder 후 switch-project를 await한 뒤 경로 갱신(배너 정합성).

## [2026-07-19] - LAN 자동 공유 (클로드 자율 발송)

### 📤 LAN 자동 공유 (A안)
- **[Feature] lan_api.py `/api/lan/auto-share`**: 클로드가 파일+세션요약을 페어링된 온라인 PC로 자동 전송하는 서버측 관문. 기존 send/chat-send/status 프리미티브 재사용, 온라인∩신뢰 피어만 대상(미페어링 절대 제외).
- **[안전] 마스터 토글 `lan_auto_share_enabled` 기본 OFF**: 켜야만 자동발송. OFF면 `{ok:false,reason:'disabled'}` no-op. 오발송/프라이버시 사고 방지 핵심.
- **[안전] 서버측 강제 방어선**: 민감파일 필터(.env/secret/token/*.pem/*.key), 내용해시 dedup(재발송 차단·변경 시 허용), 분당 레이트리밋. 스킬/프론트가 우회 불가.
- **[Feature] /vibe-share 스킬**: 클로드 자율 판단 기준 + 전송 후 명시 리포트(`📤 [자동공유] N건 + 요약 → peer`). 토글 OFF면 발송 대신 제안만.
- **[검증]** 안전장치 22개 단위 검증 통과(필터·dedup·해시·토글·레이트리밋·피어선택). 파일전송 배선은 기존 LAN Phase1/2 E2E로 검증됨.

## [2026-07-16] - A+B: 회상 정밀도 + 교훈 파이프 소생

### 🎯 A. 회상 정밀도 (노이즈 컷)
- **[Fix] pg_vector_search.py `_TABLES.quality`**: 검색 시점 저정보 행 차단 — 백필의 '(빈 내용)' placeholder 임베딩이 일반 지시와 0.5+ 매칭되던 근본 원인. 경험노트 desc<20자, 지식/제텔 title+content<30자 제외 (사고 장부는 무필터 — 짧아도 가치 높음).
- **[Fix] memory_api.py recall-smart**: 짧은 쿼리(<20자) 임계 0.45→0.60 상향 — "그럼 진행해"류 저정보 지시엔 더 높은 확신이 있을 때만 주입. ⚠️ 서버 반영은 앱 재시작 후.
- **[검증]** 저정보 행이 자기 임베딩(유사도 1.0)으로도 미노출 + 회귀 테스트 추가.

### 🔁 B. 교훈 파이프 소생 (사고 클러스터 자동 증류)
- **[Feature] lesson.py `distill_from_incidents` + CLI `distill`**: 파일별 사고 클러스터(30일 3건+) → 교훈 후보 자동 적재. 재발-only 트리거가 재발률 0%로 영영 무발화하던 파이프의 소생. dedupe upsert로 승인 큐 오염 없음, lessons.md 쓰기는 approve 게이트 불변.
- **[Feature] incident.py record 후 자동 distill**: 매 사고 기록마다 클러스터 재평가 (예외 무전파).
- **[실증]** 첫 실행에서 TerminalSlot.tsx(3건)/hive_hook.py(3건) 후보 2건 즉시 적재 — 승인 대기 중.


## [2026-07-16] - 로드맵 ③ 코덱스 회상 주입 (클로드 루프 100% 종결)

### 🧠 코덱스 래퍼 회상 주입 — 3에이전트 회상 경로 수렴
- **[Feature] agent_api.py `_codex_recall_prefix` + `handle_chat`**: 코덱스는 훅 시스템이 없어 대시보드/오피스 공용 중계 지점(POST /api/agent/chat)에서 **stdin 전달분에만** 회상 v2 요약을 접두 주입. history/텔레그램 버스는 원문 유지(UI 노출 금지). claude(hive_hook)/antigravity(BeforeAgent)는 자체 훅 주입이라 제외 — 이중 주입 방지.
- **[계측] caller='codex'**: ②에서 완비된 recall-smart caller 계측에 자동 편승 — heal_report 에이전트별 분해에 codex 행 등장 (실측: hit items=5).
- **[제약 해소] VIBE_SERVER_PORT setdefault**: 서버 자신은 이 env 미보유(데몬 자식에게만 주입) → 자기 바인드 포트로 setdefault해 recall_client 포트 스캔 생략. 멀티 프로젝트 동시 가동(9000=ons, 9010=vibe-coding) 환경에서도 **자기 프로젝트 지식만** 주입됨을 실측 확인.
- **[Test] 전체 127 pass** + recall_client→recall-smart→pg_logs 계측 엔드투엔드 실측.

### 🔌 포트 스캔 프로젝트 대조 전면화 (잔여 구멍 청산)
- **[Feature] src/server_locator.py 신설**: 9000번대 서버 탐색 공용 모듈 — /api/project-info 슬러그 대조 + 127.0.0.1 병렬 프로브. recall_client 수정(ab0f1a3)의 로직을 공용화.
- **[Fix] recall_client.py**: 자체 탐색 제거, server_locator 패스스루 (중복 금지).
- **[Fix] hive_hook.py `_update_pipeline_stage`**: 9000 하드코딩 제거 — 파이프라인 stage가 타 프로젝트 대시보드로 가던 구멍. 자기 서버 없으면 전송 생략.
- **[Fix] hook_bridge.py**: `_server_port_for` 신설 — /api/agent/run 호출과 `_start_server` 대기 판정을 자기 프로젝트 서버 기준으로 (타 서버만 살아있으면 '자기 서버 기동'으로 정상 진행).
- **[Fix] agent_shell.py / terminal_agent.py**: 첫 응답/9000 고정 → 슬러그 대조 우선, 실패 시 기존 동작 폴백.
- **[검증] 실환경(9000=ons, 9010=vibe 동시 가동)**: 6개 진입점 전부 자기 서버(9010) 채택 + 유령 슬러그 시 오염 방지 확인. pytest 127 pass ×3.


## [2026-07-13] - 지식 노트 파이프라인 재설계 (나만의 지식 창고)

### 🧹 노이즈 차단 — 세션요약이 영구지식을 점령하던 사고
- **[Fix] pg_memory.py `_auto_promote_where_clause`**: 세션요약/머지커밋을 fleeting→permanent 자동승격에서 배제. 세션요약은 auto_link로 링크 degree가 금방 3↑ → 허브형 조건에 걸려 영구지식 **65%(817건)를 점령**하던 근본 구멍. (run_zettel_refine엔 이미 있던 배제를 auto_promote에도 일치.)
- **[Migration] migrate_archive_session_summaries.py**: 기존 오승격 세션요약 **822건 archived=true** (되돌림 가능). 영구지식 1264→427건으로 정제.

### 📄 파일 지식 1급화
- **[Feature] zettel_capture.py `_read_file_description`**: 파일 역할 카드의 설명을 경로 추측(`_guess_file_role`)이 아니라 **표준 헤더 DESCRIPTION 실제 파싱**으로 격상(무헤더 시 폴백). CLAUDE.md 규칙5 자산 활용.
- **[Feature] `_extract_commit_why`**: 파일 카드 "최근 변경"에 커밋 제목만 아닌 **'무엇을/왜'**(커밋 본문 3섹션 첫 줄) 누적.
- **[Feature] `capture_project_map`**: git 추적 파일 트리 + 파일별 DESCRIPTION → 단일 upsert 노트 `🗂️ 프로젝트 파일 지도`(source_ref='project-map'). 커밋 폴링 데몬 편승 자동 갱신. **이식성**: git ls-files라 어느 프로젝트에서도 자기 트리만 스캔.

### ☁️ GDrive 크로스프로젝트 허브 정제
- **[Feature] zettel_sync.py `mirror_vault(note_filter=)` + `_is_gdrive_worthy`**: GDrive 미러에서 커밋덤프(git-commit:*)/세션요약 노이즈 제외, 파일카드·지도·결정·지식은 유지. **로컬 vault는 불변**(전체 유지), 허브만 정제.

### 🔁 GDrive 크로스-PC 양방향 동기화 (오래된 미해결 완성)
- **[Feature] daemons.py `_sync_with_gdrive`**: 단방향(로컬→GDrive)에 **역방향 흡수** 추가 — `import_from_vault(GDrive, project_id)`로 다른 PC가 올린 '이 프로젝트' 노트를 이 PG로 흡수. **project_id 스코프**라 다른 프로젝트는 각자 이름으로 격리 유지(GDrive Obsidian에서만 통합 열람).
- **[Feature] 아카이브 상태 전파**: `watch_and_sync(include_archived=)` 추가 + 양 루프 `include_archived=True` 일치 → 아카이브 노트가 `_보관`으로 export·전파, 다른 PC import가 `archived` 존중. 로컬/GDrive 두 루프의 `_보관` 핑퐁 제거.
- **[Fix] 부활 방지**: `import_from_vault`가 아카이브 노트를 신규 생성할 때 `create_note`에 archived 인자가 없어 활성으로 부활하던 구멍 → 생성 직후 `update_note(archived=True)` 보정.
- **[안전] 핑퐁/충돌**: 기존 `import_from_vault`의 mtime + `_same_note_payload` 가드 재사용으로 수렴. 라이브 통합 검증(스코프 격리·아카이브 전파·부활 방지) PASS.
- **[Test] test_knowledge_pipeline.py**: 순수 함수 계약 8건. 전체 127 pass.

## [2026-06-11] - Antigravity CLI 마이그레이션 완료 (Gemini CLI 6/18 종료 대응)

### 🚀 런타임 전환 (데드라인 크리티컬)
- **[Feature] antigravity_adapter.py**: agy 호출 격리 레이어 — closed-source 인터페이스 변경 대비 단일 격리점. **알려진 결함**: agy 1.0.7 `-p`는 파이프 환경에서 응답 미출력(콘솔 TUI 전용) → 빈 출력을 명시적 예외로 승격.
- **[Fix] gemini CLI 직접 실행 전수 제거**: hive_heartbeat / telegram_bridge / agent_api 채팅(소멸 모델 gemini-3.1-pro 지정 제거) — 전부 어댑터 경유.
- **[Fix] 외부 세션 감지**: 폐기된 `~/.gemini/tmp/*/chats` → `~/.gemini/antigravity-cli/conversations/` mtime 스캔.

### 🔁 식별자 일괄 전환 (옵션 B)
- **[Refactor] 84파일 507라인 스윕**: 'gemini'→'antigravity' (보존: API 키/모델명/npm 패키지/.gemini 경로/GEMINI.md/레거시 config 키/사실 서술).
- **[Migration] DB 13컬럼 120건 UPDATE**: 백업 후 트랜잭션 실행. **다른 PC는 `python scripts/migrate_antigravity_db.py` 1회 실행 필요**.
- **[Docs] 실측 기록**: agy는 `~/.gemini/`·`.gemini/`·`GEMINI.md`를 그대로 사용 — rename 금지 (외부 도구 소유 인터페이스).
- ⚠️ 다른 PC 첫 `agy` 실행 시 OAuth 재로그인 필요.

## [2026-06-10] - 자가 치유 2.0 (삽질 빈도 감소 시스템)

### 🧠 ④ 회상 v2 — pgvector 임베딩 회상
- **[Feature] pg_vector_search.py**: zettel/메모리/경험/사고장부 4테이블에 `embedding vector(384)` + 코사인 검색. **유사도 0.45 미만 비주입** — 무관 회상 노이즈 차단.
- **[Feature] embed_service.py**: fastembed 다국어 모델 warm 싱글톤 (memory_watcher 고아 헬퍼 이관). 캐시는 DATA_DIR 고정.
- **[Feature] recall-smart API + recall_client**: 훅은 서버 임베딩 회상 호출(2초 상한), 서버 불통 시 기존 ILIKE 자동 폴백 — 외부 프로젝트 이식성 보존.
- **[Feature] 임베딩 백필 데몬**: embedding IS NULL 행을 60초 주기 사후 채움. 참조 피드백(ref_count/access_count) 랭킹 가산.

### ⚡ ① 사고 장부 — 고친 에러는 두 번 고치지 않는다
- **[Feature] incident_ledger**: 에러 시그니처(경로/줄번호/주소/시각 정규화 해시) + 근본원인/수정법/커밋. 재발 시 recurrence_count 증가.
- **[Feature] incident.py CLI**: record/search/**stats(북극성 지표: 재발률)**.
- **[Feature] 훅 자동 주입**: 프롬프트에 에러 감지 시 과거 수정법 즉시 브리핑. vibe-debug 0단계 조회 + 종료 기록 의무화.

### 🔄 ② 의도 단위 체크포인트
- **[Feature] checkpoint.py**: "왜/결정/다음" 3요소 기록 → 크래시 복구 브리핑이 파일 목록 대신 의도를 표시.

### 📚 ③ 교훈 증류 (승인 게이트)
- **[Feature] lesson.py + .claude/rules/lessons.md**: propose(후보) → 사용자 승인 → approve만 파일 기록. CLAUDE.md 자동 수정 금지.

## [2026-03-07] - v3.7.9 (윈도우 네이티브 미션 컨트롤 고도화)

### 🛰️ Windows Native Mission Control (CMUX 스타일)

- **[Feature] 윈도우 네이티브 관제 센터 (mission_control.py)**:
    - PySide6 기반의 고성능 시스템 트레이 위젯 및 사이드바 HUD 구축.
    - 웹 브라우저 없이 윈도우 OS에서 직접 구동되는 하이브리드 관제 환경.
- **[Feature] CMUX 스타일 상태 링 (mission_control_ui.py)**:
    - 에이전트 활동 상태(Gemini/Claude)를 실시간으로 시각화하는 펄싱 링 위젯.
    - 화면 우측에서 슬라이드인(Slide-in)되는 반투명 HUD 인터페이스.
- **[Feature] 실시간 로그 테일링 (Hive Log Stream)**:
    - `task_logs.jsonl` 파일을 실시간으로 감시하여 사이드바에 즉각 로그 출력.
    - 에이전트 간의 통신과 작업 내역을 터미널 밖에서도 관제 가능.
- **[Feature] 트레이 아이콘 펄스 (Status Pulse)**:
    - 에이전트가 '생각 중'일 때 트레이 아이콘에 화려한 색상 펄스 애니메이션 적용.
    - 아이콘 툴팁을 통해 현재 어떤 에이전트가 어떤 작업을 하는지 즉시 확인.
- **[Improvement] 터미널 통합 상태바 (terminal_status.py)**:
    - `rich.live`를 활용하여 터미널 내부에서도 에이전트 상태를 요약 표시.
    - `run_vibe.bat` 실행 시 서버와 관제 센터가 동시에 백그라운드 자동 기동.

## [2026-03-06] - v3.7.8 (자율 에이전트 고도화 Phase 6)

### 🤖 자율 에이전트 3종 고도화

- **[Feature] Self-Reflect 루프 (hive_hook.py + hive_bridge.py)**:
    - `PostToolUse`: 수정/생성 파일 경로를 `_SESSION_MODIFIED_FILES`에 자동 누적.
    - `Stop`: `reflect_to_pg()`로 학습 내용·실패 이유를 pg_thoughts에 자동 기록.
    - `UserPromptSubmit`: pg_thoughts 유사 과거 반성 2건을 컨텍스트로 자동 주입.
- **[Feature] Bounded Autonomy (scripts/safety_guard.py + hive_hook.py)**:
    - `safety_guard.py`: 위험 명령 패턴 14종 탐지 엔진 신규 생성.
      - 차단: `rm -rf`, `git push --force`, `git reset --hard`, `DROP TABLE` 등.
      - 경고: `git push origin main`, `pip install --upgrade` 등.
    - `PreToolUse(Bash)`: `safety_guard.check()` 호출 → 위험 시 `exit(2)` 차단.
- **[Feature] Model Routing (scripts/cli_agent.py + agent_api.py)**:
    - `route_task_with_reason()`: `(cli, reason)` 튜플 반환으로 선택 근거 추적.
    - Claude 키워드 20종: 코드/수정/디버그/구현 등. Gemini 키워드 18종: 분석/검색/설명 등.
    - `agent_api.py`: `routing_reason`을 터미널 상태에 기록하여 UI에 전달.
- **[Feature] KanbanPanel pg-activity 컬럼 (server.py + KanbanPanel.tsx)**:
    - `/api/kanban/pg-activity`: pg_logs 터미널별 최근 활동 집계 엔드포인트 추가.
    - KanbanPanel: 스킬 체인 컬럼 + pg_logs 터미널 활동 컬럼 동시 표시.
- **[Update] AgentPanel.tsx — routing_reason 뱃지 표시**:
    - TerminalCard 헤더에 CLI 배지 옆 `routing_reason` 7px 텍스트 표시.
    - 실행 중(running) 상태에서만 표시하여 노이즈 최소화.

## [2026-03-05] - v3.7.7 (메시지 채널 실시간 자동 협업 구현)

### 🤝 에이전트 실시간 협업
- **[Feature] hive_bridge.py — Phase 1/2 실시간 협업 기능 추가**:
    - `_post_message()`: messages.jsonl 직접 기록 헬퍼 (서버 미실행 시에도 동작).
    - `log_task()` 호출 시 heartbeat 메시지를 messages.jsonl에 자동 기록 (Phase 1).
    - `lock_file(agent, file)`: 파일 수정 시작 시 LOCK 메시지 기록.
    - `unlock_file(agent, file)`: 파일 수정 완료 시 UNLOCK 메시지 기록.
    - `check_conflict(file, my_agent)`: 최근 20줄 LOCK 탐지 → 충돌 에이전트명 반환 (Phase 2).
- **[Feature] skill_orchestrator.py — Phase 3 실시간 리포팅**:
    - `_broadcast_status()`: messages.jsonl에 스킬 상태 메시지 자동 게시.
    - `cmd_plan()` 실행 시 체인 계획을 메시지 채널에 브로드캐스트.
    - `cmd_update()` 실행 시 "XX 에이전트가 현재 [스킬] 작업 중" 자동 게시.
- **[Update] vibe-orchestrate.md — 충돌 감지 + LOCK/UNLOCK 절차 통합**:
    - 0단계: `check_conflict()` 호출로 충돌 사전 감지.
    - 3단계: 파일 수정 전 `lock_file()`, 완료 후 `unlock_file()` 지시 추가.

## [2026-03-05] - v3.7.6 (터미널 파일뷰어 → 에이전트 모니터링 뷰 교체)

### 🎯 자율 에이전트 모니터링 뷰
- **[Feature] TerminalSlot.tsx — 파일뷰어 완전 제거, 모니터링 뷰 신규 구현**:
    - `👀 파일 뷰어` 버튼 → `📡 모니터링` 버튼으로 교체 (같은 토글 자리).
    - 모니터링 뷰 표시 항목: 에이전트 상태(RUNNING/WORKING/IDLE) + 현재 태스크 + 최근 메시지 + 최근 로그 5줄.
    - 에이전트 상태 자동 계산: 최근 30초 내 로그 → RUNNING, in_progress 태스크 → WORKING, 그 외 → IDLE.
    - 기존 props(`logs`, `tasks`, `messages`) 100% 재활용 — 추가 API 호출 없음.
    - 파일 fetch 로직(3초 인터벌), `VibeEditor` import, `getFileIcon` import, `API_BASE` import 전면 삭제.

## [2026-03-01] - v3.6.7 (업데이터 에셋 탐색 버그 수정 + 포트 충돌 방지)

### 🐛 버그 수정
- **[Fix] updater.py 에셋 이름 불일치 수정**:
    - GitHub 릴리스 에셋명이 `vibe-coding-v*.exe` 형태일 때도 탐지 가능하도록 패턴 매칭 추가.
    - 탐색 우선순위: `vibe-coding.exe` (정확 일치) → `vibe-coding-v*.exe` → `vibe-coding*.exe` (setup 제외).
    - `browser_download_url` 사용으로 Public 리포에서 인증 없이 직접 다운로드 가능.
- **[Fix] server.py HTTP/WebSocket 포트 충돌 방지**:
    - `WS_PORT`를 `_find_free_port(9572)` 고정 → `_find_free_port(HTTP_PORT + 1)`로 변경.
    - 9571이 사용 중일 때 HTTP와 WS가 동일 포트(9572)로 충돌하는 버그 수정.
- **[Fix] server.py do_POST 내 불필요한 `import shutil` 제거** (ruff F823).

## [2026-03-01] - v3.6.6 (AI 오케스트레이터 통합)

### 🎯 AI 오케스트레이터 A안 + B안 통합 구현
- **[Feature] vibe-orchestrate 마스터 스킬**:
    - 요청 분석 → 최적 스킬 체인 자동 수립 → 순서대로 실행.
    - 카테고리별 체인 매핑: 버그→(debug→tdd), 기능→(brainstorm→write-plan→execute), 배포→(release).
    - `skill_orchestrator.py`와 연동하여 실행 상태 JSON 영속화.
- **[Feature] skill_orchestrator.py 신규 생성**:
    - `plan / update / done / reset` CLI 커맨드로 스킬 체인 상태 추적.
    - `DATA_DIR/skill_chain.json`에 세션 단위로 저장.
- **[Feature] 스킬 체인 대시보드 위젯**:
    - 3초 폴링으로 `[vibe-debug ✅] → [vibe-tdd 🔄] → [vibe-release ⏳]` 형식 실시간 표시.
    - `GET /api/orchestrator/skill-chain`, `POST /api/orchestrator/skill-chain/update` 엔드포인트 추가.
- **[Update] hive_hook.py 복합 요청 자동 감지**:
    - 2개 이상 인텐트 동시 매칭 시 `orchestrate` 인텐트로 자동 전환.
    - orchestrate 키워드: 자동으로, 전부, 전체, 다 해줘, 알아서, 하고, 그리고, 등.

## [2026-03-01] - v3.6.5 (하이브 시스템 통합 및 대시보드 UI 최종 정리)

### 📊 하이브 시스템 및 대시보드 고도화
- **[Feature] 업데이트 확인 버튼 복원 및 API 연동**:
    - 대시보드 헤더에 '업데이트 확인' 버튼 상시 노출.
    - `/api/trigger-update-check` API 호출 및 5초 간격 폴링 로직 구현.
- **[UI/UX] 헤더 UI 정리**:
    - 중복 표시되던 폴더 경로(`currentPath`) 및 불필요한 아이콘 제거로 깔끔한 레이아웃 확보.
- **[Build] v3.6.3 정식 빌드 완료**:
    - 최신 프론트엔드 빌드(`dist`) 포함.
    - PyInstaller를 이용한 `vibe-coding.exe` 단일 실행 파일 생성.
- **[Documentation] 하이브 지침 동기화**:
    - `PROJECT_MAP.md`, `CLAUDE.md`, `GEMINI.md` 등 핵심 가이드 문서 최신화.
    - `ai_monitor_plan.md`를 통한 통합 작업 로드맵 관리 시작.

## [2026-03-01] - v3.6.0 (VS Code 스타일 사이드바 UI 완벽 복원)

### 📂 사이드바 UI/UX 혁신
- **[Restore] 호버 액션 버튼 그룹 도입 (VS Code 스타일)**:
    - 사이드바의 **트리 뷰**와 **플랫 뷰** 모두에서 파일/폴더 호버 시 우측에 액션 버튼 그룹이 나타납니다.
    - **경로 복사**, **이름 변경**, **삭제** 버튼이 일관되게 배치되었습니다.
    - 폴더 항목 호버 시 **새 파일**, **새 폴더** 아이콘이 추가로 노출되어 빠른 작업이 가능합니다.
- **[New] 인라인 이름 변경(Inline Rename) 구현**:
    - 이름 변경 클릭 시 VS Code와 동일하게 파일명 부분이 즉시 편집 가능한 `input` 박스로 전환됩니다.
    - `Enter` 키로 확정, `Esc` 키로 취소가 가능하여 기존 `prompt` 방식보다 훨씬 쾌적한 UX를 제공합니다.
- **[Update] 컨텍스트 메뉴 항목 확장**:
    - 우클릭 메뉴에 **경로 복사** 및 **이름 변경** 항목을 추가하여 마우스만으로 모든 파일 제어가 가능해졌습니다.

## [2026-02-27] - v3.5.7 (벡터 DB 제거)

### 🗑️ 의존성 제거
- **[Remove] ChromaDB(벡터 DB) 완전 제거**:
    - `scripts/vector_memory.py` 삭제
    - `server.py`에서 `migrate_sqlite_to_vector()`, `/api/vector/list`, `/api/vector/search` 엔드포인트 및 모든 Vector DB 동기화 블록 제거
    - `scripts/memory.py`에서 VectorMemory import 블록 제거
    - `ThoughtTrace.tsx`에서 벡터 메모리 검색 탭(🔍 메모리) 제거 — 사고 추적 전용으로 단순화
    - `.ai_monitor/data/vector_db/` 데이터 디렉토리는 서버 종료 후 수동 삭제 필요

## [2026-02-27] - v3.5.6 (컨텍스트 메뉴 UX 정밀 개선)

### 📂 파일 및 작업 관리 UX 고도화
- **[Fix] 컨텍스트 메뉴 '삭제' 아이콘 통일**:
    - 파일 탐색기 내 호버 삭제 버튼과 우클릭 메뉴 내 삭제 항목의 아이콘을 `Trash2`로 통일하여 시각적 일관성 확보.
- **[New] 작업(Task) 컨텍스트 메뉴 추가**:
    - 이제 왼쪽 작업 목록 패널에서도 각 작업 항목을 마우스 우클릭하여 즉시 '시작', '완료', '삭제' 처리를 할 수 있습니다.
- **[UX] 메뉴 레이아웃 최적화**:
    - 화면 하단에서 우클릭 시 메뉴가 잘리지 않도록 위치 계산 로직을 개선하고, 애니메이션 효과를 추가하여 더 부드러운 사용자 경험을 제공합니다.

## [2026-02-27] - v3.5.5 (파일 탐색기 컨텍스트 메뉴 및 이름 변경 기능)

### 📂 파일 관리 UX 개선
- **[New] 다크 네온 컨텍스트 메뉴**:
    - 파일 탐색기 아이템에서 마우스 우클릭 시 나타나는 전용 메뉴 UI 구현.
    - 네온 블루 하이라이트 효과가 적용된 다크 테마 디자인.
- **[Feature] 인라인 이름 변경(Rename)**:
    - 별도 팝업 없이 탐색기 내에서 즉시 파일/폴더 이름을 수정할 수 있는 기능 추가.
- **[Feature] 파일 관리 단축 기능**:
    - 삭제(Confirm 포함), 전체 경로 복사, 탐색기에서 보기 기능 통합.
- **[AI Integration] 에이전트 분석 요청**:
    - 특정 파일에 대해 Gemini/Claude에게 즉시 분석을 요청할 수 있는 컨텍스트 메뉴 항목 추가.

## [2026-02-27] - v3.5.3 (자동 릴리즈 및 업데이트 시스템 도입)

### 🚀 배포 자동화 (Auto-Pilot)
- **[New] 자동 버전 관리**: `scripts/auto_version.py`를 통해 빌드 시 버전 번호를 자동으로 증가시키는 체계 도입.
- **[New] GitHub Actions 연동**: 푸시(Push) 시 GitHub 서버에서 실행 파일(.exe)과 설치 파일(Setup.exe)을 자동으로 빌드하고 배포하도록 워크플로우 고도화.
- **[Feature] 실시간 업데이트 알림**: 다른 PC에서 실행 중인 앱이 새 버전을 감지하면 즉시 업데이트 안내를 띄우고 자동으로 교체하는 기능 완성.

## [2026-02-27] - v3.5.1 (하이브 통합 로그 익스플로러 추가)

### 📊 모니터링 GUI 강화
- **[New] 하이브 통합 로그 익스플로러**:
    - 대시보드 좌측 액티비티 바에 전용 로그 탭(아이콘: `ScrollText`) 추가.
    - `hive_mind.db` (SQLite)의 모든 에이전트 작업 로그를 실시간으로 스트리밍하여 표시.
    - **실시간 배지**: 새로운 로그가 기록될 때마다 탭 상단에 누적 로그 수 표시.
    - **강력한 필터링**: 에이전트 이름, 작업 내용, 프로젝트명으로 즉시 검색 가능.
    - **시각적 구분**: Gemini(파란색), Claude(초록색) 등 에이전트별 색상 태그 적용.
- **[Backend] API 확장**:
    - `/api/hive/logs` 엔드포인트 신설로 SQLite 통합 로그 데이터 제공 기반 마련.

## [2026-02-27] - v3.5.0 (배포 버전 안정화 및 경로 동기화)

### 🚀 배포 및 설치 버전 (Installer) 개선
- **[Bug Fix] 데이터 경로 동기화**: 
    - 설치 버전(`.exe`) 실행 시 공유 메모리(`memory.py`)와 벡터 DB(`vector_memory.py`)가 서버와 동일한 `%APPDATA%\VibeCoding` 폴더를 사용하도록 수정.
    - 이전 버전에서 설치 시 데이터 저장이 안 되거나 앱이 종료되던 문제 해결.
- **[Feature] 라이브러리 번들링 최적화**: 
    - PyInstaller(`.spec`) 설정에 `chromadb`, `pysqlite3`를 추가하여 배포 버전에서도 벡터 메모리 기능이 완벽하게 동작하도록 보강.
- **[Feature] 중앙 프로젝트 맵 생성**: 
    - 루트 디렉토리에 `PROJECT_MAP.md`를 신규 생성하여 전체 시스템 구조와 역할을 명시.

## [2026-02-26] - v3.4.0 (UI/UX 고도화 및 패널 리사이징)

### 레이아웃 및 UX 개선
- **[Feature] 패널 리사이징 시스템 도입**: 
    - 좌측 사이드바(Explorer)를 마우스로 자유롭게 조절 가능 (150px~800px).
    - 터미널 내 파일 뷰어 높이를 드래그로 조절 가능.
- **사이드바 최적화**: 기본 너비를 300px로 축소하여 메인 작업 영역 확보.
- **사고 과정 시각화(Thought Trace) 개선**: 우측 패널 접기/펴기 기능 추가 및 애니메이션 적용.

## [2026-02-26] - ThoughtTrace 벡터 메모리 검색 UI 추가 (v3.3.0)

## [2026-02-26] - 하이브 에볼루션 v4.0 (자가 치유 및 지식 자동화)

### 🛠️ 입력 시스템 및 UX 개선 (IME Fix)
- **[Bug Fix] 한글 IME 엔터 키 전송 해결**: `vibe-view` 대시보드 내 메시지 채널 및 터미널 입력창에서 한글 조합 중 엔터 키가 무시되던 현상 수정.
- **[Bug Fix] 글자 중복 입력 방지**: React 제어 컴포넌트와 IME 조합 간의 충돌로 인한 자음 중복 입력 현상 해결.
- **UI 개선**: 좌측 메시지 채널 패널의 입력 편의성 증대 및 전송 로직 안정화.

### 🛡️ 자가 치유 엔진 (Self-Healing)
- **[New] Hive Watchdog**: 24/7 시스템 감시 엔진(`hive_watchdog.py`) 구축. DB 무결성, 파일 동기화, 에이전트 활동을 주기적으로 체크하고 자동 복구 수행.
- **서버 통합**: `server.py` 백그라운드 스레드에서 워치독 가동 및 실시간 건강 상태 API(/api/hive/health) 연동.

### 🎨 지능형 지식 자동화 (Knowledge Automation)
- **[New] Skill Analyzer**: 최근 50개의 작업 로그를 분석하여 반복되는 패턴(Keyword)을 추출하는 엔진 구축.
- **스킬 승인 워크플로우**: 분석 결과를 바탕으로 대시보드에서 즉시 새로운 `SKILL.md` 초안을 생성하는 승인 프로세스 구현.

### 🌐 Vibe-View 대시보드 (Frontend)
- **건강 상태 HUD**: 하이브 진단 탭에서 DB 연결, 에이전트 활성도, 누적 복구 횟수를 실시간 시각화.
- **정밀 자가 치유**: 정밀 진단 및 강제 복구 버튼 추가로 시스템 관리 편의성 극대화.
- **지능형 스킬 제안**: 반복 작업 감지 시 UI 상단에 스킬 등록 제안 알림 및 목록 표시.

---

## [2026-02-25] - 에이전트 지능형 오케스트레이션 및 UI 고도화

### 🚀 하이브 마인드 엔진 (Backend)
- **[Bug Fix] DB 마이그레이션 오류 수정**: 서버 시작 시 `project` 컬럼 인덱스 생성 시점이 컬럼 추가보다 빨라 발생하는 `sqlite3.OperationalError` 해결.
- **문서화 전략 개편**: `docs/` 폴더 내 개별 파일 문서화를 중단하고, "코드 내 상세 주석 + `PROJECT_MAP.md` 중앙 관리" 체제로 전환.
- **에이전트 상태 관리**: `AGENT_STATUS` 전역 저장소 및 `/api/agents/heartbeat` API 추가. 에이전트 활동 실시간 모니터링 기반 마련.
- **Git 원격 제어 API**: 클릭 한 번으로 수정을 취소하는 `rollback` API와 변경사항을 조회하는 `diff` API 구현.

### 🌐 Vibe-View 대시보드 (Frontend)
- **실시간 HUD**: 상단 메뉴바에 현재 작업 중인 에이전트(Active) 상태를 깜빡이는 뱃지로 표시.
- **스킬 주입 안전장치**: `master`, `brainstorm` 스킬 사용 시 6단계 브레인스토밍 절차 이행 여부를 묻는 승인 팝업 추가.
- **원클릭 경로 주입 (Pinning)**: 파일 탐색기에서 📌 버튼 클릭 시 터미널 입력창에 해당 파일의 절대 경로를 자동 주입.
- **시각적 Diff 뷰어**: 터미널 위 파일 뷰어에서 변경된 코드를 빨간색/초록색으로 시각화하여 확인 가능.
- **원클릭 롤백**: Git 감시 탭에서 수정된 파일을 클릭 한 번으로 이전 상태로 되돌리는 UI 구현.

### 🧠 하이브 스킬 (Skills)
- **`master` 스킬 업그레이드**: 단순 관리를 넘어 TDD, 디버깅, 브레인스토밍 스킬을 상황에 맞게 호출하도록 오케스트레이션 로직 강화.
- **주석 규칙 표준화 (Mandatory)**: 모든 소스 코드 및 배포 스크립트에 적용할 **표준 헤더 템플릿** 도입. 파일 내 직접적인 변경 이력 기록을 통해 배포 버전에서도 설계 의도 파악이 가능하도록 개선.
- **`brainstorming` 스킬 신설**: 사용자 정의 6단계 브레인스토밍 절차(컨텍스트 파악 -> 질문 -> 제안 -> 설계 -> 승인 -> 계획)를 공식화.

---
**작업자:** Gemini (지능형 오케스트레이터)
