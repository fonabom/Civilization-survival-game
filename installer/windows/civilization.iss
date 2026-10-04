; Inno Setup script: Civilization-Setup-<build>.exe  (b12, idea #9)
;
; Built by installer/build_installer.py --iscc, which passes:
;   /DMyBuild=b12 /DClientDir=<pyinstaller one-folder build> /DServerExe=<server exe> /DOutputDir=<dist/installer>
;
; The player needs nothing installed: the client executable carries its own
; Python; the server executable is an optional component (a friend can host the
; world on the same machine or on a VPS). Settings are written to %APPDATA%.

#ifndef MyBuild
  #define MyBuild "b0"
#endif
#ifndef ClientDir
  #define ClientDir "..\..\dist\pyinstaller\dist\client"
#endif
#ifndef ServerExe
  #define ServerExe ""
#endif
#ifndef OutputDir
  #define OutputDir "..\..\dist\installer"
#endif

#define MyAppName "Civilization Survival"
#define MyAppPublisher "fonabom"
#define MyAppURL "https://github.com/fonabom/Civilization-survival-game"

[Setup]
AppId={{7C2A1B44-9E3F-4C58-9A21-5E17C0DE1B12}
AppName={#MyAppName}
AppVersion={#MyBuild}
AppVerName={#MyAppName} (сборка {#MyBuild})
AppPublisher={#MyAppPublisher}
AppPublisherURL={#MyAppURL}
AppSupportURL={#MyAppURL}
DefaultDirName={autopf}\{#MyAppName}
DefaultGroupName={#MyAppName}
DisableProgramGroupPage=yes
OutputDir={#OutputDir}
OutputBaseFilename=Civilization-Setup-{#MyBuild}
Compression=lzma2/max
SolidCompression=yes
WizardStyle=modern
PrivilegesRequired=lowest
PrivilegesRequiredOverridesAllowed=dialog
UninstallDisplayName={#MyAppName}
UninstallDisplayIcon={app}\Civilization.exe
AllowNoIcons=yes

[Languages]
Name: "russian"; MessagesFile: "compiler:Languages\Russian.isl"
Name: "english"; MessagesFile: "compiler:Default.isl"
Name: "polish";  MessagesFile: "compiler:Languages\Polish.isl"

[Tasks]
Name: "desktopicon"; Description: "{cm:CreateDesktopIcon}"; GroupDescription: "{cm:AdditionalIcons}"
Name: "server"; Description: "Сервер для друзей (без графики, чтобы играть вместе)"; GroupDescription: "Дополнительно:"

[Files]
; the whole PyInstaller client folder: Civilization.exe + _internal with assets
Source: "{#ClientDir}\*"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs createallsubdirs
Source: "..\..\HOW_TO_PLAY.txt"; DestDir: "{app}"; Flags: ignoreversion
Source: "..\..\README.md"; DestDir: "{app}"; Flags: ignoreversion
Source: "..\..\CHANGELOG.md"; DestDir: "{app}"; Flags: ignoreversion
Source: "..\..\server_config.example.json"; DestDir: "{app}"; Flags: ignoreversion
#ifdef ServerExe
Source: "{#ServerExe}"; DestDir: "{app}"; Flags: ignoreversion; Tasks: server
#endif

[Icons]
Name: "{group}\{#MyAppName}"; Filename: "{app}\Civilization.exe"
Name: "{group}\Как играть"; Filename: "{app}\HOW_TO_PLAY.txt"
Name: "{autodesktop}\{#MyAppName}"; Filename: "{app}\Civilization.exe"; Tasks: desktopicon
Name: "{group}\Сервер для друзей"; Filename: "{app}\CivilizationServer.exe"; Parameters: "--config server_config.json"; Tasks: server

[Run]
Filename: "{app}\Civilization.exe"; Description: "{cm:LaunchProgram,{#MyAppName}}"; Flags: nowait postinstall skipifsilent

[Registry]
; where the launcher looks for an installed game (and where the uninstaller cleans up)
Root: HKCU; Subkey: "Software\{#MyAppPublisher}\{#MyAppName}"; ValueType: string; \
  ValueName: "InstallPath"; ValueData: "{app}"; Flags: uninsdeletekey
Root: HKCU; Subkey: "Software\{#MyAppPublisher}\{#MyAppName}"; ValueType: string; \
  ValueName: "Build"; ValueData: "{#MyBuild}"; Flags: uninsdeletekey

[UninstallDelete]
Type: filesandordirs; Name: "{app}\_internal"
