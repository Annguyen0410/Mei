; Mei Tea Room Edition - Inno Setup installer
; Compile with:  ISCC.exe installer.iss   (Inno Setup 6.x, free: https://jrsoftware.org/isinfo.php)
; It produces dist\MeiSetup.exe — a real installer with Start Menu + desktop
; shortcut + uninstaller, just like an Electron app's NSIS installer.

#define MyAppName "Mei Tea Room Edition"
#define MyAppVersion "6.4.0"
#define MyAppExeName "Mei.exe"
#define MyAppIco "icon.ico"

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

[Icons]
Name: "{group}\{#MyAppName}"; Filename: "{app}\{#MyAppExeName}"; IconFilename: "{app}\{#MyAppExeName}"
Name: "{autodesktop}\{#MyAppName}"; Filename: "{app}\{#MyAppExeName}"; IconFilename: "{app}\{#MyAppExeName}"; Tasks: desktopicon

[Tasks]
Name: "desktopicon"; Description: "{cm:CreateDesktopIcon}"; GroupDescription: "{cm:AdditionalIcons}"; Flags: unchecked

[Run]
Filename: "{app}\{#MyAppExeName}"; Description: "{cm:LaunchProgram,{#StringChange(MyAppName, '&', '&&')}}"; Flags: nowait postinstall skipifsilent

[UninstallDelete]
Type: filesandordirs; Name: "{app}\web_support"
