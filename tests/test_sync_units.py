"""Guards the systemd timer that keeps the calendar copy fresh."""

import pathlib
import re
import unittest

_DEPLOY = pathlib.Path(__file__).parent.parent / "deploy"


class SyncServiceTest(unittest.TestCase):
    """The sync runs as the app user, with no credentials of its own."""

    def setUp(self) -> None:
        self.unit = (_DEPLOY / "diary-sync.service").read_text()

    def test_it_runs_once_as_the_app_user(self) -> None:
        self.assertIn("Type=oneshot", self.unit)
        self.assertIn("User=diary", self.unit)

    def test_it_runs_the_sync_command_from_the_checkout_venv(self) -> None:
        self.assertIn(
            "ExecStart=/opt/diary-app/.venv/bin/diary-app sync-calendar",
            self.unit,
        )

    def test_it_shares_the_apps_settings_and_state_folder(self) -> None:
        self.assertIn("EnvironmentFile=/etc/diary-app/diary-app.env", self.unit)
        self.assertIn("StateDirectory=diary-app", self.unit)
        self.assertIn("StateDirectoryMode=0700", self.unit)

    def test_it_needs_no_encrypted_credentials(self) -> None:
        self.assertNotIn("LoadCredential", self.unit)

    def test_hardening_is_kept(self) -> None:
        self.assertIn("ProtectSystem=strict", self.unit)
        self.assertIn("NoNewPrivileges=true", self.unit)


class SyncTimerTest(unittest.TestCase):
    """The timer fires soon after boot, then every 15 minutes."""

    def setUp(self) -> None:
        self.timer = (_DEPLOY / "diary-sync.timer").read_text()

    def test_it_starts_the_sync_service(self) -> None:
        self.assertIn("Unit=diary-sync.service", self.timer)

    def test_it_runs_after_boot_and_every_fifteen_minutes(self) -> None:
        self.assertIn("OnBootSec=2min", self.timer)
        self.assertIn("OnUnitActiveSec=15min", self.timer)

    def test_it_is_enabled_with_the_other_timers(self) -> None:
        self.assertIn("WantedBy=timers.target", self.timer)


class EnvTemplateTest(unittest.TestCase):
    """The public env template names the Outlook settings but not the id."""

    def setUp(self) -> None:
        self.template = (_DEPLOY / "diary-app.env.example").read_text()

    def test_the_client_id_is_left_blank(self) -> None:
        self.assertRegex(self.template, r"(?m)^MS_CLIENT_ID=$")

    def test_the_token_lives_in_the_state_folder(self) -> None:
        self.assertIn(
            "OUTLOOK_TOKEN_PATH=/var/lib/diary-app/outlook_token.json",
            self.template,
        )

    def test_the_time_zone_is_named(self) -> None:
        self.assertRegex(self.template, r"(?m)^TIMEZONE=\S+")

    def test_no_application_id_is_committed(self) -> None:
        guid = r"[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}"
        self.assertIsNone(re.search(guid, self.template, re.IGNORECASE))


if __name__ == "__main__":
    unittest.main()
