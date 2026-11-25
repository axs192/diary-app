"""Tests for how browsers are told to cache the static files.

A phone kept an old app.css after a deploy and drew the new Today page with
none of its styles, so the stylesheet and script must be re-checked on every
load (a cheap "not modified" answer when nothing changed). Fonts never
change, so they stay cached.
"""

import pathlib
import tempfile
import unittest

import pydantic
from fastapi import testclient

from diary_app import app as diary_app
from diary_app import config


class StaticCacheTest(unittest.TestCase):
    def setUp(self) -> None:
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        settings = config.Settings(
            household_pin=pydantic.SecretStr("4321"),
            session_secret=pydantic.SecretStr("static-cache-secret-0123456789"),
            database_path=pathlib.Path(tmp.name) / "diary.db",
        )
        self.client = testclient.TestClient(diary_app.create_app(settings))

    def test_the_stylesheet_and_script_must_be_revalidated(self) -> None:
        for path in ("/static/app.css", "/static/app.js"):
            response = self.client.get(path)
            self.assertEqual(response.status_code, 200, path)
            self.assertIn("no-cache", response.headers["cache-control"], path)

    def test_an_unchanged_file_answers_304_with_the_same_rule(self) -> None:
        first = self.client.get("/static/app.css")
        again = self.client.get(
            "/static/app.css", headers={"If-None-Match": first.headers["etag"]}
        )
        self.assertEqual(again.status_code, 304)
        self.assertIn("no-cache", again.headers["cache-control"])

    def test_fonts_are_not_forced_to_revalidate(self) -> None:
        fonts = sorted(
            p.name
            for p in (
                pathlib.Path(diary_app.__file__).parent / "web/static/fonts"
            ).iterdir()
        )
        response = self.client.get(f"/static/fonts/{fonts[0]}")
        self.assertEqual(response.status_code, 200)
        self.assertNotIn("no-cache", response.headers.get("cache-control", ""))


if __name__ == "__main__":
    unittest.main()
