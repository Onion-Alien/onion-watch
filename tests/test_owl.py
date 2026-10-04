"""Hoot alive (owl.OwlWidget): every act he does while he waits runs start to end and
paints, the mouse coming near cuts an act short and perks him up, and a click cheers
him. Offscreen, stepped by hand: no timers are waited on."""
from PySide6.QtCore import Qt
from PySide6.QtGui import QImage

from onionwatch import owl


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
    assert hits and w.say == "yay"
    w.step(0.4, mouse=None)
    assert "joy" in w.pose()
    w.step(2.0, mouse=None)
    assert "joy" not in w.pose() and w.say == ""


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


def test_feathers_follow_the_theme_but_artwork_stays_teal(qapp):
    from PySide6.QtCore import QRectF
    from PySide6.QtGui import QColor, QPainter

    from onionwatch import theme

    def body_colour():
        img = QImage(100, 120, QImage.Format_ARGB32)
        img.fill(Qt.transparent)
        p = QPainter(img)
        owl.draw_owl(p, QRectF(0, 0, 100, 120))
        p.end()
        return img.pixelColor(50, 30)   # the top of his head, above the face

    try:
        theme.use_palette({"accent": "#ff0000"})   # a host's theme
        assert body_colour() == QColor("#ff0000")
        img = owl.owl_image(120)
        assert img.pixelColor(img.width() // 2, 30) == owl.FEATHER
    finally:
        theme.set_current(theme.DEFAULT)
