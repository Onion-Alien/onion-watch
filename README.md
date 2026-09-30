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
- The same themes as [Onion Board](https://github.com/Onion-Alien/onionboard).
  Onion Watch started as Onion Board's Triggers tab.

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
screenshots above from made-up data.

Settings, the log, your pictures and your sound files live in
`%APPDATA%\OnionWatch`.

## Code layout

| Path | What |
|---|---|
| `onionwatch/screenwatch.py` | the engine: screen capture (DXGI Desktop Duplication, GDI fallback), the matcher, the fire-once `Gate`, the watcher thread (one capture per screen or window in use), `Trigger` and `WindowRef` |
| `onionwatch/windows.py` | listing windows, finding a remembered one again (and the right copy), `PrintWindow` capture of a covered window, full-size snapshots for cutting |
| `onionwatch/sounds.py` | the built-in alert sounds (made in code) and the added sound files |
| `onionwatch/player.py` | the output stream that mixes and rings the alerts |
| `onionwatch/settings.py` | `%APPDATA%\OnionWatch` and `config.json` |
| `onionwatch/app.py` | start-up: logging, one copy at a time, the window, `--selftest` |
| `onionwatch/ui/triggerspanel.py` | the triggers page: one card per trigger, "Look in", Watching, Cut picture |
| `onionwatch/ui/windowpicker.py` | the window list with live thumbnails |
| `onionwatch/ui/snip.py` | cutting a picture out of a capture |
| `onionwatch/ui/mainwindow.py` | the window, the alarm bar, the tray icon, notifications |
| `onionwatch/ui/settingsdialog.py` | output device, volume, notifications, tray, theme |
| `onionwatch/theme.py`, `ui/icons.py`, `ui/panel.py` | themes, the logo, painted icons and layout helpers, shared with Onion Board |
| `tests/` | pytest: the matcher, the watcher on stand-in screens and windows (several copies of a game, not open yet, closed and reopened, minimized, resized), the sounds and player, the UI offscreen |

## Licence

MIT with the Commons Clause, like Onion Board: free to use, change and share, but
not to sell. See [LICENSE](LICENSE).
