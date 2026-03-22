# Codex 터미널 에이전트 사용 설명서

> 하이브 마인드(Hive Mind)의 독립형 터미널 자율 에이전트

---

## 1. 개요

**코덱스(Codex)**는 제미나이(Gemini)나 클로드(Claude) 세션 없이도 일반 터미널(CMD, PowerShell, Bash)에서 직접 실행되는 독립형 에이전트입니다. 하이브 마인드의 일원으로서 다른 에이전트와 통신하며 태스크를 분담하거나 오케스트레이션에 참여합니다.

---

## 2. 설치 및 초기 설정

### 설치 스크립트 실행
```bash
python scripts/install_codex.py
```
- 내부적으로 `npm install -g @openai/codex`를 실행하고 설치 상태를 검증합니다.

### 사전 요구사항
- **Node.js**: npm을 통해 Codex CLI가 설치됩니다.
- **Python**: 터미널 에이전트 래퍼(`terminal_agent.py`) 실행에 필요합니다.

---

## 3. 실행 방법

### 자율 에이전트 모드 (REPL)
각 터미널을 독립된 에이전트로 식별하기 위해 `TERMINAL_ID`를 설정합니다.
```bash
# Windows (CMD)
set TERMINAL_ID=T1 && python scripts/terminal_agent.py

# Windows (PowerShell)
$env:TERMINAL_ID="T1"; python scripts/terminal_agent.py
```
- 실행 후 프롬프트에서 직접 명령어를 입력할 수 있습니다.
- 빈 줄을 입력하거나 `Ctrl+C`를 누르면 종료됩니다.

### 단발 실행 모드 (Non-interactive)
```bash
python scripts/terminal_agent.py "이 파일의 버그를 찾아줘" [auto|claude|gemini]
```
- 특정 에이전트(Claude 또는 Gemini)를 지정하여 작업을 위임할 수 있습니다.
- `auto` 모드에서는 지시 내용의 복잡도에 따라 자동으로 라우팅됩니다.

---

## 4. 하이브 마인드 협업 (ITCP)

코덱스 에이전트는 `scripts/itcp.py`를 통해 하이브의 다른 멤버들과 소통합니다.

### 주요 명령어
| 동작 | 명령어 예시 |
|------|------------|
| **메시지 전송** | `python scripts/itcp.py send codex gemini "분석 완료"` |
| **브로드캐스트** | `python scripts/itcp.py broadcast codex "모든 작업 종료"` |
| **메시지 확인** | `python scripts/itcp.py receive codex` |
| **이력 조회** | `python scripts/itcp.py history 10` |

---

## 5. 오케스트레이션 연동

코덱스 터미널에서 복잡한 설계나 계획이 필요한 작업을 입력하면, 시스템이 자동으로 **오케스트레이터(Orchestrator)**를 가동합니다.

- **판정 기준**: '설계', '계획', '아키텍처', '리뷰' 등의 키워드가 포함될 경우.
- **작업 흐름**: 지시 입력 → 오케스트레이터 라우팅 → 5단계 프로토콜 실행 → 결과 수신.

---

## 6. 고급 활용 및 팁

1. **병렬 작업**: 여러 터미널을 열고 각각 `TERMINAL_ID=T1`, `TERMINAL_ID=T2`로 설정하여 서로 다른 작업을 동시에 시킬 수 있습니다.
2. **실시간 모니터링**: 에이전트의 사고 과정과 출력은 `.ai_monitor/data/agent_live.jsonl`에 실시간으로 기록되며, 대시보드(Mission Control)에서 시각화됩니다.
3. **자동 라우팅**: 간단한 코드 수정은 클로드에게, 문서나 복잡한 분석은 제미나이에게 자동으로 할당되도록 설계되어 있습니다.
