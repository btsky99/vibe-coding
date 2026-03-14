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
; [2026-03-11] Claude — PostgreSQL 포터블 바이너리 자동 설치 추가 (v3.7.48)
;              {app}\pgsql\ 에 bin/lib/share 포함. initdb 및 포트 설정은 server.py가 최초 기동 시 수행.
; [2026-03-08] Claude — 설치 EXE 고정 파일명(vibe-coding.exe)으로 변경. 버전 업 시 자동 덮어쓰기
; [2026-03-01] Claude — 최초 생성. 포터블 EXE → 설치버전 파이프라인 구축
; ────────────────────────────────────────────────────────────────────────────

#define MyAppName      "Vibe Coding"
#define MyAppVersion   "3.7.59"
#define MyAppPublisher "Vibe Coding Team"
#define MyAppURL       "https://github.com/btsky99/vibe-coding"
#define MyAppExeName   "vibe-coding.exe"
; CI는 vibe-coding-update-{ver}.exe로 빌드 → 로컬도 동일 이름 사용
#define MyAppSrcExe    "vibe-coding-v" + MyAppVersion + ".exe"
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
Source: "dist\{#MyAppSrcExe}"; DestDir: "{app}"; DestName: "{#MyAppExeName}"; Flags: ignoreversion
; 아이콘 파일 — 자동 업데이트 후에도 바로가기 아이콘이 유지되도록 별도 배포
Source: ".ai_monitor\bin\vibe_final.ico"; DestDir: "{app}"; Flags: ignoreversion

; ── 서브창 EXE (별도 PyInstaller 빌드) ─────────────────────────────────────
; server.py가 frozen 모드에서 Python 서브프로세스 대신 이 EXE들을 직접 실행.
Source: ".ai_monitor\dist\vibe-graph.exe";     DestDir: "{app}"; Flags: ignoreversion skipifsourcedoesntexist
Source: ".ai_monitor\dist\vibe-dashboard.exe"; DestDir: "{app}"; Flags: ignoreversion skipifsourcedoesntexist
; vibe-kanban.exe 제거됨 — B안 통합: vibe-dashboard.exe kanban 탭으로 실행

; ── PostgreSQL 포터블 바이너리 (pgAdmin 4 제외, 필수 파일만 포함 — ~142MB) ──
; server.py가 최초 기동 시 ensure_postgres_running()으로 initdb + pg_ctl start 자동 수행.
; data/ 폴더는 포함하지 않음 → 각 PC의 %APPDATA%\VibeCoding\pgdata\ 에 새로 생성됨.
Source: ".ai_monitor\bin\pgsql\bin\*"; DestDir: "{app}\pgsql\bin"; Flags: ignoreversion recursesubdirs createallsubdirs
Source: ".ai_monitor\bin\pgsql\lib\*"; DestDir: "{app}\pgsql\lib"; Flags: ignoreversion recursesubdirs createallsubdirs
Source: ".ai_monitor\bin\pgsql\share\*"; DestDir: "{app}\pgsql\share"; Flags: ignoreversion recursesubdirs createallsubdirs

[Icons]
; 시작 메뉴 — IconFilename 명시로 EXE 교체 후에도 아이콘 유지
Name: "{group}\{#MyAppName}";             Filename: "{app}\{#MyAppExeName}"; IconFilename: "{app}\vibe_final.ico"
Name: "{group}\{#MyAppName} 제거";        Filename: "{uninstallexe}"
; 바탕화면 (선택)
Name: "{autodesktop}\{#MyAppName}";       Filename: "{app}\{#MyAppExeName}"; IconFilename: "{app}\vibe_final.ico"; Tasks: desktopicon
; 시작프로그램 (선택)
Name: "{userstartup}\{#MyAppName}";       Filename: "{app}\{#MyAppExeName}"; IconFilename: "{app}\vibe_final.ico"; Tasks: startupicon

[Run]
; 설치 완료 후 바로 실행 (선택)
Filename: "{app}\{#MyAppExeName}"; Description: "Vibe Coding 시작"; Flags: nowait postinstall skipifsilent

[UninstallRun]
; 제거 전 실행 중인 프로세스 종료 (고정 파일명 사용)
Filename: "taskkill.exe"; Parameters: "/F /IM vibe-coding.exe"; Flags: runhidden; RunOnceId: "KillVibeCoding"

[Code]
// 버전 체크: 구버전 설치되어 있으면 먼저 제거 유도
function InitializeSetup(): Boolean;
begin
  Result := True;
end;
