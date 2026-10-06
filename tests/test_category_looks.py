"""A category's own look: its tab's colour, its name's colour and a picture."""
import pytest
from PySide6.QtGui import QColor, QImage

from onionwatch import profiles
from onionwatch.ui import categories
from onionwatch.ui.categories import CategoriesDialog

from test_categories import make, raw  # noqa: F401  (the fixture, and its triggers)


def picture(colour="#ff0000", w=300, h=200) -> QImage:
    img = QImage(w, h, QImage.Format_RGB32)
    img.fill(QColor(colour))
    return img


def test_bad_values_are_cleaned():
    assert profiles.clean_color("#ABCDEF") == "#abcdef"
    assert profiles.clean_color("red") == "" and profiles.clean_color(None) == ""
    assert profiles.clean_picture("abc123.png") == "abc123.png"
    for bad in ("../x.png", "C:\\x.png", "a/b.png", "x.exe", 5):
        assert profiles.clean_picture(bad) == ""
    assert profiles.readable_on("#dcc060") == "#111111"
    assert profiles.readable_on("#212121") == "#ffffff"


def test_looks_load_and_save_apart_from_the_categories():
    screen = {"categories": [{"name": "Raid", "on": True}],
              "category_looks": {"Raid": {"color": "#E53935", "image": "../../evil.png"},
                                 "Gone": {"color": "#43a047"}}}
    g = profiles.Groups.load(screen)
    c = g.find("Raid")
    assert (c.color, c.text_color, c.image) == ("#e53935", "", "")
    assert categories.ink(c) == "#ffffff"        # automatic: readable on the red
    g.save(screen)
    # the categories as an older version knows them: nothing new in there
    assert screen["categories"] == [{"name": "Raid", "on": True, "open": False}]
    assert screen["category_looks"] == {"Raid": {"color": "#e53935"},
                                        "Gone": {"color": "#43a047"}}


def test_an_older_version_saving_its_categories_loses_no_look():
    screen = {"categories": [{"name": "Raid"}], "category_looks": {"Raid": {"color": "#1e88e5"}}}
    g = profiles.Groups.load(screen)
    g.save(screen)
    # an older version: rewrites `categories` its way, never touches category_looks
    screen["categories"] = [{"name": "Raid", "on": False, "open": True}]
    g2 = profiles.Groups.load(screen)
    assert g2.find("Raid").color == "#1e88e5" and g2.find("Raid").on is False


def test_rename_keeps_the_look_and_delete_drops_it_with_undo(make):  # noqa: F811
    tab = make({"triggers": [raw(1, "Old"), raw(2, "Other")]})
    tab.set_category_looks({"Old": {"color": "#8e24aa", "text_color": "#dcc060"}})
    assert tab.rename_category("Old", "New")
    assert tab.groups.find("New").color == "#8e24aa"
    looks = tab.host.screen["category_looks"]
    assert "Old" not in looks and looks["New"]["text_color"] == "#dcc060"
    assert tab.sections["New"].header.styleSheet() == categories.tab_css("#8e24aa")
    assert tab.delete_category("New", ask=False)
    assert "New" not in tab.host.screen["category_looks"]
    tab.undo_bar.btn_undo.click()
    assert tab.groups.find("New").color == "#8e24aa"
    assert tab.sections["New"].header.styleSheet() == categories.tab_css("#8e24aa")


def test_merging_into_a_plain_category_brings_the_look(make):  # noqa: F811
    tab = make({"triggers": [raw(1, "A"), raw(2, "B")]})
    tab.set_category_looks({"A": {"color": "#43a047"}})
    assert tab.rename_category("A", "B")
    assert tab.groups.find("B").color == "#43a047"


def test_the_categories_window_edits_copies_and_shows_them(make, qapp):  # noqa: F811
    tab = make({"triggers": [raw(1, "Raid"), raw(2, "Quests")]})
    dlg = CategoriesDialog(tab, tab.groups.categories, tab.host.data_dir, "Quests")
    assert dlg.list.currentItem().text() == "Quests"
    dlg.set_color("#dcc060")
    assert dlg.color_buttons["#dcc060"].isChecked() and dlg.text_buttons[""].isChecked()
    assert dlg.preview.styleSheet() == categories.tab_css("#dcc060")
    assert categories.ink(dlg.cats[1]) in dlg.preview_name.styleSheet()
    dlg.set_text_color("#ff00aa")
    assert dlg.set_picture(picture())
    name = dlg.result["Quests"]["image"]
    saved = QImage(str(categories.pictures_dir(tab.host.data_dir) / name))
    assert max(saved.width(), saved.height()) == categories.PICTURE_PX
    assert not dlg.preview_pic.isHidden()
    assert tab.groups.find("Quests").color == ""         # a copy until OK
    tab.set_category_looks(dlg.result)
    sec = tab.sections["Quests"]
    assert "qlineargradient" in sec.header.styleSheet() and "#ff00aa" in sec.btn_fold.styleSheet()
    assert not sec.pic.isHidden() and sec.pic.pixmap().width() == categories.HEADER_PICTURE
    assert tab.host.screen["category_looks"]["Quests"] == {
        "color": "#dcc060", "text_color": "#ff00aa", "image": name}
    # back to plain
    dlg = CategoriesDialog(tab, tab.groups.categories, tab.host.data_dir, "Quests")
    dlg.reset()
    tab.set_category_looks(dlg.result)
    assert sec.header.styleSheet() == "" and sec.pic.isHidden()
    assert "Quests" not in tab.host.screen["category_looks"]


