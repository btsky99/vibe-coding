---
name: vibe-release
description: >
  설치본 빌드 릴리즈 파이프라인 (Windows .exe + macOS .dmg). 버전 증가 → 커밋 → 푸시 →
  GitHub Actions가 두 플랫폼을 자동 빌드하고 하나의 Release에 함께 올린다.
  Use when: "빌드해줘", "배포해줘", "릴리즈", "push해줘", "업데이트 올려줘", "맥용 만들어줘" 요청 시.
  코드 수정 후 배포가 필요한 상황, 버전 올려달라는 요청에도 반드시 이 스킬을 사용하세요.
allowed-tools: Bash, Read, Write, Edit
user-invocable: true
---

<!-- FILE: .claude/skills/vibe-release/SKILL.md
DESCRIPTION: Vibe Coding EXE 릴리즈 스킬.
  /vibe-release 명령으로 호출. 버전 증가 → 커밋 → 푸시하면 CI가 EXE 빌드.

REVISION HISTORY:
- 2026-07-24 Claude: macOS 빌드 잡(build-mac) 추가에 따른 플랫폼 인지형 개편.
                     로컬 사전검증(Step 0/0.5)은 Windows에서만 가능하다는 점과,
                     맥 산출물은 CI에서만 검증된다는 한계를 명시.
- 2026-05-10 Claude: EXE 빌드 주의사항에 "5. spec ↔ CI command 동기화" 추가.
                     `vibe-coding.spec` datas와 `.github/workflows/build-release.yml`의
                     `--add-data` 인자가 따로 관리되어 한쪽만 갱신하면 설치 EXE에서만
                     누락이 발생함. v3.7.215~218(infra/) + v3.7.207~223(_version.py)
                     두 사고가 같은 패턴.
- 2026-04-11 Claude: Step 0.5 로컬 EXE 빌드 + smoke test 단계 추가.
                     scripts/smoke_test.py로 빌드된 EXE의 서버 기동/API 응답을 자동 검증.
                     push 전에 설치 버전 동작을 미리 확인하여 CI 실패 위험 최소화.
- 2026-04-09 Claude: 로컬 검증 명령을 `vite build` → `npm run build`로 교체.
                     vite만 돌리면 `tsc -b` 타입체크가 스킵되어 타입 에러가 CI에서
                     처음 노출되는 문제가 반복됨 (v3.7.179 릴리즈 실패 원인).
                     Step 0(푸시 전 필수 검증) 단계 신설 — 타입체크 + Python 구문검사.
- 2026-03-28 Claude: Step 4에 CI 빌드 완료 대기 + 검증 단계 추가. EXE 빌드 주의사항 섹션 신설
- 2026-03-27 Claude: EXE 빌드 방식으로 전면 재작성 — pip 전용 내용 제거
- 2026-03-26 Claude: pip 전용으로 재작성 (실패 — v3.7.146에서 EXE로 복원)
- 2026-03-21 Claude: CI 빌드 검증 단계 추가
- 2026-02-27 Claude: 최초 생성
-->

# vibe-release (EXE 빌드)

**호출**: `/vibe-release` 또는 "배포해줘", "릴리즈", "push해줘"

## 배포 방식

이 프로젝트는 **설치본 빌드 + GitHub Releases** 기반으로 배포합니다.
**2026-07-24부터 Windows와 macOS를 함께 빌드합니다.**

1. `git push origin main` → GitHub Actions가 자동 실행
2. **`build` 잡 (windows-latest)** — PyInstaller(onedir) + Inno Setup →
   `vibe-coding-setup-X.Y.Z.exe`. **버전 확정은 이 잡이 단독 수행**(태그 중복 시
   자동 patch bump 후 `_version.py` 커밋·push)하고 결과를 잡 outputs로 노출한다.
3. **`build-mac` 잡 (macos-latest, `needs: build`)** — 확정된 버전을 받아
   PyInstaller(`--windowed`) → `.app`, `hdiutil` → `vibe-coding-X.Y.Z.dmg`.
   윈도우가 만든 **같은 태그의 릴리즈에 .dmg를 덧붙인다**(새 릴리즈 생성 아님).
4. 사용자 앱이 실행 시 자동 업데이트 감지 → 다운로드 + 교체

**CI 워크플로**: `.github/workflows/build-release.yml`

