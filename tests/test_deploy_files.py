"""Guards the deployment files that keep secrets out of plain text."""

import pathlib
import unittest

_DEPLOY = pathlib.Path(__file__).parent.parent / "deploy"


class ServiceUnitTest(unittest.TestCase):
    """The systemd unit loads secrets as encrypted credentials."""

    def setUp(self) -> None:
        self.unit = (_DEPLOY / "diary-app.service").read_text()

    def test_api_key_is_loaded_as_an_encrypted_credential(self) -> None:
        self.assertIn(
            "LoadCredentialEncrypted=api_key:/etc/diary-app/creds/api_key.cred",
            self.unit,
        )

    def test_service_gets_a_private_writable_state_directory(self) -> None:
        self.assertIn("StateDirectory=diary-app", self.unit)
        self.assertIn("StateDirectoryMode=0700", self.unit)

    def test_hardening_is_kept(self) -> None:
        self.assertIn("ProtectSystem=strict", self.unit)
        self.assertIn("NoNewPrivileges=true", self.unit)


class EnvTemplateTest(unittest.TestCase):
    """The env template (committed to a public repo) holds no secrets."""

    def test_template_has_no_api_key(self) -> None:
        template = (_DEPLOY / "diary-app.env.example").read_text()
        uncommented = [
            line
            for line in template.splitlines()
            if line.strip() and not line.startswith("#")
        ]
        self.assertFalse(
            [line for line in uncommented if line.startswith("API_KEY")]
        )


if __name__ == "__main__":
    unittest.main()
