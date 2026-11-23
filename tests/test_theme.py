"""Tests for the diary_app.theme public interface."""

import unittest

from diary_app import theme


class ThemeTest(unittest.TestCase):
    """theme turns an app colour name into CSS and validates colours."""

    def test_offers_the_seven_app_colours(self) -> None:
        self.assertEqual(
            theme.app_colour_names(),
            ["Green", "Blue", "Teal", "Purple", "Pink", "Orange", "Slate"],
        )

    def test_css_defines_the_chosen_colour(self) -> None:
        css = theme.css("Blue")
        self.assertIn("#24508F", css)
        self.assertNotIn("#2F7D4F", css)

    def test_unknown_colour_falls_back_to_the_default(self) -> None:
        self.assertEqual(theme.css("Chartreuse"), theme.css(theme.DEFAULT))

    def test_default_is_green(self) -> None:
        self.assertEqual(theme.DEFAULT, "Green")
        self.assertIn("#2F7D4F", theme.css(theme.DEFAULT))

    def test_person_colours_are_a_fixed_palette(self) -> None:
        self.assertIn("#B04A17", theme.PERSON_COLOURS)
        self.assertTrue(theme.is_person_colour("#B04A17"))
        self.assertFalse(theme.is_person_colour("#123456"))
        self.assertFalse(theme.is_person_colour("red;}</style>"))


if __name__ == "__main__":
    unittest.main()