### 🔴 두 잡의 관계 — 불변식
- **버전 bump는 `build` 잡만** 한다. 두 잡이 각자 올리면 버전이 갈라진다.
  `build-mac`은 `needs.build.outputs.ver`를 받아 `_version.py`에 그대로 기록한다.
- `build-mac` 실패는 **윈도우 릴리즈를 되돌리지 않는다**(이미 발행됨). 맥만 재시도하면 된다.
- `build-mac`은 `main` push에서만 동작한다(`if: github.ref == 'refs/heads/main'`).

### 🍎 macOS 빌드에서 Windows와 다른 점 (수정 시 필독)
| 항목 | Windows | macOS |
|---|---|---|
| `--add-data` 구분자 | `;` | **`:`** |
| winpty 바이너리 4종 | 포함 | **제외**(존재하지 않음) |
| hidden-import `clr`/`win32*`/`pythoncom` | 포함 | **제외** |
| 번들 Node 파일명 | `node.exe` | **`node`** |
| PostgreSQL | EnterpriseDB zip 다운로드 | **Homebrew `postgresql@17` 복사** |
| 아이콘 | `.ico` | **`.icns`**(CI가 sips/iconutil로 생성) |
| UPX | 사용 | **`--noupx`**(맥 바이너리 손상) |
| 패키징 | Inno Setup(`.iss`) | **`hdiutil`로 `.dmg`** |

**🔴 미해결 위험 (맥)**: Homebrew PG 바이너리는 `/opt/homebrew/...` 절대경로로 dylib을
참조한다. Homebrew가 없는 사용자 맥에서 기동하려면 `install_name_tool`로 참조 재작성이
추가로 필요할 수 있다. 맥 릴리즈 후 **실기기에서 DB 기동 여부를 반드시 확인**할 것.
또한 코드서명·공증이 없어 Gatekeeper가 첫 실행을 막는다(우클릭→열기 또는 `xattr -cr` 안내 필요).

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

## 실행 절차 (6단계)

> **🖥 플랫폼 전제**: Step 0~0.5의 로컬 사전검증은 **Windows에서 실행할 때만** 유효하다.
> `pyinstaller vibe-coding.spec`은 winpty를 최상단 import하고 `smoke_test.py`는 `.exe`를
> glob하므로 **맥에서는 Step 0.5를 건너뛴다**(Step 0의 ruff/py_compile/npm build는 맥에서도 유효).
> 즉 **맥 산출물은 로컬 사전검증 수단이 없고 CI가 유일한 검증 지점**이다 — 맥 관련 변경은
> 푸시 후 `build-mac` 잡 로그와 실기기 실행으로 확인해야 한다.

### Step 0: 로컬 사전 검증 (필수 — 실패 시 중단)

푸시 후 CI에서 터지는 사고를 막기 위해 **푸시 전에 로컬에서 동일 명령을 돌려봅니다.**

```bash
# 1. Python 구문 검사
python -c "import py_compile; py_compile.compile('.ai_monitor/server.py', doraise=True)"
python -c "import py_compile; py_compile.compile('.ai_monitor/dashboard_window.py', doraise=True)"

# 2. ruff 린트 (CI와 동일한 규칙)
ruff check .ai_monitor --select E9,F821,F823

# 3. 프론트엔드 풀 빌드 (tsc 타입체크 + vite 번들링)
#    ⚠️ `vite build`만 돌리면 TypeScript 타입체크가 스킵됨 → 반드시 `npm run build`
cd .ai_monitor/vibe-view && npm run build
```

**어느 하나라도 실패하면 여기서 중단하고 수정. Step 0.5 진행 금지.**

### Step 0.5: 로컬 EXE 빌드 + Smoke Test (필수 — 실패 시 중단)

**push 전에 로컬에서 EXE를 빌드하고 실제로 서버가 뜨는지 검증합니다.**
포트 충돌 걱정 없음 — 기존 서버가 9000을 쓰면 테스트 EXE는 자동으로 빈 포트를 찾습니다.

```bash
# 1. PyInstaller로 로컬 EXE 빌드 (약 3~5분 소요)
pyinstaller vibe-coding.spec --noconfirm

# 2. Smoke test — EXE 기동 → API 응답 검증 → 자동 종료
python scripts/smoke_test.py
```

**smoke test가 실패하면 중단. EXE에서만 발생하는 문제(import 에러, 경로 문제 등)를 push 전에 잡을 수 있습니다.**

