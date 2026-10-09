"""The anonymous usage count: how many people use Onion Watch, and how.

Once a day the installed app sends one "still here" to the project's GoatCounter
(a privacy-friendly counter, the same one Onion Board uses): the version number and
a random ID made on this PC, so the same person isn't counted twice and we can follow
how people use the app over time (which features, which versions, whether they come
back) to see what to improve. Also a one-off "first start" (with where they heard
about the app, if they picked it on the installer's last page), and "updated" when
*Update now* installs a new version.
With the daily one, a rough picture of how it's used, each as a bucket or a name from
a fixed list: how long ago it was installed (`age/days-2-7`), how many triggers there
are and how often they went off since the last one (`triggers/11-50`, `fired/1-10`),
the app's language (`lang/de`), and which features are set up or were used since
then (`used/mode-colour`, `used/pack-import`: the names in FEATURES only). And once
each, the first steps of a new install (`step/added-trigger`, `step/started-watching`,
`step/trigger-fired`), to see where new people get stuck; never for a copy that was
counted before these existed.
Soon after a start, how many problems there were, as counts, never the report
itself: an error the app didn't expect (`error/<version>/<type>@<file:line>`: the
error's type and the file and line of this app's own code it happened in, e.g.
`error/1.0.0/KeyError@onionwatch/ui/triggerspanel.py:1090`, never its message), or
the last run ending without the app closing itself (`unclean-exit/<version>`: a hard
crash, ended in Task Manager, a power cut). And `uninstall/<version>` when the
uninstaller removes it.
Nothing else: no name, triggers, pictures, windows, games or IP address in the
message (GoatCounter sees the connection's address like any site does, and isn't
sent it to keep or look up).

On unless switched off: the installer's "Count me in" box, or Settings > Updates and
privacy. Switching it off sends one last `opt-out/<where>` with no ID, tag or
session, then nothing. Copies from before it existed start with it off
(settings.Config.load): they were installed as an app that sent nothing. A copy
running from source never sends anything, and neither does one on a PC with
ONIONBOARD_NO_STATS set (the developer's own PCs and test VMs, the same switch Onion
Board obeys). Inside Onion Board (as its Triggers tab) nothing here is sent: the
board counts itself, and used() only passes a feature's name to the board (its
host's optional count(), see host.py), which sends it with its own daily count."""
from __future__ import annotations

import hashlib
import json
import logging
import os
import re
import sys
import threading
import time
import traceback
import urllib.request
import uuid
from pathlib import Path

from onionwatch import __version__

log = logging.getLogger(__name__)

ENDPOINT = "https://onionalien.goatcounter.com/api/v0/count"
# a key that can only add counts (GoatCounter's "Record pageviews" permission), not
# read or change anything; "" sends nothing
TOKEN = "1mdp7aoiksvjn2e3oitmjdaqd1u33msk6p74g7samuec2tufwr"  # gitleaks:allow (count-only)
PREFIX = "onion-watch"   # every path starts with it: the counter is shared with Onion Board
EVERY_S = 24 * 3600
DAY_S = 24 * 3600
# the installer's "Where did you hear about Onion Watch?" picks; Other's typed answer
# goes through heard_tag() too, and anything else is sent as "other-<words>" or not at all
HEARD = ("youtube", "reddit", "github", "google", "friend", "onion-board")
HEARD_ALIASES = {"yt": "youtube", "you tube": "youtube", "youtube.com": "youtube",
                 "reddit.com": "reddit", "github.com": "github", "a friend": "friend",
                 "friends": "friend", "google.com": "google", "x": "twitter",
                 "twitter.com": "twitter", "tiktok.com": "tiktok", "tik tok": "tiktok",
                 "onion board": "onion-board", "onionboard": "onion-board"}
HEARD_MAX = 24   # characters of a typed answer, after tidying
TIMEOUT_S = 15
# what else is counted, only ever these names (Onion Board counts the same names,
# as `used/triggers-<name>`, for its Triggers tab: keep its usage.FEATURES in step)
USED = (  # done since the last daily count
    "watching", "went-off", "test", "cut-from-window", "picture-file", "paste-picture",
    "area-trigger", "duplicate", "pick-windows", "pack-export", "pack-import",
    "history", "restore-deleted")
SET_UP = (  # set up now (setup_features): counted every day they are
    "mode-appear", "mode-vanish", "mode-change", "mode-still", "mode-colour", "ring",
    "several-places", "every-copy", "area", "hold", "quiet-in-front", "own-interval",
    "categories", "profiles")
