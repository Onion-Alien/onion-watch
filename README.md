<p align="right"><img src="https://hits.sh/github.com/Onion-Alien/onion-watch.svg?view=total&label=total%20visits&color=6b8e23" alt="total visits"> <img src="https://img.shields.io/endpoint?url=https%3A%2F%2Fraw.githubusercontent.com%2FOnion-Alien%2Fonion-watch%2Fbadges%2Fdownloads.json" alt="downloads"></p>

<p align="center"><img src="docs/art/hoot.png?v=093af920" width="150" alt="Hoot, the Onion Watch owl"></p>

# Onion Watch

**Plays a sound when something shows up in a game, even while you're alt-tabbed
into a different one.**

A rare spawn, a queue pop, a whisper, a health bar running low: pick the game's
window, cut out the thing to watch for, choose a sound. Onion Watch keeps looking
at that window while it's behind your other windows and plays the sound, or rings
until you're back.

## ⬇️ [Download Onion Watch for Windows](https://github.com/Onion-Alien/onion-watch/releases/latest/download/OnionWatch-Installer.exe)

<!-- release -->
Version **0.13.3** · Windows 10 / 11 · free, no account, no internet needed ·
[VirusTotal: 68 of 68 clean](https://www.virustotal.com/gui/file/b380121425bec06e5918a64d9ef3d2185239cc43be441c6c867fdda8a0300962) · [what's new](https://github.com/Onion-Alien/onion-watch/releases/latest)
<!-- /release -->

![Onion Watch watching a game, one trigger open](docs/screenshots/main.png?v=ab1bf824)

| | |
|---|---|
| ![The window picker](docs/screenshots/window-picker.png?v=11bc8ea6) | ![Cutting a picture from a window](docs/screenshots/cut-picture.png?v=3f96fee0) |
| Pick the windows, or every copy of a game | Cut the thing to watch for straight out of the game |
| ![Picking a health bar and its colour](docs/screenshots/health-bar.png?v=396ea8e8) | ![Categories and profiles](docs/screenshots/categories.png?v=41cbf3ba) |
| Or point it at a health bar | Hundreds of triggers in categories and profiles |

## It only looks

Onion Watch reads pixels and plays sounds. It **never** presses keys, clicks,
moves the mouse, or reads or changes a game's memory: it sees what you'd see, like
OBS or a Discord screen share. Some games forbid every third-party tool, so check
your game's rules. Nothing it captures is saved or sent anywhere. It goes online
only to check for a new version once a day and, if you leave *Count me in* ticked,
to send anonymous usage stats (the version, which features are used, crash counts
and a random ID; never your name or device info, see
[docs/PRIVACY.md](docs/PRIVACY.md)). Both switch off in Settings →
Updates and privacy.

## What it does

- **Watches behind other windows**, not just the screen (not while minimized:
  Windows stops drawing those).
- **Every account at once**: one trigger can watch several windows, or every copy
  of a game, and says which one went off.
- **Shows up, goes away, changes, stops moving**, or a **health bar runs low**.
- **Rings until you're back**, or plays each time, and again after a rest while it stays up. *What went off* shows each
  alert with a picture of the moment.
- **Built-in alert sounds** or your own files. Categories, profiles that switch on
  with a game, search, and Recently deleted.
- **In your language**: English, Deutsch, Español, Français, Italiano, Nederlands, Polski, Português
  (Brasil), Türkçe, Bahasa Indonesia, Tiếng Việt, Русский, Українська, العربية,
  हिन्दी, ไทย, 简体中文, 繁體中文, 日本語 and 한국어
  (Settings → Look → Language; inside Onion Board it follows the board).
  Want another one? See [docs/TRANSLATING.md](docs/TRANSLATING.md).

The full list and how the matching works: [docs/FEATURES.md](docs/FEATURES.md).

## Get started

1. **[Download `OnionWatch-Installer.exe`](https://github.com/Onion-Alien/onion-watch/releases/latest/download/OnionWatch-Installer.exe)**
   and run it. It installs for your user, no admin rights. If Windows warns you
   (the installer isn't code-signed), click **More info → Run anyway**.
2. Pick your game's window at the bottom, then **Cut picture…** and drag a box
   around the thing to watch for.
3. Choose a sound, click **Start watching**, and go do something else.

Use [Onion Board](https://github.com/Onion-Alien/onion-board), the free soundboard?
Onion Watch is also its Triggers tab: click **Get Onion Watch** there.

## For developers

[docs/CODE.md](docs/CODE.md) has running from source, releasing, how it works
inside Onion Board, and the code layout. `scripts\docs.py` rebuilds this page's
pictures and version line.

## License

Open source under the [GNU GPL v3 or later](LICENSE), like Onion Board: use it anywhere,
change it and share your version. Anyone who shares a version, free or paid, has to
publish its full source under the same license, so nobody can make a closed copy. Onion
Watch itself is always free: if someone charged you for it, get it from the
[releases page](https://github.com/Onion-Alien/onion-watch/releases/latest). The name
"Onion Watch" and the Hoot logo aren't covered by the license, so your own version
needs its own name and logo.

Releases are built from this source by GitHub Actions
([release.yml](.github/workflows/release.yml)). See the
[code signing policy](https://onionalien.com/onionboard/code-signing/).
