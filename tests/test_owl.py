"""Hoot alive (style/owl.OwlWidget, the style kit copied from Onion Board): every act he
does while he waits runs start to end and paints, the mouse coming near cuts an act
short and perks him up, and a click cheers him. Offscreen, stepped by hand: no timers
are waited on."""
from PySide6.QtCore import Qt
from PySide6.QtGui import QImage

from onionwatch.style import mascotlines, owl


def paint(w):
    img = QImage(w.size(), QImage.Format_ARGB32)
    img.fill(Qt.transparent)
    w.render(img)
    return img


def test_every_act_runs_and_paints(qapp):
    w = owl.OwlWidget(80)
    w.resize(w.sizeHint())
    for act, length in owl.ACTS.items():
        w.start(act)
        assert w.act == act
        for _ in range(int(length / 0.1) + 2):
            w.step(0.1, mouse=None)
            paint(w)
        assert w.act is None


def test_begging_says_something_and_clasps(qapp):
    w = owl.OwlWidget(80, lines=("please?",))
    w.start("plead")
    w.step(owl.ACTS["plead"] / 2, mouse=None)
    assert w.say == "please?"
    assert w.pose()["clasp"] > 0.9


def test_mouse_near_perks_him_up(qapp):
    w = owl.OwlWidget(80)
    w.resize(w.sizeHint())
    sad = w.pose()["sad"]
    w.start("doze")
    for _ in range(30):
        w.step(0.05, mouse=(0.5, -0.2))
    assert w.act is None                   # woke up for you
    assert w.pose()["sad"] < sad / 3
    assert w.pose()["look"] > 0.5          # and looks your way


def test_click_cheers(qapp):
    w = owl.OwlWidget(80, joy=("yay",))
    w.resize(w.sizeHint())
    hits = []
    w.clicked.connect(lambda: hits.append(1))
    from PySide6.QtCore import QPointF
    from PySide6.QtGui import QMouseEvent
    c = QPointF(w.width() / 2, w.height() / 2)
    w.mousePressEvent(QMouseEvent(QMouseEvent.MouseButtonPress, c, c, Qt.LeftButton,
                                  Qt.LeftButton, Qt.NoModifier))
    cheer = w.say
    assert hits and cheer in ("yay",) + mascotlines.hoot()   # his own lines mix in
    w.step(0.4, mouse=None)
    assert "joy" in w.pose()
    w.step(max(2.0, mascotlines.read_secs(cheer)), mouse=None)   # long lines stay to be read
    # the cheer is over (he may already be begging again: a wait line, at random)
    assert "joy" not in w.pose() and w.say != cheer


def test_owl_image_still_plain(qapp):
    img = owl.owl_image(120)
    assert img.height() == 120 and not img.isNull()


def test_room_beside_him_gives_way(qapp):
    w = owl.OwlWidget(100, left=0, right=80)
    assert w.minimumSizeHint().width() < w.sizeHint().width() - 60
    w.resize(w.minimumSizeHint())
    w.start("plead")
    w.step(1.0, mouse=None)
    r = w._owl_rect()
    assert r.left() >= 0 and r.right() <= w.width()
    paint(w)


def test_his_look_follows_the_theme_but_artwork_stays_teal(qapp):
    """Each theme dresses Hoot in its own look (the kit's owl.LOOKS); Onion Watch's own
    Hoot theme and the artwork are plain teal Hoot."""
    from PySide6.QtCore import QRectF
    from PySide6.QtGui import QPainter

    from onionwatch.ui.kit import theme

    def hoot(**kw):
        img = QImage(100, 120, QImage.Format_ARGB32)
        img.fill(Qt.transparent)
        p = QPainter(img)
        owl.draw_owl(p, QRectF(0, 0, 100, 120), outfit=(), **kw)
        p.end()
        return img

    try:
        theme.set_current("Mocha")
        assert hoot() == hoot(kit=owl.look("Mocha")) != hoot(kit=owl.VANILLA)
        art = owl.owl_image(120)           # the artwork: plain Hoot whatever the theme
        theme.set_current("Hoot")
        assert hoot() == hoot(kit=owl.VANILLA)
        assert owl.owl_image(120) == art
    finally:
        theme.set_current(theme.DEFAULT)


def test_he_stops_while_another_program_is_in_front(qapp, monkeypatch):
    from onionwatch.style import appstate
    front = [True]
    monkeypatch.setattr(appstate, "active", lambda: front[0])
    w = owl.OwlWidget(80)
    w.resize(w.sizeHint())
    w.show()
    w._resume()
    assert w._timer.isActive()
    front[0] = False
    qapp.applicationStateChanged.emit(Qt.ApplicationInactive)
    assert not w._timer.isActive()
    front[0] = True
    qapp.applicationStateChanged.emit(Qt.ApplicationActive)
    assert w._timer.isActive()
    w.hide()
    assert not w._timer.isActive()
    qapp.applicationStateChanged.emit(Qt.ApplicationActive)   # back in front, but hidden
    assert not w._timer.isActive()
