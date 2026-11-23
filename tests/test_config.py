"""Tests for Settings reading systemd credentials from a directory."""

import os
import pathlib
import tempfile
import unittest
from unittest import mock

import pydantic

from diary_app import config

_PIN = "from-credentials-dir"
_SESSION = "session-secret-from-credentials-dir"  # dummy value


def _write_credentials(directory: str) -> None:
    folder = pathlib.Path(directory)
    (folder / "household_pin").write_text(_PIN)
    (folder / "session_secret").write_text(_SESSION)


class CredentialsDirectoryTest(unittest.TestCase):
    """Settings reads $CREDENTIALS_DIRECTORY, where systemd exposes secrets."""

    def test_credentials_are_read_from_credentials_directory(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            _write_credentials(tmp)
            env = {"CREDENTIALS_DIRECTORY": tmp}
            with mock.patch.dict(os.environ, env, clear=True):
                settings = config.Settings()
        self.assertEqual(settings.household_pin.get_secret_value(), _PIN)
        self.assertEqual(settings.session_secret.get_secret_value(), _SESSION)

    def test_environment_variable_wins_over_credentials_directory(
        self,
    ) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            _write_credentials(tmp)
            env = {"CREDENTIALS_DIRECTORY": tmp, "HOUSEHOLD_PIN": "from-env"}
            with mock.patch.dict(os.environ, env, clear=True):
                settings = config.Settings()
        self.assertEqual(settings.household_pin.get_secret_value(), "from-env")

    def test_empty_credentials_directory_still_fails_fast(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            env = {"CREDENTIALS_DIRECTORY": tmp}
            with (
                mock.patch.dict(os.environ, env, clear=True),
                self.assertRaises(pydantic.ValidationError),
            ):
                config.Settings()


if __name__ == "__main__":
    unittest.main()
