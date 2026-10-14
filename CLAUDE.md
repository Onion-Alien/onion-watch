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
- The app goes online for two things only, both switchable in Settings: the daily
  update check (`updates.py`) and the anonymous usage count (`usage.py`, the same
  GoatCounter as Onion Board, paths under `onion-watch/`). Adding anything else
  needs a line in `SECURITY.md` and the author's say-so. Neither runs inside Onion
  Board, and the count never carries triggers, pictures, windows or games.
- **It only looks.** Never add anything that sends input to a game (keys, clicks,
  mouse), reads or writes another process's memory, or injects into one. That
  promise is what keeps the app clear of game rules. Suggest it in chat instead,
  don't build it.

- **Never copy content from outside the repo** (the author's other projects,
  parent-folder docs, memory files, shell history) into files here.
- **Never put Claude session links** (`claude.ai/code/session_…`) or
  `Claude-Session:` trailers in commits, PRs or comments. Strip any your tooling
  adds; `Co-Authored-By` is fine.

Run `scripts\precommit.ps1` before committing (below); its sensitive-data scan is
also the pre-commit hook. Fix what it reports; don't add `# sensitive-scan: allow`
to silence it without telling the user why.

## Commit times and merging

Every commit's author and committer time must be `+0000`: a local time zone in a public
repo says where the author lives. The same rules as Onion Board:

- `git config core.hooksPath .githooks` (required) turns on the hooks: `pre-commit`
  scans for secrets and personal data, `post-commit` and `post-merge` re-stamp new
  commits in UTC, and `pre-push` refuses anything that isn't.
