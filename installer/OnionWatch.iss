; OnionWatch-Installer.exe: one file a non-technical person double-clicks.
;
;   - no Python needed: it ships the PyInstaller build (dist\OnionWatch)
;   - no admin needed (installs per user)
;   - a "Your privacy" page (PrivacyPage in [Code]): in plain words, the only two
;     things the app does online (the daily update check and the anonymous count)
;   - a Start menu shortcut, a Desktop one if ticked, and "Count me in" (the anonymous
;     daily count, onionwatch/usage.py; ticked). Unticked runs OnionWatch.exe
;     --usage-count off before the first start: the only thing ever sent is one
;     anonymous "opt-out/installer" (no ID)
;   - uninstalling runs OnionWatch.exe --uninstall-count: one "uninstall/<version>",
;     only if the count is on
;   - a new install with Count me in ticked: "Where did you hear about Onion Watch?"
;     (HeardPage), sent once with the first-start count
;   - then opens Onion Watch
;
; The app's own updater (onionwatch/updates.py) runs it with /SILENT /RELAUNCH=1:
; a silent install keeps the last install's boxes and never switches the count on.
;
; Built by build.ps1 (needs Inno Setup 6: winget install JRSoftware.InnoSetup), which
; also draws the icon and the wizard pictures (scripts\make_installer_art.py).

#define AppName "Onion Watch"
#define AppExeName "OnionWatch"
#ifndef AppVersion
  #define AppVersion "0.0.0"
#endif

