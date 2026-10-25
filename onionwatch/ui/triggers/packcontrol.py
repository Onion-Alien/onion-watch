"""Trigger packs on the triggers page: saving triggers (all of them, or a category's)
to a pack file, loading one, and adding what a pack brought: its triggers with their
pictures and sounds, and its categories' looks. The file format is
onionwatch.engine.packs.

TriggersTab makes one ``PackControl`` (``TriggersTab.packctl``)."""
from __future__ import annotations

import logging
import uuid
from pathlib import Path

from PySide6.QtGui import QImage
from PySide6.QtWidgets import QFileDialog, QMessageBox

from onionwatch.core import usage
from onionwatch.engine import packs, profiles
from onionwatch.engine.screenwatch import Trigger
from onionwatch.i18n import _, ngettext
from onionwatch.ui.triggers.controller import MAX_TRIGGERS, Controller
from onionwatch.ui.triggers.pictures import picture_name, save_picture

log = logging.getLogger(__name__)


class PackControl(Controller):
    """Saving and loading trigger packs for one TriggersTab (``tab``)."""

    def export_triggers(self, triggers: list[Trigger] | None = None, name: str = ""):
        """Save triggers to a pack: all of them, or `triggers` (a category, `name`)."""
        tab = self.tab
        triggers = tab.triggers if triggers is None else triggers
        if not triggers:
            return
        file = f"Onion Watch {name}.zip" if name else "Onion Watch triggers.zip"
        file = "".join("_" if c in '\\/:*?"<>|' else c for c in file)
        path, __ = QFileDialog.getSaveFileName(tab, _("Save triggers"), str(Path.home() / file),
                                              _("Trigger packs") + " (*.zip)")
        if not path:
            return
        from onionwatch.ui.triggers.categories import pictures_dir as category_pictures_dir
        names = {t.category for t in triggers}
        cats = [c for c in tab.groups.categories if c.name in names]
        try:
            packs.write_pack(path, triggers, dict(tab.host.sounds()), cats,
                             category_pictures_dir(tab.host.data_dir))
        except OSError as e:
            QMessageBox.warning(tab, _("Couldn't save the triggers"), str(e))
            return
        usage.used("pack-export")
        QMessageBox.information(
            tab, _("Triggers saved"),
            ngettext("{n} trigger saved to {name}, pictures and all, each in its category "
                     "with its colours, picture and banner. Sounds go by name: sound files of "
                     "yours aren't in it.",
                     "{n} triggers saved to {name}, pictures and all, each in its category "
                     "with its colours, picture and banner. Sounds go by name: sound files of "
                     "yours aren't in it.", len(triggers), name=Path(path).name))

    def import_triggers(self):
        tab = self.tab
        path, __ = QFileDialog.getOpenFileName(tab, _("Load triggers"), str(Path.home()),
                                              _("Trigger packs") + " (*.zip);;"
                                              + _("All files") + " (*)")
        if not path:
            return
        try:
            found = packs.read_pack(path)
        except packs.PackError as e:
            QMessageBox.warning(tab, _("Can't load those triggers"), str(e))
            return
        if found and not any(t.category for t, _p, _s in found):
            # a pack without categories (an older one): its triggers go in one named
            # after the file, so they stay together
            name = profiles.clean_name(Path(path).stem.removeprefix("Onion Watch "))
            for t, _p, _s in found:
                t.category = name
        added = self.add_pack(found)
        if added:
            usage.used("pack-import")
            self.add_pack_looks(packs.read_categories(path))
        if found and not added:
            QMessageBox.information(tab, _("Too many triggers"),
                                    _("You can have up to {max_triggers} triggers.",
                                      max_triggers=MAX_TRIGGERS))
        elif not found:
            QMessageBox.information(tab, _("No triggers"), _("That file has no triggers in it."))

    def add_pack_looks(self, looks: dict):
        """Give the categories a pack brought their looks (packs.read_categories),
        each picture kept like a picked one. A category that already has a look
        or banner of its own keeps it."""
        from onionwatch.ui.triggers.categories import save_banner
        from onionwatch.ui.triggers.categories import save_picture as save_category_picture
        tab = self.tab
        changed = {}
        for name, (look, pic, wide) in looks.items():
            c = tab.groups.find(name)
            if c is None:
                continue
            new = c.full_look()
            if not c.look():
                new.update({k: v for k, v in look.items() if k != "banner"})
                img = QImage()
                if pic and img.loadFromData(pic):
                    new["image"] = save_category_picture(img, tab.host.data_dir)
            img = QImage()
            if not c.banner and wide and img.loadFromData(wide):
                b = save_banner(img, tab.host.data_dir)
                if b:
                    new["banner"] = {**look.get("banner", {}), "image": b}
            if new != c.full_look():
                changed[name] = new
        if changed:
            tab.set_category_looks(changed)

    def add_pack(self, found) -> int:
        """Add the triggers read from a pack (packs.read_pack): each gets a new id,
        its pictures are kept like cut ones, and its sounds are the host's of the
        same id or name, else the default. Each keeps its category (made if need be).
        Returns how many were added."""
        tab = self.tab
        have = tab.host.sounds()
        ids, by_name = {sid for sid, _n in have}, {n.lower(): sid for sid, n in have}
        added = 0
        for t, pics, sounds in found:
            if len(tab.triggers) >= MAX_TRIGGERS:
                break
            t.id = uuid.uuid4().hex[:12]
            t.enabled = True
            t.images = []
            for data in pics:
                img = QImage()
                if not img.loadFromData(data) or tab._check_picture(img)[0] is None:
                    continue
                try:
                    t.images.append(save_picture(img, picture_name(t, tab.pictures),
                                                 tab.pictures))
                except OSError:
                    log.warning("couldn't keep a picture from a pack", exc_info=True)
            mapped = []
            for sid, name in sounds or [(sid, "") for sid in t.sounds]:
                got = sid if sid in ids else by_name.get(name.lower()) if name else None
                if got and got not in mapped:
                    mapped.append(got)
            if not mapped and tab.host.default_sound:
                mapped = [tab.host.default_sound]
            t.sounds = mapped
            tab._insert(t)
            added += 1
        return added
