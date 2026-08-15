---
title: LAN 브리지와 원격 실행 함정
type: 함정
sources:
  - .ai_monitor/api/agent_api.py:1133
  - .ai_monitor/api/lan_api.py:256
  - .ai_monitor/src/lan_sandbox.py:69
  - incident_ledger  # 사고 7건
related: []
confidence: high
updated: 2026-08-15
---

# LAN 브리지와 원격 실행 함정

## 한 줄

여기 creationflags 누락 시 채팅 메시지 전송마다 shell=True cmd.exe 창이

> 자동 합성 (코드 주석 3건 · 파일 3개 · 사고 장부 7건 · 추출 b28ef16).
> 🔴 **여기를 고치기 전에** 원본(주석 또는 사고 장부)을 먼저 고칠 것 — 다음 빌드에 덮어써진다.

## 🔴 밟았던 것 (사고 장부)

### 텔레그램 그룹방이 쓸모없음 — T1~T8 봇끼리 대화하는 방 구축 실패

- **원인** — ①텔레그램 원천 제약: 봇은 다른 봇 메시지를 볼 수 없음(공식 FAQ 'bots will not be able to see messages from other bots regardless of mode') → 봇 간 대화는 구현 불가 ②telegram_config_post가 TELEGRAM_ 접두 라인을 전부 버리고 TELEGRAM_BOT_T1~T8만 복원해 저장 시마다 GROUP_CHAT_ID 소멸 → send_to_group이 가드에 걸려 조용히 무동작 ③_safe_send가 _truncate만 태워 4000자 초과분 유실
- **수정** — 봇 간 대화 대신 ITCP(PostgreSQL)를 대화 버스로 두고 텔레그램은 미러링 창으로 역할 분리. .env 재작성을 순수함수 rewrite_env_telegram_tokens로 분리하고 제거 대상을 TELEGRAM_BOT_T*로 축소(멱등 보장). _split_message 신설로 유실 0, 초장문은 .txt 첨부. 임시파일 newline=''로 CRLF 손상 방지. 커밋 8697adc
- 출처: `incident_ledger` · 최초 2026-07-23

### 텔레그램 봇에서 claude -p 호출 시 CPU 0%로 멈춰 277초 타임아웃 실패 (SSH로 직접 실행하면 9초 정상)

- **원인** — Node execFile로 백그라운드 실행 시 자식 프로세스의 stdin이 열린 채로 남아, claude가 -p로 프롬프트를 이미 받았음에도 추가 입력을 무한 대기. SSH 대화형 실행에서는 stdin이 TTY/EOF라 재현되지 않아 진단이 늦어짐
- **수정** — execFile 반환 child의 stdin.end()를 즉시 호출해 EOF 전달 (apis_bot.js runClaude). 277초→9초. 부수 수정: nohup 리다이렉트와 console.log 중복으로 로그가 2줄씩 찍혀 프로세스 중복으로 오진할 뻔한 것도 console.log 제거로 해결
- 출처: `incident_ledger` · 최초 2026-07-25

### APIS 텔레그램 봇에서 인터넷 검색(WebSearch) 사용 불가

- **원인** — 탭에 ~/.claude/settings.json이 없어 도구 권한 화이트리스트가 부재. claude -p는 비대화형이라 권한 승인 UI를 못 띄워 미승인 도구가 조용히 거부됨 (Claude requested permissions to use WebSearch, but you havent granted it yet)
- **수정** — 탭 ~/.claude/settings.json 생성 — permissions.allow에 WebSearch/WebFetch/Bash/Write/Edit 등 명시, deny에 rm -rf ~ / claude logout / pkg uninstall 가드. 봇 코드 대신 설정파일을 고른 이유는 SSH 직접 실행·cron 경로에도 동일 적용되기 때문
- 출처: `incident_ledger` · 최초 2026-07-26

### 원격 터미널 분기를 넣었는데 로컬 cmd.exe가 뜸

- **원인** — pty-server.js에 셸 선택 코드가 두 벌 있었고 그중 handlePtyConnectionLegacy는 호출부가 없는 죽은 함수. 살아있는 핸들러는 handlePersistentPtyConnection(WS 연결부에서 이것만 호출)
- **수정** — 죽은 함수 313줄 삭제 + 원격 분기를 handlePersistentPtyConnection에 적용. 수정 전 grep으로 실제 호출부를 먼저 확인할 것
- 출처: `incident_ledger` · 최초 2026-07-29

