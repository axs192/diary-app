"""Tests that moving between pages does not flash the browser's backdrop.

Every tap is a full page load. Until the new page paints, the browser shows its
own backdrop (black in an iOS Home Screen app), so the page colour is set
inline, before the stylesheet is requested, and modern browsers cross-fade.
"""

import pathlib
import re
import tempfile
import unittest

import pydantic
from fastapi import testclient

from diary_app import app as diary_app
from diary_app import config

_PIN = "4321"
_SESSION_SECRET = "transition-test-session-secret-0123456789"  # noqa: S105
_PAGE_COLOUR = "#F4F5F1"


class PageTransitionTest(unittest.TestCase):
    def setUp(self) -> None:
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        settings = config.Settings(
            household_pin=pydantic.SecretStr(_PIN),
            session_secret=pydantic.SecretStr(_SESSION_SECRET),
            database_path=pathlib.Path(tmp.name) / "diary.db",
        )
        self.client = testclient.TestClient(
            diary_app.create_app(settings), follow_redirects=False
        )

    def _pages(self) -> list[tuple[str, str]]:
        pages = [("/login", self.client.get("/login").text)]
        self.client.post("/login", data={"pin": _PIN})
        pages += [
            (p, self.client.get(p).text)
            for p in ("/home", "/meals", "/settings")
        ]
        return pages

    def test_the_page_colour_is_set_before_the_stylesheet_loads(self) -> None:
        for page, html in self._pages():
            colour = html.find(f"background: {_PAGE_COLOUR}")
            stylesheet = html.find('href="/static/app.css"')
            self.assertGreater(colour, -1, page)
            self.assertLess(colour, stylesheet, page)

    def test_the_page_colour_is_set_on_the_root_element(self) -> None:
        for page, html in self._pages():
            self.assertRegex(
                html, r"<style>\s*html,\s*body\s*\{[^}]*background", page
            )

    def test_the_stylesheet_does_not_repeat_the_page_colour(self) -> None:
        # One place for the colour, so the two cannot drift apart.
        css = self.client.get("/static/app.css").text
        self.assertNotIn(_PAGE_COLOUR, css)

    def test_modern_browsers_cross_fade_between_pages(self) -> None:
        css = self.client.get("/static/app.css").text
        self.assertRegex(css, r"@view-transition\s*\{\s*navigation:\s*auto")

    def test_the_cross_fade_rule_sits_outside_any_block(self) -> None:
        # Safari 9 skips an unknown at-rule, but only if it is well formed.
        css = self.client.get("/static/app.css").text
        before = css[: css.index("@view-transition")]
        self.assertEqual(before.count("{"), before.count("}"))
        self.assertTrue(re.search(r"\{\s*navigation:\s*auto;?\s*\}", css))


if __name__ == "__main__":
    unittest.main()
