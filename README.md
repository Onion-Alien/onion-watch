<p align="center"><img src="docs/art/hoot.png" width="150" alt="Hoot, the Onion Watch owl"></p>

# Onion Watch

**Plays a sound when something shows up in a game — even while you're alt-tabbed
into a different one.**

Playing two MMO accounts at once, waiting on a rare spawn, a queue pop or a
whisper while you do something else? Pick the game's window, cut out the thing to
watch for, and choose a sound. Onion Watch keeps looking at that window while it's
behind your other windows and plays the sound, or rings until you stop it, the
moment the thing appears.

![Onion Watch watching two copies of a game, one trigger ringing](docs/screenshots/main.png)

<details>
<summary><b>More screenshots</b></summary>

Picking the window to watch (two copies of the same game are told apart):
![The window picker](docs/screenshots/window-picker.png)

Cutting the picture to watch for straight out of the game window:
![Cutting a picture from a window](docs/screenshots/cut-picture.png)

</details>

## It only looks

Onion Watch reads pixels and plays sounds. It **never** presses keys, clicks,
moves the mouse, reads or changes a game's memory, or injects anything into a
game. It sees what you'd see on your screen, the same way OBS or Discord's screen
share does. That said, some games' terms forbid any third-party tool, so check
the rules of the game you play.

Everything happens on your PC. What it captures is never saved or sent anywhere
(only the pictures you cut are kept), and the app makes no network requests.

## What it does

- **Watches a window, not just a screen.** Windows are captured on their own, so
  a game is still watched while other windows cover it. It can't see a
  **minimized** window, because Windows stops drawing those.
- **Handles several accounts at once.** Each trigger picks its own window. Two
  copies of the same game are told apart by the order they were started, so
  "copy 2" stays your second account's window.
- **Cut from window…** grabs the watched window (even from behind other
  windows) so you can drag a box around the thing to watch for. You can also add
  a picture file or paste one from Win+Shift+S.
- **Ring until stopped.** An alarm keeps playing until you click Stop, the tray
  icon or the Windows notification. Otherwise a sound plays once each time the
  thing appears.
- **Built-in alert sounds** (Chime, Ping, Ready, Bell, Alarm), or any sound file of
  yours. Sounds play on the speakers or headphones you pick in Settings.
- Per trigger:
  - several pictures (any of them counts) and several sounds (at random, in
    turn, or all at once);
  - a wait before playing, and a cooldown before it can play again;
  - how close a match must be, with the live match shown next to it.
- **Keeps watching from the tray** when you close the window.
- The same themes as [Onion Board](https://github.com/Onion-Alien/onion-board),
  plus its own teal **Hoot** theme. Onion Watch started as Onion Board's Triggers
  tab.

## How it works

Each check copies the watched window's inside with `PrintWindow`
(`PW_RENDERFULLCONTENT`). For a screen it uses Desktop Duplication, falling back
to GDI. The copy is shrunk to a few hundred pixels and turned grey. Each picture
is then found with normalised cross-correlation (an FFT), so a match scores the
same however bright the game is. Transparent parts of a picture are left out.

A trigger fires once each time its picture appears, then waits for it to go away
before it can fire again. A window that isn't open yet is looked for every two
seconds, and one that closes is picked up again when it reopens.

If a game's window comes out black (some exclusive-fullscreen games and some
anti-cheat do this), set the trigger to watch the **screen** the game is on
instead.

## Running from source

Windows 10 or 11, Python 3.12 or newer:

```bat
python -m venv .venv
.venv\Scripts\pip install -r requirements-dev.txt
.venv\Scripts\pythonw main.py
```

Checks: `.venv\Scripts\ruff check .` and `.venv\Scripts\python -m pytest`. The
tests run Qt offscreen with stand-in captures and a silent audio stream, so they
never read your screen or make a sound. `scripts\screenshots.py` renders the
screenshots above from made-up data, and `scripts\make_art.py` renders Hoot, the
avatar and the social preview into `docs\art\`.

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
2. `.venv\Scripts\python scripts\build_module.py` builds
   `dist\OnionWatch-module.zip` and prints its SHA-256. It fails if the page
   imports anything Onion Board doesn't ship (it has no pip).
3. `gh release create vX.Y.Z dist\OnionWatch-module.zip --title "Onion Watch X.Y.Z"`.
   Keep the file name: it's what Onion Board looks for.

To try a zip in Onion Board before releasing it, start Onion Board with
`ONIONBOARD_ONION_WATCH_ZIP` set to the zip's path: its *Get Onion Watch* button
then installs that file instead of downloading.

## Code layout

| Path | What |
|---|---|
| `onionwatch/screenwatch.py` | the engine: screen capture (DXGI Desktop Duplication, GDI fallback), the matcher, the fire-once `Gate`, the watcher thread (one capture per screen or window in use), `Trigger` and `WindowRef` |
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
| `onionwatch/ui/windowpicker.py` | the window list with live thumbnails |
| `onionwatch/ui/snip.py` | cutting a picture out of a capture |
| `onionwatch/ui/mainwindow.py` | the window, the tray icon, notifications |
| `onionwatch/ui/settingsdialog.py` | output device, volume, notifications, tray, theme |
| `onionwatch/owl.py` | Hoot, the mascot owl, drawn in code (Onion Board's Bun's style) |
| `onionwatch/theme.py`, `ui/icons.py`, `ui/panel.py` | themes, the logo, painted icons and layout helpers, shared with Onion Board |
| `onionwatch/singleinstance.py` | one copy at a time: a second launch brings the running one to the front |
| `onionwatch/shuffle.py`, `wheelguard.py` | picking sounds "at random" without repeats; the mouse wheel scrolls the page instead of changing a box |
| `scripts/screenshots.py`, `scripts/make_art.py` | the README screenshots and `docs/art`, rendered offscreen from made-up data |
| `scripts/check_sensitive.py` | scans files, commits and history for secrets and personal data; the pre-commit hook |
| `scripts/live_check.py` | the real thing on this PC: two copies of a stand-in game (real windows, one covered), real `PrintWindow` capture, the triggers page as Onion Board loads it; prints PASS. Opens windows for a few seconds (never takes the focus) |
| `scripts/build_module.py` | builds `OnionWatch-module.zip` for Onion Board: `module.json` and only the modules the board's tab needs, checked against what Onion Board ships |
| `tests/` | pytest: the matcher, the watcher on stand-in screens and windows (several copies of a game, not open yet, closed and reopened, minimized, resized), the sounds and player, the UI offscreen |

## Licence

MIT with the Commons Clause, like Onion Board: free to use, change and share, but
not to sell. See [LICENSE](LICENSE).
