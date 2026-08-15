---
title: LAN 브리지와 원격 실행 함정
type: 함정
sources:
  - .ai_monitor/api/agent_api.py:1133
  - .ai_monitor/api/lan_api.py:256
  - .ai_monitor/src/lan_sandbox.py:69
related: []
confidence: high
updated: 2026-08-15
---

# LAN 브리지와 원격 실행 함정

## 한 줄

여기 creationflags 누락 시 채팅 메시지 전송마다 shell=True cmd.exe 창이

> 코드 주석에서 자동 합성 (원료 3건 · 파일 3개 · 추출 7cbf195).
> 🔴 **여기를 고치기 전에** 원본 주석을 먼저 고칠 것 — 다음 빌드에 덮어써진다.

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
