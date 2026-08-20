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
#define AppVersion     "2.0.0"
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
    'Connect to PlanWise',
    'Where is PlanWise?',
    'Mail is drafted in YOUR Outlook, on this PC, so the companion connects' + #13#10 +
    'as you. After installing it opens a page where you sign in with your' + #13#10 +
    'PlanWise email and password. No password is stored by this installer.');
  PairPage.Add('PlanWise address:', False);
  PairPage.Values[0] := 'https://';
end;

function PairDir(): String;
begin
  Result := ExpandConstant('{%USERPROFILE}') + '\.planwise';
end;

procedure CurStepChanged(CurStep: TSetupStep);
var
  Server: String;
begin
  if CurStep <> ssPostInstall then Exit;

  { Only the address — it pre-fills the sign-in page so nobody has to type a
    URL from memory. Credentials are never collected here: the installer has
    no way to verify them, and a wrong one written to disk would look
    configured while quietly failing. The companion's own page proves them
    against PlanWise before writing anything. }
  Server := Trim(PairPage.Values[0]);

  { A silent install never shows the wizard, so Values[0] is still the literal
    'https://' placeholder — which passed the old Pos('http', ...) check and
    overwrote a working companion's address with nonsense. Found by running
    /VERYSILENT against a real machine. Require an actual host after the
    scheme, and never write over an address that is already there. }
  if (Server = '') or (Server = 'https://') or (Server = 'http://') then Exit;
  if (Pos('https://', Server) <> 1) and (Pos('http://', Server) <> 1) then Exit;
  if FileExists(PairDir() + '\server_url.txt') then Exit;

  ForceDirectories(PairDir());
  SaveStringToFile(PairDir() + '\server_url.txt', Server, False);
end;

[UninstallDelete]
; The pairing files stay: they are the user's, not the installer's, and a
; reinstall should not make them go and find the token again.
