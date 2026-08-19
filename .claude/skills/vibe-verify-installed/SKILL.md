---
name: vibe-verify-installed
description: >
  "개발에선 되는데 설치본에서 안 된다" 류를 추측 없이 실측으로 가르는 절차.
  설치본을 띄워 실제 엔드포인트를 때리고, 창·프로세스·포그라운드를 관측해 원인을 좁힌다.
  Use when: "설치 버전에서 안 돼", "개발에선 되는데", "빌드하기 전에 확인", EXE 전용 버그,
  "왜 여기선 되는데", 배포 전 회귀 확인 시.
user-invocable: true
---

<!--
FILE: .claude/skills/vibe-verify-installed/SKILL.md
DESCRIPTION: 설치본(frozen EXE) 전용 결함을 실측으로 재현·검증하는 절차 스킬.

[🔴 이 스킬이 생긴 이유 — 2026-08-11 하루에 오진 3연발]
  "설치본에서 폴더 변경이 안 된다"를 두고 추측만으로 세 번 틀렸다.
    ① "파이썬이 없어서" → 하트비트가 외부 파이썬으로 5분마다 돌고 있었다(반증)
    ② "tkinter 가 없어서" → 두 인터프리터 모두 tkinter OK(반증)
    ③ "설치본이 다른 파이썬을 고른다" → 후보 목록이 개발본과 **완전히 동일**(반증)
  실제 원인은 넷째였다 — 다이얼로그는 **정상적으로 열리되 앱 창 뒤에** 열린다.
  창을 실제로 열거해 보고 GetForegroundWindow 를 재는 순간 5분 만에 드러났다.
  교훈: EXE 결함은 코드를 노려보지 말고 **띄워서 관측**한다.

REVISION HISTORY:
- 2026-08-11 Claude: 최초 작성 — 위 사고 직후 사용자 요청("테스트도 스킬로 만들어").
-->

# 설치본 실측 검증

**원칙: 코드를 읽어 추론하기 전에, 설치본을 띄워 관측한다.** 추론은 관측 뒤에 한다.

## 0단계 — 과거 사고 조회 (필수)

```bash
python scripts/incident.py search "<증상 키워드>"
```

## 1단계 — 설치본 실체 확인

버전이 저장소와 다를 수 있다. **어떤 코드가 도는지 먼저 못 박는다.**

```powershell
$root = "$env:LOCALAPPDATA\Programs\VibeCoding"
Get-Content "$root\_internal\_version.py"          # 실제 설치된 버전
Get-ChildItem "$root\_internal\<의심 모듈>.py"      # 그 버전의 소스를 직접 읽는다
```

- 설치본 버전이 저장소보다 낮으면 **지금 고친 코드는 거기 없다** — 재현되는 것이
  현재 결함인지 옛 결함인지부터 가른다.
- 개발/설치본은 config.json 이 갈린다(`%APPDATA%\VibeCoding` vs `.ai_monitor/data`).
  둘 중 어느 쪽을 앱이 보는지 항상 경로째로 확인한다.

## 2단계 — 띄우고 포트 찾기

```powershell
Start-Process "$env:LOCALAPPDATA\Programs\VibeCoding\vibe-coding.exe"
Start-Sleep 15
Get-NetTCPConnection -State Listen | Where-Object { $_.LocalPort -ge 9000 -and $_.LocalPort -le 9019 } |
  ForEach-Object { "{0} pid={1} {2}" -f $_.LocalPort, $_.OwningProcess, (Get-Process -Id $_.OwningProcess).Path }
```

개발본이 9000 을 잡고 있으면 설치본은 **다른 포트**를 쓴다(9000~9009 스캔).
`find_server_port()` 를 믿지 말 것 — 그건 이 프로젝트 기준 포트를 고른다.

## 3단계 — 엔드포인트를 직접 때리며 관측

프론트를 클릭하지 말고 API 를 때린다. 클릭은 실패 지점이 프론트인지 백엔드인지 안 가른다.

관측 3종을 **동시에** 건다 — 하나만 보면 오판한다:

| 관측 | 도구 | 놓치면 생기는 오판 |
|------|------|--------------------|
| 자식 프로세스 | `Get-CimInstance Win32_Process` + CommandLine | "스폰조차 안 됐다"고 오판 |
| 보이는 창 | `EnumWindows` + 클래스명 | "창이 안 떴다"고 오판 |
| 포그라운드 | `GetForegroundWindow` | "안 뜬다"와 "뒤에 뜬다"를 못 가름 |

