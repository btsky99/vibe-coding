## 하이브 동기화 프로토콜

### 상태 확인 원칙 (필수)
- **DB 우선**: 작업 이력/진행 상황 확인 시 PostgreSQL(`pg_logs`, `hive_tasks`, `agent_heartbeats`)을 **먼저** 조회
- **git log는 보조**: 커밋 내역 확인용으로만 사용. "어제 뭐 했지" 류 질문에 git log만 보고 답변 금지
- DB에 명령 실행/완료, 태스크 상태 변경, 에이전트 하트비트 등 세부 이력이 기록됨

### 작업 시작 전 (필수)
```bash
python scripts/memory.py list        # 공유 메모리 확인
python scripts/analyze_hive.py       # 하이브 상태 분석
cat ai_monitor_plan.md               # 현재 계획 확인
```

### 작업 완료 후 (필수)
```bash
python scripts/hive_bridge.py        # 로그 기록
python scripts/memory.py             # 지식 공유
```

### 에이전트 역할
- **Gemini**: 전체 설계 및 오케스트레이션
- **Claude**: 정밀 로직 구현 및 프론트엔드 최적화
- `hive_tasks` 테이블로 진행 상황 공유
