; ────────────────────────────────────────────────────────────────────────────
; 파일명: vibe-coding-setup.iss
; 설명: Vibe Coding Windows 설치버전 빌드 스크립트 (Inno Setup 6)
;       PyInstaller로 생성된 vibe-coding-vX.Y.Z.exe를 설치 패키지로 포장.
;       결과물: dist/vibe-coding-setup-X.Y.Z.exe
;
; 빌드 방법:
;   1. Inno Setup 6 설치: https://jrsoftware.org/isinfo.php
;   2. PyInstaller EXE 먼저 빌드 (pyinstaller vibe-coding.spec --noconfirm)
;   3. ISCC.exe "vibe-coding-setup.iss"
;      또는 Inno Setup Compiler에서 이 파일 열고 Build > Compile
;
; 변경 이력:
; [2026-07-10] Claude — [설치/제거 DLL 잠금] onedir 재설치 시 "DeleteFile 실패; 코드 5:
;              ...\pgsql\bin\libcrypto-3-x64.dll" 사고. 근본원인: vibe-coding.exe만 taskkill →
;              자식 postgres.exe/node.exe가 고아로 살아남아 pgsql DLL 잠금. onefile은 DLL이 _MEI
;              추출이라 안 잠겼으나 onedir은 설치폴더 직접 배치라 잠금 노출. → InitializeSetup +
;              [UninstallRun]에서 '경로가 VibeCoding 설치폴더 밑'인 프로세스만 스코프 종료(KillLockingProcesses).
; [2026-07-10] Claude — [바로가기 복구] onefile→onedir per-user 전환 사고 대응.
;              구 설치(%LOCALAPPDATA%\VibeCoding\app)에서 신 경로(%LOCALAPPDATA%\Programs\VibeCoding)로
;              이사하며 바탕화면/시작메뉴 .lnk가 죽은 옛 경로를 계속 가리켜 "아이콘 눌러도 무반응" 사고.
;              silent 업데이트는 desktopicon(기본 unchecked) task를 안 돌려 새 바로가기도 안 생김.
;              → [Run]에서 죽은 VibeCoding .lnk를 새 {app}\exe로 repoint + InitializeSetup에서 구 빈 폴더 청소.
; [2026-05-26] Claude — [Registry] 섹션 추가: 시스템 환경변수 VIBE_HIVE_HOOK 등록 (B3)
;              설치 EXE 단독 PC에서도 install_hive_hooks.py가 자동으로 EXE 경로를
;              찾을 수 있도록 HKLM\...\Environment에 vibe-coding.exe 절대경로를 박는다.
;              제거 시 함께 삭제(uninsdeletevalue) — 잔여 환경변수 방지.
; [2026-05-05] Claude — PrivilegesRequired=admin 강제 (v3.7.221)
;              v3.7.220의 Defender 예외 자동 등록이 lowest 권한에서 SilentlyContinue로
;              조용히 실패하던 문제 수정. admin 강제 → UAC 1회로 모든 단계 정상 권한 확보.
;              {autopf}는 Program Files로 고정, 구버전(LocalAppData)은 자동 제거 로직이 처리.
; [2026-05-05] Claude — Windows Defender 예외 자동 등록 추가 (v3.7.220)
;              [Run] 섹션에서 PowerShell로 Add-MpPreference 자동 호출.
;              PyInstaller EXE의 _MEI 추출 시 python311.dll 격리 사고 자동 방지.
;              setup.exe 자체는 Inno Setup 빌드라 Defender가 안 막지만, 설치 후 실행되는
;              vibe-coding.exe(PyInstaller)는 새 hash마다 격리 위험 → 사전 예외 등록.
;              실패해도 무시(SilentlyContinue) — 비관리자 환경 대비.
; [2026-03-16] Claude — 설치 폴더 영문화 (바이브코딩→VibeCoding), 아이콘/표시명만 한글 유지 (v3.7.78)
;              MyAppName="VibeCoding"(폴더용), MyAppDisplayName="바이브코딩"(UI표시용) 분리
; [2026-03-11] Claude — PostgreSQL 포터블 바이너리 자동 설치 추가 (v3.7.48)
;              {app}\pgsql\ 에 bin/lib/share 포함. initdb 및 포트 설정은 server.py가 최초 기동 시 수행.
; [2026-03-08] Claude — 설치 EXE 고정 파일명(vibe-coding.exe)으로 변경. 버전 업 시 자동 덮어쓰기
; [2026-03-01] Claude — 최초 생성. 포터블 EXE → 설치버전 파이프라인 구축
; ────────────────────────────────────────────────────────────────────────────

