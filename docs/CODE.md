# Inside Onion Watch

For people changing the code. The rules are in the repo's `CLAUDE.md`.

## Running from source

Windows 10 or 11, Python 3.12 or newer:

```bat
python -m venv .venv
.venv\Scripts\pip install -r requirements-dev.txt
.venv\Scripts\pythonw main.py
```

Checks: `.venv\Scripts\ruff check .` and `.venv\Scripts\python -m pytest`. The
tests run Qt offscreen with stand-in captures and a silent audio stream, so they
never read your screen or make a sound. `scripts\docs.py` rebuilds the README's and website's pictures (`screenshots.py`, from
made-up data in the Retro 98 theme, and `make_art.py`: Hoot, the avatar and the social
preview in `docs\art\`) and their version line.

Settings, the log, your pictures and your sound files live in
`%APPDATA%\OnionWatch`.

## Inside Onion Board

Onion Watch is also [Onion Board](https://github.com/Onion-Alien/onion-board)'s
Triggers tab, as an add-on. When you click **Get Onion Watch** on that tab, Onion
Board downloads `OnionWatch-module.zip` from this project's latest release,
checks it against the SHA-256 GitHub lists for it, and runs it right there: the
same triggers page, playing the board's sounds into your mic mix, in the board's
theme. Triggers made in the old built-in tab carry on as they were. It's one
codebase: the page talks to whichever program it runs in through a small host
interface (`onionwatch/host.py`).

To release a new version:

1. Bump `__version__` in `onionwatch/__init__.py`. If the host interface changed
   in a way an older Onion Board can't follow, also bump `API_VERSION` in
   `onionwatch/host.py` (Onion Board refuses a module whose version it doesn't
   know, with a message, instead of crashing).
2. `powershell -ExecutionPolicy Bypass -File build.ps1 -Clean -Scan` builds the app
   (`dist\OnionWatch\OnionWatch.exe`, self-tested), the installer
   (`dist\OnionWatch-Installer.exe`, needs [Inno Setup 6](https://jrsoftware.org/isinfo.php))
   and the add-on (`dist\OnionWatch-module.zip`, via `scripts\build_module.py`, which
   fails if the page imports anything Onion Board doesn't ship: it has no pip).
   `-Scan` then checks the installer on VirusTotal (`scripts\vt_scan.py`, needs a free
   API key in `VT_API_KEY` or `~/.secrets/virustotal.env`).

   **Microsoft's `Trojan:Win32/Wacatac.B!ml`** (a machine-learning false positive on
   VirusTotal; Windows Defender itself finds nothing) is handled by two things in the
   build. Don't undo either:
   - the installer is **zip-compressed, not lzma** (`Compression=zip`,
     `SolidCompression=no` in `installer\OnionWatch.iss`). With solid lzma, 8 of 9
     test installers were flagged whatever was in them: 0.4.0, 0.3.1's source built
     again, even one with no `OnionWatch.exe` inside. So it was never the app's code
     or the bootloader, and 0.3.1's clean scan was luck. The same files zipped scanned
     clean every time. It costs about 30 MB;
   - every build uses a PyInstaller bootloader compiled on your PC
     (`scripts\build_bootloader.ps1`, needs gcc: `winget install
     BrechtSanders.WinLibs.POSIX.UCRT`), because PyPI's stock one is the same file in
     thousands of programs; `build.ps1` compiles one itself if the stock one is
     installed.

   If the scan flags the installer anyway, **don't release it**. Find what changed
   with one change at a time (an installer takes a minute to build with Inno Setup, a
   new file scans in a few), and scan several samples of a fix before trusting it:
   one clean scan can be luck.
3. `gh release create vX.Y.Z dist\OnionWatch-Installer.exe dist\OnionWatch-module.zip --target main --title "Onion Watch X.Y.Z"`.
   Keep both file names: the website links to the installer, Onion Board looks for the zip.
   GitHub lists a release's files by name, so the installer is named to sort first
   (`OnionWatch-I…` before `OnionWatch-m…`): it's the file people should click.
   Under the notes' one-line headline, put a download line, since GitHub adds two
   *Source code* files that people mistake for the app:
   `**[⬇ Download OnionWatch-Installer.exe](https://github.com/Onion-Alien/onion-watch/releases/download/vX.Y.Z/OnionWatch-Installer.exe)**: the one file you need. Run it to install Onion Watch. (The *Source code* files are for developers.)`
   Keep it second, not first: Onion Board's Triggers tab shows the start of the notes
   when it offers the update (newer boards skip the ⬇ line, older ones don't).

To try a zip in Onion Board before releasing it, start Onion Board with
`ONIONBOARD_ONION_WATCH_ZIP` set to the zip's path: its *Get Onion Watch* button
then installs that file instead of downloading.

## Code layout

| Path | What |
|---|---|
| `onionwatch/screenwatch.py` | the engine: screen capture (DXGI Desktop Duplication, GDI fallback, grey and when needed colour), the matcher, the kinds of trigger (appears, goes away, area changes / stops changing, colour level) and their areas, the fire-once `Gate`, the watcher thread (one capture per screen or window in use, every copy of a game expanded), `Trigger`, `WindowRef` and `Hit` |
| `onionwatch/cutout.py` | learning a cut's background while it's cut: grabs of the window while the cut dialog is open, the scenery that moved left out of the picture when that does better, and how well the kept picture did (for the cut-time warning) |
| `onionwatch/imgops.py` | the matcher's image operations: FFTs (scipy.fft, numpy's without it), Gaussian softening, smooth enlarging, mask erosion (numpy). Of scipy, Onion Board ships only scipy.fft |
| `onionwatch/windows.py` | listing windows, finding a remembered one again (and the right copy), `PrintWindow` capture of a covered window, full-size snapshots for cutting |
| `onionwatch/sounds.py` | the built-in alert sounds (made in code) and the added sound files |
| `onionwatch/player.py` | the output stream that mixes and rings the alerts |
| `onionwatch/settings.py` | `%APPDATA%\OnionWatch` and `config.json` |
| `onionwatch/app.py` | start-up: logging, one copy at a time, the window, `--selftest` |
| `onionwatch/host.py` | what the triggers page needs from the program it runs in (settings, sounds, playing, theme): the Onion Watch app or Onion Board |
| `onionwatch/apphost.py` | the Onion Watch app as that host |
| `onionwatch/board.py` | the Onion Board add-on's entry point: `create(host)` gives the board its Triggers tab (alarm bar + triggers page) |
| `onionwatch/ui/triggerspanel.py` | the triggers page: one card per trigger, "Look in", Watching, Cut picture. Talks only to its host |
| `onionwatch/ui/alarmbar.py` | the red bar shown while a trigger rings, with Stop |
| `onionwatch/profiles.py` | trigger categories and profiles: which triggers are on now (Manual switches, a profile, or Automatic by the programs open), saved beside the triggers in `Config.screen` |
| `onionwatch/ui/categories.py` | a category's section in the list (fold, switch, counts, menu; its cards made only once opened) and the Profiles window |
| `onionwatch/ui/windowpicker.py` | the window list with live thumbnails; ticking several windows and screens, or every copy of a game |
| `onionwatch/ui/snip.py` | cutting a picture out of a capture; picking a trigger's area and a bar's colour |
| `onionwatch/ui/viewer.py` | a trigger's pictures shown big (whole pixels, full screen), to swap or remove them |
| `onionwatch/ui/history.py` | "What went off": the latest alerts with a picture of each moment (in memory only) |
| `onionwatch/ui/deleted.py` | Recently deleted triggers (kept 30 days with their pictures, in the saved settings) |
| `onionwatch/packs.py` | saving triggers to a .zip with their pictures and loading them back |
| `onionwatch/ui/mainwindow.py` | the window, the tray icon, notifications |
| `onionwatch/ui/settingsdialog.py` | output device, volume, notifications, tray, theme |
| `onionwatch/ui/watching.py` | the Triggers bar's ⚙: how much of the processor watching may use, "Max detection", and how often each trigger is checked now |
| `onionwatch/owl.py` | Hoot, the mascot owl, drawn in code (Onion Board's Bun's style), and `OwlWidget`: Hoot animated, waiting for a trigger |
| `onionwatch/theme.py`, `ui/icons.py`, `ui/panel.py` | themes, the logo, painted icons and layout helpers, shared with Onion Board |
| `onionwatch/singleinstance.py` | one copy at a time: a second launch brings the running one to the front |
| `onionwatch/shuffle.py`, `wheelguard.py` | picking sounds "at random" without repeats; the mouse wheel scrolls the page instead of changing a box |
| `scripts/docs.py`, `scripts/screenshots.py`, `scripts/make_art.py` | the README and website in one go: the screenshots and `docs/art` (rendered offscreen from made-up data), the version and VirusTotal line from `docs/release.json`, picture links that skip cached copies |
| `build.ps1`, `installer/OnionWatch.iss` | the Windows build (PyInstaller) and its installer (Inno Setup) |
| `scripts/prune_build.py`, `make_notices.py`, `make_installer_art.py`, `make_version_info.py` | the build's helpers: drop the Qt parts the app never loads, the third-party licence notices, the icon and the setup wizard's pictures, the exe's version details |
| `scripts/build_bootloader.ps1`, `scripts/vt_scan.py` | PyInstaller with a bootloader compiled on your PC (virus scanners distrust the stock one); the VirusTotal check for a release |
| `docs/index.html` | the website, [onion-alien.github.io/onion-watch](https://onion-alien.github.io/onion-watch/) (GitHub Pages, from `docs/`) |
| `scripts/check_sensitive.py` | scans files, commits and history for secrets and personal data; the pre-commit hook |
| `scripts/live_check.py` | the real thing on this PC: two copies of a stand-in game (real windows, one covered), real `PrintWindow` capture, the triggers page as Onion Board loads it, one trigger for every copy in an area, one for a picture going away; prints PASS. Opens windows for a few seconds (never takes the focus) |
| `scripts/build_module.py` | builds `OnionWatch-module.zip` for Onion Board: `module.json` and only the modules the board's tab needs, checked against what Onion Board ships |
| `tests/` | pytest: the matcher, the watcher on stand-in screens and windows (several copies of a game, every copy, not open yet, closed and reopened, minimized, resized), each kind of trigger and its area, the sounds and player, the UI offscreen |
