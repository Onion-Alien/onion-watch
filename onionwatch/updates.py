"""Is there a newer Onion Watch, and installing it. The app asks the project's latest
GitHub release once a day (Settings > Updates and privacy; on unless unticked), plus
a "Check now" button.

A newer version is only announced. Nothing is downloaded until the user presses
*Update now*: then the release's installer is fetched from the project's own GitHub
release, checked against the SHA-256 GitHub lists for it, and run silently over the
installed copy (the app closes, the installer opens it again). A copy running from
source is never updated: it only says what's new. Inside Onion Board (as its Triggers
tab) this module isn't used: the board updates its add-ons itself. The requests
carry no data about the user beyond what any HTTPS request does (see SECURITY.md)."""
from __future__ import annotations

import hashlib
import json
import logging
import os
import re
import subprocess
import sys
import time
import urllib.error
import urllib.request
from collections.abc import Callable
from dataclasses import dataclass

from onionwatch import __version__, settings

log = logging.getLogger(__name__)

REPO = "Onion-Alien/onion-watch"
API = f"https://api.github.com/repos/{REPO}/releases/latest"
RELEASES = f"https://github.com/{REPO}/releases/latest"
ASSET = "OnionWatch-Installer.exe"
# the same file uploaded a second time for *Update now* to fetch, so GitHub's download
# counts tell updates apart from downloads off the website; releases without it: ASSET
UPDATE_ASSET = "OnionWatch-Update.exe"   # sorts after the installer on the release page
# the only place an installer is ever fetched from (GitHub then redirects to its CDN)
DOWNLOADS = f"https://github.com/{REPO}/releases/download/"
UPDATES_DIR = settings.APP_DIR / "updates"
INSTALL_LOG = UPDATES_DIR / "install.log"
EVERY_S = 24 * 3600
LIMIT = 1 << 20          # the API's answer is a few KB
MAX_SIZE = 300 << 20     # the installer is ~90 MB
CHUNK = 1 << 20
SHA_RE = re.compile(r"[0-9a-f]{64}")


class UpdateError(Exception):
    """An update that couldn't be downloaded: the message is shown to the user as is."""


@dataclass
class Release:
    version: str      # "0.8.0"
    url: str          # its page on GitHub
    notes: str = ""   # the first lines of its description
    asset_url: str = ""   # its installer; "" = nothing to install
    sha256: str = ""      # that file's SHA-256 (lowercase hex), as GitHub lists it
    size: int = 0


def parse_version(text: str) -> tuple[int, ...] | None:
    """'v0.8.1' / '0.8.1' / 'Onion Watch 0.8' -> (0, 8, 1); None if there's no version."""
    m = re.search(r"(\d+)(?:\.(\d+))?(?:\.(\d+))?", text or "")
    if not m:
        return None
    return tuple(int(g or 0) for g in m.groups())


def newer(latest: str, current: str = __version__) -> bool:
    a, b = parse_version(latest), parse_version(current)
    return a is not None and b is not None and a > b


def _get(url: str) -> dict:
    """A GitHub API answer. A gateway error is retried once with a distinct URL (a
    gateway can cache a failed lookup)."""
    headers = {"User-Agent": "OnionWatch (update check)",   # no version: a name is enough
               "Accept": "application/vnd.github+json"}
    for attempt in range(2):
        target = url if attempt == 0 else url + ("&" if "?" in url else "?") + "retry=1"
        req = urllib.request.Request(target, headers=headers)
        try:
            with urllib.request.urlopen(req, timeout=15) as r:
                return json.loads(r.read(LIMIT).decode("utf-8"))
        except urllib.error.HTTPError as e:
            e.close()
            if attempt or e.code not in (502, 503, 504):
                raise
    raise AssertionError("release lookup exhausted without a result")


def find_asset(data: dict, name: str) -> tuple[str, str, int]:
    """A GitHub release's file called `name`: (download link, SHA-256, size), or
    blanks when its link isn't this project's, or it has no checksum to hold it to.
    The checksum is GitHub's own `digest` for the file; a release without one may
    carry it in its notes ("SHA-256: `…`")."""
    for a in data.get("assets") or []:
        if not isinstance(a, dict) or a.get("name") != name:
            continue
        url = str(a.get("browser_download_url") or "")
        if not url.startswith(DOWNLOADS):
            return "", "", 0
        digest = str(a.get("digest") or "").lower()
        sha = digest.removeprefix("sha256:") if digest.startswith("sha256:") else ""
        if not SHA_RE.fullmatch(sha):
            m = re.search(r"SHA-256:\W*([0-9a-fA-F]{64})\b", str(data.get("body") or ""))
            sha = m.group(1).lower() if m else ""
        if not sha:
            return "", "", 0
        size = a.get("size")
        return url, sha, size if isinstance(size, int) and size > 0 else 0
    return "", "", 0


