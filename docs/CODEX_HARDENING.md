<!--
FILE: docs/CODEX_HARDENING.md
DESCRIPTION: Codex 경로 고도화 적용 내용과 다른 Windows PC 배포 조건을 정리한 운영 문서.

REVISION HISTORY:
- 2026-03-22 Codex: Codex 컨텍스트 부트스트랩, 디스패처 가드레일, 후행 검증 루프 문서화 추가.
-->

# Codex 고도화 적용 가이드

## 1. 이번에 바뀐 점

이번 변경은 `Codex` 자체를 교체한 것이 아니라, 이 저장소에서 `Codex`를 호출하는 방식에 가드레일을 추가한 것입니다.

- `Codex` 실행 전 `RULES.md`, `PROJECT_MAP.md`, `memory.md`, 하이브 요약 정보를 프롬프트에 함께 주입합니다.
- `Codex`가 `review`, `security`, `architecture`, `research`, `docs` 같은 고문맥 작업에 자동 배정되지 않도록 제한합니다.
- `Codex`가 수정 대상으로 보이는 파일을 추출하면 파일 락을 먼저 시도합니다.
- `Codex` 실행 후 `rules_validator.py`와 기본 문법 검증을 자동 수행합니다.
- 프론트엔드 경로가 포함되면 `npm run lint`, `npm run build`까지 후행 검증에 포함합니다.

## 2. 다른 PC에서도 바로 적용 가능한가

같은 저장소 내용을 pull 받은 **다른 Windows PC**라면 대부분 바로 적용 가능합니다.
다만 아래 조건은 맞아야 합니다.

- Python 실행 가능
- Node.js / npm 설치됨
- `codex` CLI 설치됨
- 이 저장소 루트에서 스크립트를 실행함
- `.ai_monitor` 및 `scripts/` 구조가 현재와 동일함

즉, 별도 "윈도우 전용 새 버전" 설치가 필요한 것이 아니라, **이 저장소 변경분을 가져오면 적용**됩니다.

## 3. 바로 적용 확인 방법

```powershell
codex --version
python -m py_compile scripts\itcp.py scripts\cli_agent.py scripts\auto_dispatcher.py
pytest tests\test_itcp_context.py tests\test_dispatcher_loop.py
```

정상 기준:

- `codex --version` 이 출력됨
- `py_compile` 에러 없음
- 테스트 통과

## 4. 현재 적용 범위

이번 변경은 아래 경로에 반영되었습니다.

- `scripts/itcp.py`
- `scripts/cli_agent.py`
- `scripts/auto_dispatcher.py`
- `tests/test_itcp_context.py`
- `tests/test_dispatcher_loop.py`

## 5. 운영 권장 방식

`Codex`는 다음 용도로 쓰는 것이 안전합니다.

- 좁은 범위 버그 수정
- 테스트 코드 작성
- 국소 리팩터링
- 지정 파일 기준 검증성 작업

아래 작업은 기본적으로 `Claude` 또는 `Gemini` 우선이 맞습니다.

- 프로젝트 방향 결정
- 아키텍처 설계
- 광범위 리뷰
- 보안 감사
- 조사/리서치 중심 작업

## 6. 알려진 한계

- 이 저장소 전체는 여전히 Windows 운영 흐름에 강하게 맞춰져 있습니다.
- `Codex`가 파일 경로를 프롬프트에 명시적으로 받지 못하면 파일 락과 후행 검증 범위가 줄어듭니다.
- `rules_validator.py` 자체는 규칙 검사 중심이며, 도메인별 테스트까지 모두 대체하지는 않습니다.

## 7. 추천 배포 방식

다른 PC에 적용할 때는 아래 순서를 권장합니다.

1. 저장소 최신 변경 pull
2. `codex --version` 확인
3. Python / npm 의존성 확인
4. 위 검증 명령 실행
5. 실제로는 작은 `Codex` 작업부터 시범 운영