- CI's *Commit times in UTC* step fails a PR that has any.
- **Merge only with `sh scripts/merge_pr.sh N [--delete-branch]`**: it checks CI is
  green, makes the merge commit here in UTC and pushes it to main. Never GitHub's merge
  (the `gh` merge command, the API's merge call, the Merge button) or *Update branch*:
  GitHub writes those commits in your local time zone, and no hook can touch them.
- Bring main into a branch with a local `git merge origin/main` (the hook stamps it).
- A branch whose commits aren't UTC: `sh scripts/utc_fix.sh`, then
  `git push --force-with-lease`.
- The same goes for anything else that records where you are: never write your time
  zone, locale, city or machine names into commits, PR text or files.
- Never rewrite history already pushed to `main` (no filter-repo, rebase or force-push).
  To clean up old commits, add a new commit instead.

## Text the app shows: every language, in the same change

Onion Watch ships in every language in `onionwatch/lang/` (the same set as Onion Board). So any change
that adds or edits text a user can see (labels, buttons, tooltips, dialogs, toasts,
errors) does all of this **before committing**, not "later":

1. Wrap it: `_("…")` / `ngettext("…", "…", n)` from `onionwatch.i18n`. Whole sentences with
   `{placeholders}`: never an f-string, `+`, or an English word passed into a
   placeholder ("{what}" = "sounds" can't be translated).
2. `python scripts/i18n_extract.py --update`: adds the new texts (empty) to every
   catalog and drops the unused ones.
3. Translate every text you added or changed into **every** catalog: plain, short,
   friendly words for gamers, the same words the catalog already uses (and Onion Board
   uses, for shared things), every `{placeholder}`, `<b>…</b>`, `&amp;` and line break
   kept, and the language's number of plural forms (`i18n.FORMS`). Lots of text: one
   subagent per language.
4. `ruff`, the i18n tests, and check that `i18n_extract.py` lists none of your texts as
   missing.

Never wrap log messages, settings keys, file names, the update / usage JSON or the changelog. A new language goes into
both apps at once. Details: [docs/TRANSLATING.md](docs/TRANSLATING.md).

## Working in the code

- Checks: `powershell -NoProfile -ExecutionPolicy Bypass -File scripts\precommit.ps1`
  (about 15 s): ruff, the sensitive-data scan, every text in every catalog, every
  module in docs/CODE.md's table, and pyright on the changed files. `-Tests` also runs
  the whole suite (under a minute; or `.venv\Scripts\python -m pytest`). CI
  (`.github/workflows/checks.yml`) runs all of it on every PR, the tests on Windows.
  Tests use Qt's offscreen platform, stand-in captures and a silent audio stream
  (`tests/conftest.py`): no window, no screen read, no sound.
- Type checking: pyright, basic mode (`[tool.pyright]`). The errors from before it was
  turned on are in `scripts/pyright_baseline.json` and only new ones fail
  (`scripts/check_types.py`). Fixed old ones? `check_types.py --update` so the
  baseline shrinks and they can't come back. pyright wrong? `# pyright: ignore[rule]`
  with a reason.
- A fix comes with the test that would have caught it; the PR's `Regression test:`
  line names it (or says why there's none).
- Don't launch the app, or anything that opens windows, without asking first.
  The author may be mid-game.
- Screenshots: `.venv\Scripts\python scripts\screenshots.py`. Offscreen,
  made-up data.
- Edit files with UTF-8-safe tools. Windows PowerShell 5.1's
  `Get-Content`/`Set-Content` mangles UTF-8.
- The audio callback (`player.Player._callback`) never blocks or takes a lock.
- **`onionwatch/style/` is Onion Board's style kit, copied exactly: never edit it
  here.** The themes' colours and textures, Bun's outfits and Hoot live in Onion
  Board's `soundboard/style`; change them there, then
  `python scripts/sync_style.py --board <Onion Board checkout>` (its `origin/main`).
  `tests/test_style_kit.py` fails on a hand-edited copy. Onion Watch's own Hoot theme
  is in `theme.py`. Inside Onion Board, Hoot is drawn with the board's kit
  (`kit.py`) and follows its theme (`theme.follow_host`).
- `theme.py`, `ui/icons.py`, `ui/panel.py`, `wheelguard.py`, `shuffle.py` and
  the capture / matching half of `screenwatch.py` came from Onion Board. Keep
  them close to it.
- **Look and feel: follow Onion Board's design system**,
  [docs/DESIGN.md](https://github.com/Onion-Alien/onion-board/blob/main/docs/DESIGN.md)
  (flat controls with no resting outlines, theme tokens never hex colours, one accent
  main button, quiet buttons, focus rings). `theme.STYLE` and `POLISH_STYLE` are
  copies of Board's (the derived tokens come with the style kit): when Board's change, copy them over from Board's
  `origin/main` (not a working tree, which may be on an old branch) rather than
  restyling here.
- Onion Watch is also Onion Board's Triggers tab, as an add-on module
  (`onionwatch/board.py`, zipped by `scripts/build_module.py`). So:
  - The triggers page (`ui/triggerspanel.py`) and what it imports never touch the
    app's settings, sounds, player or tray: everything goes through the host
    (`onionwatch/host.py`). The engine (`screenwatch.py`, `windows.py`) doesn't know
    about hosts at all.
  - The module may only import what Onion Board ships: the standard library,
    numpy, PySide6's QtCore / QtGui / QtWidgets. Of scipy, Onion Board ships only
    scipy.fft, and the module only tries it (`imgops.py`, numpy's FFTs if it's
    missing); the matcher's filters are numpy. `build_module.py` and its
    test refuse anything else.
  - Changing `Host` in a way the other side can't follow means bumping
    `API_VERSION` and a matching change in Onion Board.
  - Keep `Config.screen`'s format readable by both: add fields, don't rename them.
- Keep the code layout table in [docs/CODE.md](docs/CODE.md) current when adding modules.

## Releasing

Follow [docs/CODE.md](docs/CODE.md) → *Inside Onion Board* → "To release a new version". Build with
`build.ps1 -Clean -Scan`, never a plain build. Two things keep Microsoft's false
`Trojan:Win32/Wacatac.B!ml` off the installer on VirusTotal, and neither may be undone:
the installer is zip-compressed, not lzma (`installer\OnionWatch.iss`; with solid lzma
nearly every build was flagged whatever was inside it, even with no exe), and the
PyInstaller bootloader is compiled on this PC. If the scan still flags it, don't
release, and don't retry blindly: a verdict can change with any byte, so test one
change at a time and scan several samples (docs/CODE.md has how). Never publish a flagged
installer.
