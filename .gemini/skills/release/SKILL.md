---
name: release
description: Vibe Coding 배포 릴리즈 워크플로우. 버전 업데이트, 프론트엔드 빌드, PyInstaller exe 빌드, Inno Setup 인스톨러 빌드까지 전체 릴리즈 파이프라인을 검증하고 실행합니다.
---

<!-- FILE: .gemini/skills/release/SKILL.md
DESCRIPTION: Vibe Coding 배포(릴리즈) 워크플로우 스킬.
             빌드 → 패키징 → 릴리즈 전 체크리스트를 단계별로 수행합니다.

REVISION HISTORY:
- 2026-02-27 Claude: 배포 버전 반복 에러 해결을 위해 표준 릴리즈 스킬 신규 생성
-->

# 🚀 Vibe Coding 릴리즈 워크플로우

이 스킬은 반복되는 배포 에러를 방지하기 위한 표준화된 릴리즈 파이프라인입니다.
**순서를 절대 바꾸지 마세요.** 각 단계는 이전 단계의 결과물에 의존합니다.

---

## ✅ 0단계: 사전 점검 (Pre-flight Check)

다음 항목을 모두 확인한 후에만 빌드를 시작합니다.

```bash
# Node.js / npm 확인
node --version
npm --version

# Python / PyInstaller 확인
python --version
python -m PyInstaller --version

# Inno Setup 확인 (Windows 전용)
# C:\Program Files (x86)\Inno Setup 6\ISCC.exe 가 존재해야 함
ls "C:/Program Files (x86)/Inno Setup 6/ISCC.exe" 2>/dev/null || echo "❌ Inno Setup 미설치"
```

**체크리스트:**
- [ ] `git status` 가 clean (미커밋 변경사항 없음)
- [ ] `_version.py` 버전 번호 최신화 확인
- [ ] `vibe-view/package.json` name/version 확인
- [ ] `.ai_monitor/vibe-view/dist/` 삭제 후 재빌드할 것 (stale 빌드 방지)

---

## 📦 1단계: 버전 업데이트

### _version.py 수정
```
# .ai_monitor/_version.py
__version__ = "X.Y.Z"  ← 여기만 수정
```

### 확인
```bash
python -c "from _version import __version__; print(__version__)"
```

---

## ⚛️ 2단계: 프론트엔드 빌드

```bash
cd .ai_monitor/vibe-view

# 의존성 설치 (첫 빌드 또는 package.json 변경 시)
npm install

# 프로덕션 빌드
npm run build
```

**성공 확인**: `dist/index.html` 파일이 생성되었는지 확인.
```bash
ls .ai_monitor/vibe-view/dist/
```

> ⚠️ 빌드 경고 "chunks larger than 500 kB" 는 무시해도 됩니다. 에러가 아닙니다.

---

## 🐍 3단계: PyInstaller exe 빌드

```bash
cd .ai_monitor

# --noconfirm: 기존 dist/ 폴더 자동 덮어쓰기
python -m PyInstaller vibe-coding.spec --noconfirm
```

**성공 확인**: 마지막 줄에 `Build complete!` 출력 및 `dist/vibe-coding.exe` 존재 확인.
```bash
ls .ai_monitor/dist/vibe-coding.exe
```

> ⚠️ `ext-ms-win-uiacore-l1-1-*.dll not found` 경고는 winpty의 OpenConsole.exe 관련 시스템 DLL이며,
> Windows 11 런타임에 기본 내장되어 있어 무시해도 됩니다.

---

## 📀 4단계: Inno Setup 인스톨러 빌드

```bash
cd .ai_monitor

# VERSION 변수 주입하여 인스톨러 빌드
ISCC_PATH="C:/Program Files (x86)/Inno Setup 6/ISCC.exe"
VERSION=$(python -c "from _version import __version__; print(__version__)")

"$ISCC_PATH" installer.iss /DMyAppVersion=$VERSION
```

**성공 확인**: `dist/vibe-coding-setup-{VERSION}.exe` 생성 확인.
```bash
ls .ai_monitor/dist/vibe-coding-setup-*.exe
```

---

## 🏷️ 5단계: Git 커밋 & 태그

```bash
# 변경사항 커밋
git add .ai_monitor/_version.py
git commit -m "chore(release): bump version to vX.Y.Z"

# 릴리즈 태그
git tag -a "vX.Y.Z" -m "Release vX.Y.Z"
```

---

## 🔁 빌드 순서 요약 (절대 준수)

```
0. 사전점검 → 1. 버전 업데이트 → 2. npm build → 3. PyInstaller → 4. Inno Setup → 5. Git 태그
```

---

## ⚠️ 자주 발생하는 에러 & 해결법

| 에러 | 원인 | 해결 |
|------|------|------|
| `NameError: name 'BASE_DIR' is not defined` | 배포 코드에서 초기화 순서 오류 | server.py 상단 BASE_DIR 정의 확인 |
| exe 실행 시 즉시 종료 | frozen 모드 경로 오류 | `%APPDATA%\VibeCoding\server_error.log` 확인 |
| 인스톨러에 dist/vibe-coding.exe 없음 | PyInstaller 빌드 미실행 | 3단계 먼저 실행 |
| `npm run build` 실패 | TypeScript 컴파일 에러 | `tsc` 에러 메시지 확인 후 타입 오류 수정 |
| winpty ImportError | venv에 winpty 미설치 | `.ai_monitor/venv/` 활성화 후 `pip install pywinpty` |
| Inno Setup `Source file not found` | 빌드 순서 오류 또는 경로 불일치 | `installer.iss` Source 경로와 실제 파일 위치 대조 |

---

## 📝 배포 전 최종 체크리스트

- [ ] exe 직접 실행하여 UI 정상 로드 확인
- [ ] 터미널 기능 (WebSocket PTY) 동작 확인
- [ ] `%APPDATA%\VibeCoding\server_error.log` 에 에러 없음 확인
- [ ] 인스톨러 실행 → 설치 → 실행 전체 플로우 테스트
