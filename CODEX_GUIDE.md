# Codex Guide

Codex는 터미널 작업, 테스트 작성, 반복 리팩터링, 검증 자동화를 담당한다.
이 문서는 짧은 진입점만 제공하고 상세 규칙은 분리 문서를 따른다.

## Read Order
- [RULES.md](./RULES.md)
- [docs/HARNESS_V2.md](./docs/HARNESS_V2.md)
- [PROJECT_MAP.md](./PROJECT_MAP.md)
- [ai_monitor_plan.md](./ai_monitor_plan.md)
- [.codex/rules/architecture.md](./.codex/rules/architecture.md)
- [.codex/rules/hive-sync.md](./.codex/rules/hive-sync.md)
- [.codex/rules/commit-rules.md](./.codex/rules/commit-rules.md)

## Core Principles
1. 작업 전 규칙, 계획, 관련 코드 경로를 먼저 읽는다.
2. 세부 설명을 이 파일에 복제하지 말고 source of truth로 이동한다.
3. 가능하면 git worktree에서 작업한다.
4. 에이전트 협업은 ITCP(`pg_messages`)를 우선 사용한다.
5. 변경 전후 최소 검증을 직접 실행한다.
6. 반복 실패는 문서, 테스트, 스크립트, lint로 고정한다.

## Build And Run
```bash
pip install -e .
python scripts/install_codex.py
python scripts/vibe_cli.py codex status
python scripts/vibe_cli.py codex start --id T1
python scripts/build_verify.py
pytest
```
