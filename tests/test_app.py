"""Tests for the diary_app public interface: Settings and create_app."""

import os
import unittest
from unittest import mock

import pydantic
from fastapi import testclient

from diary_app import app as diary_app
from diary_app import config

_SECRET = "s3cret-value-that-must-never-leak"  # noqa: S105  # dummy test value


def _make_client() -> testclient.TestClient:
    settings = config.Settings(api_key=pydantic.SecretStr(_SECRET))
    return testclient.TestClient(diary_app.create_app(settings))


class SettingsTest(unittest.TestCase):
    """Settings loads credentials from the environment and fails fast."""

    def test_settings_reads_api_key_from_environment(self) -> None:
        with mock.patch.dict(os.environ, {"API_KEY": _SECRET}, clear=True):
            settings = config.Settings()
        self.assertEqual(settings.api_key.get_secret_value(), _SECRET)

    def test_settings_missing_api_key_raises(self) -> None:
        with (
            mock.patch.dict(os.environ, {}, clear=True),
            self.assertRaises(pydantic.ValidationError),
        ):
            config.Settings()

    def test_settings_empty_api_key_raises(self) -> None:
        with (
            mock.patch.dict(os.environ, {"API_KEY": ""}, clear=True),
            self.assertRaises(pydantic.ValidationError),
        ):
            config.Settings()

    def test_settings_repr_hides_api_key(self) -> None:
        settings = config.Settings(api_key=pydantic.SecretStr(_SECRET))
        self.assertNotIn(_SECRET, repr(settings))


class AppTest(unittest.TestCase):
    """create_app serves the hello-world routes without leaking secrets."""

    def test_root_returns_hello_message(self) -> None:
        response = _make_client().get("/")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json(), {"message": "Hello from diary-app"})

    def test_health_returns_ok(self) -> None:
        response = _make_client().get("/health")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json(), {"status": "ok"})

    def test_config_check_reports_key_configured_without_value(self) -> None:
        response = _make_client().get("/config-check")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json(), {"api_key_configured": True})
        self.assertNotIn(_SECRET, response.text)

    def test_create_app_never_logs_api_key(self) -> None:
        settings = config.Settings(api_key=pydantic.SecretStr(_SECRET))
        with self.assertLogs("diary_app", level="INFO") as logs:
            client = testclient.TestClient(diary_app.create_app(settings))
            client.get("/config-check")
        self.assertNotIn(_SECRET, "\n".join(logs.output))


if __name__ == "__main__":
    unittest.main()
