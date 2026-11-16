#define AppVer GetEnv("APP_VER")
[Setup]
AppId=MOT XA Energy
AppName=MCP Architecture and Interiors XA Energy
AppVersion={#AppVer}
AppVerName=MCP Architecture and Interiors XA Energy {#AppVer}
VersionInfoVersion={#AppVer}.0
VersionInfoProductVersion={#AppVer}.0
UninstallDisplayName=MCP Architecture and Interiors XA Energy {#AppVer}
AppPublisher=MCP Architecture & Interiors
DefaultDirName={autopf}\MCP Architecture and Interiors XA Energy
DefaultGroupName=MCP Architecture and Interiors XA Energy
OutputBaseFilename=MCP_XA_Energy_Setup_{#AppVer}
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
Source: "dist\MCP_XA_Energy\*"; DestDir: "{app}"; Flags: recursesubdirs ignoreversion
[InstallDelete]
Type: files; Name: "{app}\MOT_XA_Energy.exe"
Type: files; Name: "{autodesktop}\MOT XA Energy.lnk"
Type: filesandordirs; Name: "{userprograms}\MOT XA Energy"
Type: filesandordirs; Name: "{commonprograms}\MOT XA Energy"
[Icons]
Name: "{group}\MCP Architecture and Interiors XA Energy"; Filename: "{app}\MCP_XA_Energy.exe"
Name: "{autodesktop}\MCP Architecture and Interiors XA Energy"; Filename: "{app}\MCP_XA_Energy.exe"
[Run]
Filename: "{app}\MCP_XA_Energy.exe"; Parameters: "--after-update"; Flags: nowait postinstall skipifsilent runasoriginaluser
Filename: "{app}\MCP_XA_Energy.exe"; Parameters: "--after-update"; Flags: nowait runasoriginaluser; Check: WizardSilent
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
  end
  else if C is TNewMemo then
  begin
    TNewMemo(C).Color := PANEL;
    TNewMemo(C).Font.Color := TXT;
  end
  else if C is TEdit then
  begin
    TEdit(C).Color := PANEL;
    TEdit(C).Font.Color := TXT;
  end
  else if C is TNewComboBox then
  begin
    TNewComboBox(C).Color := PANEL;
    TNewComboBox(C).Font.Color := TXT;
  end
  else if C is TNewCheckBox then
    TNewCheckBox(C).Font.Color := TXT
  else if C is TNewRadioButton then
    TNewRadioButton(C).Font.Color := TXT;
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
var
  V: TNewStaticText;
begin
  WizardForm.Caption := 'MCP Architecture and Interiors XA Energy {#AppVer} - Setup';
  V := TNewStaticText.Create(WizardForm);
  V.Parent := WizardForm;
  V.Caption := 'Version {#AppVer}';
  V.Font.Style := [fsBold];
  V.Left := ScaleX(20);
  V.Top := WizardForm.NextButton.Top + (WizardForm.NextButton.Height - V.Height) div 2;
  V.Font.Color := SUB;
  ThemeAll;
end;

procedure CurPageChanged(CurPageID: Integer);
begin
  ThemeAll;
end;
