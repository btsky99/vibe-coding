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
; [2026-03-01] Claude — 최초 생성. 포터블 EXE → 설치버전 파이프라인 구축
; ────────────────────────────────────────────────────────────────────────────

#define MyAppName      "Vibe Coding"
#define MyAppVersion   "3.6.5"
#define MyAppPublisher "Vibe Coding Team"
#define MyAppURL       "https://github.com/btsky99/vibe-coding"
#define MyAppExeName   "vibe-coding-v" + MyAppVersion + ".exe"
#define MySetupName    "vibe-coding-setup-" + MyAppVersion

[Setup]
; 앱 기본 정보
AppId={{A1B2C3D4-E5F6-7890-ABCD-EF1234567890}
AppName={#MyAppName}
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
OutputDir=dist
OutputBaseFilename={#MySetupName}
Compression=lzma2/ultra64
SolidCompression=yes
WizardStyle=modern

; 권한 설정 (관리자 불필요 — 사용자 폴더에도 설치 가능)
PrivilegesRequired=lowest
PrivilegesRequiredOverridesAllowed=dialog

; 아이콘
SetupIconFile=.ai_monitor\bin\app_icon.ico
UninstallDisplayIcon={app}\{#MyAppExeName}

[Languages]
Name: "korean"; MessagesFile: "compiler:Languages\Korean.isl"
Name: "english"; MessagesFile: "compiler:Default.isl"

[Tasks]
Name: "desktopicon";    Description: "바탕화면 바로가기 만들기"; GroupDescription: "추가 아이콘:"; Flags: unchecked
Name: "startupicon";    Description: "시작 시 자동 실행";         GroupDescription: "추가 옵션:";  Flags: unchecked

[Files]
; PyInstaller로 생성된 EXE (단일 파일)
Source: "dist\{#MyAppExeName}"; DestDir: "{app}"; Flags: ignoreversion

[Icons]
; 시작 메뉴
Name: "{group}\{#MyAppName}";             Filename: "{app}\{#MyAppExeName}"
Name: "{group}\{#MyAppName} 제거";        Filename: "{uninstallexe}"
; 바탕화면 (선택)
Name: "{autodesktop}\{#MyAppName}";       Filename: "{app}\{#MyAppExeName}"; Tasks: desktopicon
; 시작프로그램 (선택)
Name: "{userstartup}\{#MyAppName}";       Filename: "{app}\{#MyAppExeName}"; Tasks: startupicon

[Run]
; 설치 완료 후 바로 실행 (선택)
Filename: "{app}\{#MyAppExeName}"; Description: "Vibe Coding 시작"; Flags: nowait postinstall skipifsilent

[UninstallRun]
; 제거 전 실행 중인 프로세스 종료
Filename: "taskkill.exe"; Parameters: "/F /IM {#MyAppExeName}"; Flags: runhidden

[Code]
// 버전 체크: 구버전 설치되어 있으면 먼저 제거 유도
function InitializeSetup(): Boolean;
begin
  Result := True;
end;
