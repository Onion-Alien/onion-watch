"""The anonymous usage count: how many people use Onion Watch, and which versions.

Once a day the installed app sends one "still here" to the project's GoatCounter
(a privacy-friendly counter, the same one Onion Board uses): the version number and
a random ID made on this PC, so the same person isn't counted twice and we can see how
people use the app over time. Also a one-off
"first start" (with where they heard about the app, if they picked it on the
installer's last page), and "updated" when *Update now* installs a new version.
Nothing else: no name, triggers, pictures, windows, games or IP address in the
message (GoatCounter sees the connection's address like any site does, and isn't
sent it to keep or look up).

On unless switched off: the installer's "Count me in" box, or Settings > Updates and
privacy. Copies from before it existed start with it off (settings.Config.load):
they were installed as an app that sent nothing. A copy running from source never
sends anything, and neither does one on a PC with ONIONBOARD_NO_STATS set (the
developer's own PCs and test VMs, the same switch Onion Board obeys). Inside Onion
Board (as its Triggers tab) this module isn't used at all: the board counts itself."""
from __future__ import annotations

import hashlib
import json
import logging
import os
import re
import sys
import threading
import time
import urllib.request
import uuid

from onionwatch import __version__

log = logging.getLogger(__name__)

ENDPOINT = "https://onionalien.goatcounter.com/api/v0/count"
# a key that can only add counts (GoatCounter's "Record pageviews" permission), not
# read or change anything; "" sends nothing
TOKEN = "1mdp7aoiksvjn2e3oitmjdaqd1u33msk6p74g7samuec2tufwr"  # gitleaks:allow (count-only)
PREFIX = "onion-watch"   # every path starts with it: the counter is shared with Onion Board
EVERY_S = 24 * 3600
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


def hits(cfg, now: float, event: str = "") -> list[dict]:
    """What a send would say: the daily "still here" for this version if one is due
    (and "first-start" the first time ever), or the one `event`."""
    sid = install_id(cfg)
    if event:
        return [{"path": event, "title": event, "event": True, "session": sid,
                 "ref": user_tag(sid)}]
    if now - cfg.stats_sent < EVERY_S:
        return []
    out = [{"path": f"/{PREFIX}/app/{__version__}", "title": f"Onion Watch {__version__}",
            "session": sid, "ref": user_tag(sid)}]
    if not cfg.stats_sent:
        heard = heard_tag(cfg.stats_heard)
        first = f"{PREFIX}/first-start" + (f"/heard-{heard}" if heard else "")
        out.append({"path": first, "title": first, "event": True, "session": sid,
                    "ref": user_tag(sid)})
    return out


def update_event(to: str) -> str:
    """The event for *Update now* from this version to `to`."""
    return f"{PREFIX}/update-now/{__version__}-to-{to}"


def send(payload: list[dict]) -> bool:
    """POST them to the counter. True if it took them. Call off the UI thread."""
    body = json.dumps({"hits": payload}).encode("utf-8")
    req = urllib.request.Request(ENDPOINT, data=body, method="POST", headers={
        "Authorization": f"Bearer {TOKEN}", "Content-Type": "application/json",
        "User-Agent": "OnionWatch"})
    try:
        with urllib.request.urlopen(req, timeout=TIMEOUT_S) as r:
            return 200 <= r.status < 300
    except Exception as e:  # noqa: BLE001 - offline, counter down
        log.info("usage count not sent: %s", e)
        return False


def maybe_send(cfg, saved=None, event: str = "") -> threading.Thread | None:
    """The daily count if it's due (or `event` now), on a thread, when it's switched
    on. `saved()` is called on that thread after cfg.stats_sent changed. The thread,
    or None when nothing goes."""
    if not enabled() or not cfg.usage_count:
        return None
    now = time.time()
    payload = hits(cfg, now, event)
    if not payload:
        return None

    def run():
        if send(payload) and not event:
            cfg.stats_sent = now
            if saved is not None:
                saved()
    t = threading.Thread(target=run, daemon=True, name="usage-count")
    t.start()
    return t
