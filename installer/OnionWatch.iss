; OnionWatchSetup.exe: one file a non-technical person double-clicks.
;
;   - no Python needed: it ships the PyInstaller build (dist\OnionWatch)
;   - no admin needed (installs per user)
;   - a Start menu shortcut, a Desktop one if ticked, then opens Onion Watch
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
WizardStyle=modern
SetupIconFile=..\build\onionwatch.ico
; Hoot, drawn by scripts\make_installer_art.py
WizardImageFile=wizard-1x.bmp,wizard-2x.bmp
WizardSmallImageFile=wizard-small-1x.bmp,wizard-small-2x.bmp
UninstallDisplayIcon={app}\{#AppExeName}.exe
OutputDir=..\dist
OutputBaseFilename=OnionWatchSetup
Compression=lzma2/ultra64
SolidCompression=yes
LZMAUseSeparateProcess=yes
ArchitecturesAllowed=x64compatible
ArchitecturesInstallIn64BitMode=x64compatible
CloseApplications=yes

[Messages]
WelcomeLabel1=Let's set up Onion Watch
WelcomeLabel2=Onion Watch plays a sound when something shows up in your game: a rare spawn, a queue pop, a whisper, even while you're alt-tabbed away. It only looks: it never clicks, types or touches the game.%n%nDid Windows or your browser warn you before this opened ("Windows protected your PC", "not commonly downloaded")? That's normal for a free app that isn't code-signed. Next time: More info, then Run anyway.%n%nClick Next to start.
FinishedHeadingLabel=All done!
FinishedLabel=Onion Watch is installed. You can find it later in the Start menu.

[Tasks]
Name: "desktopicon"; Description: "Put an Onion Watch shortcut on my Desktop"; GroupDescription: "Shortcuts"

[InstallDelete]
; the last version's runtime: cleared first so files a release no longer ships don't
; linger. Settings, pictures and sounds live in %APPDATA%\OnionWatch.
Type: filesandordirs; Name: "{app}\_internal"

[Files]
Source: "..\dist\OnionWatch\*"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs createallsubdirs

[Icons]
Name: "{autodesktop}\{#AppName}"; Filename: "{app}\{#AppExeName}.exe"; AppUserModelID: "OnionWatch.App"; Tasks: desktopicon
Name: "{autoprograms}\{#AppName}"; Filename: "{app}\{#AppExeName}.exe"; AppUserModelID: "OnionWatch.App"

[Run]
Filename: "{app}\{#AppExeName}.exe"; Description: "Open Onion Watch now"; Flags: nowait postinstall skipifsilent

; Uninstalling leaves %APPDATA%\OnionWatch (settings, pictures, sounds) in place.
