"""Guards the deployment files that keep secrets out of plain text."""

import pathlib
import unittest

_DEPLOY = pathlib.Path(__file__).parent.parent / "deploy"


class ServiceUnitTest(unittest.TestCase):
    """The systemd unit loads secrets as encrypted credentials."""

    def setUp(self) -> None:
        self.unit = (_DEPLOY / "diary-app.service").read_text()

    def test_secrets_are_loaded_as_encrypted_credentials(self) -> None:
        for name in ("household_pin", "session_secret"):
            self.assertIn(
                f"LoadCredentialEncrypted={name}:"
                f"/etc/diary-app/creds/{name}.cred",
                self.unit,
            )

    def test_retired_api_key_credential_is_not_loaded(self) -> None:
        self.assertNotIn("api_key", self.unit)

    def test_service_gets_a_private_writable_state_directory(self) -> None:
        self.assertIn("StateDirectory=diary-app", self.unit)
        self.assertIn("StateDirectoryMode=0700", self.unit)

    def test_hardening_is_kept(self) -> None:
        self.assertIn("ProtectSystem=strict", self.unit)
        self.assertIn("NoNewPrivileges=true", self.unit)


class EnvTemplateTest(unittest.TestCase):
    """The env template (committed to a public repo) holds no secrets."""

    def test_template_has_no_secrets(self) -> None:
        template = (_DEPLOY / "diary-app.env.example").read_text()
        uncommented = [
            line
            for line in template.splitlines()
            if line.strip() and not line.startswith("#")
        ]
        for secret in ("API_KEY", "HOUSEHOLD_PIN", "SESSION_SECRET"):
            self.assertFalse(
                [line for line in uncommented if line.startswith(secret)],
                secret,
            )


if __name__ == "__main__":
    unittest.main()
