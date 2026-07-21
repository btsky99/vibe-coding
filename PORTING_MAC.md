# PORTING_MAC.md — macOS 포팅 계획서

> **상태**: 초안 (아직 미착수). 실제 진행 시 이 문서를 체크리스트로 사용.
> **작성**: 2026-07-21, Claude(Windows 세션) — 코드 전수 조사 기반.
> **검증 원칙**: 이 프로젝트는 프로세스 관리·PG 부팅·자동 업데이트가 OS에 깊게 물려 있어
> **블라인드 포팅 금지**. 반드시 실제 맥에서 `python .ai_monitor/server.py`를 띄워 계측하며 진행.
> (교훈: "메커니즘이 맞아도 실사용 계측 없이 '작동한다' 가정 말 것" — lessons.md 2026-07-14)

---

## 0. 실행 환경 세팅 (맥에서)

```bash
# Node + Claude Code (없으면)
brew install node
npm install -g @anthropic-ai/claude-code

# 저장소
git clone https://github.com/btsky99/vibe-coding.git
cd vibe-coding

# Python 3.11+ (mac)
python3 -m venv .ai_monitor/venv
source .ai_monitor/venv/bin/activate
pip install -e .        # pywin32/pythonnet은 sys_platform=='win32' 조건부라 mac에서 스킵됨

# 프론트엔드 빌드
cd .ai_monitor/vibe-view && npm install && npm run build && cd -

# 개발 모드 실행 (검증의 핵심)
python .ai_monitor/server.py
```

**전략**: `boot.py`(PyInstaller/frozen 진입점)가 아니라 `server.py`를 직접 실행하는
**개발 모드**로 먼저 UI를 띄운다. frozen/EXE 관련 종속(6번 카테고리)은 배포 단계에서만
문제이므로, 개발 모드 부팅이 되면 포팅의 80%는 검증된 것.

---

## 1. 마일스톤

| 단계 | 목표 | 산출물 |
|------|------|--------|
| **M1** | 맥 개발 모드에서 UI 부팅 (PG + 서버 + WebView) | `python server.py`로 창 뜸 |
| **M2** | 터미널(PTY) + 에이전트 실행 동작 | 채팅→CLI 에이전트, xterm 정상 |
| **M3** | 프로세스 관리 안정화 (좀비/정리) | 종료·재시작 시 좀비 없음 |
| **M4** | `.app` 배포 빌드 + 자동 업데이트 | dmg/pkg 설치본 |

M1~M2가 실질적 목표. M3~M4는 배포까지 갈 때만.

---

## 2. 이미 크로스플랫폼 (건드릴 필요 없음) ✅

조사에서 확인 — 아래는 **이미 mac 분기가 있거나 무해**하다. 재작성 금지, 회귀만 주의.

- `infra/proc.py` — `NO_WINDOW = CREATE_NO_WINDOW if win32 else 0`. mac에서 자동 0.
- `infra/postgres_runtime.py` — pg 바이너리 **경로 주입형**. 로직 자체는 이식 불필요.
- `infra/lifecycle.py` — 자식 정리에 `os.killpg(SIGTERM)` POSIX else 분기 이미 존재.
- `api/pty_api.py` — node-pty REST 프록시. 순수 HTTP, 플랫폼 무관.
- `api/agent_api.py:1252` / `fs_dialog_api.py:57` — win32 가드에 else 분기 존재.
- `bin/mcp_server.py`, `bin/codex_wrapper.py` — `getattr(...,0)` / `os.name` 가드됨.
- `server.py:624` DATA_DIR — frozen(Windows) else `~/.vibe-coding` 분기 존재
  (→ mac 관례 `~/Library/Application Support/VibeCoding`로 다듬으면 더 좋음).

---

## 3. High — 구조적 재작성 필요 🔴

### 3-1. 프로세스 관리 psutil화 (`infra/pty_process.py`) — 최우선
- **현재**: `wmic process where ...`, `taskkill /F /T /PID`, `tasklist`로 좀비 node 정리.
- **문제**: `wmic`/`taskkill`은 mac에 없음 (게다가 Win11 24H2에서 wmic 자체 제거 예정).
- **작업**: `psutil`로 전면 재작성 — `psutil.process_iter(['pid','cmdline','exe','ppid'])` +
  `p.children(recursive=True)` + `p.kill()`. **이러면 Windows/mac 양쪽 단일 코드로 통합됨** (이득 큼).
- **파급**: `heartbeat_daemon.py:296`, `daemons.py:111,200`, `agent_api.py:1253`(else 개선),
  `lifecycle.py:81` 도 같은 psutil 헬퍼로 흡수 권장 → 중복 제거(규칙: feedback_no_duplicates).
- **의존성**: `pyproject.toml`에 `psutil` 추가.

### 3-2. PostgreSQL mac 바이너리 번들 (`server.py:250-257`)
- **현재**: `bin/pgsql/bin/{psql,pg_ctl,initdb}.exe` (Windows 포터블 PG 18).
- **작업**:
  1. mac용 PostgreSQL 18 바이너리 확보 — Homebrew(`/opt/homebrew/opt/postgresql@18/bin`)
     또는 mac 포터블 빌드(EnterpriseDB/Postgres.app 내부 바이너리).
  2. `server.py:250-257` 경로 결정에 `sys.platform=='darwin'` 분기 추가, `.exe` 제거.
  3. `_PG_DATA_DIR`(`server.py:280`) → `~/Library/Application Support/VibeCoding/pgdata`.
