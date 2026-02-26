<!-- FILE: skills/claude/vibe-release.md
DESCRIPTION: Vibe Coding 릴리즈 스킬 (Claude Code 전용).
             /vibe-release 명령으로 호출. 표준 릴리즈 파이프라인을 단계별로 실행합니다.

REVISION HISTORY:
- 2026-02-27 Claude: 배포 반복 에러 방지를 위한 릴리즈 스킬 신규 생성
-->

# 🚀 vibe-release 스킬

**호출 방법**: `/vibe-release` 또는 "릴리즈", "빌드 배포" 요청 시 자동 실행

이 스킬은 Vibe Coding 릴리즈 파이프라인을 안전하게 실행합니다.
빌드 순서를 지키고, 각 단계 완료를 검증한 후 다음 단계로 진행합니다.

---

## ⚡ 실행 절차

### Step 0: 사전 점검
```bash
# 현재 버전 확인
python -c "from _version import __version__; print('현재 버전:', __version__)" 2>/dev/null || cd .ai_monitor && python -c "from _version import __version__; print(__version__)"

# git 상태 확인 (clean 여야 함)
git status --short
```

사용자에게 물어볼 것:
1. 새 버전 번호는? (현재 버전 + 1 제안)
2. 릴리즈 노트 요약은?

### Step 1: 버전 번호 업데이트
```python
# .ai_monitor/_version.py 수정
__version__ = "{NEW_VERSION}"
```

### Step 2: 프론트엔드 빌드
```bash
cd .ai_monitor/vibe-view && npm run build
```
- 성공 기준: `✓ built in` 메시지 출력
- 실패 시: TypeScript 에러 먼저 수정

### Step 3: PyInstaller 빌드
```bash
cd .ai_monitor && python -m PyInstaller vibe-coding.spec --noconfirm
```
- 성공 기준: `Build complete!` + `dist/vibe-coding.exe` 존재
- WARNING은 무시 (ext-ms-win-uiacore DLL 경고는 정상)

### Step 4: Inno Setup 인스톨러 빌드
```bash
VERSION=$(cd .ai_monitor && python -c "from _version import __version__; print(__version__)")
"C:/Program Files (x86)/Inno Setup 6/ISCC.exe" .ai_monitor/installer.iss /DMyAppVersion=$VERSION
```
- 성공 기준: `dist/vibe-coding-setup-{VERSION}.exe` 생성

### Step 5: Git 커밋 & 태그
```bash
git add .ai_monitor/_version.py
git commit -m "chore(release): v{NEW_VERSION}"
git tag -a "v{NEW_VERSION}" -m "Release v{NEW_VERSION}"
```

---

## ⚠️ 에러 발생 시 즉시 확인할 것

1. **exe 크래시**: `%APPDATA%\VibeCoding\server_error.log` 내용 확인
2. **BASE_DIR 에러**: server.py 상단 (line ~33)에 BASE_DIR 정의가 있는지 확인
3. **빌드 순서**: 반드시 `npm build → PyInstaller → Inno Setup` 순서 준수

---

## 📋 자동 보고 형식

```
수정/생성된 파일: .ai_monitor/_version.py, dist/vibe-coding.exe, dist/vibe-coding-setup-X.Y.Z.exe
원인: 표준 릴리즈 파이프라인 실행
수정 내용: 버전 X.Y.Z 빌드 완료. 인스톨러 생성 완료.
```
