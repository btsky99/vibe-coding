---
name: vibe-release
description: >
  EXE 빌드 릴리즈 파이프라인. 버전 증가 → 커밋 → 푸시 → GitHub Actions가 자동으로 EXE 빌드 + Release 생성.
  Use when: "빌드해줘", "배포해줘", "릴리즈", "push해줘", "업데이트 올려줘" 요청 시.
  코드 수정 후 배포가 필요한 상황, 버전 올려달라는 요청에도 반드시 이 스킬을 사용하세요.
allowed-tools: Bash, Read, Write, Edit
user-invocable: true
---

<!-- FILE: .claude/skills/vibe-release/SKILL.md
DESCRIPTION: Vibe Coding EXE 릴리즈 스킬.
  /vibe-release 명령으로 호출. 버전 증가 → 커밋 → 푸시하면 CI가 EXE 빌드.

REVISION HISTORY:
- 2026-03-28 Claude: Step 4에 CI 빌드 완료 대기 + 검증 단계 추가. EXE 빌드 주의사항 섹션 신설
- 2026-03-27 Claude: EXE 빌드 방식으로 전면 재작성 — pip 전용 내용 제거
- 2026-03-26 Claude: pip 전용으로 재작성 (실패 — v3.7.146에서 EXE로 복원)
- 2026-03-21 Claude: CI 빌드 검증 단계 추가
- 2026-02-27 Claude: 최초 생성
-->

# vibe-release (EXE 빌드)

**호출**: `/vibe-release` 또는 "배포해줘", "릴리즈", "push해줘"

## 배포 방식

이 프로젝트는 **EXE 빌드 + GitHub Releases** 기반으로 배포합니다.

1. `git push origin main` → GitHub Actions가 자동 실행
2. CI가 PyInstaller + Inno Setup으로 EXE 4종 빌드
3. GitHub Releases에 자동 업로드
4. 사용자 앱이 실행 시 자동 업데이트 감지 → EXE 다운로드 + 교체

**CI 워크플로**: `.github/workflows/build-release.yml`

---

## 버전 관리

| 파일 | 역할 |
|------|------|
| `.ai_monitor/_version.py` | **진실의 원천** — `__version__ = "X.Y.Z"` |
| `.ai_monitor/vibe-view/package.json` | 프론트엔드 버전 (auto_version.py가 동기화) |
| `vibe-coding-setup.iss` | Inno Setup 설치버전 (auto_version.py가 동기화) |
| `scripts/auto_version.py` | patch +1 자동 증가 + 위 파일 동기화 |

`_version.py`를 직접 편집하지 마세요. 반드시 `auto_version.py`를 사용합니다.

---

## 실행 절차 (4단계)

### Step 1: 버전 자동 증가

```bash
python scripts/auto_version.py
```

`_version.py`, `package.json`, `vibe-coding-setup.iss`가 동시에 동기화됩니다.

### Step 2: 변경 파일 스테이징

```bash
# git add . 절대 금지! 변경된 파일만 명시적으로 추가
git add .ai_monitor/_version.py .ai_monitor/vibe-view/package.json vibe-coding-setup.iss
# 소스 코드 변경이 있으면 해당 파일도 함께 추가
```

민감 파일(.env, credentials 등)이 포함되지 않았는지 `git status`로 확인합니다.

### Step 3: 커밋

커밋 메시지는 Conventional Commits 형식 + 한글 본문 필수 (RULES.md 섹션 3).

```bash
git commit -m "$(cat <<'EOF'
<type>(<scope>): <영문 요약> — v<NEW_VER>

<한글 본문: 변경 사항을 상세히 설명>

Co-Authored-By: Claude Opus 4.6 (1M context) <noreply@anthropic.com>
EOF
)"
```

커밋 메시지에 반드시 포함할 내용:
- 무엇을 왜 변경했는지 (한글)
- 버전 번호

### Step 4: 푸시 + CI 빌드 검증 (필수)

```bash
git push origin main
```

**푸시 후 반드시 CI 빌드 완료를 확인해야 합니다.** 확인 없이 끝내지 마세요.

```bash
# 1. 빌드 시작 확인
gh run list --limit 1

# 2. 빌드 완료까지 주기적 확인 (보통 10~15분 소요)
gh run view <RUN_ID>
gh run view --job <JOB_ID> | grep -E "✓|✗|\*"

# 3. 실패 시 즉시 원인 확인
gh run view <RUN_ID> --log-failed | tail -30
```

**CI 검증 체크리스트:**
- [ ] `✓ Lint & syntax check (Python)` — ruff 통과 여부
- [ ] `✓ Pre-build verification (Phase 1 + 2)` — import/구문 검증
- [ ] `✓ Build exe` + `Build exe (console)` — PyInstaller 빌드
- [ ] `✓ Build installer` — Inno Setup 패키징
- [ ] `✓ Create Release` — GitHub Releases 업로드

CI 실패 시:
1. `--log-failed`로 에러 원인 확인
2. 수정 후 다시 Step 1부터 재실행
3. **절대 실패한 채로 방치하지 않기**

---

## CI가 빌드하는 EXE 목록

| 파일명 | 설명 |
|--------|------|
| `vibe-coding-update-X.Y.Z.exe` | GUI 모드 (콘솔 없음) |
| `vibe-coding-console-X.Y.Z.exe` | 콘솔 모드 (디버깅용) |
| `vibe-dashboard.exe` | 대시보드 서브창 |
| `vibe-coding-setup-X.Y.Z.exe` | Inno Setup 설치버전 (올인원) |

---

## EXE 빌드 주의사항 (과거 사고 사례)

설치 버전(PyInstaller EXE)에서는 개발 환경과 다르게 동작하는 부분이 많습니다.
**코드 수정 후 반드시 아래 사항을 체크하세요.**

### 1. `sys.executable` 주의
- **개발 모드**: `sys.executable` = `python.exe`
- **EXE 빌드**: `sys.executable` = `vibe-coding.exe`
- subprocess로 Python 스크립트 실행 시 `sys.executable` 대신 `_python_runner_cmds()` 사용

### 2. 상대/절대 import 주의
- `from .module import func` → EXE에서 `ImportError` 발생 가능
- 반드시 `try/except ImportError` 패턴으로 감싸서 양쪽 호환
- **조건부 import**: 해당 기능이 실제 필요한 시점에서만 import (top-level 금지)

### 3. API 응답 null 방어 (프론트엔드)
- 서버 API가 null/undefined 반환할 수 있음 → `.length`, `.map()`, `.filter()` 등 호출 전 방어 필수
- 패턴: `(data.items ?? []).map(...)` 또는 `data.items?.length ?? 0`

### 4. 푸시 전 로컬 검증
```bash
# Python 구문 검사
python -c "import py_compile; py_compile.compile('.ai_monitor/server.py', doraise=True)"

# ruff 린트 (CI와 동일한 규칙)
ruff check .ai_monitor/server.py --select E9,F821,F823

# 프론트엔드 빌드 (타입 에러 확인)
cd .ai_monitor/vibe-view && npx vite build
```

---

## 절대 금지 사항

1. `_version.py` 직접 편집 → `auto_version.py` 사용
2. `git add .` 또는 `git add -A` → 파일 명시적 지정
3. 로컬에서 PyInstaller 직접 실행 → CI가 알아서 빌드
4. pip install로 배포 → EXE 전용 배포

---

## 에러 발생 시

1. **CI 빌드 실패**: `gh run list --limit 1` → `gh run view <ID> --log-failed`
2. **push 거부**: `git pull --rebase origin main` 후 재시도
3. **버전 충돌**: `auto_version.py` 재실행 후 커밋
