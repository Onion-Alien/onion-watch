"""Trigger categories and profiles: which triggers are watched for now.

A library of triggers can be far bigger than what's worth watching at once (each
picture on costs a share of the 1 % of the processor watching keeps to; see
screenwatch.CPU_SHARE). So triggers sit in categories (Trigger.category, the
user's own names; "" is Uncategorised), and a category can be switched off as a
whole. Turning it off leaves its triggers' own switches alone, so turning it back
on brings back just the ones that were on.

A profile is a set of categories to have on. Who decides which are on (`Groups.mode`):

    ""          Manual: each category's own switch
    a profile   picked by hand: just that profile's categories
    "auto"      the profiles whose program is running (or in front), their
                categories together; Manual's switches while none is

A profile's programs are exe names the user picked or typed ("game.exe", any
program); there are no built-in lists. AppWatch says which profiles fit the
windows open now.

Everything is kept in Config.screen beside the triggers, as plain lists and dicts
(an older version leaves them be):

    categories  [{"name", "on", "open"}]   in the order they're shown
    profiles    [{"id", "name", "apps": ["game.exe"], "when": "running" | "front",
                  "categories": [names]}]
    profile     "" | "auto" | a profile's id
"""
from __future__ import annotations

import ntpath
import uuid
from dataclasses import dataclass, field

UNCATEGORISED = ""              # the category of a trigger that isn't in one
UNCATEGORISED_LABEL = "Uncategorised"
NAME_MAX = 60                   # characters in a category's or profile's name
MAX_CATEGORIES = 200
MAX_PROFILES = 50
MAX_APPS = 16                   # programs one profile can be tied to
WHENS = ("running", "front")    # a profile's program has a window open / is in front
AUTO = "auto"
FRONT_LINGER = 10.0             # seconds a "front" profile stays on after its program
                                # leaves the front (an alt-tab doesn't flick it off)


def clean_name(text) -> str:
    """A category's or profile's name as kept: one line, trimmed, at most NAME_MAX."""
    if not isinstance(text, str):
        return ""
    return " ".join(text.split())[:NAME_MAX]


def label(name: str) -> str:
    """A category's name on screen."""
    return name or UNCATEGORISED_LABEL


def exe_name(text) -> str:
    """A program as a profile keeps it: its file name in lower case ("game.exe"),
    from what was typed (a path, quotes, no ".exe"); "" for nothing usable."""
    if not isinstance(text, str):
        return ""
    name = ntpath.basename(text.strip().strip('"').strip()).lower()
    if not name or name in (".", ".."):
        return ""
    if "." not in name:
        name += ".exe"
    return name[:260]


@dataclass
class Category:
    name: str
    on: bool = True
    open: bool = False          # its section is unfolded in the list

    def to_raw(self) -> dict:
        return {"name": self.name, "on": self.on, "open": self.open}


@dataclass
class Profile:
    id: str
    name: str = "Profile"
    apps: list[str] = field(default_factory=list)
    when: str = "running"
    categories: list[str] = field(default_factory=list)

    @classmethod
    def from_raw(cls, d) -> Profile | None:
        if not isinstance(d, dict) or not isinstance(d.get("id"), str) or not d["id"]:
            return None
        p = cls(id=d["id"][:40], name=clean_name(d.get("name")) or "Profile")
        apps = d.get("apps")
        for a in apps if isinstance(apps, list) else []:
            a = exe_name(a)
            if a and a not in p.apps and len(p.apps) < MAX_APPS:
                p.apps.append(a)
        if d.get("when") in WHENS:
            p.when = d["when"]
        cats = d.get("categories")
        for c in cats if isinstance(cats, list) else []:
            if isinstance(c, str) and clean_name(c) == c and c not in p.categories:
                p.categories.append(c)
        return p

    def to_raw(self) -> dict:
        return {"id": self.id, "name": self.name, "apps": list(self.apps),
                "when": self.when, "categories": list(self.categories)}

    def copy(self) -> Profile:
        p = Profile.from_raw(self.to_raw())
        assert p is not None
        return p


def new_profile(name: str = "Profile") -> Profile:
    return Profile(id=uuid.uuid4().hex[:12], name=clean_name(name) or "Profile")


