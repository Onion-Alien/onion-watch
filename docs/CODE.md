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
made-up data in the Dark theme, and `make_art.py`: Hoot, the avatar and the social
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

Closed cards have a remembered "Show more info" view (`Config.screen.advanced_cards`).
Each trigger may save `interval_ms`; zero or an absent value inherits the global
interval. The watcher shares captures and its processor budget, checking only
triggers whose interval has elapsed. A host may optionally provide
`sound_details(id)` to describe volume and hotkeys; older hosts remain supported.
It may also provide `language()` (the board's language code): the page then shows in
that language when Onion Watch has it, else in Windows' language. Both are optional,
so `API_VERSION` stays the same.

To release a new version:

1. Bump `__version__` in `onionwatch/__init__.py`. If the host interface changed
   in a way an older Onion Board can't follow, also bump `API_VERSION` in
   `onionwatch/host.py` (Onion Board refuses a module whose version it doesn't
   know, with a message, instead of crashing).
2. `powershell -ExecutionPolicy Bypass -File build.ps1 -Clean -Scan` builds the app
   (`dist\OnionWatch\OnionWatch.exe`, self-tested), the installer
   (`dist\OnionWatch-Installer.exe`, needs [Inno Setup 6](https://jrsoftware.org/isinfo.php))
   and the add-on (`dist\OnionWatch-module.zip`, via `scripts\buildtools\build_module.py`, which
   fails if the page imports anything Onion Board doesn't ship: it has no pip).
   `-Scan` then checks the installer on VirusTotal (`scripts\buildtools\vt_scan.py`, needs a free
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
     (`scripts\buildtools\build_bootloader.ps1`, needs gcc: `winget install
     BrechtSanders.WinLibs.POSIX.UCRT`), because PyPI's stock one is the same file in
     thousands of programs; `build.ps1` compiles one itself if the stock one is
     installed.

   If the scan flags the installer anyway, **don't release it**. Find what changed
   with one change at a time (an installer takes a minute to build with Inno Setup, a
   new file scans in a few), and scan several samples of a fix before trusting it:
   one clean scan can be luck.
3. `gh release create vX.Y.Z dist\OnionWatch-Installer.exe dist\OnionWatch-Update.exe dist\OnionWatch-module.zip --target main --title "Onion Watch X.Y.Z"`.
   Keep the file names: the website links to the installer, Onion Board looks for the zip,
   and the app's *Update now* (`onionwatch/core/updates.py`) fetches `OnionWatch-Update.exe`
   (the installer uploaded twice, so GitHub's download counts tell updates apart from
   downloads off the website; without it, the installer).
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

The package is sorted by what each part does. Only the entry points stay at the top of
`onionwatch/`: `board.py` (what Onion Board loads), `host.py` (what the triggers page
needs from the program it runs in), `i18n.py` with `langnames_data.py`, and
`__main__.py`.

| Folder | What's in it |
|---|---|
| `onionwatch/engine/` | watching: capture, the matcher and the watcher thread, the windows to watch, triggers' categories and profiles, packs. Knows nothing about hosts or the UI |
| `onionwatch/core/` | the app's plumbing: start-up, settings, one copy at a time, updates, the usage count, feedback links |
| `onionwatch/audio/` | the alert sounds and the player that rings them (the app only: inside Onion Board the board plays them) |
| `onionwatch/style/` | Onion Board's style kit, copied exactly (`scripts/sync_style.py`): never edited here |
| `onionwatch/ui/kit/` | shared UI pieces: the theme, the style kit in use, icons, bars and cards, the logo |
| `onionwatch/ui/window/` | the Onion Watch app's own window: the main window, the splash, the update dialog |
| `onionwatch/ui/settings/` | Settings: the app's dialog, the board's Settings tab, Watching settings and what they open |
| `onionwatch/ui/triggers/` | the triggers page both hosts show, its cards and everything it opens |
| `scripts/checks/`, `scripts/buildtools/` | the checks precommit and CI run; the build's steps. What people run by hand stays in `scripts/` |

Nothing goes deeper than two folders below `onionwatch/` (an error's count only names
our files that deep: `core/usage.py` `_OUR_FRAME`).

| Path | What |
|---|---|
| `onionwatch/engine/screenwatch.py` | the engine: screen capture (DXGI Desktop Duplication, GDI fallback, grey and when needed colour), the matcher, the kinds of trigger (appears, goes away, area changes / stops changing, colour level) and their areas, the fire-once `Gate`, the watcher thread (one capture per screen or window in use, every copy of a game expanded), `Trigger`, `WindowRef` and `Hit` |
| `onionwatch/engine/cutout.py` | learning a cut's background while it's cut: grabs of the window while the cut dialog is open, the scenery that moved left out of the picture when that does better, and how well the kept picture did (for the cut-time warning) |
| `onionwatch/engine/imgops.py` | the matcher's image operations: FFTs (scipy.fft, numpy's without it), Gaussian softening, smooth enlarging, mask erosion (numpy). Of scipy, Onion Board ships only scipy.fft |
| `onionwatch/engine/windows.py` | listing windows, finding a remembered one again (and the right copy), `PrintWindow` capture of a covered window (a fullscreen game in front is read off its screen through a shared duplication, `screenwatch.share_dup`), full-size snapshots for cutting |
| `onionwatch/audio/sounds.py` | the built-in alert sounds (made in code) and the added sound files |
| `onionwatch/audio/player.py` | the output stream that mixes and rings the alerts |
| `onionwatch/core/settings.py` | `%APPDATA%\OnionWatch` and `config.json` |
| `onionwatch/core/updates.py` | the daily update check and *Update now* (standalone app only) |
| `onionwatch/core/usage.py` | the anonymous daily usage count, GoatCounter (standalone app only) |
| `onionwatch/ui/settings/countdialog.py` | *What Count me in sends*: the table behind Settings' eye button (in step with `usage.py` and SECURITY.md) |
| `onionwatch/core/feedback.py` | Send feedback / Report a problem links |
| `onionwatch/core/app.py` | start-up: logging, one copy at a time, the window, `--selftest` |
| `onionwatch/ui/kit/themecover.py` | a still of each window with Hoot over it while a theme switch restyles every widget, faded in and out (the kit's `style/cover.py`): never a half-styled frame or a flash |
| `onionwatch/ui/window/splash.py` | the start-up splash: Hoot hopping on the desktop until the window is up, drawn on a thread of its own |
| `onionwatch/__main__.py` | `python -m onionwatch` |
| `onionwatch/host.py` | what the triggers page needs from the program it runs in (settings, sounds, playing, theme): the Onion Watch app or Onion Board |
| `onionwatch/core/apphost.py` | the Onion Watch app as that host |
| `onionwatch/board.py` | the Onion Board add-on's entry point: `create(host, parent=None)` gives the board its Triggers tab, made on `parent` when given (alarm bar + triggers page) |
| `onionwatch/ui/triggers/triggerspanel.py` | the triggers page (`TriggersTab`): the list of cards, search and views, "Look in", Watching, Cut picture, saving the triggers. Talks only to its host |
| `onionwatch/ui/triggers/card.py` | one trigger's card (`TriggerRow`): its header and, opened, everything about the trigger |
| `onionwatch/ui/triggers/cardkit.py` | the small widgets a card is built from: lists and number boxes that fit their text, the picture strip, flowing rows, the tune grid, switches, the cards' style sheet |
| `onionwatch/ui/triggers/pictures.py` | a trigger's pictures on disk: the size each was cut at, saving, loading, deleting, thumbnails |
| `onionwatch/ui/triggers/pages.py` | the triggers page as both hosts show it: the Triggers / Log tabs and the Playing now bar under them |
| `onionwatch/ui/kit/watchlogo.py` | the logo that shows it's watching: a start-up animation and an idle animation that suit the theme, the eye looking around while it watches |
| `onionwatch/ui/settings/boardsettings.py` | inside Onion Board only, the Settings tab: what Onion Watch is with its links, the Watching cards, and the board's Remove Onion Watch |
| `onionwatch/ui/triggers/alarmbar.py` | the red bar shown while a trigger rings, with Stop |
| `onionwatch/engine/profiles.py` | trigger categories and profiles: which triggers are on now (Manual switches, a profile, or Automatic by the programs open), saved beside the triggers in `Config.screen` (a category's look in `category_looks`, apart, so older versions keep it) |
| `onionwatch/ui/triggers/categories.py` | a category's section in the list (fold, switch, counts, menu, its colours and picture; its cards made only once opened), the Categories window (each one's look) and the Profiles window |
| `onionwatch/ui/triggers/windowpicker.py` | the window list with live thumbnails; ticking several windows and screens, or every copy of a game |
| `onionwatch/ui/triggers/soundmenu.py` | A trigger card's Play + menu: search box, the host's sound categories, the sounds, Choose a sound file |
| `onionwatch/ui/triggers/whatpick.py` | + New trigger's first steps: what it watches for (five kinds, picked then Continue), then for every kind where its picture comes from (paste it, drop or choose a file, take it from the game): the picture to look for, or a picture of the game to drag the bar's or area's box on |
| `onionwatch/ui/triggers/snip.py` | cutting a picture out of a capture; picking a trigger's area and a bar's colour |
| `onionwatch/ui/triggers/viewer.py` | a trigger's pictures shown big (whole pixels, full screen), to swap or remove them; read on threads so a big one never freezes the window |
| `onionwatch/ui/triggers/chances.py` | Live chances: the card's score bar (with the trigger's line) and the window, from the Playing now bar's Chances button, with every trigger's chance right now ("show_chances" hides the button) |
| `onionwatch/ui/triggers/history.py` | "What went off": the latest alerts with a picture of each moment (in memory only) |
| `onionwatch/ui/triggers/deleted.py` | Recently deleted triggers (kept 30 days with their pictures, in the saved settings) |
| `onionwatch/engine/packs.py` | saving triggers to a .zip with their pictures and loading them back |
| `onionwatch/ui/window/mainwindow.py` | the window, the tray icon, notifications |
| `onionwatch/ui/settings/settingsdialog.py` | Settings, laid out like Onion Board's (categories on the left): output device, volume, notifications, tray, language and theme, updates and privacy, about |
| `onionwatch/ui/settings/langpick.py`, `onionwatch/langnames_data.py` | the Language picker: a tile per language with a search; language names from Unicode CLDR (`scripts/make_langnames.py` writes them) |
| `onionwatch/ui/window/updatedialog.py` | "a new version is out": Update now / Later / Skip |
| `onionwatch/ui/settings/watching.py` | the Triggers bar's ⚙: how much of the processor watching may use, "Max detection", and how often each trigger is checked now |
| `onionwatch/style/` | the style kit: an exact copy of Onion Board's `soundboard/style` (never edited here: `scripts/sync_style.py` copies it and stamps `SOURCE.json`, `tests/test_style_kit.py` checks it). The themes' colours (`palettes.py`) and textures, Bun's outfits (`bunnyfit.py`), and Hoot (`owl.py`: drawn in code, wearing the theme's outfit; `OwlWidget`, Hoot animated, waiting for a trigger) |
| `onionwatch/ui/kit/kit.py` | which style kit draws Hoot: ours, or inside Onion Board the board's (`host.kit()`) when it's at least as new |
| `onionwatch/ui/kit/theme.py`, `ui/kit/icons.py`, `ui/kit/panel.py` | the current theme (Onion Board's themes from the style kit, plus Onion Watch's own Hoot), the stylesheet, the logo, painted icons and layout helpers, shared with Onion Board |
| `onionwatch/core/singleinstance.py` | one copy at a time: a second launch brings the running one to the front (a restart waits for the old copy to close) |
| `onionwatch/i18n.py`, `onionwatch/lang/*.json` | other languages: `_()` / `ngettext()`, the catalogs (inside the package, so they ride in the add-on zip), which language (Settings → Appearance → Language; inside Onion Board, the board's own), Qt's OK / Cancel words, the `xx` pseudo-language. See [TRANSLATING.md](TRANSLATING.md) |
| `onionwatch/ui/kit/fit.py` | dialogs grow to fit their wrapped text (a translation is often longer), shared with Onion Board |
| `scripts/i18n_extract.py` | the wrapped texts against the catalogs: what's missing or unused per language, `--update`, `--check` |
| `onionwatch/audio/shuffle.py` | picking sounds "at random" without repeats |
| `onionwatch/ui/kit/wheelguard.py` | the mouse wheel scrolls the page instead of changing a box |
| `scripts/docs.py`, `scripts/screenshots.py`, `scripts/buildtools/make_art.py` | `sync_style.py` copies Onion Board's style kit into `onionwatch/style`; the others: the README and website in one go: the screenshots and `docs/art` (rendered offscreen from made-up data), the version and VirusTotal line from `docs/release.json`, picture links that skip cached copies |
| `build.ps1`, `installer/OnionWatch.iss` | the Windows build (PyInstaller) and its installer (Inno Setup) |
| `scripts/buildtools/prune_build.py`, `make_notices.py`, `make_installer_art.py`, `make_version_info.py` | the build's helpers: drop the Qt parts the app never loads, the third-party licence notices, the icon and the setup wizard's pictures, the exe's version details |
| `scripts/buildtools/build_bootloader.ps1`, `scripts/buildtools/vt_scan.py` | PyInstaller with a bootloader compiled on your PC (virus scanners distrust the stock one); the VirusTotal check for a release |
| `docs/index.html` | forwards the old address, onion-alien.github.io/onion-watch, to the website at [onionalien.com/onionwatch](https://onionalien.com/onionwatch/) (GitHub Pages, from `docs/`) |
| `scripts/check_sensitive.py` | scans files, commits and history for secrets and personal data; the pre-commit hook |
| `scripts/precommit.ps1` | every check a commit needs in one go (see CLAUDE.md); `-Tests` adds the suite |
| `scripts/checks/check_types.py`, `scripts/checks/pyright_baseline.json` | pyright, failing only on errors that aren't in the baseline |
| `scripts/checks/check_code_doc.py` | every module is in this Code layout table, and the table names none that's gone |
| `scripts/check_utc.sh`, `utc_fix.sh`, `merge_pr.sh` | commit times in UTC: the check (hooks and CI), re-stamping a branch, merging a PR with a UTC merge commit |
| `scripts/checks/live_check.py` | the real thing on this PC: two copies of a stand-in game (real windows, one covered), real `PrintWindow` capture, the triggers page as Onion Board loads it, one trigger for every copy in an area, one for a picture going away; prints PASS. Opens windows for a few seconds (never takes the focus) |
| `scripts/buildtools/build_module.py` | builds `OnionWatch-module.zip` for Onion Board: `module.json` and only the modules the board's tab needs, checked against what Onion Board ships |
| `tests/` | pytest: the matcher, the watcher on stand-in screens and windows (several copies of a game, every copy, not open yet, closed and reopened, minimized, resized), each kind of trigger and its area, the sounds and player, the UI offscreen |
