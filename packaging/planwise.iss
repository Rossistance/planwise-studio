; Inno Setup script for PlanWise — the complete desktop install.
;
; Build:  "%LOCALAPPDATA%\Programs\Inno Setup 6\ISCC.exe" packaging\planwise.iss
; (after: python -m PyInstaller planwise-desktop.spec
;         python -m PyInstaller planwise-companion.spec)
;
; ONE installer, TWO programs, and the address already filled in:
;   PlanWise.exe           the app window (Start menu + desktop icon)
;   PlanWiseCompanion.exe  the Outlook helper, started with Windows
;
; The teammate is asked NOTHING during setup. The server address is compiled
; in below, so the only thing they ever type is their own PlanWise password,
; on first launch, in the app itself. That was the whole point of the
; zero-token work (D39/D40): nothing is handed person to person.
;
; PER-USER by design (PrivilegesRequired=lowest): no admin, so no IT ticket —
; the same property that made the COM-not-Graph approach viable (D10) — and
; the companion drafts into the mailbox of whoever is signed in, so a
; per-machine install would be wrong anyway.

#define AppName        "PlanWise"
#define AppVersion     "2.0.3"
#define AppPublisher   "1910 Legacy / White Electrical Construction"
#define AppExe         "PlanWise.exe"
#define CompanionExe   "PlanWiseCompanion.exe"
; Change this and rebuild if PlanWise ever moves.
#define PlanWiseUrl    "https://planwise-rahj.onrender.com"

[Setup]
AppId={{3F7A9C21-64D8-4B0E-9A73-PLANWISEAPP01}
AppName={#AppName}
AppVersion={#AppVersion}
AppPublisher={#AppPublisher}
AppSupportURL={#PlanWiseUrl}
DefaultDirName={autopf}\PlanWise
DefaultGroupName=PlanWise
DisableProgramGroupPage=yes
; Nothing to ask, so don't make them click through a page that asks it.
DisableDirPage=auto
PrivilegesRequired=lowest
OutputDir=..\dist
OutputBaseFilename=PlanWise-{#AppVersion}-Setup
SetupIconFile=planwise.ico
UninstallDisplayIcon={app}\{#AppExe}
UninstallDisplayName={#AppName}
Compression=lzma2
SolidCompression=yes
WizardStyle=modern
ArchitecturesInstallIn64BitMode=x64compatible
; Both programs may be running during an upgrade. Inno closes them itself
; rather than leaving half the files stale.
CloseApplications=yes
RestartApplications=no

[Files]
Source: "..\dist\{#AppExe}";       DestDir: "{app}"; Flags: ignoreversion
Source: "..\dist\{#CompanionExe}"; DestDir: "{app}"; Flags: ignoreversion
Source: "..\dist\PlanWise-Getting-Started.pdf"; DestDir: "{app}"; Flags: ignoreversion

[Icons]
Name: "{group}\PlanWise";          Filename: "{app}\{#AppExe}"
Name: "{group}\Getting started (PDF)"; Filename: "{app}\PlanWise-Getting-Started.pdf"
Name: "{userdesktop}\PlanWise";    Filename: "{app}\{#AppExe}"; Tasks: desktopicon
; Startup matters more than it looks: a companion nobody remembers to launch
; means a customer reply nobody sees. The exe self-installs this on first run
; too, so the two agree rather than fight.
Name: "{userstartup}\PlanWise Companion"; Filename: "{app}\{#CompanionExe}"

[Tasks]
Name: "desktopicon"; Description: "Create a desktop shortcut"; GroupDescription: "Shortcuts:"

[Run]
Filename: "{app}\{#AppExe}"; Description: "Open PlanWise now"; \
  Flags: nowait postinstall skipifsilent

[UninstallDelete]
; The pairing and the browser profile stay: they are the user's, not the
; installer's, and a reinstall should not make them sign in all over again.

[Code]
function PairDir(): String;
begin
  Result := ExpandConstant('{%USERPROFILE}') + '\.planwise';
end;

function PrepareToInstall(var NeedsRestart: Boolean): String;
var
  Code: Integer;
begin
  Result := '';
  { Close both programs before replacing their files.

    CloseApplications alone is not enough: it drives the Restart Manager,
    which asks a program to close by posting to its WINDOWS — and the
    companion deliberately has none (it is a background service, D37). So the
    file stayed locked and an unattended upgrade aborted with exit code 5,
    having installed nothing. Found by upgrading this machine.

    The app is closed too, since a running window would otherwise keep the
    old build on screen after a successful upgrade. Both are restarted by the
    post-install Run entry, or by the Startup shortcut at next sign-in.
    (Do not start a line in this comment with a bracketed word — the parser
    reads it as a section tag.) }
  Exec(ExpandConstant('{sys}\taskkill.exe'), '/F /IM PlanWiseCompanion.exe',
       '', SW_HIDE, ewWaitUntilTerminated, Code);
  Exec(ExpandConstant('{sys}\taskkill.exe'), '/F /IM PlanWise.exe',
       '', SW_HIDE, ewWaitUntilTerminated, Code);
  { taskkill returns before the handles are actually released. }
  Sleep(1500);
end;

procedure CurStepChanged(CurStep: TSetupStep);
var
  UrlFile: String;
begin
  if CurStep <> ssPostInstall then Exit;

  { Write the address both programs read, so the app window and the companion
    can never end up pointing at different servers.

    Never overwrite one that already exists: an upgrade must not disturb a
    working install, and someone running their own PlanWise elsewhere has
    already put the right value here. (A silent install once clobbered a live
    pairing with a placeholder — hence the belt and braces.) }
  UrlFile := PairDir() + '\server_url.txt';
  if FileExists(UrlFile) then Exit;

  ForceDirectories(PairDir());
  SaveStringToFile(UrlFile, '{#PlanWiseUrl}', False);
end;
