# CLAUDE.md

Guidance for AI coding agents working in this repo.

## This repo is public

Like Onion Board, everything here is published, history included:

- **Never write personal or machine-specific data** into the repo: user names,
  real names, e-mails, `C:\Users\<name>\…` paths, host names, IPs (other than
  `127.0.0.1`), names of the author's other projects or machines, or where the
  author lives. Use `%APPDATA%`, `Path.home()`, `example.com`, placeholders.
- **Never commit secrets** or anything from `%APPDATA%\OnionWatch\` (config,
  logs, pictures, sounds).
- **Never add audio files, binaries, third-party assets or real game
  screenshots.** Alert sounds and tests synthesize audio with numpy; icons, the
  logo and the screenshots' made-up game are drawn in code.
- The app makes no network requests. Adding one needs a line in `SECURITY.md`
  and the author's say-so. No telemetry.
- **It only looks.** Never add anything that sends input to a game (keys, clicks,
  mouse), reads or writes another process's memory, or injects into one. That
  promise is what keeps the app clear of game rules. Suggest it in chat instead,
  don't build it.

Run `python scripts/check_sensitive.py` before committing. It's also the
pre-commit hook: `git config core.hooksPath .githooks`, which also re-stamps
commit times in UTC.

## Working in the code

- Checks: `.venv\Scripts\ruff check .` and `.venv\Scripts\python -m pytest`.
  Tests use Qt's offscreen platform, stand-in captures and a silent audio stream
  (`tests/conftest.py`): no window, no screen read, no sound.
- Don't launch the app, or anything that opens windows, without asking first.
  The author may be mid-game.
- Screenshots: `.venv\Scripts\python scripts\screenshots.py`. Offscreen,
  made-up data.
- Edit files with UTF-8-safe tools. Windows PowerShell 5.1's
  `Get-Content`/`Set-Content` mangles UTF-8.
- The audio callback (`player.Player._callback`) never blocks or takes a lock.
- `theme.py`, `ui/icons.py`, `ui/panel.py`, `wheelguard.py`, `shuffle.py` and
  the capture / matching half of `screenwatch.py` came from Onion Board. Keep
  them close to it.
- Onion Watch is also Onion Board's Triggers tab, as an add-on module
  (`onionwatch/board.py`, zipped by `scripts/build_module.py`). So:
  - The triggers page (`ui/triggerspanel.py`) and what it imports never touch the
    app's settings, sounds, player or tray: everything goes through the host
    (`onionwatch/host.py`). The engine (`screenwatch.py`, `windows.py`) doesn't know
    about hosts at all.
  - The module may only import what Onion Board ships: the standard library,
    numpy, scipy, PySide6's QtCore / QtGui / QtWidgets. `build_module.py` and its
    test refuse anything else.
  - Changing `Host` in a way the other side can't follow means bumping
    `API_VERSION` and a matching change in Onion Board.
  - Keep `Config.screen`'s format readable by both: add fields, don't rename them.
- Keep the README's code layout table current when adding modules.

## Releasing

Follow README → *Inside Onion Board* → "To release a new version". Build with
`build.ps1 -Clean -Scan`, never a plain build. It uses a PyInstaller bootloader
compiled on this PC (that is the fix for Microsoft's false `Trojan:Win32/Wacatac.B!ml`
on VirusTotal: the stock bootloader got 0.3.0 flagged), and if the installer is still
flagged it compiles a fresh bootloader and rebuilds by itself. If it fails after every
try, don't release: the author reports the installer to Microsoft as a false positive
(README has the steps), then scan again. Never publish a flagged installer.