def _installer(data: dict) -> tuple[str, str, int]:
    """The release's installer for *Update now*: UPDATE_ASSET, else ASSET."""
    names = {a.get("name") for a in data.get("assets") or [] if isinstance(a, dict)}
    return find_asset(data, UPDATE_ASSET if UPDATE_ASSET in names else ASSET)


def summary(body: str, limit: int = 420) -> str:
    """The start of a release's notes as plain text for the dialog: Markdown marks
    (**bold**, `code`, [links](…)) taken out, and whole paragraphs only, as many as
    fit in `limit` characters (at least the first, cut at a sentence if it's long).
    The "⬇ Download …" line for people on the release page is left out."""
    text = re.sub(r"\[([^\]]*)\]\([^)]*\)", r"\1", body.replace("\r\n", "\n"))
    text = re.sub(r"\*\*|__|`", "", text)
    paras = [" ".join(line.strip() for line in p.splitlines())
             for p in re.split(r"\n\s*\n", text.strip()) if p.strip()]
    paras = [p for p in paras if not p.startswith("⬇")]
    out: list[str] = []
    for p in paras:
        if out and len("\n\n".join(out + [p])) > limit:
            break
        out.append(p)
    first = out[0] if out else ""
    if len(first) > limit:   # one long paragraph: end it at a sentence
        cut = first[:limit]
        end = max(cut.rfind(". "), cut.rfind("! "), cut.rfind("? "))
        out[0] = cut[:end + 1] if end > 0 else cut.rsplit(" ", 1)[0] + "…"
    return "\n\n".join(out)


def latest() -> Release | None:
    """The newest published release (drafts and pre-releases aren't 'latest')."""
    data = _get(API)
    tag = str(data.get("tag_name") or data.get("name") or "")
    ver = parse_version(tag)
    if ver is None:
        return None
    url = str(data.get("html_url") or RELEASES)
    if not url.startswith(f"https://github.com/{REPO}/"):
        url = RELEASES   # only ever open the project's own page
    notes = summary(str(data.get("body") or ""))
    return Release(".".join(map(str, ver)), url, notes, *_installer(data))


def check(cfg, force: bool = False) -> Release | None:
    """A newer release than this one, or None. Without `force` it only asks if the
    box is ticked, once a day, and stays quiet about a version they skipped.
    Network errors are logged and read as 'nothing new' (a forced check raises them).
    Call off the UI thread."""
    if not force and (not cfg.update_check or time.time() - cfg.update_checked < EVERY_S):
        return None
    try:
        rel = latest()
    except Exception as e:  # noqa: BLE001 - offline, rate-limited, GitHub down…
        log.info("update check failed: %s", e)
        if force:
            raise
        return None
    cfg.update_checked = time.time()
    if rel is None or not newer(rel.version):
        return None
    if not force and rel.version == cfg.update_skip:
        return None
    log.info("a newer version is out: %s", rel.version)
    return rel


# --------------------------------------------------------------------------- installing

def can_install() -> bool:
    """Only the installed (frozen) app updates itself; from source it's `git pull`."""
    return bool(getattr(sys, "frozen", False)) and sys.platform == "win32"


def installer_path(rel: Release):
    return UPDATES_DIR / f"OnionWatch-Installer-{rel.version}.exe"


