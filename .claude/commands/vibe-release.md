---
name: vibe-release
description: >
  빌드 + 릴리즈 파이프라인 자동 실행. 버전 증가 → 커밋 → 푸시 → GitHub Actions 빌드.
  Use when: "빌드해줘", "배포해줘", "릴리즈", "push하고 업데이트", "EXE 만들어줘" 요청 시.
allowed-tools: Bash, Read, Write, Edit
user-invocable: true
---

<!-- FILE: .claude/commands/vibe-release.md
DESCRIPTION: Vibe Coding 릴리즈 스킬 (Claude Code 전용).
             /vibe-release 명령으로 호출. 표준 릴리즈 파이프라인을 단계별로 실행합니다.

REVISION HISTORY:
- 2026-03-15 Claude: [자기치유] 포트 충돌 방지(Step 0) 추가, Inno Setup 빌드 단계 추가,
                     ISS 버전 동기화 필수사항 추가, Publisher 고정 주의사항 추가
- 2026-03-13 Claude: [Skills 2.0] .claude/commands → .claude/skills 마이그레이션
- 2026-03-01 Claude: [자기치유] 버전 번호 관리 위치 및 EXE 빌드 순서 명시 추가
- 2026-02-27 Claude: 배포 반복 에러 방지를 위한 릴리즈 스킬 신규 생성
-->

# 🚀 vibe-release (Auto-Pilot)

**호출 방법**: `/vibe-release` 또는 "빌드해서 배포해줘", "푸시하고 업데이트 띄워줘"

이 스킬은 **포트 충돌 해소 → 버전 증가 → 프론트빌드 → EXE → 설치버전 → 커밋 → 푸시**를 수행합니다.

---

## 📍 버전 번호 관리 위치 (필수 지식)

| 파일 | 역할 |
|------|------|
| `.ai_monitor/_version.py` | **Python 소스 진실의 원천** — `__version__ = "X.Y.Z"` |
| `.ai_monitor/vibe-view/package.json` | 프론트엔드 버전 — Python과 항상 동일하게 유지 |
| `vibe-coding-setup.iss` | Inno Setup 설치버전 — `#define MyAppVersion` 반드시 동기화 |
| `scripts/auto_version.py` | 자동 버전 증가 스크립트 (patch 자동 +1) |

> **설치버전(EXE)에 표시되는 버전** = `_version.py`의 `__version__` 값
> 버전 변경 시 `_version.py` + `vibe-coding-setup.iss`의 MyAppVersion 둘 다 맞춰야 함.

---

## ⚡ 빌드 전체 순서 (Step 0~5, 반드시 이 순서!)

### Step 0: 포트 충돌 방지 (빌드 전 필수!)
```bash
# 기존 vibe-coding 프로세스가 9000~9007 포트를 점유하고 있으면 빌드 후
# 새 인스턴스가 같은 포트에 바인딩 실패함.
# 빌드 전에 반드시 기존 프로세스 종료!

# 1) 포트 점유 프로세스 확인
powershell -NoProfile -Command "Get-NetTCPConnection -State Listen -ErrorAction SilentlyContinue | Where-Object { \$_.LocalPort -in @(9000,9001,9002,9003,9004,9005,9006,9007) } | Select-Object LocalPort,OwningProcess"

# 2) vibe-coding 관련 프로세스 종료 (pythonw/python으로 server.py 실행 중인 것)
taskkill /F /IM vibe-coding.exe 2>/dev/null || true
# 개발 모드 서버가 떠있으면 PID로 직접 종료
# (위 1단계에서 확인한 OwningProcess PID 사용)
```

> ⚠️ **포트 충돌 원인**: 기존 인스턴스가 9000/9001 포트를 잡고 있는데
> 새 빌드 결과를 실행하면 같은 포트를 바인딩하려다 실패.
> Step 0을 건너뛰면 "Server Start Error on port 9000" 에러 발생.

### Step 1: 버전 자동 증가 및 ISS 동기화
```bash
# 1. 현재 버전 자동 증가
python scripts/auto_version.py

# 2. 결과 확인
NEW_VER=$(python -c "exec(open('.ai_monitor/_version.py').read()); print(__version__)")
echo "새로운 버전: $NEW_VER"

# 3. vibe-coding-setup.iss 의 MyAppVersion도 반드시 동기화!
#    sed로 자동 교체하거나 Edit 도구로 수정
```

> ⚠️ ISS의 `#define MyAppVersion`이 _version.py와 다르면
> 설치버전에 표시되는 버전이 실제와 불일치.
> ⚠️ ISS의 `MyAppPublisher`는 반드시 `"Vibe Coding Team"` 고정!
> 다른 이름으로 바꾸면 프로그램 목록에 게시자 불일치 발생.

### Step 2: 프론트엔드 빌드 (먼저!)
```bash
cd .ai_monitor/vibe-view && npm run build
```

### Step 3: PyInstaller EXE 패키징
```bash
cd ../../ && pyinstaller vibe-coding.spec --noconfirm
# → dist/vibe-coding-vX.Y.Z.exe 생성
```

> ⚠️ Step 2 없이 Step 3만 하면 **구 버전 UI**가 EXE에 포함됨.

### Step 4: Inno Setup 설치버전 빌드
```bash
ISCC_PATH="C:/Users/com/AppData/Local/Programs/Inno Setup 6/ISCC.exe"
"$ISCC_PATH" vibe-coding-setup.iss
# → dist/vibe-coding-setup-X.Y.Z.exe 생성
```

> ⚠️ ISS에 구버전 자동 제거 로직이 포함되어 있음 (InitializeSetup).
> 새 설치 시 기존 버전을 사일런트 언인스톨 후 설치.

### Step 5: Git 커밋 및 푸시
```bash
git add .ai_monitor/vibe-view/dist/ vibe-coding-setup.iss .claude/commands/
git add -f .ai_monitor/vibe-view/dist/
git commit -m "chore(release): v$NEW_VER — [변경 요약]"
git push origin main
```

---

## ⚠️ 에러 발생 시 즉시 확인할 것

1. **포트 충돌**: Step 0 재실행 → 기존 프로세스 종료 확인
2. **GitHub 토큰**: `.ai_monitor/data/github_token.txt` 확인
3. **exe 크래시**: `%APPDATA%\VibeCoding\server_error.log` 내용 확인
4. **빌드 순서**: 반드시 `Step 0(포트) → Step 2(npm) → Step 3(PyInstaller) → Step 4(Inno)` 순서 준수
5. **버전 불일치**: `_version.py` ↔ `vibe-coding-setup.iss` 버전이 같은지 확인

---

## 📋 자동 보고 형식

```
수정/생성된 파일: .ai_monitor/_version.py, dist/vibe-coding-vX.Y.Z.exe, dist/vibe-coding-setup-X.Y.Z.exe
원인: 표준 릴리즈 파이프라인 실행
수정 내용: 버전 X.Y.Z 빌드 완료. 포트 충돌 해소 → 프론트빌드 → EXE → 설치버전 → 깃 푸시.
```
