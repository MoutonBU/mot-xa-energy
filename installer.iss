#define AppVer GetEnv("APP_VER")
[Setup]
AppName=MOT XA Energy
AppVersion={#AppVer}
AppPublisher=MOT Studio
DefaultDirName={autopf}\MOT XA Energy
DefaultGroupName=MOT XA Energy
OutputBaseFilename=MOT_XA_Energy_Setup
OutputDir=installer_out
SetupIconFile=mcp_logo.ico
Compression=lzma2/fast
SolidCompression=yes
CloseApplications=yes
RestartApplications=no
PrivilegesRequired=lowest
[Files]
Source: "dist\MOT_XA_Energy\*"; DestDir: "{app}"; Flags: recursesubdirs ignoreversion
[Icons]
Name: "{group}\MOT XA Energy"; Filename: "{app}\MOT_XA_Energy.exe"
Name: "{autodesktop}\MOT XA Energy"; Filename: "{app}\MOT_XA_Energy.exe"
[Run]
Filename: "{app}\MOT_XA_Energy.exe"; Parameters: "--after-update"; Flags: nowait postinstall skipifsilent runasoriginaluser
Filename: "{app}\MOT_XA_Energy.exe"; Parameters: "--after-update"; Flags: nowait runasoriginaluser; Check: WizardSilent
