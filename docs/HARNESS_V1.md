# 🛡️ Vibe Coding Harness V1 (Deprecated → V2)

> **이 문서는 V2로 대체되었습니다.** 최신 하네스 명세는 [HARNESS_V2.md](./HARNESS_V2.md)를 참고하세요.

이 문서는 AI 에이전트(Claude, Gemini, Codex)가 효율적으로 작동하기 위한 최적화된 환경(Harness)의 명세입니다.

## 🎯 핵심 원칙 (Harness Principles)
1. **지도를 주고 매뉴얼을 주지 마라**: `PROJECT_MAP.md`를 최우선으로 참고하여 시스템 구조를 파악한다.
2. **불변식을 강제하라**: `scripts/harness_verify.py`가 정의하는 제약 조건(파일 크기, 필수 문서 등)을 준수한다.
3. **격리된 작업 (Git Worktrees)**: 메인 브랜치 오염을 방지하기 위해 항상 워크트리에서 작업한다.

## 🏗️ 하네스 구조
- **컨텍스트 하네스**: `AGENTS.md`, `PROJECT_MAP.md`, `RULES.md`
- **검증 하네스**: `scripts/harness_verify.py`, `plan_validator.py`
- **실행 하네스**: `scripts/auto_dispatcher.py`, `itcp.py`

## 🚫 금지 사항
- `server.py`의 5000줄 초과 수정 금지 (분리 권장)
- `RULES.md`에 명시되지 않은 에이전트 행동 지침 임의 수정 금지