def _sha256(path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        while chunk := f.read(CHUNK):
            h.update(chunk)
    return h.hexdigest()


def _length(header) -> int:
    """Content-Length as a number; 0 (unknown) when it's missing or isn't one."""
    try:
        return max(int(str(header or 0).strip()), 0)
    except ValueError:
        return 0


def download(rel: Release, progress: Callable[[int, int], None] | None = None,
             cancelled: Callable[[], bool] | None = None):
    """Fetch the release's installer into UPDATES_DIR (via a .part file, so a failed
    download never leaves a half file under its name) and prove it's the file GitHub
    lists (SHA-256); its path. `progress(done, total)` is called as it arrives.
    Raises UpdateError with a message for the user. Call off the UI thread."""
    if not rel.asset_url.startswith(DOWNLOADS) or not SHA_RE.fullmatch(rel.sha256):
        raise UpdateError("this release has no installer the app can check, "
                          "so it can only be downloaded from its page")
    dest = installer_path(rel)
    if dest.is_file() and _sha256(dest) == rel.sha256:
        return dest   # downloaded earlier, never used
    dest.parent.mkdir(parents=True, exist_ok=True)
    part = dest.with_name(dest.name + ".part")
    h = hashlib.sha256()
    done = 0
    req = urllib.request.Request(rel.asset_url,
                                 headers={"User-Agent": "OnionWatch (update download)"})
    try:
        with urllib.request.urlopen(req, timeout=30) as r, open(part, "wb") as f:
            if not r.geturl().startswith("https://"):
                raise UpdateError("the download was redirected off HTTPS")
            total = _length(r.headers.get("Content-Length")) or rel.size or 0
            if total > MAX_SIZE:
                raise UpdateError("the download is far bigger than an installer")
            while chunk := r.read(CHUNK):
                if cancelled is not None and cancelled():
                    raise UpdateError("cancelled")
                done += len(chunk)
                if done > MAX_SIZE:
                    raise UpdateError("the download is far bigger than an installer")
                h.update(chunk)
                f.write(chunk)
                if progress is not None:
                    progress(done, total)
        if h.hexdigest() != rel.sha256:
            log.warning("%s: SHA-256 %s, expected %s", dest.name, h.hexdigest(), rel.sha256)
            raise UpdateError("the downloaded file isn't the one GitHub lists "
                              "(its checksum doesn't match), so it wasn't kept")
        os.replace(part, dest)
    except UpdateError:
        part.unlink(missing_ok=True)
        raise
    except OSError as e:   # offline, disk full, connection dropped…
        part.unlink(missing_ok=True)
        raise UpdateError(f"the download failed ({e})") from e
    log.info("downloaded update %s (%d bytes, SHA-256 checked)", rel.version, done)
    return dest


def installer_args(path) -> list[str]:
    """Run the installer over this copy with no questions, keeping the user's
    choices, then open the app again (/RELAUNCH, see installer/OnionWatch.iss)."""
    return [str(path), "/SILENT", "/SUPPRESSMSGBOXES", "/NORESTART", "/CLOSEAPPLICATIONS",
            "/RELAUNCH=1", f"/LOG={INSTALL_LOG}"]


def installer_env(env: dict[str, str] | None = None,
                  bundle: str | None = None) -> dict[str, str]:
    """This process's environment minus what the frozen app set up for itself:
    PyInstaller's _PYI_* / _MEIPASS2 bookkeeping, and PATH / QT_PLUGIN_PATH /
    QML2_IMPORT_PATH pointing into its own _internal folder. The installer passes its
    environment on to the app it reopens, and a new version started with the old
    one's can crash on start (Onion Board 1.3.3 -> 1.4.0 did)."""
    env = dict(os.environ if env is None else env)
    bundle = bundle if bundle is not None else getattr(sys, "_MEIPASS", None)
    for k in list(env):
        if k.upper().startswith("_PYI_") or k.upper() == "_MEIPASS2":
            del env[k]
    if bundle:
        root = os.path.normcase(os.path.abspath(bundle))

        def inside(p: str) -> bool:
            p = os.path.normcase(os.path.abspath(p.strip('"'))) if p.strip() else ""
            return bool(p) and (p == root or p.startswith(root + os.sep))
        for k in ("QT_PLUGIN_PATH", "QML2_IMPORT_PATH"):
            if k in env and inside(env[k].split(os.pathsep)[0]):
                del env[k]
        path_key = next((k for k in env if k.upper() == "PATH"), None)
        if path_key:
            env[path_key] = os.pathsep.join(
                p for p in env[path_key].split(os.pathsep) if not inside(p))
    env["PYINSTALLER_RESET_ENVIRONMENT"] = "1"
    return env


def start_install(path) -> None:
    """Start the installer on its own; the caller then quits the app so it can
    replace the files. Raises OSError if it couldn't be started."""
    flags = (getattr(subprocess, "DETACHED_PROCESS", 0)
             | getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0))
    subprocess.Popen(installer_args(path), creationflags=flags, close_fds=True,
                     cwd=str(UPDATES_DIR), env=installer_env())
    log.info("started the installer for the update: %s", path.name)


def cleanup() -> None:
    """Remove downloaded installers (and half-downloads). One still running, just
    after it reopened the app, is locked: it goes next time."""
    for p in UPDATES_DIR.glob("OnionWatch-Installer-*"):
        try:
            p.unlink()
        except OSError:
            pass
