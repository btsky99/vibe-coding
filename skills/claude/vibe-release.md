<!-- FILE: skills/claude/vibe-release.md
DESCRIPTION: Vibe Coding 릴리즈 스킬 (Claude Code 전용).
             /vibe-release 명령으로 호출. 표준 릴리즈 파이프라인을 단계별로 실행합니다.

REVISION HISTORY:
- 2026-02-27 Claude: 배포 반복 에러 방지를 위한 릴리즈 스킬 신규 생성
-->

# 🚀 vibe-release (Auto-Pilot)

**호출 방법**: `/vibe-release` 또는 "빌드해서 배포해줘", "푸시하고 업데이트 띄워줘"

이 스킬은 **버전 자동 증가 -> 커밋 -> 푸시 -> GitHub 자동 빌드**로 이어지는 전체 배포 과정을 수행합니다.

---

## ⚡ 자동 실행 절차 (Agent 가이드)

### Step 1: 버전 자동 증가 및 점검
```bash
# 1. 현재 버전 자동 증가 (scripts/auto_version.py 사용)
python scripts/auto_version.py

# 2. 결과 확인
NEW_VER=$(python -c "exec(open('.ai_monitor/_version.py').read()); print(__version__)")
echo "새로운 버전: $NEW_VER"
```

### Step 2: Git 커밋 및 푸시 (자동 업데이트 트리거)
```bash
git add .
git commit -m "chore(release): v$NEW_VER 자동 릴리즈"
git push origin main
```
- **중요**: 푸시가 완료되면 GitHub Actions가 감지하여 약 5분 내로 다른 PC에 '업데이트 알림'을 보냅니다.

---

## ⚠️ 에러 발생 시 즉시 확인할 것

1. **GitHub 토큰**: `.ai_monitor/data/github_token.txt` 확인.
2. **빌드 실패**: GitHub Actions 탭 모니터링.

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
