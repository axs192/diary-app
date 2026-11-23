"""Tests for the diary_app public interface: Settings and create_app."""

import os
import pathlib
import unittest
from unittest import mock

import pydantic
from fastapi import testclient

from diary_app import app as diary_app
from diary_app import config

_PIN = "4321"
_SESSION_SECRET = "session-secret-that-must-never-leak-0123456789"  # noqa: S105
_SECRETS = (_PIN, _SESSION_SECRET)


def _settings() -> config.Settings:
    return config.Settings(
        household_pin=pydantic.SecretStr(_PIN),
        session_secret=pydantic.SecretStr(_SESSION_SECRET),
        database_path=pathlib.Path(":memory:"),
    )


def _make_client() -> testclient.TestClient:
    return testclient.TestClient(diary_app.create_app(_settings()))


def _make_logged_in_client() -> testclient.TestClient:
    client = _make_client()
    client.post("/login", data={"pin": _PIN})
    return client


class SettingsTest(unittest.TestCase):
    """Settings loads credentials from the environment and fails fast."""

    def test_settings_reads_credentials_from_environment(self) -> None:
        env = {"HOUSEHOLD_PIN": _PIN, "SESSION_SECRET": _SESSION_SECRET}
        with mock.patch.dict(os.environ, env, clear=True):
            settings = config.Settings()
        self.assertEqual(settings.household_pin.get_secret_value(), _PIN)
        self.assertEqual(
            settings.session_secret.get_secret_value(), _SESSION_SECRET
        )

    def test_settings_missing_credentials_raises(self) -> None:
        with (
            mock.patch.dict(os.environ, {}, clear=True),
            self.assertRaises(pydantic.ValidationError),
        ):
            config.Settings()

    def test_settings_empty_pin_raises(self) -> None:
        env = {"HOUSEHOLD_PIN": "", "SESSION_SECRET": _SESSION_SECRET}
        with (
            mock.patch.dict(os.environ, env, clear=True),
            self.assertRaises(pydantic.ValidationError),
        ):
            config.Settings()

    def test_settings_repr_hides_credentials(self) -> None:
        text = repr(_settings())
        for secret in _SECRETS:
            self.assertNotIn(secret, text)


class AppTest(unittest.TestCase):
    """create_app serves the basic routes without leaking secrets."""

    def test_root_returns_hello_message(self) -> None:
        response = _make_client().get("/")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json(), {"message": "Hello from diary-app"})

    def test_health_returns_ok(self) -> None:
        response = _make_client().get("/health")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json(), {"status": "ok"})

    def test_config_check_reports_credentials_without_values(self) -> None:
        response = _make_client().get("/config-check")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(
            response.json(),
            {
                "household_pin_configured": True,
                "session_secret_configured": True,
            },
        )
        for secret in _SECRETS:
            self.assertNotIn(secret, response.text)

    def test_create_app_never_logs_credentials(self) -> None:
        with self.assertLogs("diary_app", level="INFO") as logs:
            client = testclient.TestClient(diary_app.create_app(_settings()))
            client.get("/config-check")
        for secret in _SECRETS:
            self.assertNotIn(secret, "\n".join(logs.output))


class HomePageTest(unittest.TestCase):
    """The /home page is HTML that an iPad can run as a full-screen app."""

    def test_home_returns_html(self) -> None:
        response = _make_logged_in_client().get("/home")
        self.assertEqual(response.status_code, 200)
        self.assertIn("text/html", response.headers["content-type"])

    def test_home_declares_ios_web_app_capable(self) -> None:
        html = _make_logged_in_client().get("/home").text
        self.assertIn(
            '<meta name="apple-mobile-web-app-capable" content="yes">', html
        )

    def test_home_sets_viewport_for_ipad(self) -> None:
        html = _make_logged_in_client().get("/home").text
        self.assertIn('name="viewport"', html)
        self.assertIn("width=device-width", html)

    def test_home_never_shows_credentials(self) -> None:
        html = _make_logged_in_client().get("/home").text
        for secret in _SECRETS:
            self.assertNotIn(secret, html)

    def test_home_uses_no_javascript(self) -> None:
        # Safari on iOS 9 (iPad mini 1st gen) predates modern JS features.
        html = _make_logged_in_client().get("/home").text
        self.assertNotIn("<script", html)


if __name__ == "__main__":
    unittest.main()
