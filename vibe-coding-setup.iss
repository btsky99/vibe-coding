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
  #define MyAppVersion   "3.7.222"
#endif
#define MyAppPublisher "Vibe Coding Team"
#define MyAppURL       "https://github.com/btsky99/vibe-coding"
#define MyAppExeName   "vibe-coding.exe"
; CI에서 /DMyAppExeName=... 으로 소스 EXE 파일명 오버라이드 가능
#ifndef MyAppSrcExe
  #define MyAppSrcExe    "vibe-coding-v" + MyAppVersion + ".exe"
#endif
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

; 설치 경로 (기본: C:\Program Files\Vibe Coding)
DefaultDirName={autopf}\{#MyAppName}
DefaultGroupName={#MyAppName}
AllowNoIcons=yes

; 출력 설정
OutputDir=.ai_monitor\dist
OutputBaseFilename={#MySetupName}
Compression=lzma2/ultra64
SolidCompression=yes
WizardStyle=modern

; 권한 설정 — admin 강제 (Defender 예외 등록 + Program Files 설치 + 구버전 제거 통합)
; [2026-05-05] lowest → admin: Add-MpPreference가 lowest에서 권한 부족으로 silently 실패
;              UAC 1회만 받으면 모든 [Run] 단계가 정상 권한으로 동작.
PrivilegesRequired=admin
PrivilegesRequiredOverridesAllowed=dialog
; 설치 전 실행 중인 앱 자동 종료 (덮어쓰기 허용)
CloseApplications=yes
CloseApplicationsFilter=*vibe-coding*

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
; PyInstaller로 생성된 EXE (단일 파일) — 고정 파일명(vibe-coding.exe)으로 설치
Source: ".ai_monitor\dist\{#MyAppSrcExe}"; DestDir: "{app}"; DestName: "{#MyAppExeName}"; Flags: ignoreversion
; 아이콘 파일 — 자동 업데이트 후에도 바로가기 아이콘이 유지되도록 별도 배포
Source: ".ai_monitor\bin\vibe_final.ico"; DestDir: "{app}"; Flags: ignoreversion
; Claude Code 상태줄 스크립트 — 설치 PC의 %USERPROFILE%\.claude\ 에 복사
Source: "statusline.py"; DestDir: "{%USERPROFILE}\.claude"; Flags: ignoreversion
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
Filename: "{app}\{#MyAppExeName}"; Description: "{#MyAppDisplayName} 시작"; Flags: nowait postinstall skipifsilent

[UninstallRun]
; 제거 전 실행 중인 프로세스 종료 (고정 파일명 사용)
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

// ── PyInstaller _MEI* 잔여 디렉터리 정리 ──────────────────────────────
// PyInstaller --onefile 모드는 실행 시 Temp\_MEI* 폴더에 DLL을 추출.
// 앱 비정상 종료 시 이 폴더가 남아 다음 실행 시 python311.dll 로드 실패 유발.
// 설치/업데이트 전에 모든 _MEI* 잔여 폴더를 삭제하여 충돌 방지.
// [2026-03-22 Claude: 업데이트 시 python311.dll 로드 실패 완전 해결]
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

function InitializeSetup(): Boolean;
var
  iResultCode: Integer;
  sUnInstallString: String;
begin
  Result := True;

  // 실행 중인 vibe-coding 프로세스 강제 종료 (DLL 잠금 방지)
  Exec('taskkill.exe', '/F /IM vibe-coding.exe', '', SW_HIDE, ewWaitUntilTerminated, iResultCode);
  // 잠시 대기하여 프로세스 종료 및 파일 잠금 해제 완료 대기
  Sleep(1500);

  // PyInstaller _MEI* 잔여 폴더 정리 (python311.dll 로드 실패 방지)
  CleanupMEIDirectories();

  sUnInstallString := GetUninstallString();
  if sUnInstallString <> '' then begin
    // 구버전 언인스톨러 실행 (사일런트 모드 — 사용자 질문 없이 자동 제거)
    sUnInstallString := RemoveQuotes(sUnInstallString);
    Exec(sUnInstallString, '/SILENT /NORESTART /SUPPRESSMSGBOXES', '', SW_HIDE, ewWaitUntilTerminated, iResultCode);
    // 제거 완료 후 새 버전 설치 계속 진행
  end;
end;