[Setup]
AppId={{3F7C2B1E-8A4D-4E6B-9C2F-1D5A7E9B0C44}
AppName={#AppName}
AppVersion={#AppVersion}
AppPublisher=Onion Watch
AppPublisherURL=https://github.com/Onion-Alien/onion-watch
AppSupportURL=https://github.com/Onion-Alien/onion-watch/issues
AppUpdatesURL=https://github.com/Onion-Alien/onion-watch/releases
AppCopyright=Copyright (C) Onion Watch contributors
; a named, versioned setup file rather than a blank one (Properties -> Details), which
; also helps virus scanners that distrust those
VersionInfoVersion={#AppVersion}
VersionInfoProductName={#AppName}
VersionInfoProductVersion={#AppVersion}
VersionInfoCompany=Onion Watch
VersionInfoDescription={#AppName} Setup
VersionInfoCopyright=Copyright (C) Onion Watch contributors
DefaultDirName={localappdata}\Programs\{#AppExeName}
DefaultGroupName={#AppName}
PrivilegesRequired=lowest
DisableDirPage=yes
DisableProgramGroupPage=yes
DisableReadyPage=yes
DisableWelcomePage=no
WizardStyle=modern
WizardSizePercent=110
SetupIconFile=..\build\onionwatch.ico
; Hoot, drawn by scripts\make_installer_art.py
WizardImageFile=wizard-1x.bmp,wizard-2x.bmp
WizardSmallImageFile=wizard-small-1x.bmp,wizard-small-2x.bmp
UninstallDisplayIcon={app}\{#AppExeName}.exe
OutputDir=..\dist
OutputBaseFilename=OnionWatch-Installer
; zip, not solid: DON'T go back to lzma. With Compression=lzma2 + SolidCompression=yes
; Microsoft's machine-learning scanner on VirusTotal called nearly every build of this
; installer Trojan:Win32/Wacatac.B!ml, whatever was inside it (even with no
; OnionWatch.exe); the same files zipped scan clean. Costs about 30 MB. See README.
Compression=zip
SolidCompression=no
ArchitecturesAllowed=x64compatible
ArchitecturesInstallIn64BitMode=x64compatible
CloseApplications=yes

[Messages]
WelcomeLabel1=Let's set up Onion Watch
WelcomeLabel2=Onion Watch plays a sound when something shows up in your game: a rare spawn, a queue pop, a whisper, even while you're alt-tabbed away. It only looks: it never clicks, types or touches the game.%n%nDid Windows or your browser warn you before this opened ("Windows protected your PC", "not commonly downloaded")? That's normal for a free app that isn't code-signed. Next time: More info, then Run anyway.%n%nClick Next to start.
FinishedHeadingLabel=All done!
FinishedLabel=Onion Watch is installed. You can find it later in the Start menu.%n%nPrivacy: no account or ads. If you left Count me in ticked, it sends anonymous usage stats once a day (never your name, IP address or device info). Settings > Updates and privacy can switch it and the update check off.
WizardSelectTasks=Pick what you want
SelectTasksDesc=Tick what you'd like. If you're not sure, leave the boxes as they are.

[Tasks]
Name: "desktopicon"; Description: "Put an Onion Watch shortcut on my Desktop"; GroupDescription: "Shortcuts"
Name: "countme"; Description: "Count me in: anonymous usage stats (features used, crash counts)"; GroupDescription: "Privacy (optional)"

[InstallDelete]
; the last version's runtime: cleared first so files a release no longer ships don't
; linger. Settings, pictures and sounds live in %APPDATA%\OnionWatch.
Type: filesandordirs; Name: "{app}\_internal"

[Files]
; /DPREVIEW: a look at the pages only, for screenshots (nothing to install)
#ifndef PREVIEW
Source: "..\dist\OnionWatch\*"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs createallsubdirs
#endif

[Icons]
Name: "{autodesktop}\{#AppName}"; Filename: "{app}\{#AppExeName}.exe"; AppUserModelID: "OnionWatch.App"; Tasks: desktopicon
Name: "{autoprograms}\{#AppName}"; Filename: "{app}\{#AppExeName}.exe"; AppUserModelID: "OnionWatch.App"

[Run]
; "Count me in" (onionwatch/usage.py): unticked, it's switched off before the first
; start; the only thing ever sent is one anonymous "opt-out/installer" (no ID). Ticked on a page the user saw, it's switched on (an
; old install had it off); a silent update never switches it on.
Filename: "{app}\{#AppExeName}.exe"; Parameters: "--usage-count off"; \
  StatusMsg: "Switching off the usage count..."; \
  Tasks: not countme; Flags: runhidden waituntilterminated
; It also passes on the last page's "Where did you hear about Onion Watch?".
Filename: "{app}\{#AppExeName}.exe"; Parameters: "--usage-count on{code:HeardArg}"; \
  StatusMsg: "Switching on the usage count..."; \
  Tasks: countme; Check: not WizardSilent; Flags: runhidden waituntilterminated
Filename: "{app}\{#AppExeName}.exe"; Description: "Open Onion Watch now"; Flags: nowait postinstall skipifsilent
; The app's own updater (onionwatch/updates.py) runs this silently with /RELAUNCH=1
; after closing itself: open it again once the new version is in place. Through
; Explorer, so it starts with the user's own environment like a double-click does,
; not the old frozen app's (Onion Board 1.3.3 -> 1.4.0 crashed on start from that).
Filename: "{win}\explorer.exe"; Parameters: """{app}\{#AppExeName}.exe"""; Flags: nowait; Check: Relaunch

; Uninstalling leaves %APPDATA%\OnionWatch (settings, pictures, sounds) in place.

[Code]
const
  PrivacyURL = 'https://github.com/Onion-Alien/onion-watch/blob/main/SECURITY.md#what-the-app-touches';

var
  PrivacyPage: TWizardPage;
  HeardPage: TWizardPage;      // "Where did you hear about Onion Watch?": new installs
  HeardRadios: array of TNewRadioButton;
  HeardKeys: array of String;  // what each one sends (onionwatch/usage.py's HEARD)
  HeardOther: TNewEdit;        // Other's own answer

// /RELAUNCH=1: started by the app's Update now (see [Run])
function Relaunch: Boolean;
begin
  Result := ExpandConstant('{param:RELAUNCH|0}') = '1';
end;

procedure OpenPrivacyLink(Sender: TObject);
var
  Code: Integer;
begin
  ShellExecAsOriginalUser('open', PrivacyURL, '', '', SW_SHOWNORMAL, ewNoWait, Code);
end;

// "Your privacy": what the app connects to, in plain words. Interactive installs only.
procedure CreatePrivacyPage;
var
  Body, Link: TNewStaticText;
  Bullet: String;
begin
  Bullet := '  ' + #$2022 + '  ';
  PrivacyPage := CreateCustomPage(wpWelcome, 'Your privacy',
    'What Onion Watch connects to, and when');
  Body := TNewStaticText.Create(PrivacyPage);
  Body.Parent := PrivacyPage.Surface;
  Body.AutoSize := False;
  Body.WordWrap := True;
  Body.Width := PrivacyPage.SurfaceWidth;
  Body.ShowAccelChar := False;
  Body.Caption :=
    'No account, no ads. Onion Watch looks at your windows on this PC only: what it ' +
    'sees is never saved or sent anywhere.' + #13#10#13#10 +
    'It goes online for just two things, once a day:' + #13#10 +
    Bullet + 'to check GitHub for a new version (nothing downloads until you click ' +
    'Update now)' + #13#10 +
    Bullet + 'to send anonymous usage stats if Count me in is ticked on the next ' +
    'page: the version, which features are used, crash counts and a random number ' +
    'made on this PC. Never your name, IP address or device info.' + #13#10#13#10 +
    'You can switch both off any time in Settings > Updates and privacy.';
  Body.AdjustHeight;
  Link := TNewStaticText.Create(PrivacyPage);
  Link.Parent := PrivacyPage.Surface;
  Link.Caption := 'See exactly what the app touches';
  Link.Cursor := crHand;
  Link.Font.Color := clHotLight;
  Link.Font.Style := [fsUnderline];
  Link.OnClick := @OpenPrivacyLink;
  Link.Top := Body.Top + Body.Height + ScaleY(10);
end;

procedure HeardOtherTyped(Sender: TObject);
begin
  if HeardOther.Text <> '' then
    HeardRadios[GetArrayLength(HeardRadios) - 2].Checked := True;   // Other
end;

procedure AddHeardRadio(Key, Caption: String; var Top: Integer);
var
  I: Integer;
  R: TNewRadioButton;
begin
  I := GetArrayLength(HeardRadios);
  SetArrayLength(HeardRadios, I + 1);
  SetArrayLength(HeardKeys, I + 1);
  R := TNewRadioButton.Create(HeardPage);
  R.Parent := HeardPage.Surface;
  R.Top := Top;
  R.Width := HeardPage.SurfaceWidth;
  R.Height := ScaleY(17);
  R.Caption := Caption;
  HeardRadios[I] := R;
  HeardKeys[I] := Key;
  Top := Top + ScaleY(21);
end;

// The last page of a new install with Count me in ticked: where they heard about the
// app, sent once with the first-start count (onionwatch/usage.py heard_tag, which
// drops a typed answer that doesn't look like a name). "Rather not say" is picked.
procedure CreateHeardPage;
var
  Body, Note: TNewStaticText;
  Top: Integer;
begin
  HeardPage := CreateCustomPage(wpSelectTasks, 'One last thing',
    'Where did you hear about Onion Watch?');
  Body := TNewStaticText.Create(HeardPage);
  Body.Parent := HeardPage.Surface;
  Body.AutoSize := False;
  Body.WordWrap := True;
  Body.Width := HeardPage.SurfaceWidth;
  Body.ShowAccelChar := False;
  Body.Caption := 'It helps us know where people find it. Your pick goes once with the ' +
    'anonymous Count me in, and nothing else is sent.';
  Body.AdjustHeight;
  Top := Body.Top + Body.Height + ScaleY(10);
  AddHeardRadio('youtube', 'YouTube', Top);
  AddHeardRadio('reddit', 'Reddit', Top);
  AddHeardRadio('github', 'GitHub', Top);
  AddHeardRadio('google', 'Google', Top);
  AddHeardRadio('friend', 'A friend', Top);
  AddHeardRadio('onion-board', 'Onion Board', Top);
  AddHeardRadio('other', 'Other:', Top);
  HeardOther := TNewEdit.Create(HeardPage);
  HeardOther.Parent := HeardPage.Surface;
  HeardOther.Left := ScaleX(70);
  HeardOther.Top := HeardRadios[6].Top - ScaleY(3);
  HeardOther.Width := ScaleX(200);
  HeardOther.MaxLength := 40;
  HeardOther.OnChange := @HeardOtherTyped;
  HeardRadios[6].Width := HeardOther.Left - ScaleX(4);
  AddHeardRadio('', 'Rather not say', Top);
  HeardRadios[7].Checked := True;
  Note := TNewStaticText.Create(HeardPage);
  Note.Parent := HeardPage.Surface;
  Note.AutoSize := False;
  Note.WordWrap := True;
  Note.Width := HeardPage.SurfaceWidth;
  Note.Top := Top + ScaleY(4);
  Note.ShowAccelChar := False;
  Note.Caption := 'For Other, just a name like Discord or TikTok. Anything else ' +
    '(an email address, a link, a number) is left out.';
  Note.AdjustHeight;
end;

// A first install: no settings from an earlier one. An update already sent its
// first-start, so it isn't asked.
function IsNewInstall: Boolean;
begin
  Result := not FileExists(ExpandConstant('{userappdata}\OnionWatch\config.json'));
end;

function HeardShown: Boolean;
begin
  Result := IsNewInstall and WizardIsTaskSelected('countme') and not WizardSilent;
end;

// " --heard-from <answer>" for the "--usage-count on" entry, or nothing
function HeardArg(Param: String): String;
var
  I: Integer;
  V: String;
begin
  Result := '';
  if not HeardShown then
    exit;
  V := '';
  for I := 0 to GetArrayLength(HeardRadios) - 1 do
    if HeardRadios[I].Checked then
      V := HeardKeys[I];
  if V = 'other' then
  begin
    V := Trim(HeardOther.Text);
    StringChangeEx(V, '"', '', True);
  end;
  if V <> '' then
    Result := ' --heard-from "' + V + '"';
end;

function ShouldSkipPage(PageID: Integer): Boolean;
begin
  Result := (PageID = HeardPage.ID) and not HeardShown;
end;

// Next or Install on the boxes page (there's no Ready page): Install when the
// "where did you hear" page won't follow, which changes as Count me in is ticked.
procedure UpdateInstallCaption;
begin
  if (WizardForm.CurPageID = HeardPage.ID) or
     ((WizardForm.CurPageID = wpSelectTasks) and not HeardShown) then
    WizardForm.NextButton.Caption := SetupMessage(msgButtonInstall)
  else if WizardForm.CurPageID = wpSelectTasks then
    WizardForm.NextButton.Caption := SetupMessage(msgButtonNext);
end;

procedure TasksClicked(Sender: TObject);
begin
  UpdateInstallCaption;
end;

procedure InitializeWizard;
begin
  CreatePrivacyPage;
  CreateHeardPage;
  WizardForm.TasksList.OnClickCheck := @TasksClicked;
end;

procedure CurPageChanged(CurPageID: Integer);
begin
  UpdateInstallCaption;
end;

procedure CurUninstallStepChanged(CurUninstallStep: TUninstallStep);
var
  Code: Integer;
begin
  if CurUninstallStep <> usUninstall then
    exit;
  // the anonymous usage count's "uninstall/<version>" (onionwatch/usage.py): the app
  // sends it only if the count is switched on, and gives up after 15 s offline
  Exec(ExpandConstant('{app}\{#AppExeName}.exe'), '--uninstall-count', '', SW_HIDE,
       ewWaitUntilTerminated, Code);
end;
