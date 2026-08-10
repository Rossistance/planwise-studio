; Inno Setup script for the PlanWise Companion.
;
; Build:  "C:\Program Files (x86)\Inno Setup 6\ISCC.exe" packaging\companion.iss
; (after: python -m PyInstaller planwise-companion.spec)
;
; Deliberately a PER-USER install (PrivilegesRequired=lowest):
;   * no admin rights, so no IT ticket — the same property that made the whole
;     COM-not-Graph approach viable (D10);
;   * the companion drafts into the mailbox of whoever is signed in, so a
;     per-machine install would be wrong anyway.
;
; The installer collects the pairing details itself, so a teammate never has
; to find a file path. It writes them where the companion looks; the app's own
; /pair page remains the fallback if they skip this page.

#define AppName        "PlanWise Companion"
#define AppVersion     "1.0.0"
#define AppPublisher   "1910 Legacy / White Electrical Construction"
#define ExeName        "PlanWiseCompanion.exe"

[Setup]
AppId={{8E5C1E4A-2C7E-4E5B-9E2A-PLANWISE0001}
AppName={#AppName}
AppVersion={#AppVersion}
AppPublisher={#AppPublisher}
DefaultDirName={autopf}\PlanWise Companion
DefaultGroupName=PlanWise
DisableProgramGroupPage=yes
PrivilegesRequired=lowest
OutputDir=..\dist
OutputBaseFilename=PlanWiseCompanion-{#AppVersion}-Setup
SetupIconFile=companion.ico
UninstallDisplayIcon={app}\{#ExeName}
Compression=lzma2
SolidCompression=yes
WizardStyle=modern
ArchitecturesInstallIn64BitMode=x64compatible

[Files]
Source: "..\dist\{#ExeName}"; DestDir: "{app}"; Flags: ignoreversion

[Icons]
Name: "{group}\PlanWise Companion"; Filename: "{app}\{#ExeName}"
; Startup matters more than it looks: a companion nobody remembers to launch
; means a customer reply nobody sees. The exe also self-installs this on first
; run, so the two agree rather than fight.
Name: "{userstartup}\PlanWise Companion"; Filename: "{app}\{#ExeName}"

[Run]
Filename: "{app}\{#ExeName}"; Description: "Start PlanWise Companion now"; \
  Flags: nowait postinstall skipifsilent

[Code]
var
  PairPage: TInputQueryWizardPage;

procedure InitializeWizard;
begin
  PairPage := CreateInputQueryPage(wpSelectDir,
    'Pair with PlanWise',
    'Where is PlanWise, and what is your pairing token?',
    'Mail is drafted in YOUR Outlook, on this PC. Find the pairing token in' + #13#10 +
    'PlanWise under Settings. You can skip this and pair later from the' + #13#10 +
    'companion itself.');
  PairPage.Add('PlanWise address:', False);
  PairPage.Add('Pairing token:', False);
  PairPage.Values[0] := 'https://';
end;

function PairDir(): String;
begin
  Result := ExpandConstant('{%USERPROFILE}') + '\.planwise';
end;

procedure CurStepChanged(CurStep: TSetupStep);
var
  Server, Token: String;
begin
  if CurStep <> ssPostInstall then Exit;

  Server := Trim(PairPage.Values[0]);
  Token  := Trim(PairPage.Values[1]);
  { Both or neither — a half-written pairing is worse than none, because the
    companion would look configured and quietly fail to reach anything. }
  if (Length(Token) < 16) or (Pos('http', Server) <> 1) then Exit;

  ForceDirectories(PairDir());
  SaveStringToFile(PairDir() + '\server_url.txt', Server, False);
  SaveStringToFile(PairDir() + '\companion_token.txt', Token, False);
end;

[UninstallDelete]
; The pairing files stay: they are the user's, not the installer's, and a
; reinstall should not make them go and find the token again.
