---
name: vibe-release
description: >
  빌드 + 릴리즈 파이프라인 자동 실행. 버전 증가 → 커밋 → 푸시 → GitHub Actions 빌드.
  Use when: "빌드해줘", "배포해줘", "릴리즈", "push하고 업데이트", "EXE 만들어줘" 요청 시.
allowed-tools: Bash, Read, Write, Edit
user-invocable: true
---

<!-- FILE: .claude/skills/vibe-release/SKILL.md
DESCRIPTION: Vibe Coding 릴리즈 스킬 (Claude Code 전용).
             /vibe-release 명령으로 호출. 표준 릴리즈 파이프라인을 단계별로 실행합니다.

REVISION HISTORY:
- 2026-03-21 Claude: CI 빌드 검증 단계 추가, git add . → 명시적 파일 지정, 빌드 모니터링 단계 추가
- 2026-03-13 Claude: [Skills 2.0] .claude/commands → .claude/skills 마이그레이션
- 2026-03-01 Claude: [자기치유] 버전 번호 관리 위치 및 EXE 빌드 순서 명시 추가
- 2026-02-27 Claude: 배포 반복 에러 방지를 위한 릴리즈 스킬 신규 생성
-->

# vibe-release (Auto-Pilot)

**호출**: `/vibe-release` 또는 "빌드해줘", "배포해줘", "릴리즈"

버전 증가 → 커밋 → 푸시 → GitHub Actions 자동 빌드 → 검증

---

## 아키텍처: 빌드는 GitHub Actions가 수행

로컬에서 PyInstaller를 직접 실행하지 않는다.
push하면 `.github/workflows/build-release.yml`이 자동 실행:
1. 프론트엔드 빌드 (npm ci + npm run build)
2. PyInstaller EXE 패키징 (noconsole + console 2종)
3. 서브창 EXE 빌드 (vibe-graph, vibe-dashboard)
4. Inno Setup 설치 패키지 생성
5. GitHub Release 에셋 업로드

---

## 버전 관리 위치

| 파일 | 역할 |
|------|------|
| `.ai_monitor/_version.py` | **진실의 원천** — `__version__ = "X.Y.Z"` |
| `.ai_monitor/vibe-view/package.json` | 프론트엔드 버전 (auto_version.py가 동기화) |
| `vibe-coding-setup.iss` | 설치 패키지 버전 (auto_version.py가 동기화) |
| `scripts/auto_version.py` | patch +1 자동 증가 + 위 파일 동기화 |

---

## 자동 실행 절차

### Step 1: 버전 자동 증가
```bash
python scripts/auto_version.py
```
_version.py, package.json, setup.iss 세 곳이 동시에 동기화된다.

### Step 2: 변경 파일 스테이징 및 커밋
```bash
# 주의: git add . 금지! 변경된 파일만 명시적으로 추가
git add .ai_monitor/_version.py .ai_monitor/vibe-view/package.json vibe-coding-setup.iss
# 추가로 변경된 소스 파일이 있으면 함께 스테이징
git commit -m "chore(release): v$NEW_VER 자동 릴리즈"
```

### Step 3: 푸시 → CI 빌드 자동 트리거
```bash
git push origin main
```

### Step 4: 빌드 모니터링 (필수!)
```bash
# 빌드 시작 확인
gh run list --limit 1
# 백그라운드에서 완료 대기 (약 17~18분 소요)
gh run watch <RUN_ID> --exit-status
```

### Step 5: 빌드 결과 검증
```bash
# 릴리즈 에셋 확인
gh release view v$NEW_VER
```
성공 시 사용자에게 릴리즈 URL 전달.
실패 시 `gh run view <RUN_ID> --log-failed`로 에러 원인 분석.

---

## CI 빌드와 로컬 spec 파일 차이 (주의!)

| 항목 | 로컬 spec (vibe-coding.spec) | CI (build-release.yml) |
|------|------|------|
| 프론트엔드 경로 | `vibe-view/dist` → `vibe-view/dist` | `vibe-view\dist;vibe-view/dist` |
| API 모듈 | `api` → `api` | `api;api` |
| runtime_tmpdir | `%APPDATA%\VibeCoding\runtime` | 미설정 (기본 Temp) |

CI 워크플로우 수정 시 반드시 로컬 spec과 경로가 일치하는지 확인할 것.
**과거 사고**: CI에서 `vibe-view\dist;dist`로 설정 → 프론트엔드가 `_MEIPASS/dist/`에 배치 → server.py는 `_MEIPASS/vibe-view/dist/`를 참조 → "Not Found" (v3.7.95에서 수정)

---

## 에러 발생 시 즉시 확인

1. **CI 빌드 실패**: `gh run view <RUN_ID> --log-failed` → 에러 로그 확인
2. **EXE 크래시**: `%APPDATA%\VibeCoding\server_error.log` 확인
3. **"Not Found" 에러**: CI의 --add-data 경로가 server.py의 STATIC_DIR과 일치하는지 확인
4. **빌드 에셋 누락**: `gh release view vX.Y.Z`로 setup/update EXE 존재 확인