### PTY Init Error: File not found: (원격 ssh spawn 실패)

- **원인** — node-pty는 PATH 탐색을 하지 않는다. pty.spawn('ssh', ...)처럼 실행파일 이름만 넘기면 즉사한다. 셸을 경유하지 않는 spawn의 대가
- **수정** — PATH를 직접 훑어 절대경로를 해석한 뒤 넘긴다 (remote_hosts.resolveSshPath)
- 출처: `incident_ledger` · 최초 2026-07-29

### E2E 테스트가 통과했는데 실제로는 기능이 동작 안 함

- **원인** — 판정 기준이 느슨했다. 원격 셸 검증에 'Microsoft Windows' 배너를 썼는데 로컬 cmd도 같은 배너를 출력해 거짓 통과
- **수정** — 원격에서만 나오는 고유값(호스트명)으로 판정 + 로컬 유출 탐지 조건을 별도로 추가
- 출처: `incident_ledger` · 최초 2026-07-29

### LAN 원격실행이 수신 PC 프로젝트 루트를 무제한 편집 가능 (샌드박스 부재)

- **원인** — lan_api._run_remote_exec가 yolo=True(--dangerously-skip-permissions) + cwd=_project_root로 claude 실행. 3중 게이트(페어링/토글/승인팝업)는 '누가 요청하나'만 막고 승인 후 '무엇을 건드리나'는 무제한. exec_trust=auto면 팝업도 없음. 폴더 지정 개념 자체가 없었음
- **수정** — src/lan_sandbox.py 신설 — 화이트리스트(resolve() 후 비교로 junction 탈출 차단) + 폴더별 copy/direct 모드 + yolo 제거 후 deny 프로파일 --settings 주입. copy는 git worktree 우선으로 .env 구조적 배제. exec 토큰 서명에 target_dir 포함(변조 차단). 회귀 21건
- 출처: `incident_ledger` · 최초 2026-07-30

## 코드에 박힌 지식

## `.ai_monitor/api/agent_api.py`

### _sse_send `[과거사고]`

stderr=DEVNULL로 변경 — stderr 버퍼 데드락 방지
(stderr가 꽉 차면 자식 프로세스가 block → stdout 읽기도 멈춤)
shell=True 필수 — Windows에서 claude.CMD 등 .cmd 파일은 cmd.exe 경유 필요
[과거사고] 여기 creationflags 누락 시 채팅 메시지 전송마다 shell=True cmd.exe 창이
번쩍였다(2026-07-19 발견). _proc.popen이 CREATE_NO_WINDOW를 자동 주입해 차단.

출처: `.ai_monitor/api/agent_api.py:1133`

## `.ai_monitor/api/lan_api.py`

### _run_remote_exec `[과거사고]`

[리뷰 C1] task를 -p 인자로 전달 + stdin=DEVNULL — handle_chat의 유일 검증된 claude 실행 패턴.
[과거사고] claude에 stdin=PIPE로 프롬프트를 주면 'stdin is not a terminal' 실패 이력이 있어
-p 인자 전달만이 이 코드베이스에서 검증됐다(claude-api 확인). 셸 메타문자 잔여 위험(보안 W1)은
승인 팝업(태스크 전문 표시)+yolo 전제상 handle_chat과 동일 수준으로 수용 — 임의 실행은 이미 승인됨.

출처: `.ai_monitor/api/lan_api.py:256`

## `.ai_monitor/src/lan_sandbox.py`

### materialize_settings `[과거사고]`

deny 프로파일을 실제 파일로 떨어뜨리고 절대경로를 반환.
[과거사고] 상대경로로 --settings를 넘기면 claude가 cwd 기준으로 해석해 settings 미발견 시
즉시 exit 1 (2026-07-17 스모크 실측). 반드시 resolve()된 절대경로를 넘긴다.

출처: `.ai_monitor/src/lan_sandbox.py:69`

## 확인법

```bash
python scripts/wiki_lint.py        # 이 페이지의 출처가 아직 살아 있는지
python scripts/wiki_build.py       # 원본 주석 변경분 재합성
```

<!-- tags: 과거사고 -->
