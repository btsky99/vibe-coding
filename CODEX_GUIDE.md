# 🤖 Vibe Coding: 코덱스(Codex) 에이전트 가이드

**코덱스(Codex)**는 하이브 마인드의 독립형 터미널 에이전트입니다. 제미나이나 클로드 세션 없이도 일반 터미널에서 직접 실행되며, 특정 작업을 위임받아 수행하는 데 최적화되어 있습니다.

- **공통 하네스 계약**: [docs/HARNESS_V2.md](./docs/HARNESS_V2.md)

---

## 🚀 퀵 스타트 (3초 실행)

가장 빠른 실행 방법은 `vibe` 명령어를 사용하는 것입니다.

```bash
# 코덱스 상태 확인
python scripts/vibe_cli.py codex status

# 코덱스 에이전트 실행 (ID: T1)
python scripts/vibe_cli.py codex start --id T1
```

---

## 🛠️ 설치 및 설정

코덱스를 처음 사용한다면 설치 스크립트를 먼저 실행하세요.

```bash
python scripts/install_codex.py
```
- **요구사항**: Node.js (v18 이상 권장), Python 3.10 이상

---

## 💻 주요 명령어 (vibe codex)

강화된 `vibe_cli.py`를 통해 코덱스를 제어할 수 있습니다.

| 명령어 | 설명 |
| :--- | :--- |
| `vibe codex status` | 설치 상태 및 활성 터미널 확인 |
| `vibe codex start --id [ID]` | 특정 ID(T1, T2...)로 코덱스 실행 |
| `vibe codex msg --to [에이전트] --text "[메시지]"` | ITCP 메시지 전송 |
| `vibe codex guide` | 이 도움말을 터미널에 출력 |

> **팁**: `python scripts/vibe_cli.py` 대신 `vibe` 별칭(Alias)을 설정하면 더 편리합니다.

---

## 🐝 하이브 협업 (ITCP)

코덱스는 다른 에이전트(Claude, Gemini)와 대화할 수 있습니다.

- **메시지 보내기**: 코덱스 터미널에서 `itcp send gemini "파일 분석 완료"` 입력
- **메시지 받기**: `itcp receive`를 통해 나에게 온 지시 확인
- **자동 오케스트레이션**: 복잡한 태스크를 입력하면 시스템이 자동으로 클로드나 제미나이에게 도움을 요청합니다.

---

## 💡 고급 활용

1. **멀티 터미널**: 여러 개의 터미널을 열고 `T1`, `T2`, `T3`로 각각 실행하여 병렬 작업을 수행할 수 있습니다.
2. **백그라운드 실행**: `vibe codex start --id T3 --bg` (준비 중)
3. **상태 모니터링**: 에이전트의 사고 과정은 Mission Control UI의 'Agent Live' 패널에서 실시간으로 확인할 수 있습니다.

---
**문서 버전:** v1.0.0 (2026-03-22)
