---
name: vibe-release
description: >
  pip 기반 릴리즈 파이프라인. 로컬 테스트 → 버전 증가 → 커밋 → 푸시.
  CI 빌드 없이 git push만으로 배포 완료 (사용자가 pip install --upgrade로 받음).
  Use when: "빌드해줘", "배포해줘", "릴리즈", "push해줘", "업데이트 올려줘" 요청 시.
  코드 수정 후 배포가 필요한 상황, 버전 올려달라는 요청에도 반드시 이 스킬을 사용하세요.
allowed-tools: Bash, Read, Write, Edit
user-invocable: true
---

<!-- FILE: .claude/skills/vibe-release/SKILL.md
DESCRIPTION: Vibe Coding pip 릴리즈 스킬.
  /vibe-release 명령으로 호출. 로컬 테스트 후 안전하게 배포합니다.

REVISION HISTORY:
- 2026-03-26 Claude: pip 전용으로 전면 재작성 — CI/PyInstaller/Inno Setup 제거
- 2026-03-21 Claude: CI 빌드 검증 단계 추가
- 2026-02-27 Claude: 최초 생성
-->

# vibe-release (pip 전용)

**호출**: `/vibe-release` 또는 "배포해줘", "릴리즈", "push해줘"

## 배포 방식

이 프로젝트는 pip install 기반으로 배포합니다.
git push만 하면 사용자가 아래 명령으로 업데이트합니다:

```
pip install --no-cache-dir --upgrade git+https://github.com/btsky99/vibe-coding.git
```

CI 빌드, PyInstaller, Inno Setup은 사용하지 않습니다.
로컬에서 EXE를 빌드하거나 GitHub Actions를 기다릴 필요가 없습니다.

---

## 버전 관리

| 파일 | 역할 |
|------|------|
| `.ai_monitor/_version.py` | **진실의 원천** — `__version__ = "X.Y.Z"` |
| `.ai_monitor/vibe-view/package.json` | 프론트엔드 버전 (auto_version.py가 동기화) |
| `scripts/auto_version.py` | patch +1 자동 증가 + 위 파일 동기화 |

`_version.py`를 직접 편집하지 마세요. 반드시 `auto_version.py`를 사용합니다.

---

## 실행 절차 (5단계)

### Step 1: 로컬 테스트 (필수!)

push 전에 반드시 pip install로 설치 후 동작을 확인합니다.
이 단계를 건너뛰면 다른 PC에서 에러가 발생해도 디버깅이 어렵습니다.

```bash
pip install --no-cache-dir .
```

설치 후 핵심 기능 검증:
```bash
vibe-coding --install   # 바로가기 + PTY 빌드 테스트
vibe-coding --uninstall # 언인스톨 테스트
```

문제가 있으면 수정하고 다시 테스트합니다. 테스트 통과 후에만 다음 단계로.

테스트 완료 후 editable install로 복원:
```bash
pip install -e .
```

### Step 2: 버전 자동 증가

```bash
python scripts/auto_version.py
```

`_version.py`와 `package.json`이 동시에 동기화됩니다.

### Step 3: 변경 파일 스테이징

```bash
# git add . 절대 금지! 변경된 파일만 명시적으로 추가
git add .ai_monitor/_version.py .ai_monitor/vibe-view/package.json
# 소스 코드 변경이 있으면 해당 파일도 함께 추가
```

민감 파일(.env, credentials 등)이 포함되지 않았는지 `git status`로 확인합니다.

### Step 4: 커밋

커밋 메시지는 Conventional Commits 형식 + 한글 본문 필수 (RULES.md 섹션 3).

```bash
git commit -m "$(cat <<'EOF'
<type>(<scope>): <영문 요약> — v<NEW_VER>

<한글 본문: 변경 사항을 상세히 설명>

chore(release): v<NEW_VER> 자동 릴리즈
EOF
)"
```

커밋 메시지에 반드시 포함할 내용:
- 무엇을 왜 변경했는지 (한글)
- 버전 번호

### Step 5: 푸시

```bash
git push origin main
```

푸시 성공 후 사용자에게 보고:
- 새 버전 번호
- 주요 변경 사항 요약
- 업데이트 명령어: `pip install --no-cache-dir --upgrade git+https://github.com/btsky99/vibe-coding.git`

---

## 절대 금지 사항

1. `_version.py` 직접 편집 → `auto_version.py` 사용
2. `git add .` 또는 `git add -A` → 파일 명시적 지정
3. 로컬 테스트 없이 push → Step 1 필수
4. PyInstaller / npm build / ISCC 실행 → pip 전용 배포
5. GitHub Actions 빌드 대기 → CI 없음, push로 끝

---

## 에러 발생 시

1. **pip install 실패**: `pip install --no-cache-dir .` 에러 로그 확인
2. **import 에러**: `__init__.py`의 sys.path 설정 및 패키지 구조 확인
3. **다른 PC에서 안됨**: `vibe-coding` 명령 실행 후 콘솔 에러 확인