#define MyAppName      "VibeCoding"
#define MyAppDisplayName "바이브코딩"
; CI에서 /DMyAppVersion=X.Y.Z 로 오버라이드 가능
#ifndef MyAppVersion
  #define MyAppVersion   "3.7.261"
#endif
#define MyAppPublisher "Vibe Coding Team"
#define MyAppURL       "https://github.com/btsky99/vibe-coding"
#define MyAppExeName   "vibe-coding.exe"
; CI에서 /DMyAppExeName=... 으로 소스 EXE 파일명 오버라이드 가능
#ifndef MyAppSrcExe
  #define MyAppSrcExe    "vibe-coding-v" + MyAppVersion + ".exe"
#endif
; [전략 #2a onedir] PyInstaller onedir 결과 폴더/내부 exe명 (spec _EXE_NAME과 일치, 버전 파생).
;   onedir: dist/<MyOneDirName>/<MyOneDirName>.exe + dist/<MyOneDirName>/_internal/
#define MyOneDirName   "vibe-coding-v" + MyAppVersion
#define MySetupName    "vibe-coding-setup-" + MyAppVersion

[Setup]
; 앱 기본 정보
AppId={{A1B2C3D4-E5F6-7890-ABCD-EF1234567890}
AppName={#MyAppDisplayName}
AppVersion={#MyAppVersion}
AppPublisher={#MyAppPublisher}
AppPublisherURL={#MyAppURL}
AppSupportURL={#MyAppURL}
AppUpdatesURL={#MyAppURL}

; [전략 #2a per-user] 설치 경로: %LOCALAPPDATA%\Programs\VibeCoding (사용자 폴더 → admin 불필요).
;   onedir이 _MEI 추출을 없애 Defender 격리 리스크가 사라져 admin 정당성 소멸 → per-user로 전환.
;   효과: 업데이트(setup /SILENT)마다 뜨던 UAC 제거 = 완전 무음 업데이트(onedir의 핵심 목적).
DefaultDirName={localappdata}\Programs\{#MyAppName}
DefaultGroupName={#MyAppName}
AllowNoIcons=yes

; 출력 설정
OutputDir=.ai_monitor\dist
OutputBaseFilename={#MySetupName}
Compression=lzma2/ultra64
SolidCompression=yes
WizardStyle=modern

; [전략 #2a per-user] admin → lowest. onedir은 _MEI 추출이 없어 Defender 예외 등록(admin 필요)이
;   불필요해졌다. lowest면 UAC 없이 설치/업데이트 → 무음 업데이트 성립.
;   [주의] Add-MpPreference([Run])는 lowest에서 실패하지만 SilentlyContinue + onedir이라 무해.
;   [불변식] VIBE_HIVE_HOOK 레지스트리는 HKCU 분기(Check: not IsAdminInstallMode)가 처리 — 이미 대응됨.
PrivilegesRequired=lowest
; 설치 전 실행 중인 앱 자동 종료 (덮어쓰기 허용) — 업데이트 시 실행 중 vibe-coding을 닫고 교체.
CloseApplications=yes
CloseApplicationsFilter=*vibe-coding*

; 환경변수 변경 시 WM_SETTINGCHANGE 자동 broadcast — VIBE_HIVE_HOOK 등록을 새 셸에 즉시 반영
; [2026-05-26] B3 — 외부 프로젝트가 설치 EXE만 있는 PC에서도 hive_hook 자동 발견 가능
ChangesEnvironment=yes

; 아이콘 — vibe_final.ico를 설치 폴더에 복사 후 바로가기에 명시적 지정
; (자동 업데이트로 EXE만 교체해도 아이콘이 최신 상태로 유지됨)
SetupIconFile=.ai_monitor\bin\vibe_final.ico
UninstallDisplayIcon={app}\vibe_final.ico

[Languages]
Name: "korean"; MessagesFile: "compiler:Languages\Korean.isl"
Name: "english"; MessagesFile: "compiler:Default.isl"

[Tasks]
Name: "desktopicon";    Description: "바탕화면 바로가기 만들기"; GroupDescription: "추가 아이콘:"; Flags: unchecked
Name: "startupicon";    Description: "시작 시 자동 실행";         GroupDescription: "추가 옵션:";  Flags: unchecked

[Files]
; [전략 #2a onedir] PyInstaller onedir 결과 — 메인 exe + _internal 폴더를 함께 설치.
;   메인 exe는 고정명(vibe-coding.exe)으로 리네임, _internal은 폴더째 복사. onedir exe는 자기
;   옆의 _internal을 찾으므로 리네임해도 정상 동작. (구 onefile 단일 exe 방식 폐기 —
;   매 부팅 _MEI 추출/좀비 node/DLL로드실패 버그 클래스를 구조적으로 제거.)
;   [불변식] _internal은 반드시 {app}\_internal (exe 형제) — 위치 어긋나면 부팅 실패.
Source: ".ai_monitor\dist\{#MyOneDirName}\{#MyOneDirName}.exe"; DestDir: "{app}"; DestName: "{#MyAppExeName}"; Flags: ignoreversion
Source: ".ai_monitor\dist\{#MyOneDirName}\_internal\*"; DestDir: "{app}\_internal"; Flags: ignoreversion recursesubdirs createallsubdirs
; 아이콘 파일 — 자동 업데이트 후에도 바로가기 아이콘이 유지되도록 별도 배포
Source: ".ai_monitor\bin\vibe_final.ico"; DestDir: "{app}"; Flags: ignoreversion
; Claude Code 상태줄 스크립트 — 설치 PC의 %USERPROFILE%\.claude\ 에 복사
; [과거사고] c330a45에서 루트 statusline.py를 scripts/로 이동 후 이 경로 미갱신 →
; CI "Build installer" 실패 → v3.7.230 릴리즈 미게시 → 설치 버전 업데이트 알림 중단.
; 파일 이동 시 vibe-coding.spec / build-release.yml --add-data / 이 .iss 3곳 동기화 필수.
Source: "scripts\statusline.py"; DestDir: "{%USERPROFILE}\.claude"; Flags: ignoreversion
; Playwright CLI 설치 스크립트 (앱 내부 AI 도구 메뉴에서 수동 실행용)
Source: "scripts\install_playwright_cli.py"; DestDir: "{app}\scripts"; Flags: ignoreversion

; ── 서브창 EXE (별도 PyInstaller 빌드) ─────────────────────────────────────
; server.py가 frozen 모드에서 Python 서브프로세스 대신 이 EXE들을 직접 실행.
Source: ".ai_monitor\dist\vibe-dashboard.exe"; DestDir: "{app}"; Flags: ignoreversion skipifsourcedoesntexist
; vibe-kanban.exe 제거됨 — B안 통합: vibe-dashboard.exe kanban 탭으로 실행

; ── PostgreSQL 포터블 바이너리 (pgAdmin 4 제외, 필수 파일만 포함 — ~142MB) ──
; server.py가 최초 기동 시 ensure_postgres_running()으로 initdb + pg_ctl start 자동 수행.
; data/ 폴더는 포함하지 않음 → 각 PC의 %APPDATA%\VibeCoding\pgdata\ 에 새로 생성됨.
Source: ".ai_monitor\bin\pgsql\bin\*"; DestDir: "{app}\pgsql\bin"; Flags: ignoreversion recursesubdirs createallsubdirs
Source: ".ai_monitor\bin\pgsql\lib\*"; DestDir: "{app}\pgsql\lib"; Flags: ignoreversion recursesubdirs createallsubdirs
Source: ".ai_monitor\bin\pgsql\share\*"; DestDir: "{app}\pgsql\share"; Flags: ignoreversion recursesubdirs createallsubdirs

[Registry]
; ── VIBE_HIVE_HOOK 시스템 환경변수 등록 ──────────────────────────────────
; [2026-05-26] B3 — 외부 프로젝트가 dev 체크아웃 없이도 설치 EXE를 hook 진입점으로 찾을 수 있게 함.
; install_hive_hooks.py가 우선 탐색하는 변수. 값이 .exe이면 EXE 모드(`<exe> hook`),
; .py/디렉토리면 Python 모드로 동작한다.
; uninsdeletevalue: 제거 시 값 자동 삭제. preservestringtype: REG_EXPAND_SZ 유지.
; [과거사고 v3.7.226~230] HKLM 무조건 쓰기 → "현재 사용자용 설치"(비관리자 모드)에서 액세스 거부(코드 5)
; 레지스트리 에러 팝업. IsAdminInstallMode로 분기 — 비관리자는 HKCU\Environment에 동일 변수 등록.
Root: HKLM; Subkey: "SYSTEM\CurrentControlSet\Control\Session Manager\Environment"; ValueType: expandsz; ValueName: "VIBE_HIVE_HOOK"; ValueData: "{app}\{#MyAppExeName}"; Flags: preservestringtype uninsdeletevalue; Check: IsAdminInstallMode
Root: HKCU; Subkey: "Environment"; ValueType: expandsz; ValueName: "VIBE_HIVE_HOOK"; ValueData: "{app}\{#MyAppExeName}"; Flags: preservestringtype uninsdeletevalue; Check: not IsAdminInstallMode

[Icons]
; 시작 메뉴 — 폴더는 영문(MyAppName), 아이콘 표시명은 한글(MyAppDisplayName)
Name: "{group}\{#MyAppDisplayName}";             Filename: "{app}\{#MyAppExeName}"; IconFilename: "{app}\vibe_final.ico"
Name: "{group}\{#MyAppDisplayName} 제거";        Filename: "{uninstallexe}"
; 바탕화면 (선택) — 아이콘 이름만 한글
Name: "{autodesktop}\{#MyAppDisplayName}";       Filename: "{app}\{#MyAppExeName}"; IconFilename: "{app}\vibe_final.ico"; Tasks: desktopicon
; 시작프로그램 (선택) — 아이콘 이름만 한글
Name: "{userstartup}\{#MyAppDisplayName}";       Filename: "{app}\{#MyAppExeName}"; IconFilename: "{app}\vibe_final.ico"; Tasks: startupicon


[Run]
; ── Windows Defender 예외 자동 등록 ──────────────────────────────────────
; PyInstaller EXE는 매 빌드마다 새 hash → Defender의 reputation check가
; 추출된 python311.dll을 격리하는 사고 다발. 설치 폴더와 추출 디렉토리(%APPDATA%
; \VibeCoding\runtime)를 사전 예외 등록하여 자동 업데이트 시점에도 격리 방지.
; 비관리자/Defender 미사용 환경에서도 SilentlyContinue로 무해하게 패스.
Filename: "powershell.exe"; Parameters: "-NoProfile -ExecutionPolicy Bypass -Command ""try {{ Add-MpPreference -ExclusionPath ('{app}') -ErrorAction SilentlyContinue }} catch {{}}; try {{ Add-MpPreference -ExclusionPath ($env:APPDATA + '\VibeCoding') -ErrorAction SilentlyContinue }} catch {{}}"""; Flags: runhidden; StatusMsg: "Windows Defender 예외 등록 중..."

; Claude Code settings.json에 statusLine 자동 설정
; — .claude 폴더 생성 + settings.json 읽어서 statusLine 키 추가/갱신 후 저장
Filename: "powershell.exe"; Parameters: "-NoProfile -ExecutionPolicy Bypass -Command ""$p = Join-Path $env:USERPROFILE '.claude'; if (-not (Test-Path $p)) {{ New-Item -ItemType Directory -Path $p | Out-Null }}; $f = Join-Path $p 'settings.json'; $d = if (Test-Path $f) {{ Get-Content $f -Raw -Encoding UTF8 | ConvertFrom-Json }} else {{ [PSCustomObject]@{{}} }}; $sl = [PSCustomObject]@{{ type = 'command'; command = 'python ' + (Join-Path $env:USERPROFILE '.claude\statusline.py') }}; $d | Add-Member -NotePropertyName 'statusLine' -NotePropertyValue $sl -Force; $d | ConvertTo-Json -Depth 10 | Set-Content $f -Encoding UTF8"""; Flags: runhidden; Description: "Claude Code 상태줄 설정 적용"
; ── 구 설치 바로가기 경로 복구 ──────────────────────────────────────────
; [과거사고 2026-07-10] onefile(admin, %LOCALAPPDATA%\VibeCoding\app) → onedir(per-user,
;   %LOCALAPPDATA%\Programs\VibeCoding) 전환 시 exe 경로가 이사. 구 설치의 바탕화면/시작메뉴
;   .lnk가 죽은 옛 경로를 계속 가리켜 "아이콘 눌러도 무반응" 사고. silent 업데이트는
;   desktopicon(기본 unchecked) task를 안 돌려 새 바로가기도 생기지 않음.
;   → Desktop/StartMenu(사용자+공용)에서 VibeCoding을 가리키지만 타깃이 사라진 .lnk를 찾아
;     새 {app}\exe로 repoint. 정상 타깃(Test-Path True)은 건드리지 않음(멱등).
;   [불변식] skipifsilent 금지 — 이 복구는 무음 업데이트에서 반드시 실행돼야 함(그게 주 사고 경로).
Filename: "powershell.exe"; Parameters: "-NoProfile -ExecutionPolicy Bypass -Command ""$new='{app}\{#MyAppExeName}'; $ws=New-Object -ComObject WScript.Shell; $dirs=@([Environment]::GetFolderPath('Desktop'),[Environment]::GetFolderPath('Programs'),[Environment]::GetFolderPath('CommonDesktopDirectory'),[Environment]::GetFolderPath('CommonPrograms')); Get-ChildItem $dirs -Filter *.lnk -Recurse -EA SilentlyContinue | ForEach-Object {{ try {{ $sc=$ws.CreateShortcut($_.FullName); if(($sc.TargetPath -like '*VibeCoding*vibe-coding.exe') -and -not (Test-Path $sc.TargetPath)){{ $sc.TargetPath=$new; $sc.WorkingDirectory=Split-Path $new; if(Test-Path ('{app}\vibe_final.ico')){{ $sc.IconLocation='{app}\vibe_final.ico' }}; $sc.Save() }} }} catch {{}} }}"""; Flags: runhidden; StatusMsg: "구 바로가기 경로 복구 중..."
Filename: "{app}\{#MyAppExeName}"; Description: "{#MyAppDisplayName} 시작"; Flags: nowait postinstall skipifsilent

[UninstallRun]
; 제거 전 실행 중인 프로세스 종료 — 앱 + 자식 postgres.exe/node.exe(pgsql DLL 잠금 방지).
; [과거사고 2026-07-10] vibe-coding.exe만 죽이면 자식 postgres가 살아남아 pgsql\bin\*.dll 잠금 →
;   제거 시 파일 삭제 실패(코드 5). 경로가 VibeCoding 설치폴더 밑인 프로세스만 스코프 종료(개발/타 PG 무관).
Filename: "powershell.exe"; Parameters: "-NoProfile -ExecutionPolicy Bypass -Command ""Get-CimInstance Win32_Process | Where-Object {{ $_.ExecutablePath -like '*VibeCoding*' }} | ForEach-Object {{ try {{ Stop-Process -Id $_.ProcessId -Force -ErrorAction SilentlyContinue }} catch {{}} }}"""; Flags: runhidden; RunOnceId: "KillVibeChildren"
Filename: "taskkill.exe"; Parameters: "/F /IM vibe-coding.exe"; Flags: runhidden; RunOnceId: "KillVibeCoding"

[Code]
// ── 구버전 자동 제거 로직 ──────────────────────────────────────────────
// 동일 AppId를 가진 이전 설치를 감지하여, 설치 전 자동으로 제거합니다.
// 이전에 InitializeSetup()이 비어있어 구버전(3.7.64 등)이 프로그램 목록에
// 계속 남아있는 문제를 해결합니다.
// [2026-03-15 Claude: 구버전 자동 제거 로직 추가 — 프로그램 중복 등록 방지]
function GetUninstallString(): String;
var
  sUnInstPath: String;
  sUnInstallString: String;
begin
  // 레지스트리에서 현재 AppId의 UninstallString 조회
  sUnInstPath := 'Software\Microsoft\Windows\CurrentVersion\Uninstall\{#SetupSetting("AppId")}_is1';
  sUnInstallString := '';
  // HKLM (관리자 설치) 또는 HKCU (사용자 설치) 모두 확인
  if not RegQueryStringValue(HKLM, sUnInstPath, 'UninstallString', sUnInstallString) then
    RegQueryStringValue(HKCU, sUnInstPath, 'UninstallString', sUnInstallString);
  Result := sUnInstallString;
end;

// ── (레거시) PyInstaller _MEI* 잔여 디렉터리 정리 ──────────────────────
// [2026-07-10 전략 #2a] 신규 빌드는 onedir이라 _MEI 추출 자체가 없다. 이 정리는 이제
//   '구 onefile 설치본 → onedir 전환' 시 남아있는 레거시 _MEI 잔재를 청소하는 용도로 유지한다.
//   (구 onefile: 실행 시 %APPDATA%\VibeCoding\runtime\_MEI*에 DLL 추출 → 비정상 종료 시 잔존 →
//    python DLL 로드 실패 유발. 전환 설치가 이를 제거해 깨끗한 상태에서 onedir로 넘어간다.)
procedure CleanupMEIDirectories();
var
  TempDir: String;
  RuntimeDir: String;
  FindRec: TFindRec;
  FullPath: String;
begin
  // 1. %TEMP%\_MEI* 잔여 폴더 정리
  TempDir := ExpandConstant('{tmp}\..'); // %TEMP% 디렉터리
  if FindFirst(TempDir + '\_MEI*', FindRec) then begin
    try
      repeat
        if FindRec.Attributes and FILE_ATTRIBUTE_DIRECTORY <> 0 then begin
          FullPath := TempDir + '\' + FindRec.Name;
          DelTree(FullPath, True, True, True);
        end;
      until not FindNext(FindRec);
    finally
      FindClose(FindRec);
    end;
  end;

  // 2. runtime-tmpdir 경로 생성 (%APPDATA%\VibeCoding\runtime)
  RuntimeDir := ExpandConstant('{userappdata}\VibeCoding\runtime');
  if not DirExists(RuntimeDir) then
    ForceDirectories(RuntimeDir);

  // 3. runtime-tmpdir 내 _MEI* 잔여 폴더도 정리
  if FindFirst(RuntimeDir + '\_MEI*', FindRec) then begin
    try
      repeat
        if FindRec.Attributes and FILE_ATTRIBUTE_DIRECTORY <> 0 then begin
          FullPath := RuntimeDir + '\' + FindRec.Name;
          DelTree(FullPath, True, True, True);
        end;
      until not FindNext(FindRec);
    finally
      FindClose(FindRec);
    end;
  end;
end;

// ── 설치폴더에서 도는 잠금 프로세스 전멸 (postgres.exe / node.exe 포함) ──
// [과거사고 2026-07-10 v3.7.250] onedir 전환 후 재설치 시
//   "DeleteFile 실패; 코드 5(액세스 거부): ...\pgsql\bin\libcrypto-3-x64.dll" 발생.
//   [근본원인] InitializeSetup이 vibe-coding.exe 하나만 taskkill → 부모가 띄운
//     자식 postgres.exe(내장 PG)·node.exe(PTY 서버)가 고아로 살아남아 pgsql DLL을
//     계속 잠금 → 파일 덮어쓰기 불가. onefile 시절엔 DLL이 %TEMP%\_MEI에 추출돼
//     설치폴더가 안 잠겼으나, onedir은 DLL이 설치폴더에 직접 놓여 잠금이 그대로 드러남.
//   [해법] 이미지명(IM)이 아니라 '실행 경로가 VibeCoding 설치폴더 밑'인 프로세스만
//     골라 죽인다 → 남의 PostgreSQL/Node나 개발 체크아웃(경로가 'vibe-coding' 하이픈,
//     'VibeCoding'와 불일치)은 절대 안 건드림. -like는 대소문자 무시지만 하이픈 유무로 분리됨.
//   [불변식] vibe-coding.exe 단독 taskkill만으로는 부족 — 자식 DB/PTY까지 반드시 정리.
procedure KillLockingProcesses();
var
  iResultCode: Integer;
  sPs: String;
begin
  // 경로 기준 스코프 종료: ExecutablePath가 '*VibeCoding*'인 프로세스 전부 강제 종료.
  //   postgres.exe / node.exe / vibe-coding.exe / vibe-dashboard.exe 모두 포함됨.
  sPs :=
    'Get-CimInstance Win32_Process | ' +
    'Where-Object { $_.ExecutablePath -like ''*VibeCoding*'' } | ' +
    'ForEach-Object { try { Stop-Process -Id $_.ProcessId -Force -ErrorAction SilentlyContinue } catch {} }';
  Exec('powershell.exe',
       '-NoProfile -ExecutionPolicy Bypass -Command "' + sPs + '"',
       '', SW_HIDE, ewWaitUntilTerminated, iResultCode);
  // 이미지명 폴백(경로 없는 좀비 대비) — 개발 postgres/node는 위 경로필터에서 이미 제외됐고
  //   여기선 vibe-coding.exe만 IM으로 마무리 (postgres/node를 IM으로 죽이면 개발 것까지 죽으므로 금지).
  Exec('taskkill.exe', '/F /IM vibe-coding.exe', '', SW_HIDE, ewWaitUntilTerminated, iResultCode);
end;

function InitializeSetup(): Boolean;
var
  iResultCode: Integer;
  sUnInstallString: String;
begin
  Result := True;

  // 실행 중인 앱 + 자식 프로세스(postgres.exe/node.exe) 강제 종료 (DLL 잠금 방지)
  KillLockingProcesses();
  // 잠시 대기하여 프로세스 종료 및 파일 잠금 해제 완료 대기
  Sleep(1500);

  // PyInstaller _MEI* 잔여 폴더 정리 (python311.dll 로드 실패 방지)
  CleanupMEIDirectories();

  // [과거사고 2026-07-10] onefile(구 %LOCALAPPDATA%\VibeCoding\app) → onedir(신 %LOCALAPPDATA%\Programs\VibeCoding)
  //   전환 후 구 설치 폴더가 exe 없이 빈 껍데기로 남아 죽은 바로가기의 원인이 됨. 잔재 폴더 청소.
  //   [주의] pgdata는 %APPDATA%(Roaming)\VibeCoding 이라 무관 — 여기서 지우는 건 Local의 구 프로그램 폴더뿐.
  if DirExists(ExpandConstant('{localappdata}\VibeCoding\app')) then
    DelTree(ExpandConstant('{localappdata}\VibeCoding\app'), True, True, True);

  sUnInstallString := GetUninstallString();
  if sUnInstallString <> '' then begin
    // 구버전 언인스톨러 실행 (사일런트 모드 — 사용자 질문 없이 자동 제거)
    sUnInstallString := RemoveQuotes(sUnInstallString);
    Exec(sUnInstallString, '/SILENT /NORESTART /SUPPRESSMSGBOXES', '', SW_HIDE, ewWaitUntilTerminated, iResultCode);
    // 제거 완료 후 새 버전 설치 계속 진행
  end;
end;