- **주의**: 개발 모드에선 Homebrew PG를 쓰고, 배포(.app)에서만 번들 바이너리 → 단계 분리.
- `postgres_runtime.py` 로직은 그대로 재사용 가능 (경로만 주입 바꾸면 됨).

### 3-3. 아이콘/바로가기 (`create_shortcut.py`, `infra/win32_icon.py`)
- **현재**: `.lnk`(WScript.Shell/win32com), `.ico`, `FindWindowW`+`WM_SETICON`.
- **작업**: mac은 `.app` 번들 `Info.plist`의 `.icns`가 아이콘을 자동 처리 →
  `win32_icon.py` 전체를 mac에서 **no-op**로 가드. `create_shortcut.py`는 `.app` 별칭
  (`osascript 'make alias'`) 또는 그냥 스킵(mac은 앱 자체가 실행 단위).
- **삭제 후보**: `rebuild_icon_final.py`, `fix_icon_final.py`, `convert_icon.py`(Windows 전용 유틸).

### 3-4. 자동 업데이트 재시작 체인 (`updater.py`, `soft_updater.py`)
- **현재**: `_update.bat`+인라인 PowerShell로 `_MEI` node kill→폴더 삭제→`os.rename` exe swap.
- **작업**: mac은 `.app`/pkg 교체 + shell 스크립트(`ps`/`kill`/`rm`). **가장 복잡** — M4에서만.
- **단기 회피**: 개발 모드(M1~M2)에선 자동 업데이트 자체를 mac에서 비활성 가드로 두면 됨.

### 3-5. CLI 에이전트 런처 (`launch_api.py`, `install_api.py`, `tools_api.py`)
- **현재**: `start "" cmd.exe /k "cd /d ... && claude ..."` 로 새 콘솔에 CLI 실행.
- **작업**: mac은 `osascript -e 'tell app "Terminal" to do script "..."'` 또는 `open -a Terminal`.
  `cd /d`→`cd`, `&&`는 유지. `CREATE_NEW_CONSOLE`(install_api.py:340) 도 동일.

---

## 4. Medium — 경로·분기 추가 🟡

- **frozen 정적탐색 블록** (`boot.py:36-56`): `import clr / win32com / win32api / winpty` —
  mac 빌드에선 pywebview가 **Cocoa(WKWebView)** 백엔드라 전부 불필요. `sys.platform` 분기로 감싸기.
  또한 `boot.py:147-151` 인라인 `creationflags=0x08000000`은 mac에서 무의미 → win32 가드 필요.
- **APPDATA 경로 계열** (`server.py:280`, `pg_base.py:35`, `project_context.py:118`,
  `setup_doctor.py:32`, `tools_api.py:38`): `%APPDATA%\VibeCoding` →
  mac `~/Library/Application Support/VibeCoding`. **공용 헬퍼 1개로 통합** 권장(현재 산재).
- **venv 경로** (`runtime.py:28`, `create_shortcut.py:143`, `tools_api.py:384`, `codex_wrapper.py:39`):
  `venv\Scripts\python.exe`/`pythonw.exe` → `venv/bin/python` (mac은 `pythonw` 없음).
- **외부 도구 탐색** (`tools_api.py`): `%ProgramFiles%`/`winreg` Uninstall 키 →
  mac `/Applications`, `/opt/homebrew/bin`, `/usr/local/bin`, `mdfind`/`which`.
- **클립보드** (`server.py:1082`): `powershell Set-Clipboard` → mac `pbcopy`
  (참고: WebView2 clipboard LF→CRLF 이슈는 mac WKWebView엔 무관).
- **방화벽** (`lan_bridge.py:111`): `netsh advfirewall` → mac은 대개 불필요(스킵) 또는 `socketfilterfw`.

---

## 5. 배포 빌드 (M4) — `.spec` / CI

- `vibe-coding.spec`은 Windows onedir 전제: `import winpty`(L38), winpty 4종 바이너리,
  `icon=.ico`, `win32com/clr` hiddenimports, `boot.py` 진입점.
- **작업**: 별도 `vibe-coding-mac.spec` 작성 —
  - winpty 바이너리/hiddenimports(clr/win32*) 제거
  - `icon=app_icon.icns`, `BUNDLE()` 추가해 `.app` 생성 (`argv_emulation=True`)
  - mac PG 바이너리를 `datas`/`binaries`에 포함
- **CI**: `.github/workflows/`에 macOS 러너(`runs-on: macos-latest`) job 추가.
  spec ↔ CI `--add-data` **양쪽 동시 갱신** 필수 (과거사고 v3.7.215~218 — feedback_spec_datas_check).

---

## 6. 삭제/정리 후보 (Windows 전용)

`test_pty.py`, `test_winpty.py`(winpty 이미 은퇴), `rebuild_icon_final.py`,
`fix_icon_final.py`, `convert_icon.py`. — mac 포팅과 무관, 정리 시 함께.

---

## 7. 권장 진행 순서 (맥 세션에서)

1. **M1-a**: Homebrew PG로 `server.py:250` 경로 mac 분기 → `python server.py` 부팅 시도.
   부팅 막는 win32 import를 하나씩 `sys.platform` 가드. **여기서 UI 뜨면 큰 산 넘음.**
2. **M1-b**: APPDATA/venv 경로 헬퍼 통합 (4번).
3. **M2**: `pty_process.py` psutil화 (3-1) → 터미널·에이전트 동작.
4. **M3**: 좀비/정리 psutil로 마무리, 종료 안정화.
5. **M4**: `.app` spec + CI (배포가 필요할 때만).

각 단계 후 `python scripts/checkpoint.py`로 기록 — 세션 튕겨도 이어받게.
```
