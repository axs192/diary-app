"""Tests that every main-menu item has its own icon."""

import pathlib
import re
import tempfile
import unittest

import pydantic
from fastapi import testclient

from diary_app import app as diary_app
from diary_app import config

_PIN = "4321"


class NavIconTest(unittest.TestCase):
    """Meals shows a food icon, not the Settings cog."""

    def setUp(self) -> None:
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        settings = config.Settings(
            household_pin=pydantic.SecretStr(_PIN),
            session_secret=pydantic.SecretStr(
                "nav-icon-test-secret-0123456789"
            ),
            database_path=pathlib.Path(tmp.name) / "diary.db",
        )
        client = testclient.TestClient(
            diary_app.create_app(settings), follow_redirects=False
        )
        client.post("/login", data={"pin": _PIN})
        self.html = client.get("/home").text

    def _icons(self) -> dict[str, str]:
        found = re.findall(
            r'<a class="nav-item"[^>]*>\s*<svg[^>]*data-icon="([a-z]+)"'
            r'.*?<span class="nav-label">([^<]+)</span>',
            self.html,
            re.DOTALL,
        )
        return {label: icon for icon, label in found}

    def test_every_menu_item_has_an_icon(self) -> None:
        self.assertEqual(set(self._icons()), {"Today", "Meals", "Settings"})

    def test_no_two_menu_items_share_an_icon(self) -> None:
        icons = list(self._icons().values())
        self.assertEqual(len(icons), len(set(icons)))

    def test_meals_is_not_the_settings_cog(self) -> None:
        icons = self._icons()
        self.assertNotEqual(icons["Meals"], icons["Settings"])
        meals_item = self.html.split('href="/meals"', 1)[1].split("</a>")[0]
        self.assertNotIn("M19.4 15a1.7", meals_item)  # the cog's outline


if __name__ == "__main__":
    unittest.main()
