"""Light themes: buttons and boxes stand out from what they sit on."""
import pytest

from onionwatch import theme


@pytest.mark.parametrize("name", [n for n in theme.THEMES if theme.is_light(n)])
def test_a_light_themes_buttons_and_boxes_show_on_every_surface(name):
    """Light's buttons were 1.06:1 on the window and its boxes white on white cards."""
    t = theme.THEMES[name]
    for surface in ("bg", "panel"):
        assert theme._contrast(t["btn"], t[surface]) >= 1.12, surface
    assert theme._contrast(t["card_ctl"], t["panel"]) >= 1.10


def test_the_style_has_the_main_buttons_gradient():
    """The filled main button is Onion Board's gradient, not a flat accent."""
    css = theme.stylesheet("Hoot")
    rule = css[css.index("QPushButton#primary, QFrame#card QPushButton#primary"):]
    assert "qlineargradient" in rule.split("}")[0]