FEATURES = USED + SET_UP
STEPS = ("added-trigger", "started-watching", "trigger-fired")
LANG_RE = r"[a-z]{2,3}(?:-[A-Za-z0-9]{2,4})?"
VERSION_RE = r"[0-9][0-9A-Za-z.\-]{0,20}"
RUNNING = "running.txt"     # in the app folder while the app runs (mark_running)
MAX_PROBLEMS = 10           # problem events kept / sent at once: a bug in a loop isn't 1000
OPT_OUT_WHERE = ("installer", "settings")
OPT_OUT_TIMEOUT_S = 5       # the installer waits on it: never long


def enabled() -> bool:
    """Could anything be sent at all: the installed app, with a key, not on a dev PC."""
    return (bool(TOKEN) and bool(getattr(sys, "frozen", False))
            and not os.environ.get("ONIONBOARD_NO_STATS"))


def install_id(cfg) -> str:
    """This PC's random ID (made once, kept in config.json)."""
    if not cfg.stats_id:
        cfg.stats_id = uuid.uuid4().hex
    return cfg.stats_id


def user_tag(sid: str) -> str:
    """A short tag made from the random ID, sent as each count's "ref". GoatCounter
    swaps "session" for its own number that starts over after 8 hours, so one person's
    daily counts only link up across days through this. A hash, not the ID itself."""
    return "u-" + hashlib.sha256(sid.encode()).hexdigest()[:12]


def _wordlike(w: str) -> bool:
    """A word, a short name ("tv") or a number: not keyboard mashing ("asdfgh")."""
    return w.isdigit() or ((len(w) <= 3 or bool(re.search(r"[aeiouy]", w)))
                           and not re.search(r"[^aeiouy\d]{5}", w))


def heard_tag(text: str) -> str:
    """The installer's answer as a short tag for the first-start event: one of HEARD,
    "other-<a-few-words>" for a typed answer that reads like a name (a site, an app,
    "discord server"), or "" for none. Typed text that doesn't look like that is
    dropped, not sent: an email address, a link with a path, a number (a phone),
    symbols, keyboard mashing or more than three words."""
    t = " ".join(str(text or "").lower().split())
    t = HEARD_ALIASES.get(t, t)
    if t in HEARD:
        return t
    if (not t or len(t) > HEARD_MAX or "@" in t or "/" in t
            or not re.fullmatch(r"[a-z0-9 .\-]+", t) or re.search(r"\d{3}", t)):
        return ""
    words = re.findall(r"[a-z0-9]+", t.replace(".com", ""))
    if not 1 <= len(words) <= 3 or not all(_wordlike(w) for w in words):
        return ""
    for w in words:   # "a youtube video", "my friend", "google search"
        w = HEARD_ALIASES.get(w, w)
        if w in HEARD:
            return w
    return "other-" + "-".join(words)


def _event(name: str, sid: str) -> dict:
    return {"path": name, "title": name, "event": True, "session": sid, "ref": user_tag(sid)}


def hits(cfg, now: float, event: str = "", extra=()) -> list[dict]:
    """What a send would say: the daily "still here" for this version if one is due
    (with "first-start" the first time ever, and about() with it), or the one
    `event`. `extra` (problem events) go now, due or not."""
    sid = install_id(cfg)
    if event:
        return [_event(event, sid)]
    out = [_event(e, sid) for e in extra]
    if now - cfg.stats_sent < EVERY_S:
        return out
    out.insert(0, {"path": f"/{PREFIX}/app/{__version__}",
                   "title": f"Onion Watch {__version__}", "session": sid,
                   "ref": user_tag(sid)})
    if not cfg.stats_sent:
        heard = heard_tag(cfg.stats_heard)
        out.append(_event(f"{PREFIX}/first-start" + (f"/heard-{heard}" if heard else ""),
                          sid))
    out += [_event(f"{PREFIX}/{e}", sid) for e in about(cfg, now)]
    return out


def bucket(n: int) -> str:
    """A count as a rough bucket: 0, 1-10, 11-50, 51-plus."""
    return "0" if n <= 0 else "1-10" if n <= 10 else "11-50" if n <= 50 else "51-plus"


def age_bucket(days: float) -> str:
    """How long ago it was installed, roughly."""
    return ("day-1" if days < 1 else "days-2-7" if days < 7 else "days-8-30" if days < 30
            else "days-31-plus")


def _raw_triggers(screen) -> list[dict]:
    """The saved triggers (Config.screen / the host's screen), as stored."""
    if not isinstance(screen, dict):
        return []
    return [d for k in ("triggers", "more_triggers")
            for d in (screen.get(k) if isinstance(screen.get(k), list) else [])
            if isinstance(d, dict)]


