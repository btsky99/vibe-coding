; Inno Setup Script for Vibe Coding
; CI에서 자동 빌드됨
; [변경 이력]
; [2026-03-15] Claude — [Run]/[Icons]에서 MyAppExeName 대신 고정명 vibe-coding.exe 사용.
;              근본 원인: CI가 --name vibe-coding-update-X.Y.Z.exe로 빌드하지만
;              [Files]는 DestName: "vibe-coding.exe"로 이름을 바꿔 설치하므로
;              원본 이름을 참조하는 [Run]/[Icons]에서 CreateProcess 코드 2 오류 발생.

#define MyAppName "Vibe Coding"
; MyAppExeName = CI에서 넘어오는 빌드 소스 파일명 (vibe-coding-update-X.Y.Z.exe)
; MyInstalledExeName = 실제 설치되는 고정 파일명 (항상 vibe-coding.exe)
#ifndef MyAppExeName
  #define MyAppExeName "vibe-coding.exe"
#endif
#define MyInstalledExeName "vibe-coding.exe"
#define MyAppPublisher "btsky99"
#define MyAppURL "https://github.com/btsky99/vibe-coding"
#ifndef MyAppVersion
  #define MyAppVersion "dev"
#endif

[Setup]
AppId={{B7E3A1D0-5F4C-4E8A-9D2B-1A3C5F7E9D0B}
AppName={#MyAppName}
AppVersion={#MyAppVersion}
AppPublisher={#MyAppPublisher}
AppPublisherURL={#MyAppURL}
DefaultDirName={autopf}\{#MyAppName}
DefaultGroupName={#MyAppName}
OutputBaseFilename=vibe-coding-setup-{#MyAppVersion}
Compression=lzma
SolidCompression=yes
WizardStyle=modern
PrivilegesRequired=lowest
OutputDir=dist
CloseApplications=force
CloseApplicationsFilter=vibe-coding.exe,vibe-coding_console.exe
SetupIconFile=bin\vibe_final.ico
UninstallDisplayIcon={app}\vibe_final.ico
; 환경변수 PATH에 설치 경로 추가 — 터미널에서 vibe-coding 명령어 실행 가능하게 함
ChangesEnvironment=yes

[Languages]
Name: "korean"; MessagesFile: "compiler:Languages\Korean.isl"
Name: "english"; MessagesFile: "compiler:Default.isl"

[Tasks]
Name: "desktopicon"; Description: "{cm:CreateDesktopIcon}"; GroupDescription: "{cm:AdditionalIcons}"
Name: "startup"; Description: "Windows 시작 시 자동 실행"; GroupDescription: "추가 옵션:"

[Files]
Source: "dist\{#MyAppExeName}"; DestDir: "{app}"; DestName: "vibe-coding.exe"; Flags: ignoreversion
Source: "dist\vibe-coding-console-{#MyAppVersion}.exe"; DestDir: "{app}"; DestName: "vibe-coding-console.exe"; Flags: ignoreversion skipifsourcedoesntexist
Source: "bin\vibe_final.ico"; DestDir: "{app}"; Flags: ignoreversion

; ── 서브창 EXE (별도 PyInstaller 빌드) ─────────────────────────────────────
; server.py가 frozen 모드에서 Python 서브프로세스 대신 이 EXE들을 직접 실행.
; vibe-graph.exe    : 지식 그래프 독립 창 (QWebEngineView)
; vibe-dashboard.exe: 대시보드 독립 창   (QWebEngineView)
; vibe-dashboard.exe: 대시보드 + kanban 탭 통합 (B안 — kanban_board.py 제거됨)
Source: "dist\vibe-graph.exe";     DestDir: "{app}"; Flags: ignoreversion skipifsourcedoesntexist
Source: "dist\vibe-dashboard.exe"; DestDir: "{app}"; Flags: ignoreversion skipifsourcedoesntexist

; ── PostgreSQL 포터블 바이너리 (pgsql\bin, lib, share) ──────────────────────
; server.py가 최초 기동 시 ensure_postgres_running()으로 initdb+pg_ctl 자동 수행.
; data/ 폴더 미포함 → 각 PC의 %APPDATA%\VibeCoding\pgdata\ 에 새로 생성됨.
Source: "bin\pgsql\bin\*"; DestDir: "{app}\pgsql\bin"; Flags: ignoreversion recursesubdirs createallsubdirs skipifsourcedoesntexist
Source: "bin\pgsql\lib\*"; DestDir: "{app}\pgsql\lib"; Flags: ignoreversion recursesubdirs createallsubdirs skipifsourcedoesntexist
Source: "bin\pgsql\share\*"; DestDir: "{app}\pgsql\share"; Flags: ignoreversion recursesubdirs createallsubdirs skipifsourcedoesntexist

[Dirs]
Name: "{app}\data"

[Icons]
; 설치된 고정 파일명(MyInstalledExeName)을 사용해야 함.
; MyAppExeName은 CI 빌드 소스명이므로 바로가기에 사용하면 파일을 찾지 못함.
Name: "{group}\{#MyAppName}"; Filename: "{app}\{#MyInstalledExeName}"; IconFilename: "{app}\vibe_final.ico"
Name: "{group}\{cm:UninstallProgram,{#MyAppName}}"; Filename: "{uninstallexe}"
Name: "{autodesktop}\{#MyAppName}"; Filename: "{app}\{#MyInstalledExeName}"; IconFilename: "{app}\vibe_final.ico"; Tasks: desktopicon
Name: "{userstartup}\{#MyAppName}"; Filename: "{app}\{#MyInstalledExeName}"; IconFilename: "{app}\vibe_final.ico"; Tasks: startup

[Registry]
; 사용자 PATH에 설치 디렉토리 추가 — 터미널(cmd/PowerShell)에서 vibe-coding 명령어 직접 실행 가능
Root: HKCU; Subkey: "Environment"; ValueType: expandsz; ValueName: "Path"; \
  ValueData: "{olddata};{app}"; Check: NeedsAddPath('{app}')

[Code]
{ 이미 PATH에 해당 경로가 있으면 중복 추가 방지 }
function NeedsAddPath(Param: string): boolean;
var
  OrigPath: string;
begin
  if not RegQueryStringValue(HKEY_CURRENT_USER, 'Environment', 'Path', OrigPath) then
  begin
    Result := True;
    exit;
  end;
  { 대소문자 무시하여 경로 중복 체크 }
  Result := Pos(';' + Lowercase(Param) + ';', ';' + Lowercase(OrigPath) + ';') = 0;
end;

[Run]
; 설치 후 실행은 반드시 DestName으로 설치된 고정 파일명(MyInstalledExeName) 사용
Filename: "{app}\{#MyInstalledExeName}"; Description: "{cm:LaunchProgram,{#MyAppName}}"; Flags: nowait postinstall skipifsilent

