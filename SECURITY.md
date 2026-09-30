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
| Network | **none** | |
| A local socket (`OnionWatch.App`) | this PC only | a second launch asks the running copy to come to the front |

Inside Onion Board (as its Triggers tab) the pictures are kept in
`%APPDATA%\OnionBoard\triggers` and the settings in Onion Board's own settings file,
and the sounds are the board's. Onion Board downloads the add-on only when you click
*Get Onion Watch* (or *Update*), from this project's GitHub releases, checked against
the SHA-256 GitHub lists; see its SECURITY.md.

Onion Watch never sends input to other programs, never reads or writes their
memory and never injects code into them. A change that does any of these is
out of scope for the project, not just a security concern.
