"""Tests for the settings the background jobs read (no credentials)."""

import os
import pathlib
import unittest
from unittest import mock

from diary_app import config


class JobSettingsTest(unittest.TestCase):
    """The sync job runs without the household PIN or session secret."""

    def load(self, env: dict[str, str] | None = None) -> config.JobSettings:
        with mock.patch.dict(os.environ, env or {}, clear=True):
            return config.JobSettings()

    def test_needs_no_credentials(self) -> None:
        settings = self.load()
        self.assertEqual(settings.ms_client_id, "")
        self.assertEqual(settings.timezone, "Europe/London")

    def test_reads_the_outlook_settings_from_the_environment(self) -> None:
        settings = self.load(
            {
                "MS_CLIENT_ID": "abc-123",
                "OUTLOOK_TOKEN_PATH": "/var/lib/diary-app/outlook_token.json",
                "TIMEZONE": "Europe/Dublin",
                "DATABASE_PATH": "/var/lib/diary-app/diary.db",
            }
        )
        self.assertEqual(settings.ms_client_id, "abc-123")
        self.assertEqual(
            settings.outlook_token_path,
            pathlib.Path("/var/lib/diary-app/outlook_token.json"),
        )
        self.assertEqual(settings.timezone, "Europe/Dublin")
        self.assertEqual(
            settings.database_path, pathlib.Path("/var/lib/diary-app/diary.db")
        )

    def test_the_web_settings_include_them_too(self) -> None:
        with mock.patch.dict(
            os.environ,
            {
                "HOUSEHOLD_PIN": "1234",
                "SESSION_SECRET": "x" * 16,
                "MS_CLIENT_ID": "abc-123",
            },
            clear=True,
        ):
            settings = config.Settings()
        self.assertEqual(settings.ms_client_id, "abc-123")


if __name__ == "__main__":
    unittest.main()