Smoke test 검증 항목:
- [ ] EXE 서버 기동 성공 (30초 내)
- [ ] `GET /api/config` 응답 200
- [ ] `GET /api/agents` 응답 200
- [ ] `GET /api/hive/health` 응답 200
- [ ] `GET /` 프론트엔드 HTML 로드

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

#### 🔴 빌드를 지켜보고 있지 말 것 — 끝나면 통보받는다 (2026-08-17 사장 지시)

빌드는 10~15분 걸린다. 그동안 `gh run view` 를 주기적으로 두드리는 것은 **금지**다.
지켜보는 동안 다른 일을 못 하고, 사장은 "다 됐냐"를 되묻게 된다.

**한 줄로 건다 — 끝날 때 알림이 한 번 온다:**

```bash
python scripts/wait_ci.py        # ← Bash 도구의 run_in_background: true 로 띄운다
```

이 명령은 **빌드가 끝나는 순간 스스로 종료**한다. 종료 자체가 통보라
따로 확인하러 갈 필요가 없다. 거는 즉시 **다음 일을 계속한다.**

- ❌ `sleep` 을 늘어놓거나 `gh run view` 를 반복 호출 — 지켜보는 것이다
- ❌ `tail -f` 처럼 안 끝나는 명령 — 알림이 안 온다
- ✅ 조건이 참이 되면 **끝나는** 명령을 백그라운드로 — 알림이 한 번 온다

실패했을 때만 로그를 본다:

```bash
gh run view --log-failed | tail -30
```

**🔴 빌드 도는 중에 또 푸시하지 말 것.** CI 가 태그 중복 시 스스로 `_version.py` 를
bump 해 커밋·푸시하는데, 그 커밋이 거부되고 exit 0 이 그것을 삼킨다.
두 번째 푸시가 있으면 **위 대기가 끝난 뒤**에 한다.

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

## CI 릴리즈 산출물

| 파일명 | 플랫폼 | 설명 |
|--------|--------|------|
| `vibe-coding-setup-X.Y.Z.exe` | Windows | Inno Setup 설치본 (올인원, PG 포함) |
| `vibe-coding-X.Y.Z.dmg` | macOS | `.app` 번들 + Applications 링크 (드래그&드롭) |

> **주의**: 릴리즈에 실제로 첨부되는 것은 위 2개뿐이다. 빌드 과정에서 console exe·
> `vibe-dashboard.exe` 등이 만들어지지만 릴리즈 자산으로는 올라가지 않는다
> (`build-release.yml`의 `files:` 목록이 진실의 원천).

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

### 5. spec ↔ CI command 동기화 (중요 — 두 번 사고)
PyInstaller는 두 가지 빌드 경로가 있고 **각각 다른 데이터 소스**를 본다:
- 로컬 빌드 (`pyinstaller vibe-coding.spec`): `vibe-coding.spec`의 `datas=[...]` 사용
- CI 빌드 (`build-release.yml`): `pyinstaller --onefile ... server.py`의 `--add-data` 인자 사용

**spec datas만 갱신하면 로컬 EXE는 통과해도 CI 설치 EXE에서 누락 발생**.

PR/커밋에서 다음 변경이 있으면 양쪽 동시 갱신 필수:
- `.ai_monitor/`에 새 디렉토리 추가 (예: `infra/`, `api/`, `pty-server/`)
- `.ai_monitor/`에 새 데이터 파일 추가 (예: `_version.py`, 마이그레이션 SQL)
- 모듈 import 방식을 `import X` → `open('X.py')` 같은 파일 읽기로 전환

**체크 명령:**
```bash
# spec datas와 CI --add-data 항목 비교
grep -E "add-data" .github/workflows/build-release.yml
grep -E "datas=|\\('\\.ai_monitor/" vibe-coding.spec
```

과거 사고: v3.7.215~218(`infra/` 누락 → ModuleNotFoundError 좀비 4릴리즈),
v3.7.207~223(`_version.py` 누락 → 우상단 버전 미표시 장기 미해결).

---

## 절대 금지 사항

1. `_version.py` 직접 편집 → `auto_version.py` 사용
2. `git add .` 또는 `git add -A` → 파일 명시적 지정
3. smoke test 없이 push → Step 0.5 필수
4. pip install로 배포 → EXE 전용 배포

---

## 에러 발생 시

1. **CI 빌드 실패**: `gh run list --limit 1` → `gh run view <ID> --log-failed`
2. **push 거부**: `git pull --rebase origin main` 후 재시도
3. **버전 충돌**: `auto_version.py` 재실행 후 커밋
