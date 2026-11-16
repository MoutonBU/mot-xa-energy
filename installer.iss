#define AppVer GetEnv("APP_VER")
[Setup]
AppName=MOT XA Energy
AppVersion={#AppVer}
AppPublisher=MCP Architecture & Interiors
DefaultDirName={autopf}\MOT XA Energy
DefaultGroupName=MOT XA Energy
OutputBaseFilename=MOT_XA_Energy_Setup
OutputDir=installer_out
SetupIconFile=mcp_logo.ico
WizardStyle=modern
WizardImageFile=wiz_big.bmp
WizardSmallImageFile=wiz_small.bmp
WizardImageBackColor=$1A1716
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
[Code]
const
  BGC = $1A1716;      { #16171a }
  PANEL = $25211F;    { #1f2125 }
  TXT = $F0EEEC;      { #eceef0 }
  SUB = $A8A09A;      { #9aa0a8 }

procedure ThemeControl(C: TControl);
var
  i: Integer;
begin
  if C is TNewStaticText then
    TNewStaticText(C).Font.Color := TXT
  else if C is TPanel then
    TPanel(C).Color := BGC
  else if C is TNewCheckListBox then
  begin
    TNewCheckListBox(C).Color := PANEL;
    TNewCheckListBox(C).Font.Color := TXT;
  end
  else if C is TRichEditViewer then
  begin
    TRichEditViewer(C).Color := PANEL;
    TRichEditViewer(C).Font.Color := TXT;
  end;
  if C is TWinControl then
    for i := 0 to TWinControl(C).ControlCount - 1 do
      ThemeControl(TWinControl(C).Controls[i]);
end;

procedure ThemeAll;
begin
  WizardForm.Color := BGC;
  WizardForm.Font.Color := TXT;
  WizardForm.InnerPage.Color := BGC;
  WizardForm.MainPanel.Color := PANEL;
  WizardForm.PageNameLabel.Font.Color := TXT;
  WizardForm.PageDescriptionLabel.Font.Color := SUB;
  WizardForm.WelcomeLabel1.Font.Color := TXT;
  WizardForm.WelcomeLabel2.Font.Color := SUB;
  WizardForm.FinishedHeadingLabel.Font.Color := TXT;
  WizardForm.FinishedLabel.Font.Color := SUB;
  WizardForm.WelcomePage.Color := BGC;
  WizardForm.FinishedPage.Color := BGC;
  ThemeControl(WizardForm);
end;

procedure InitializeWizard;
begin
  ThemeAll;
end;

procedure CurPageChanged(CurPageID: Integer);
begin
  ThemeAll;
end;
