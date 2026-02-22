; Inno Setup Script for Vibe Coding
; CI에서 자동 빌드됨

#define MyAppName "Vibe Coding"
#define MyAppExeName "vibe-coding.exe"
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
OutputBaseFilename=vibe-coding-setup
Compression=lzma
SolidCompression=yes
WizardStyle=modern
PrivilegesRequired=lowest
OutputDir=dist
CloseApplications=force
CloseApplicationsFilter=vibe-coding.exe,vibe-coding_console.exe

[Languages]
Name: "korean"; MessagesFile: "compiler:Languages\Korean.isl"
Name: "english"; MessagesFile: "compiler:Default.isl"

[Tasks]
Name: "desktopicon"; Description: "{cm:CreateDesktopIcon}"; GroupDescription: "{cm:AdditionalIcons}"
Name: "startup"; Description: "Windows 시작 시 자동 실행"; GroupDescription: "추가 옵션:"

[Files]
Source: "dist\vibe-coding.exe"; DestDir: "{app}"; Flags: ignoreversion
Source: "dist\vibe-coding_console.exe"; DestDir: "{app}"; Flags: ignoreversion skipifsourcedoesntexist

[Dirs]
Name: "{app}\data"

[Icons]
Name: "{group}\{#MyAppName}"; Filename: "{app}\{#MyAppExeName}"
Name: "{group}\{cm:UninstallProgram,{#MyAppName}}"; Filename: "{uninstallexe}"
Name: "{autodesktop}\{#MyAppName}"; Filename: "{app}\{#MyAppExeName}"; Tasks: desktopicon
Name: "{userstartup}\{#MyAppName}"; Filename: "{app}\{#MyAppExeName}"; Tasks: startup

[Run]
Filename: "{app}\{#MyAppExeName}"; Description: "{cm:LaunchProgram,{#MyAppName}}"; Flags: nowait postinstall skipifsilent

