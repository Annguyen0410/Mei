; Mei Tea Room Edition — Inno Setup installer (free toolchain)
; Compile with:  ISCC.exe installer.iss   (Inno Setup 6.x, https://jrsoftware.org/isinfo.php)
; Produces dist\MeiSetup.exe — Start Menu + optional desktop/taskbar icons + uninstaller.
; The app itself is portable: the installer only copies files and adds shortcuts.
; User data (profiles, SafeVault) lives outside {app}, so uninstalling never
; wipes someone's notes.

#define MyAppName "Mei Tea Room Edition"
#define MyAppVersion "0.6.8.0"
#define MyAppExeName "Mei.exe"

[Setup]
AppId={{6E2D3C4B-6E5F-4F7A-B8C2-2F3B4C5D6E7F}
AppName={#MyAppName}
AppVersion={#MyAppVersion}
AppPublisher=Mei
DefaultDirName={autopf}\Mei
DefaultGroupName=Mei
UninstallDisplayIcon={app}\{#MyAppExeName}
OutputDir=dist
OutputBaseFilename=MeiSetup
Compression=lzma2
SolidCompression=yes
WizardStyle=modern
ArchitecturesAllowed=x64compatible
ArchitecturesInstallIn64BitMode=x64compatible

[Files]
Source: "dist\{#MyAppExeName}"; DestDir: "{app}"; Flags: ignoreversion
; web_support (~600 MB) is served from beside the exe, so install it too:
Source: "dist\web_support\*"; DestDir: "{app}\web_support"; Flags: ignoreversion recursesubdirs createallsubdirs

[Tasks]
Name: "desktopicon"; Description: "{cm:CreateDesktopIcon}"; GroupDescription: "{cm:AdditionalIcons}"; Flags: checkedonce
Name: "quicklaunchicon"; Description: "Pin to taskbar"; GroupDescription: "{cm:AdditionalIcons}"; Flags: unchecked

[Icons]
Name: "{group}\{#MyAppName}"; Filename: "{app}\{#MyAppExeName}"; IconFilename: "{app}\{#MyAppExeName}"
Name: "{group}\Uninstall {#MyAppName}"; Filename: "{uninstallexe}"
Name: "{autodesktop}\{#MyAppName}"; Filename: "{app}\{#MyAppExeName}"; IconFilename: "{app}\{#MyAppExeName}"; Tasks: desktopicon
Name: "{userappdata}\Microsoft\Internet Explorer\Quick Launch\User Pinned\TaskBar\{#MyAppName}"; Filename: "{app}\{#MyAppExeName}"; Tasks: quicklaunchicon

[Run]
Filename: "{app}\{#MyAppExeName}"; Description: "{cm:LaunchProgram,{#StringChange(MyAppName, '&', '&&')}}"; Flags: nowait postinstall skipifsilent

[UninstallDelete]
Type: filesandordirs; Name: "{app}\web_support"

[UninstallRun]
; Nothing outside {app} is touched: profiles/SafeVault stay on disk on purpose.
