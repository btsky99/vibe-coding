<!--
FILE: docs/DISCORD_SETUP.md
DESCRIPTION: Vibe Coding Discord 대시보드와 Gateway 환경 설정 계약.

REVISION HISTORY:
- 2026-08-03 Codex: Vibe View T1~T3 기본 토큰과 T4~T9 추가 저장 UI 문서화
- 2026-08-03 Codex: 웹훅, ACL, 터미널·그룹 binding 설정 최초 작성
- 2026-08-03 Codex: PC별 공용 봇 토큰 1개와 터미널별 채널 ID 저장 흐름으로 교정
-->

# Discord Setup

Discord는 단일 bot 연결을 사용한다. 터미널마다 bot token을 만들지 않고 채널 또는 스레드를
`node_id:terminal_id`에 연결한다. 기본 터미널은 T1~T3이고 필요하면 T9까지 확장한다.
여러 PC는 같은 bot token을 사용하되 각각 다른 `node_id`와 채널 ID를 저장한다.

## Discord 설정

1. Discord Developer Portal에서 application과 bot을 하나 만든다.
2. Bot 설정에서 Message Content Intent를 활성화한다.
3. 서버에 bot을 초대하고 대상 채널의 View Channel, Read Message History,
   Send Messages 권한만 허용한다.
4. 대시보드용 채널에는 webhook 하나를 만든다.
5. Vibe View 왼쪽 Discord 설정에 공용 bot token, 현재 PC의 Node ID, Discord 서버 ID,
   허용할 사용자 ID, T1~T3의 채널 ID를 입력한다. T4부터는 `추가` 버튼으로
   필요한 슬롯만 만든다. Windows 저장본은 현재 사용자 DPAPI로 암호화되며 API는
   토큰 원문을 반환하지 않는다.

저장 후 앱을 재시작하면 PC마다 Gateway 프로세스 하나가 시작되고 그 PC의 모든
터미널 binding을 처리한다. `DISCORD_BOT_TOKEN` 단일 환경변수 방식도 하위 호환으로 유지한다.

## 환경변수

민감값은 저장소 `.env`나 일반 설정 API에 저장하지 않고 프로세스 환경으로 주입한다.

```text
DISCORD_BOT_TOKEN=<bot token>
DISCORD_WEBHOOK_URL=<dashboard webhook URL>
DISCORD_GUILD_IDS=<허용 server ID, 쉼표 구분>
DISCORD_CHANNEL_IDS=<허용 channel ID, 쉼표 구분>
DISCORD_USER_IDS=<허용 user ID, 쉼표 구분>
VIBE_NODE_ID=desktop-a
```

터미널별 채널 binding:

```json
DISCORD_CHANNEL_BINDINGS={
  "111111111111111111": "T1",
  "222222222222222222": {
    "node_id": "desktop-a",
    "terminal_id": "T2",
    "project_id": "vibe-coding"
  }
}
```

그룹 채널 binding:

```json
DISCORD_GROUP_BINDINGS={
  "333333333333333333": {
    "project_id": "vibe-coding",
    "members": [
      {"node_id": "desktop-a", "terminal_id": "T1", "agent_type": "claude", "orchestrator": true},
      {"node_id": "desktop-a", "terminal_id": "T2", "agent_type": "codex"},
      {"node_id": "laptop-b", "terminal_id": "T1", "agent_type": "codex"}
    ]
  }
}
```

Windows 환경변수에 넣을 때 JSON은 한 줄로 전달한다.

## 그룹 라우팅

| 메시지 | 대상 |
|--------|------|
| `상태 알려줘` | room orchestrator |
| `@desktop-a:T2 테스트해줘` | 특정 PC·터미널 |
| `@codex 검토해줘` | Codex room member들 |
| `@all 상태 점검` | 전체 room member |

여러 터미널로 동시에 전달되는 요청은 현재 자동 실행하지 않고 승인 대기 안내를 반환한다.
단일 대상 요청만 PTY에 주입된다.

## 데이터와 보안

- 수신 이벤트는 `connector_events`에 먼저 기록하며 같은 Discord event ID는 재실행하지 않는다.
- 중복 키는 node별로 분리되어 다중 PC가 동일 그룹 이벤트를 안전하게 평가한다.
- bot·webhook이 보낸 메시지는 다시 입력으로 처리하지 않는다.
- PTY 출력은 ANSI를 제거하고 token/password/secret 형태의 값을 마스킹한다.
- Discord 연결 실패는 별도 daemon 프로세스에서 재시도하며 로컬 PTY를 종료하지 않는다.
