# CLAUDE.md

Guidance for AI coding agents working in this repo.

## This repo will be public

It's private while the first version is being finished and signed off, then it
goes public like Onion Board. Write everything as if it were public already:

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
  them close to it: the plan is for Onion Watch to plug back into Onion Board as
  an add-on module, replacing its built-in Triggers tab.
- Keep the README's code layout table current when adding modules.
