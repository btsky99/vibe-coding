<!--
FILE: docs/HARNESS_CHECKS.md
DESCRIPTION: harness_verify.py V2에서 수행하는 검사 항목 명세와 대응 방안.

REVISION HISTORY:
- 2026-03-29 Codex: 최초 작성 — V1 검사 5개
- 2026-03-30 Claude: V2 업그레이드 — 검사 10개로 확장
-->

# Harness V2 Checks Specification

`scripts/harness_verify.py`에서 수행하는 주요 검사 항목과 대응 방안입니다.

## V1 검사 (구조적 무결성)

| # | 검사 ID | 설명 | 실패 시 대응 |
|---|---------|------|--------------|
| 1 | `required-doc-missing` | 필수 문서 누락 | 문서를 생성하거나 PROJECT_MAP을 갱신한다. |
| 2 | `agents-too-long` | `AGENTS.md`가 120줄 초과 | 내용을 요약하거나 하위 문서로 분리한다. |
| 3 | `agents-link-missing` | 필수 참조 링크 누락 | `AGENTS.md`에 해당 문서 링크를 추가한다. |
| 4 | `guide-link-missing` | 에이전트 가이드 내 필수 링크 누락 | 해당 가이드에 링크를 추가한다. |
| 5 | `runtime-path-missing` | 핵심 런타임 스크립트 누락 | 파일 복구 또는 경로 설정을 확인한다. |
| 6 | `hot-file-large` | 주요 파일 크기 초과 (경고) | 파일을 모듈화하여 분리한다. |

## V2 검사 (하네스 품질)

| # | 검사 ID | 설명 | 실패 시 대응 |
|---|---------|------|--------------|
| 7 | `feature-list-missing` | `feature_list.json` 부재 | 파일을 생성한다. 스키마는 HARNESS_V2.md 참고. |
| 8 | `feature-list-schema` | 스키마 위반 (필수 필드 누락 등) | 누락된 필드를 추가하고 값을 채운다. |
| 9 | `progress-stale` | `progress.md` 3일 이상 미갱신 | 현재 상태로 progress.md를 업데이트한다. |
| 10 | `self-eval-detected` | Generator=Evaluator 동일 (경고) | 다른 에이전트를 Evaluator로 지정한다. |
| 11 | `contract-missing` | P0/P1 활성 작업에 스프린트 계약 없음 (경고) | `sprint_contracts/` 에 계약 파일을 작성한다. |

## 수동 검증 방법

```bash
# 일반 모드 — 텍스트 출력
python scripts/harness_verify.py

# CI 모드 — 에러 시 exit 1
python scripts/harness_verify.py --ci

# JSON 모드 — 대시보드 연동용
python scripts/harness_verify.py --json
```

모든 에이전트는 작업 완료 전 이 명령어를 실행하여 하네스 상태가 `ok`인지 확인해야 합니다.

## 에이전트별 필수 실행 시점

| 시점 | Claude | Gemini | Codex |
|------|--------|--------|-------|
| 세션 시작 | 자동 (훅) | 수동 | 수동 |
| 커밋 전 | 권장 | 권장 | 권장 |
| PR 생성 전 | **필수** | **필수** | **필수** |
| 스프린트 완료 | **필수** | **필수** | **필수** |
