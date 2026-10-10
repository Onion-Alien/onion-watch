# Security policy

## Reporting a vulnerability

**Please don't open a public issue for security problems.** Use GitHub's
private reporting instead: go to the repository's **Security** tab and choose
**Report a vulnerability**.

## What the app touches

| What | Where | Why |
|---|---|---|
| Screen and window pixels | kept in memory only, never saved or sent | finding the pictures you picked |
| Pictures you cut or add | `%APPDATA%\OnionWatch\triggers` | what the triggers look for |
| Sound files you add | copied to `%APPDATA%\OnionWatch\sounds` | what the triggers play |
| Settings and log | `%APPDATA%\OnionWatch` | |
| Network: update check | `api.github.com` once a day, unless switched off | is there a newer release? Nothing downloads until you click *Update now* |
| Network: *Update now* | this project's GitHub release files only | the new installer, checked against the SHA-256 GitHub lists, then run over the installed copy |
| Network: usage count | `onionalien.goatcounter.com` once a day, unless switched off | anonymous usage stats: the version and a random ID made on your PC, plus a short tag made from it as the count's referrer (they link your counts together so we can see how people use the app over time and what to improve; it isn't tied to your name or anything else about you). With it, a rough picture of how it's used, as buckets and names from a fixed list: how long ago it was installed, how many triggers there are and how often they went off (`triggers/11-50`, `fired/1-10`), the app's language, and which features are set up or were used (`used/mode-colour`, `used/pack-import`: the names in `onionwatch/usage.py` FEATURES only). Once each: a first start (with where you heard about it, if you picked that in the installer) and a new install's first steps (`step/added-trigger`, `step/started-watching`, `step/trigger-fired`). Problems as counts: an unexpected error's type and the file and line of this app's code it happened in (`error/0.9.6/KeyError@onionwatch/ui/triggerspanel.py:1090`, never its message), and a last run that ended without closing itself (`unclean-exit/0.9.6`). Also *Update now* events and `uninstall/<version>`. Switching it off sends one last `opt-out/installer` or `opt-out/settings` with no ID, tag or session, then nothing. Never triggers, pictures, window names, games or anything you type |
| Send feedback / Report a problem | opens your browser | the app itself sends nothing |
| A local socket (`OnionWatch.App`) | this PC only | a second launch asks the running copy to come to the front |

Settings → *Updates and privacy* switches the update check and the count off.
Copies installed before the count existed start with it off, and a copy running
from source never sends it.

Inside Onion Board (as its Triggers tab) the update check and the count aren't used
(the board has its own: the Triggers tab only tells it which of the feature names above
were used or are set up, sent as `used/triggers-<name>` with the board's daily count when
its Count me in is on), the pictures are kept in
`%APPDATA%\OnionBoard\triggers` and the settings in Onion Board's own settings file,
and the sounds are the board's. Onion Board downloads the add-on only when you click
*Get Onion Watch* (or *Update*), from this project's GitHub releases, checked against
the SHA-256 GitHub lists; see its SECURITY.md.

Onion Watch never sends input to other programs, never reads or writes their
memory and never injects code into them. A change that does any of these is
out of scope for the project, not just a security concern.
