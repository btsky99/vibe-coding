## 하이브 동기화 프로토콜

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
