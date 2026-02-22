# 📡 Agent-to-Agent Communication Protocol (Hive Mind)

이 규약은 프로젝트 내의 모든 AI 에이전트(Gemini-1/2, Claude-1/2)가 협업할 때 반드시 준수해야 하는 표준입니다.

## 1. 에이전트 식별자 (ID)
작업 시 자신의 ID를 명확히 밝히고 로그를 남깁니다.
- **Gemini-1/2**: 주 설계 및 오케스트레이션 담당.
- **Claude-1/2**: 정밀 코딩 및 프론트엔드 최적화 담당.

## 2. 작업 시작 전: 상태 동기화 (Sync)
새로운 작업을 시작하기 전, 반드시 다음을 수행합니다.
1. `.ai_monitor/data/task_logs.jsonl` 파일을 읽어 다른 에이전트가 수행 중인 작업을 확인합니다.
2. 현재 수정하려는 파일에 '작업 중(Lock)' 로그가 있는지 확인하여 충돌을 방지합니다.

## 3. 작업 중: 실시간 로깅 (Heartbeat)
중요한 중간 단계가 완료될 때마다 `scripts/hive_bridge.py`를 호출하여 로그를 남깁니다.
- 예: `python scripts/hive_bridge.py "Claude-1" "Started refactoring App.tsx components"`

## 4. 작업 위임 및 인수도 (Handoff)
다른 에이전트에게 작업을 넘길 때는 다음과 같은 형식을 로그에 남깁니다.
- **포맷**: `[DELEGATE TO {Target}] {Task Description} {Branch/File Info}`
- 예: `python scripts/hive_bridge.py "Gemini-1" "DELEGATE TO Claude-2: Please style the new login button in index.css"`

## 5. 충돌 해결 (Conflict Resolution)
동일한 파일을 수정해야 할 경우:
1. 먼저 작업 중인 에이전트의 완료 로그가 올라올 때까지 대기합니다.
2. 또는 각자 다른 브랜치(`feat/agent-name-...`)에서 작업 후 `master` 에이전트에게 병합을 요청합니다.
