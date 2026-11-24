"""Tests for the error-banner switch and the overlay/banner styles."""

import os
import pathlib
import re
import tempfile
import unittest
from unittest import mock

import pydantic
from fastapi import testclient

from diary_app import app as diary_app
from diary_app import config

_PIN = "4321"
_SESSION_SECRET = "banner-flag-test-secret-0123456789"  # noqa: S105


class _ClientTestCase(unittest.TestCase):
    def make_client(self, error_banner: bool = True) -> testclient.TestClient:
        """Builds an app on a temporary database and returns a client."""
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        settings = config.Settings(
            household_pin=pydantic.SecretStr(_PIN),
            session_secret=pydantic.SecretStr(_SESSION_SECRET),
            database_path=pathlib.Path(tmp.name) / "diary.db",
            error_banner=error_banner,
        )
        return testclient.TestClient(
            diary_app.create_app(settings), follow_redirects=False
        )


class ErrorBannerFlagTest(_ClientTestCase):
    def test_the_banner_is_on_by_default(self) -> None:
        self.assertTrue(
            config.Settings(
                household_pin=pydantic.SecretStr(_PIN),
                session_secret=pydantic.SecretStr(_SESSION_SECRET),
            ).error_banner
        )

    def test_the_environment_can_turn_it_off(self) -> None:
        env = {
            "HOUSEHOLD_PIN": _PIN,
            "SESSION_SECRET": _SESSION_SECRET,
            "ERROR_BANNER": "false",
        }
        with mock.patch.dict(os.environ, env):
            self.assertFalse(config.Settings().error_banner)

    def test_every_page_says_whether_the_banner_is_on(self) -> None:
        for value, expected in ((True, "on"), (False, "off")):
            client = self.make_client(error_banner=value)
            pages = [client.get("/login").text]
            client.post("/login", data={"pin": _PIN})
            pages += [
                client.get(p).text for p in ("/home", "/meals", "/settings")
            ]
            for html in pages:
                self.assertRegex(
                    html, rf'<body[^>]*data-error-banner="{expected}"'
                )


class OverlayStyleTest(_ClientTestCase):
    def setUp(self) -> None:
        self.css = self.make_client().get("/static/app.css").text

    def test_the_overlay_and_banner_are_styled(self) -> None:
        for selector in (".reconnecting", ".js-error", ".js-error-dismiss"):
            self.assertIn(selector, self.css)

    def test_the_overlay_covers_the_screen_above_the_menu(self) -> None:
        block = re.search(r"\.reconnecting\s*\{([^}]*)\}", self.css)
        assert block is not None
        self.assertIn("position: fixed", block.group(1))
        z = re.search(r"z-index:\s*(\d+)", block.group(1))
        assert z is not None
        self.assertGreater(int(z.group(1)), 10)  # the phone menu is 10

    def test_no_custom_properties_or_sticky(self) -> None:
        self.assertNotIn("var(--", self.css)
        self.assertNotRegex(self.css, r"position:\s*sticky")


if __name__ == "__main__":
    unittest.main()
