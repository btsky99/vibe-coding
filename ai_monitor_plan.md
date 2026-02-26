# 📜 하이브 에볼루션 (Hive Evolution) v4.0 구현 계획

이 계획은 시스템의 안정성(Self-Healing)과 지식 자동화(Skill Generation)를 목표로 합니다.

## 🛡️ 단계 1: 하이브 자가 치유(Self-Healing) 엔진

### [ ] Task 1: `scripts/hive_watchdog.py` 생성
- **파일**: `scripts/hive_watchdog.py`
- **방법**: 
    - DB 연결성, 파일 권한, 에이전트 활동 주기를 체크하는 독립 클래스 구현.
    - 이상 감지 시 `scripts/memory.py` 호출 또는 DB 인덱스 재구성 로직 포함.
- **검증**: `python scripts/hive_watchdog.py --check` 실행 시 상태 보고서 출력.
- **위험**: 감시 루프가 너무 빈번할 경우 디스크 I/O 부하 발생 가능 (30~60초 주기로 설정).

### [ ] Task 2: `server.py` 백그라운드 스레드 및 API 추가
- **파일**: `.ai_monitor/server.py`
- **방법**:
    - 서버 시작 시 `Watchdog` 스레드 가동.
    - `/api/health`, `/api/health/repair` 엔드포인트 구현.
- **검증**: `curl http://localhost:PORT/api/health` 호출 시 JSON 응답 확인.

### [ ] Task 3: 프론트엔드 자가 치유 대시보드 연동
- **파일**: `vibe-view/src/App.tsx`, `vibe-view/src/types.ts`
- **방법**:
    - `HiveHealth` 위젯에 상세 상태 UI 추가.
    - 자가 치유 로그를 실시간으로 보여주는 팝업/패널 구현.
- **검증**: UI에서 "Health" 클릭 시 상세 로그 및 복구 버튼 작동 확인.

---

## 🎨 단계 2: 지능형 스킬 자동 생성기 (Skill Auto-Generator)

### [ ] Task 4: `scripts/skill_analyzer.py` 생성
- **파일**: `scripts/skill_analyzer.py`
- **방법**:
    - `task_logs.jsonl`의 최근 50개 항목을 분석하여 반복되는 파일 수정 패턴 추출.
    - LLM(Gemini)에 분석 데이터를 전달하여 `SKILL.md` 초안 생성 요청 루틴 작성.
- **검증**: 특정 작업을 반복한 후 실행했을 때 초안 파일이 생성되는지 확인.

### [ ] Task 5: 스킬 승인 워크플로우 UI 구현
- **파일**: `vibe-view/src/App.tsx`
- **방법**:
    - "새로운 스킬 제안" 알림 UI 추가.
    - 마크다운 미리보기 및 저장 버튼 연동.
- **검증**: 제안된 스킬을 저장했을 때 `.gemini/skills/` 폴더에 정상 저장되는지 확인.

---

## 🔄 최종 자동화 및 동기화 (Hive Sync)
- 모든 작업 완료 후 `scripts/hive_bridge.py`를 통해 모든 에이전트에게 업데이트 전파.
- `PROJECT_MAP.md` 및 `CHANGELOG.md` 최신화.

---
**작성일**: 2026-02-26
**에이전트**: Gemini-1 (Master)