def setup_features(screen) -> list[str]:
    """The SET_UP features the saved triggers use now (names only, in SET_UP's order)."""
    from onionwatch import screenwatch
    have = set()
    for d in _raw_triggers(screen):
        t = screenwatch.Trigger.from_raw(d)
        if t is None:
            continue
        have.add(f"mode-{t.mode}")
        if t.ring:
            have.add("ring")
        if len(t.sources) > 1:
            have.add("several-places")
        if any(getattr(w, "every", False) for w in t.windows):
            have.add("every-copy")
        if t.region is not None:
            have.add("area")
        if t.hold > 0:
            have.add("hold")
        if t.unfocused:
            have.add("quiet-in-front")
        if t.interval_ms > 0:
            have.add("own-interval")
        if t.category:
            have.add("categories")
    if isinstance(screen, dict) and isinstance(screen.get("profiles"), list) \
            and screen["profiles"]:
        have.add("profiles")
    return [k for k in SET_UP if k in have]


def settle(cfg, now: float) -> None:
    """Once: when this install started, for age/. A copy counted before this existed
    isn't a new install: its age comes from when it was first counted, and its first
    steps are long done, so they're never sent."""
    if cfg.stats_started:
        return
    if cfg.stats_sent:
        cfg.stats_started = cfg.stats_sent
        cfg.stats_steps = list(STEPS)
    else:
        cfg.stats_started = now


def about(cfg, now: float) -> list[str]:
    """The daily count's picture of how it's used (see the docstring): buckets and
    names from fixed lists only."""
    settle(cfg, now)
    out = [f"age/{age_bucket((now - (cfg.stats_started or now)) / DAY_S)}",
           f"triggers/{bucket(len(_raw_triggers(cfg.screen)))}",
           f"fired/{bucket(cfg.stats_fired)}"]
    lang = cfg.language if re.fullmatch(LANG_RE, cfg.language or "") else "auto"
    out.append(f"lang/{lang}")
    have = (set(cfg.stats_used if isinstance(cfg.stats_used, list) else [])
            | set(setup_features(cfg.screen)))
    out += [f"used/{k}" for k in FEATURES if k in have]
    return out


# ---------------------------------------------------------------- features, steps
_used: set[str] = set()   # features used this run, kept in cfg by remember()
_sink = None              # inside Onion Board: the host's count(), see forward_to()


def forward_to(count) -> None:
    """Inside Onion Board: pass used() names to the board (its host's count()) instead
    of keeping them here. None: back to Onion Watch's own count."""
    global _sink
    _sink = count


def used(key: str) -> None:
    """Feature `key` (one of FEATURES) was used, for the next daily count."""
    if key not in FEATURES:
        return
    if _sink is not None:
        try:
            _sink(key)
        except Exception:  # noqa: BLE001 - never in the way of what was clicked
            log.debug("host count(%s) failed", key, exc_info=True)
        return
    _used.add(key)


def fired(cfg) -> None:
    """A trigger went off (not a Test), for fired/ (the panel counts used/went-off)."""
    cfg.stats_fired = max(0, int(cfg.stats_fired or 0)) + 1


_pending: list[str] = []   # problems found this run, kept in cfg by remember()


def note(event: str) -> None:
    """Send `event` (a problem) with the next count."""
    if event and len(_pending) < MAX_PROBLEMS:
        _pending.append(event)


def remember(cfg) -> None:
    """Keep this run's used() features and note()d problems in cfg (so they survive a
    quit before the next send)."""
    have = cfg.stats_used if isinstance(cfg.stats_used, list) else []
    new = [k for k in FEATURES if k in _used and k not in have]
    _used.clear()
    if new:
        cfg.stats_used = [*have, *new]
    if _pending:
        old = cfg.stats_problems if isinstance(cfg.stats_problems, list) else []
        cfg.stats_problems = [*old, *_pending][:MAX_PROBLEMS]
        _pending.clear()


def step(cfg, name: str, saved=None) -> None:
    """A new install's first time doing `name` (one of STEPS): sent right away, once.
    A copy counted before these existed never sends them (settle)."""
    if name not in STEPS or not enabled() or not cfg.usage_count:
        return
    settle(cfg, time.time())
    if name in cfg.stats_steps:
        return
    cfg.stats_steps = [*cfg.stats_steps, name]
    maybe_send(cfg, saved, event=f"{PREFIX}/step/{name}")


# ---------------------------------------------------------------- problems
# a stack line: `File "...\onionwatch\ui\triggerspanel.py", line 1090, in ...`; only
# our own files count, named from the package folder down (never the folder above it)
_OUR_FRAME = re.compile(r'(?:[\\/]|^)(onionwatch(?:[\\/][a-z0-9_]+)?[\\/][a-z0-9_]+\.py)$')