```python
# 🔴 argtypes 를 반드시 선언한다 — 없으면 HWND 가 32비트로 잘려 조용히 0건이 된다
u.EnumWindows.argtypes = [P, wintypes.LPARAM]
u.GetClassNameW.argtypes = [wintypes.HWND, wintypes.LPWSTR, ctypes.c_int]
```

- **창은 제목이 아니라 클래스로 찾는다.** 공용 다이얼로그 캡션은 API 인자와 다르다
  (`SHBrowseForFolderW` 의 `lpszTitle` 은 캡션이 아니라 안내 문구, 캡션은 '폴더 찾아보기').
  `Get-Process | MainWindowTitle` 은 소유 창이 숨겨진 다이얼로그를 **못 본다** — EnumWindows 를 쓴다.
- 요청은 **별도 스레드/잡**으로 쏘고 그 사이에 관측한다. 동기로 쏘면 모달에 붙잡혀 아무것도 못 본다.

## 4단계 — 원인 후보를 실측으로 하나씩 죽인다

"~라서 안 될 것이다"는 전부 **반증 가능한 명제**로 바꿔 재본다.

```bash
# 예: "그 PC에 파이썬이 없어서" → 있는지 재라
python -c "import shutil; print(shutil.which('python'))"
# 예: "설치본이 다른 인터프리터를 고른다" → 두 경우를 같이 출력해 대조하라
```

한 후보를 죽일 때마다 근거(명령 + 출력)를 남긴다. 근거 없이 다음 후보로 넘어가면
같은 후보로 되돌아온다.

## 5단계 — 고친 뒤 검증은 '실사용 조건'에서

- 서버 코드는 **워커 스레드**에서 돈다. 메인 스레드 테스트만 통과시키면 안 된다 —
  COM 초기화처럼 스레드에 따라 갈리는 API 는 메인에서만 우연히 통과한다(실제 사고).
- 다이얼로그류는 사람이 클릭할 필요 없이 검증한다: 창을 찾아 `PostMessage(WM_CLOSE)` 로
  닫고 **취소 반환값**을 확인한다.
- 테스트가 띄운 창·프로세스는 반드시 정리한다. 남기면 다음 관측이 오염된다.

## 🔴 6단계 — 「됐다」의 마지막 자리: **다른 PC 에 깔아 본다** (결재 17)

**여기까지 안 하면 완료가 아니다.** 1~6단계는 *이 PC* 얘기다.

사장 승인 2026-08-16, 원문: *"다른 PC 에 깔아보고 말하는 거야"*

| 이것만으로는 완료가 **아니다** | 완료다 |
|---|---|
| CI 초록불 | 그 PC 에 **깔았다** |
| 릴리즈 발행됨 | 앱을 **열었다** |
| 내 PC 에서 된다 | 문제 기능을 **실제로 눌러 봤다** |

- **확인 자리 = 아픽스3** (사장이 안 쓰시는 PC).
  🔴 사장님 PC 에서 확인하지 마라 — **이미 돌고 있던 앱**을 보고 「된다」고 읽는다.
- 🔴 **실측 사고**: v3.7.340 을 CI 성공·릴리즈 발행만 보고 「배포 완료」로 보고했는데
  깐 판에서는 **마이크도 edge-tts 도 안 됐다.** 팀원이 확인한 것이 돌고 있던 앱이었다.

**최소 확인 3줄** — 깐 PC 에서:

```powershell
Get-Content "$env:LOCALAPPDATA\Programs\VibeCoding\_internal\_version.py"   # 판이 맞나
Start-Process "$env:LOCALAPPDATA\Programs\VibeCoding\vibe-coding.exe"         # 열린다
# 고친 기능을 손으로 눌러 본다 — 이것이 빠지면 위 두 줄은 의미가 없다
```

🔴 **보고에는 「어느 PC 에서 · 어느 판을 · 무엇을 눌렀나」를 적는다.**
"됐다"만 적으면 무엇을 확인했는지 아무도 모른다.

## 7단계 — 마무리

```bash
python scripts/incident.py record --error "..." --cause "..." --fix "..."
```

빌드는 검증 뒤에. 설치본 전용 결함은 `/vibe-release` 로 내보내야 실환경에 반영된다
(소스만 고치면 그 PC는 그대로다).
