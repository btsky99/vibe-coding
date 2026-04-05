## 하이브 동기화 절차 (Gemini)

Gemini는 하이브의 **오케스트레이터**로서, 작업 전후에 다른 에이전트와의 동기화를 주도합니다.

### 1. 작업 시작 전 (Mandatory)
Gemini는 다음 명령을 통해 하이브의 최신 상태를 로드해야 합니다.
```powershell
python scripts/analyze_hive.py       # 실시간 하이브 상태 분석
python scripts/memory.py list        # 공유 지식(memory.md) 확인
cat ai_monitor_plan.md               # 현재 계획 및 진행 상황 확인
check_new_messages                   # MCP groupchat 확인
```

### 2. 작업 완료 후 (Mandatory)
작업 결과를 공유하고 다음 에이전트(예: Claude)에게 인계합니다.
```powershell
python scripts/hive_bridge.py        # 작업 로그 PostgreSQL 기록
python scripts/memory.py add "내용"  # 새로 발견된 지식 공유
send_group_message "작업 완료..."    # 그룹챗을 통한 결과 공유
```

### 에이전트 역할 분담
- **Gemini (Orchestrator)**: 전체 설계, 워크플로우 조율, 데이터 분석, 인프라 및 자동화 스크립트.
- **Claude (Implementer)**: 정밀 로직 구현, 프론트엔드(React) 최적화, 세부 버그 수정.
- **Codex (Worker)**: 단순 반복 작업, 대량 파일 수정, 유틸리티 함수 작성.
- `hive_tasks` 테이블을 통해 상호 태스크를 감시하고 충돌을 방지합니다.