def error_event(etype, tb) -> str:
    """`onion-watch/error/<version>/<Type>@onionwatch/ui/x.py:<line>` for an error the
    app didn't expect: its type only (a message can hold a path or a window title),
    and the deepest line of this app's own code in its stack (the same file and line
    anyone can look up in the public source)."""
    name = getattr(etype, "__name__", "") or ""
    name = name if re.fullmatch(r"[A-Za-z_]\w{0,39}", name) else ""
    where = ""
    for fs in traceback.extract_tb(tb) if tb is not None else []:
        m = _OUR_FRAME.search(fs.filename or "")
        if m:
            where = f"{m.group(1).replace(chr(92), '/')}:{fs.lineno}"
    tag = "@".join(p for p in (name, where) if p)
    return f"{PREFIX}/error/{__version__}" + (f"/{tag}" if tag else "")


def mark_running(app_dir: Path) -> str:
    """At start: note that the app is running. Returns `onion-watch/unclean-exit/
    <version>` when the last run never got to mark_stopped (it crashed hard, was
    ended in Task Manager, or the PC lost power), else ""."""
    path = Path(app_dir) / RUNNING
    event = ""
    try:
        old = path.read_text(encoding="utf-8").strip()
        if re.fullmatch(VERSION_RE, old):
            event = f"{PREFIX}/unclean-exit/{old}"
    except OSError:
        pass
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(__version__, encoding="utf-8")
    except OSError:
        pass
    return event


def mark_stopped(app_dir: Path) -> None:
    """At a real quit (MainWindow.shutdown, also when Windows ends the session)."""
    try:
        (Path(app_dir) / RUNNING).unlink(missing_ok=True)
    except OSError:
        pass


def uninstall_event() -> str:
    return f"{PREFIX}/uninstall/{__version__}"


def update_event(to: str) -> str:
    """The event for *Update now* from this version to `to`."""
    return f"{PREFIX}/update-now/{__version__}-to-{to}"


# ---------------------------------------------------------------- sending
def send(payload: list[dict], timeout: float = TIMEOUT_S, no_sessions: bool = False) -> bool:
    """POST them to the counter. True if it took them. Call off the UI thread."""
    body = json.dumps({"hits": payload, "no_sessions": True} if no_sessions
                      else {"hits": payload}).encode("utf-8")
    req = urllib.request.Request(ENDPOINT, data=body, method="POST", headers={
        "Authorization": f"Bearer {TOKEN}", "Content-Type": "application/json",
        "User-Agent": "OnionWatch"})
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            return 200 <= r.status < 300
    except Exception as e:  # noqa: BLE001 - offline, counter down
        log.info("usage count not sent: %s", e)
        return False


def opt_out(where: str) -> bool:
    """Count me in switched from on to off (`where`: the installer's box or Settings):
    one last "onion-watch/opt-out/<where>" so we know how many people aren't counted,
    then nothing ever again. No random ID, no tag, no session: it can't be tied to
    anything they sent before. Call it before switching it off, off the UI thread
    (it waits for the answer, OPT_OUT_TIMEOUT_S at most)."""
    if where not in OPT_OUT_WHERE or not enabled():
        return False
    name = f"{PREFIX}/opt-out/{where}"
    return send([{"path": name, "title": name, "event": True}],
                timeout=OPT_OUT_TIMEOUT_S, no_sessions=True)


def maybe_send(cfg, saved=None, event: str = "") -> threading.Thread | None:
    """The daily count if it's due (or `event` now), on a thread, when it's switched
    on. Problems since the last send go too, due or not. `saved()` is called on that
    thread after cfg changed. The thread, or None when nothing goes."""
    if not enabled() or not cfg.usage_count:
        return None
    now = time.time()
    settle(cfg, now)
    remember(cfg)
    problems = [] if event else list(cfg.stats_problems or [])[:MAX_PROBLEMS]
    payload = hits(cfg, now, event, problems)
    if not payload:
        return None
    daily = not event and any(not h.get("event") for h in payload)
    feats = [h["path"].rsplit("/", 1)[-1] for h in payload
             if h["path"].startswith(f"{PREFIX}/used/")]
    fired_n = cfg.stats_fired

    def run():
        if not send(payload) or event:
            return
        if daily:
            cfg.stats_sent = now
            cfg.stats_used = [k for k in cfg.stats_used if k not in feats]
            cfg.stats_fired = max(0, cfg.stats_fired - fired_n)
        cfg.stats_problems = [p for p in cfg.stats_problems if p not in problems]
        if saved is not None:
            saved()
    t = threading.Thread(target=run, daemon=True, name="usage-count")
    t.start()
    return t


def send_now(cfg, event: str) -> bool:
    """Send one `event` and wait for it (the uninstaller's `--uninstall-count`)."""
    if not enabled() or not cfg.usage_count:
        return False
    return send(hits(cfg, time.time(), event))
