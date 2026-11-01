# Privacy

Onion Watch has no account and no ads. It looks at the game windows you pick, on
your PC, and plays a sound. What it sees is never saved or sent anywhere. The full
detail, file by file and address by address, is in
[SECURITY.md](../SECURITY.md#what-the-app-touches).

## What it sends

Only two things go online by themselves, both once a day and both switchable off in
Settings → *Updates and privacy*:

- **The update check:** asks GitHub (`api.github.com`) whether there's a newer
  version. Nothing downloads until you click *Update now*.
- **The anonymous usage count** (*Count me in*), to `onionalien.goatcounter.com`: the
  version, a random ID made on your PC, rough numbers (how many triggers, how often
  they went off), the app's language, which features are used, and crash counts (the
  error's type and where in Onion Watch's own code, never its message). Never your
  name, IP address, device details, triggers, pictures, window names, games or
  anything you type. The installer shows this on its *Your privacy* page and has a
  *Count me in* box (ticked) on its options page: untick it there or switch it off
  later, and one last anonymous "opted out" is sent, then nothing.

Everything else goes out only when you click it: *Update now* downloads the new
installer from this project's GitHub releases, and *Send feedback* / *Report a
problem* open your browser.

Inside Onion Board (as its Triggers tab) neither of these runs: the board has its own,
see its privacy page.

## What it reads on your PC

- **Pictures of the windows or screens you pick**, to find the pictures you cut out:
  a window is copied with Windows' `PrintWindow` (so it's still seen behind other
  windows), a screen with Windows' Desktop Duplication, the same way screen recorders
  and Discord's screen share do. Kept in memory only.
- **The list of open windows** (their titles and program names), so you can pick
  one, and to find a picked game again when it restarts.
- **How long since the mouse or keyboard was last touched**, from Windows' own idle
  timer, for triggers that ring until you're back. Only that time: no keyboard or
  mouse hook, and nothing about which keys.

It never sends input to a game or any other program (no keys, clicks or mouse
moves), never reads or writes another program's memory and never injects code.

## What it changes on your PC

The installer (no admin rights needed, for your Windows user only) adds:

- the app, in `%LOCALAPPDATA%\Programs\OnionWatch`;
- a Start menu shortcut, and a Desktop one if you tick it;
- its entry in Windows' *Installed apps*, for uninstalling.

The app keeps its settings, log, the pictures you cut and copies of the sounds you
add in `%APPDATA%\OnionWatch`, update downloads in its `updates` folder (removed
after installing), and a few small drawn images in your temp folder. It doesn't start
with Windows, adds no services, drivers or scheduled tasks, and changes no Windows
settings.

## Uninstalling

Windows Settings → *Apps* → *Installed apps* → Onion Watch → *Uninstall* removes the
app, its shortcuts and its *Installed apps* entry. It then asks whether to delete your
triggers, pictures, sounds and settings too: *Yes* puts `%APPDATA%\OnionWatch` in the
Recycle Bin, *No* (the default) keeps them for a later install. A silent uninstall
never asks and keeps them.