class Groups:
    """The categories, the profiles and who decides, as saved in Config.screen."""

    def __init__(self):
        self.categories: list[Category] = []
        self.profiles: list[Profile] = []
        self.mode = ""

    # ------------------------------------------------------------------ load / save
    @classmethod
    def load(cls, screen: dict, used: list[str] = ()) -> Groups:
        """From Config.screen. `used`: the triggers' categories, each given a
        category (on) when the saved list doesn't have it, so a trigger is never in
        a category that isn't shown."""
        g = cls()
        raw = screen.get("categories")
        for d in raw if isinstance(raw, list) else []:
            if not isinstance(d, dict) or not isinstance(d.get("name"), str):
                continue
            name = clean_name(d["name"])
            if name != d["name"] or g.find(name) is not None:
                continue
            if len(g.categories) >= MAX_CATEGORIES:
                break
            g.categories.append(Category(name, d.get("on") is not False,
                                         d.get("open") is True))
        for name in used:
            g.ensure(name)
        raw = screen.get("profiles")
        for d in raw if isinstance(raw, list) else []:
            p = Profile.from_raw(d)
            if p is not None and g.profile(p.id) is None and len(g.profiles) < MAX_PROFILES:
                g.profiles.append(p)
        mode = screen.get("profile")
        if mode == AUTO or (isinstance(mode, str) and g.profile(mode) is not None):
            g.mode = mode
        return g

    def save(self, screen: dict):
        screen["categories"] = [c.to_raw() for c in self.categories]
        screen["profiles"] = [p.to_raw() for p in self.profiles]
        screen["profile"] = self.mode

    # ------------------------------------------------------------------ categories
    def names(self) -> list[str]:
        return [c.name for c in self.categories]

    def find(self, name: str) -> Category | None:
        return next((c for c in self.categories if c.name == name), None)

    def ensure(self, name: str, on: bool = True) -> Category:
        """The category called `name`, added at the end (Uncategorised: at the top)
        if it isn't there yet."""
        c = self.find(name)
        if c is None:
            c = Category(name, on)
            if name == UNCATEGORISED:
                self.categories.insert(0, c)
            else:
                self.categories.append(c)
        return c

    def rename(self, old: str, new: str) -> bool:
        """Rename a category (into another one: the two become one). The caller
        moves the triggers. False if there's no such category."""
        c = self.find(old)
        if c is None or old == new:
            return False
        other = self.find(new)
        if other is not None:
            self.categories.remove(c)
        else:
            c.name = new
        for p in self.profiles:
            if old in p.categories:
                p.categories = [n for n in p.categories if n != old]
                if new not in p.categories:
                    p.categories.append(new)
        return True

    def remove(self, name: str) -> int:
        """Take a category away (its triggers go to Uncategorised: the caller moves
        them). Returns where it was, for putting it back."""
        c = self.find(name)
        if c is None:
            return -1
        i = self.categories.index(c)
        self.categories.remove(c)
        for p in self.profiles:
            p.categories = [n for n in p.categories if n != name]
        return i

    def move(self, name: str, step: int):
        c = self.find(name)
        if c is None:
            return
        i = self.categories.index(c)
        j = min(max(i + step, 0), len(self.categories) - 1)
        self.categories.insert(j, self.categories.pop(i))

    # ------------------------------------------------------------------ profiles
    def profile(self, pid: str) -> Profile | None:
        return next((p for p in self.profiles if p.id == pid), None)

    def in_charge(self, matched: list[str] = ()) -> list[Profile]:
        """The profiles deciding what's on now ([]: Manual's switches). `matched`:
        the ids of the profiles whose program fits now (AppWatch.matched)."""
        if self.mode == AUTO:
            return [p for p in self.profiles if p.id in matched]
        p = self.profile(self.mode) if self.mode else None
        return [p] if p is not None else []

    def active(self, matched: list[str] = ()) -> set[str]:
        """The categories that are on now."""
        ps = self.in_charge(matched)
        if ps:
            return {n for p in ps for n in p.categories}
        return {c.name for c in self.categories if c.on}

    def set_on(self, name: str, on: bool, matched: list[str] = ()) -> bool:
        """A category's switch was flipped: change whatever decides now (Manual's
        switch, or the one profile in charge). False when two or more profiles are
        in charge (then the switches only show what they say)."""
        ps = self.in_charge(matched)
        if len(ps) > 1:
            return False
        if not ps:
            c = self.ensure(name)
            c.on = on
            return True
        p = ps[0]
        if on and name not in p.categories:
            p.categories.append(name)
        elif not on:
            p.categories = [n for n in p.categories if n != name]
        return True


class AppWatch:
    """Which profiles' programs fit the windows open now. update() is given the
    programs with a window open and the one in front, now and then; a "front"
    profile stays on FRONT_LINGER seconds after its program leaves the front."""

    def __init__(self):
        self.matched: list[str] = []
        self._front_seen: dict[str, float] = {}     # profile id -> last time in front

    def update(self, profiles: list[Profile], running: set[str], front: str,
               now: float) -> bool:
        """Work out `matched` again; True if it changed."""
        out = []
        for p in profiles:
            if not p.apps:
                continue
            if p.when == "front":
                if front in p.apps:
                    self._front_seen[p.id] = now
                seen = self._front_seen.get(p.id)
                if seen is not None and now - seen <= FRONT_LINGER:
                    out.append(p.id)
            elif running & set(p.apps):
                out.append(p.id)
        changed = out != self.matched
        self.matched = out
        return changed
