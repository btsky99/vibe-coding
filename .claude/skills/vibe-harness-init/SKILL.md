<!--
FILE: .claude/skills/vibe-harness-init/SKILL.md
DESCRIPTION: 하네스 V2를 새 프로젝트에 자동 설치하는 스킬.
             /vibe-harness-init 명령으로 호출. 프로젝트에 맞게 커스터마이즈된 하네스 구조를 생성.

REVISION HISTORY:
- 2026-03-30 Claude: 최초 생성 — 하네스 V2 설치 자동화 스킬
-->

# vibe-harness-init

**호출**: `/vibe-harness-init` 또는 "하네스 설치해줘", "하네스 세팅해줘"

새 프로젝트에 하네스 V2 환경을 자동으로 설치합니다.

---

## 이 스킬이 하는 일

현재 프로젝트 디렉토리를 분석하고, 아래 파일들을 **프로젝트에 맞게 커스터마이즈**하여 생성합니다.

### 생성되는 파일 목록

| 파일 | 역할 |
|------|------|
| `AGENTS.md` | 에이전트 구성 + 역할 정의 (짧은 진입점) |
| `RULES.md` | 공통 행동 규칙 (한글 주석, 커밋 메시지 등) |
| `docs/HARNESS_V2.md` | 하네스 V2 마스터 명세서 |
| `docs/HARNESS_CHECKS.md` | 검증 항목 + 대응 방안 |
| `feature_list.json` | 기능 목록 (프로젝트 분석 후 자동 생성) |
| `progress.md` | 진행 상황 추적 파일 |
| `scripts/harness_verify.py` | 하네스 V2 검증 스크립트 (10개 검사) |
| `scripts/session_init.py` | 세션 시작 프로토콜 실행기 |
| `.github/workflows/harness-check.yml` | CI 게이트 워크플로우 |

### 선택적 설치

| 파일 | 조건 |
|------|------|
| `scripts/itcp.py` | PostgreSQL 사용 시 |
| `scripts/auto_dispatcher.py` | 멀티 에이전트(3개+) 사용 시 |
| `CLAUDE.md` / `GEMINI.md` / `CODEX_GUIDE.md` | 해당 에이전트 사용 시 |

---

## 실행 절차 (5단계)

### Step 1: 프로젝트 분석

현재 디렉토리의 프로젝트 구조를 분석합니다:
- 언어/프레임워크 감지 (Python, Node.js, React 등)
- 기존 파일 구조 파악
- git 초기화 여부 확인
- 이미 하네스가 설치되어 있는지 확인

```bash
# 프로젝트 구조 확인
ls -la
git status
```

**이미 하네스가 있으면 (AGENTS.md 또는 feature_list.json 존재):**
→ "이미 설치됨" 경고 출력. 업그레이드할지 사용자에게 확인.

### Step 2: 사용자에게 확인

아래 질문을 사용자에게 물어보세요:
1. **에이전트 구성**: "어떤 에이전트를 사용하나요? (Claude만 / Claude+Gemini / Claude+Gemini+Codex)"
2. **PostgreSQL**: "PostgreSQL을 사용하나요? (하이브 통신용)"
3. **CI**: "GitHub Actions CI를 설정할까요?"

기본값: Claude만 / PostgreSQL 없음 / CI 설정함

### Step 3: 핵심 파일 생성

아래 파일들을 **프로젝트에 맞게 커스터마이즈**하여 생성합니다.
D:\vibe-coding 프로젝트의 파일을 템플릿으로 참고하되, 내용은 현재 프로젝트에 맞게 작성합니다.

#### 3-1. feature_list.json

프로젝트를 분석하여 주요 기능을 자동 감지하고 feature_list.json을 생성합니다.

```json
{
  "version": "2.0",
  "last_updated": "YYYY-MM-DD",
  "last_updated_by": "human",
  "features": [
    {
      "id": "F001",
      "category": "functional",
      "priority": "P0",
      "description": "(프로젝트 분석 후 자동 채움)",
      "acceptance_criteria": ["(구체적 검증 기준)"],
      "assigned_to": null,
      "evaluated_by": null,
      "passes": false
    }
  ]
}
```

#### 3-2. scripts/harness_verify.py

D:\vibe-coding\scripts\harness_verify.py를 복사하되:
- `REQUIRED_DOCS` 목록을 현재 프로젝트에 맞게 조정
- `HOT_FILE_THRESHOLDS`를 현재 프로젝트의 핵심 파일로 설정
- `REQUIRED_RUNTIME_FILES`를 현재 프로젝트의 스크립트로 설정

#### 3-3. scripts/session_init.py

D:\vibe-coding\scripts\session_init.py를 복사합니다. (범용적이므로 수정 불필요)

#### 3-4. docs/HARNESS_V2.md

D:\vibe-coding\docs\HARNESS_V2.md를 기반으로 프로젝트명과 에이전트 구성을 반영하여 생성.

#### 3-5. AGENTS.md

에이전트 구성에 맞게 생성. 역할, 강점, 가이드 문서 링크 포함.

### Step 4: CI 설정 (선택)

GitHub Actions를 설정합니다:

```yaml
name: Harness V2 Check
on:
  pull_request:
    paths: [AGENTS.md, docs/**, scripts/harness_verify.py, feature_list.json]
  push:
    branches: [main]
    paths: [AGENTS.md, docs/**, scripts/harness_verify.py, feature_list.json]
jobs:
  harness:
    runs-on: ubuntu-latest  # 또는 windows-latest
    steps:
      - uses: actions/checkout@v4
      - uses: actions/setup-python@v5
        with: { python-version: "3.11" }
      - run: python scripts/harness_verify.py --ci
```

### Step 5: 검증 + 안내

설치 완료 후:
1. `python scripts/harness_verify.py` 실행하여 설치 상태 확인
2. `python scripts/session_init.py` 실행하여 세션 프로토콜 테스트
3. 사용자에게 결과 보고 + 다음 단계 안내

```bash
python scripts/harness_verify.py
python scripts/session_init.py --agent claude
```

---

## 참고: 소스 프로젝트 (vibe-coding)

이 스킬의 원본 구현은 `D:\vibe-coding` 프로젝트에 있습니다.
각 파일의 상세 구조와 설계 의도는 아래 파일을 참조하세요:

- `D:\vibe-coding\docs\HARNESS_V2.md` — 마스터 명세서
- `D:\vibe-coding\scripts\harness_verify.py` — 검증 스크립트 (10개 검사)
- `D:\vibe-coding\scripts\session_init.py` — 세션 프로토콜
- `D:\vibe-coding\feature_list.json` — 기능 목록 예시
- `D:\vibe-coding\AGENTS.md` — 에이전트 구성 예시

---

## 절대 금지

1. 기존 프로젝트 파일을 덮어쓰기 하지 않기 (항상 확인 후 생성)
2. feature_list.json에 빈 features 배열로 생성하지 않기 (최소 1개 이상 감지)
3. 설치 후 harness_verify.py 실행 없이 완료 보고하지 않기
