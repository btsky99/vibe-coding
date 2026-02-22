# 📜 프로젝트 하이브 마인드 지침 (Project Constitution)

이 프로젝트는 **Gemini-1/2**와 **Claude-1/2**가 협업하는 **하이브 마인드(Hive Mind)** 체제로 운영됩니다. 모든 AI 에이전트는 이 파일의 지침을 최우선으로 준수해야 합니다.

## 🤖 기본 행동 원칙
1. **마스터 워크플로우 우선**: 모든 작업은 `.gemini/skills/master/SKILL.md`의 지침을 따릅니다.
2. **하이브 동기화**: 모든 작업의 시작과 끝에는 반드시 `scripts/hive_bridge.py`를 호출하여 로그를 남겨야 합니다.
3. **상태 확인**: 작업 시작 전 반드시 `.ai_monitor/data/task_logs.jsonl`을 읽어 다른 에이전트의 상태를 확인하세요.

## 📡 에이전트 역할
- **Gemini**: 전체 설계, 워크플로우 조율, 데이터 및 ML 분석 담당.
- **Claude**: 정밀 프론트엔드(React/Tailwind) 구현 및 세부 로직 최적화 담당.

## 📂 핵심 참조 파일
- **작업 계획**: `ai_monitor_plan.md`
- **전문 지식**: `.gemini/skills/master/references/` 폴더 내 모든 가이드 참고
