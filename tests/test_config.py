"""Tests for Settings reading systemd credentials from a directory."""

import os
import pathlib
import tempfile
import unittest
from unittest import mock

import pydantic

from diary_app import config

_SECRET = "from-credentials-dir"  # noqa: S105  # dummy test value


class CredentialsDirectoryTest(unittest.TestCase):
    """Settings reads $CREDENTIALS_DIRECTORY, where systemd exposes secrets."""

    def test_api_key_is_read_from_credentials_directory(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            (pathlib.Path(tmp) / "api_key").write_text(_SECRET)
            env = {"CREDENTIALS_DIRECTORY": tmp}
            with mock.patch.dict(os.environ, env, clear=True):
                settings = config.Settings()
        self.assertEqual(settings.api_key.get_secret_value(), _SECRET)

    def test_environment_variable_wins_over_credentials_directory(
        self,
    ) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            (pathlib.Path(tmp) / "api_key").write_text(_SECRET)
            env = {"CREDENTIALS_DIRECTORY": tmp, "API_KEY": "from-env"}
            with mock.patch.dict(os.environ, env, clear=True):
                settings = config.Settings()
        self.assertEqual(settings.api_key.get_secret_value(), "from-env")

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
