<!--
FILE: .claude/skills/vibe-dispatcher/references/dispatcher-commands.md
DESCRIPTION: 멀티 LLM 디스패처 CLI 명령어 레퍼런스.
             모든 에이전트(Claude, Gemini, Codex)가 공통으로 참조하는 명령어 가이드.

REVISION HISTORY:
- 2026-03-19 Claude: 최초 작성 — skill-creator로 vibe-dispatcher 스킬 생성
-->

# 디스패처 CLI 명령어 레퍼런스

## 1. dispatch — 단일 태스크 분배

```bash
python scripts/auto_dispatcher.py dispatch "태스크 설명" [옵션]
```

| 옵션 | 설명 | 기본값 |
|------|------|--------|
| `--type TYPE` | 태스크 유형 강제 지정 (자동 감지 가능) | 자동 감지 |
| `--to AGENT` | 에이전트 강제 지정 (claude/gemini/codex) | 자동 선택 |
| `--priority PRIO` | 우선순위 (low/medium/high/critical) | medium |
| `--no-verify` | 크로스 검증 생략 | 검증 활성화 |

### 태스크 유형 (자동 감지 키워드)

| 유형 | 키워드 예시 |
|------|------------|
| `bug_fix` | 버그, 에러, 오류, 수정, fix, debug |
| `feature` | 기능, 추가, 구현, 만들어, implement |
| `security` | 보안, 취약점, OWASP, injection |
| `perf` | 성능, 최적화, 느림, performance |
| `frontend` | UI, 프론트, 화면, CSS, React |
| `refactor` | 리팩, 정리, 클린, clean |
| `test` | 테스트, TDD, assert, coverage |
| `docs` | 문서, README, 주석, comment |
| `research` | 조사, 검색, 분석, 트렌드 |
| `review` | 리뷰, 검토, 점검, audit |
| `architecture` | 아키텍처, 설계, 구조, design |

## 2. fan-out — 병렬 다중 분배

```bash
python scripts/auto_dispatcher.py fan-out "태스크1" "태스크2" "태스크3"
```

- 각 태스크를 독립적으로 최적 에이전트에 분배
- 동일 에이전트 과부하 방지 (부하 패널티 자동 적용)
- `--type TYPE` 옵션으로 전체 태스크에 동일 유형 적용 가능

## 3. verify — 크로스 검증 요청

```bash
python scripts/auto_dispatcher.py verify TASK_ID "결과 요약" --author claude
```

- 작성자 ≠ 검증자 강제 (자기 검증 불가)
- 검증 관점: 코드 정확성, 보안, 성능, 호환성

## 4. status — 현황 조회

```bash
python scripts/auto_dispatcher.py status
```

- 전체 디스패치 건수, 완료/검증 건수
- 에이전트별 현재 부하 (할당량/최대동시처리)
- 검증 대기 건수

## 5. score — 적합도 점수 미리보기

```bash
python scripts/auto_dispatcher.py score "태스크 설명" [--type TYPE]
```

- 실제 분배 없이 에이전트별 점수만 확인
- 어떤 에이전트가 선택될지 사전 확인 용도

## 에이전트 역량 프로필 요약

| 역량 | Claude (T1) | Gemini (T2) | Codex (T3) |
|------|------------|------------|-----------|
| code_review | **0.95** | 0.80 | 0.60 |
| security | **0.95** | 0.70 | 0.60 |
| precision_logic | 0.90 | 0.65 | **0.90** |
| debugging | **0.90** | 0.70 | 0.80 |
| research | 0.30 | **0.95** | 0.20 |
| architecture | 0.70 | **0.90** | 0.50 |
| documentation | 0.80 | **0.90** | 0.50 |
| testing | 0.85 | 0.65 | **0.90** |
| refactoring | 0.85 | 0.70 | **0.85** |
| frontend | 0.80 | 0.75 | 0.70 |

## 전달 채널

디스패치 시 2가지 채널로 동시 전달:

1. **MUX (Named Pipe)** — 즉시 전달. `vibe_mux.py` 서버가 실행 중일 때 사용.
2. **ITCP (PostgreSQL)** — 비동기 큐. 에이전트의 다음 `UserPromptSubmit` 훅에서 수신.

MUX 서버 미실행 시 ITCP만으로 폴백. MUX 성공 시에도 ITCP는 히스토리 기록용으로 병행 전송.
