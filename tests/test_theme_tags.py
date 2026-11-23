"""Tests for the recipe tag colours in diary_app.theme."""

import unittest

from diary_app import recipes, theme

_LINEAR_CUTOFF = 0.03928  # from the WCAG contrast formula


def _luminance(hex_colour: str) -> float:
    channels = [int(hex_colour[i : i + 2], 16) / 255 for i in (1, 3, 5)]
    linear = [
        c / 12.92 if c <= _LINEAR_CUTOFF else ((c + 0.055) / 1.055) ** 2.4
        for c in channels
    ]
    return 0.2126 * linear[0] + 0.7152 * linear[1] + 0.0722 * linear[2]


def _contrast(first: str, second: str) -> float:
    a, b = sorted((_luminance(first), _luminance(second)), reverse=True)
    return (a + 0.05) / (b + 0.05)


class TagColourTest(unittest.TestCase):
    """Every recipe tag has a readable colour chip."""

    def test_every_tag_has_a_colour(self) -> None:
        for tag in recipes.TAGS:
            self.assertIn(tag, theme.TAG_COLOURS)

    def test_chip_text_is_readable_on_its_background(self) -> None:
        for tag, (background, text) in theme.TAG_COLOURS.items():
            self.assertGreaterEqual(_contrast(background, text), 4.5, tag)

    def test_tag_style_is_inline_css_for_a_known_tag(self) -> None:
        style = theme.tag_style("Veg-led")
        background, text = theme.TAG_COLOURS["Veg-led"]
        self.assertIn(f"background: {background}", style)
        self.assertIn(f"color: {text}", style)

    def test_unknown_tag_gets_a_neutral_style_not_user_text(self) -> None:
        style = theme.tag_style("x;}</style><script>")
        self.assertNotIn("<", style)
        self.assertNotIn("script", style)


if __name__ == "__main__":
    unittest.main()
