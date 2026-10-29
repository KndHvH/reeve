; Inno Setup script: Reeve installer (built by scripts/build.py after PyInstaller).
;
;   ISCC /DAppVersion=0.2.0 packaging\reeve.iss
;
; Per-user install, no admin rights: %LOCALAPPDATA%\Programs\Reeve. Start
; menu shortcut carrying the app's AppUserModelID, so notifications show as
; Reeve. Optional start with Windows and desktop shortcut. The user's data
; (%APPDATA%\reeve: matches, settings, sounds) is kept on uninstall.

#ifndef AppVersion
  #define AppVersion "0.0.0"
#endif

[Setup]
AppId={{6F1C2B9E-4D7A-4E8B-9A35-2C7E5B0D8F41}
AppName=Reeve
AppVersion={#AppVersion}
AppVerName=Reeve {#AppVersion}
AppPublisher=Reeve
VersionInfoVersion={#AppVersion}
DefaultDirName={localappdata}\Programs\Reeve
DisableProgramGroupPage=yes
PrivilegesRequired=lowest
OutputDir=..\dist
OutputBaseFilename=Reeve-{#AppVersion}-setup
SetupIconFile=..\assets\app.ico
UninstallDisplayIcon={app}\Reeve.exe
UninstallDisplayName=Reeve
WizardStyle=modern
Compression=lzma2/max
SolidCompression=yes
ArchitecturesAllowed=x64compatible
ArchitecturesInstallIn64BitMode=x64compatible
; The running app holds this mutex (reeve.launcher): setup and uninstall ask to close it.
AppMutex=Reeve.App
CloseApplications=yes

[Languages]
Name: "en"; MessagesFile: "compiler:Default.isl"
Name: "ptbr"; MessagesFile: "compiler:Languages\BrazilianPortuguese.isl"

[CustomMessages]
en.StartWithWindows=Start Reeve when Windows starts
ptbr.StartWithWindows=Iniciar o Reeve com o Windows
en.LaunchReeve=Start Reeve now
ptbr.LaunchReeve=Abrir o Reeve agora

[Tasks]
Name: "startup"; Description: "{cm:StartWithWindows}"
Name: "desktopicon"; Description: "{cm:CreateDesktopIcon}"; GroupDescription: "{cm:AdditionalIcons}"; Flags: unchecked

[Files]
Source: "..\dist\Reeve\*"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs createallsubdirs

[InstallDelete]
; A new version replaces the bundled code and data completely.
Type: filesandordirs; Name: "{app}\_internal"

[Icons]
Name: "{autoprograms}\Reeve"; Filename: "{app}\Reeve.exe"; AppUserModelID: "Reeve"
Name: "{autodesktop}\Reeve"; Filename: "{app}\Reeve.exe"; AppUserModelID: "Reeve"; Tasks: desktopicon

[Registry]
; Name and icon Windows shows on notifications (the app also writes them at start).
Root: HKCU; Subkey: "Software\Classes\AppUserModelId\Reeve"; ValueType: string; ValueName: "DisplayName"; ValueData: "Reeve"; Flags: uninsdeletekey
Root: HKCU; Subkey: "Software\Classes\AppUserModelId\Reeve"; ValueType: string; ValueName: "IconUri"; ValueData: "{app}\_internal\assets\app.ico"
Root: HKCU; Subkey: "Software\Microsoft\Windows\CurrentVersion\Run"; ValueType: string; ValueName: "Reeve"; ValueData: """{app}\Reeve.exe"""; Flags: uninsdeletevalue; Tasks: startup

[Run]
Filename: "{app}\Reeve.exe"; Description: "{cm:LaunchReeve}"; Flags: postinstall nowait skipifsilent