def test_a_missing_picture_just_isnt_shown(make):  # noqa: F811
    tab = make({"triggers": [raw(1, "Raid"), raw(2)],
                "category_looks": {"Raid": {"image": "deadbeef.png"}}})
    assert tab.sections["Raid"].pic.isHidden()


@pytest.mark.parametrize("named", [True, False])
def test_the_categories_button_is_there_once_there_is_a_category(make, named):  # noqa: F811
    tab = make({"triggers": [raw(1, "Raid" if named else ""), raw(2)]})
    tab.resize(1200, 600)
    tab._fit_top()
    assert tab.btn_categories.isEnabled() == named


def test_tabs_are_soft_and_fade_into_the_panel():
    css = categories.tab_css("#ff0000")
    start = categories.mix("#ff0000", categories._panel(), categories.TINT_FROM)
    end = categories.mix("#ff0000", categories._panel(), categories.TINT_TO)
    assert "#ff0000" not in css and start in css and end in css
    assert categories.tab_css("") == ""
    # automatic text reads on the soft yellow; a picked one is kept as it is
    c = profiles.Category("Q", color="#ffff00")
    soft = categories.mix("#ffff00", categories._panel(), categories.TINT_FROM)
    assert categories.ink(c) == profiles.readable_on(soft)
    c.text_color = "#123456"
    assert categories.ink(c) == "#123456"
    assert categories.ink(profiles.Category("Plain")) == ""


def test_a_banner_is_kept_apart_so_older_versions_keep_it():
    screen = {"categories": [{"name": "Raid"}],
              "category_banners": {"Raid": {"image": "abc.png", "x": 1.7, "y": "no",
                                            "height": "huge"},
                                   "Gone": {"image": "def.png"}}}
    g = profiles.Groups.load(screen)
    c = g.find("Raid")
    assert (c.banner, c.banner_x, c.banner_y, c.banner_height) == ("abc.png", 1.0, 0.5,
                                                                   "medium")
    g.save(screen)
    assert screen["category_banners"]["Raid"] == {"image": "abc.png", "x": 1.0, "y": 0.5,
                                                  "height": "medium"}
    assert "Gone" in screen["category_banners"]     # an older version's rename: kept
    # an older version rewrites category_looks with what it knows: the banner stays
    screen["category_looks"] = {"Raid": {"color": "#1e88e5"}}
    assert profiles.Groups.load(screen).find("Raid").banner == "abc.png"


def test_a_banner_shows_across_the_header_and_drags_into_place(make, qapp):  # noqa: F811
    tab = make({"triggers": [raw(1, "Raid"), raw(2)]})
    dlg = CategoriesDialog(tab, tab.groups.categories, tab.host.data_dir, "Raid")
    assert dlg.set_banner(picture("#00ff00", 1600, 200))
    c = dlg._current()
    assert c.banner and (c.banner_x, c.banner_y) == (0.5, 0.5)
    dlg.cb_banner_height.setCurrentIndex(dlg.cb_banner_height.findData("tall"))
    # dragging the preview's picture right shows more of its left
    pv = dlg.preview
    pv.resize(400, profiles.BANNER_HEIGHTS["tall"])
    from PySide6.QtCore import QPointF
    from PySide6.QtGui import QMouseEvent
    from PySide6.QtCore import QEvent, Qt

    def mouse(kind, x):
        return QMouseEvent(kind, QPointF(x, 20), QPointF(x, 20), Qt.LeftButton,
                           Qt.LeftButton, Qt.NoModifier)
    pv.mousePressEvent(mouse(QEvent.MouseButtonPress, 100))
    pv.mouseMoveEvent(mouse(QEvent.MouseMove, 160))
    pv.mouseReleaseEvent(mouse(QEvent.MouseButtonRelease, 160))
    assert c.banner_x < 0.5 and c.banner_y == 0.5
    tab.set_category_looks(dlg.result)
    dlg.deleteLater()
    saved = tab.host.screen["category_banners"]["Raid"]
    assert saved["height"] == "tall" and saved["x"] < 0.5
    head = tab.sections["Raid"].header
    assert head.img is not None and head.maximumHeight() == profiles.BANNER_HEIGHTS["tall"]


def test_a_pack_carries_its_categories_looks_and_banners(make, tmp_path):  # noqa: F811
    from onionwatch import packs
    a = make({"triggers": [raw(1, "Raid"), raw(2, "Plain")]})
    dlg = CategoriesDialog(a, a.groups.categories, a.host.data_dir, "Raid")
    dlg.set_color("#8e24aa")
    dlg.set_picture(picture("#ff0000", 64, 64))
    dlg.set_banner(picture("#0000ff", 1200, 150))
    dlg._current().banner_x = 0.2
    a.set_category_looks(dlg.result)
    dlg.deleteLater()
    path = tmp_path / "p.zip"
    packs.write_pack(path, a.triggers, {}, a.groups.categories,
                     categories.pictures_dir(a.host.data_dir))
    looks = packs.read_categories(path)
    assert set(looks) == {"Raid"} and looks["Raid"][1] and looks["Raid"][2]
    b = make({"triggers": []})
    assert b.add_pack(packs.read_pack(path)) == 2
    b.add_pack_looks(looks)
    c = b.groups.find("Raid")
    assert c.color == "#8e24aa" and c.image and c.banner and c.banner_x == 0.2
    assert categories.banner_image(c, b.host.data_dir) is not None
