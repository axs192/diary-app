"""Tests for the ``diary-app`` command (sign-in and the calendar sync job)."""

import contextlib
import datetime
import io
import os
import pathlib
import tempfile
import unittest
from unittest import mock

from diary_app import calendar_sync, cli, db, outlook
from tests.graph_fake import FakeGraph, SignedOutToken, StaticToken, graph_event


class _CliTestCase(unittest.TestCase):
    def setUp(self) -> None:
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.db_path = pathlib.Path(tmp.name) / "diary.db"
        self.env = {
            "DATABASE_PATH": str(self.db_path),
            "OUTLOOK_TOKEN_PATH": str(pathlib.Path(tmp.name) / "token.json"),
            "MS_CLIENT_ID": "client-id",
        }

    def run_cli(
        self,
        *argv: str,
        client: outlook.GraphClient | None = None,
        now: datetime.datetime | None = None,
        **env: str,
    ) -> tuple[int, str]:
        out = io.StringIO()
        with (
            mock.patch.dict(os.environ, {**self.env, **env}, clear=True),
            contextlib.redirect_stdout(out),
            contextlib.redirect_stderr(out),
        ):
            code = cli.main(list(argv), client=client, now=now)
        return code, out.getvalue()


class SyncCalendarTest(_CliTestCase):
    """``diary-app sync-calendar`` is what the timer runs."""

    def graph(self) -> tuple[FakeGraph, outlook.GraphClient]:
        graph = FakeGraph(
            calendars={"cal": "Family"},
            events={
                "cal": [
                    graph_event(
                        "e1",
                        "Mum : Swimming",
                        "2030-01-08T17:00:00",
                        "2030-01-08T18:00:00",
                    )
                ]
            },
        )
        client = outlook.GraphClient(
            StaticToken(), graph.client(), sleep=lambda _s: None
        )
        return graph, client

    def test_without_an_app_id_it_explains_and_fails(self) -> None:
        code, text = self.run_cli("sync-calendar", MS_CLIENT_ID="")
        self.assertEqual(code, 2)
        self.assertIn("MS_CLIENT_ID", text)

    def test_a_good_sync_succeeds_and_stores_events(self) -> None:
        _, client = self.graph()
        now = datetime.datetime(2030, 1, 8, 12)
        self.assertEqual(
            self.run_cli("sync-calendar", client=client, now=now)[0], 0
        )
        conn = db.connect(self.db_path)
        self.addCleanup(conn.close)
        self.assertEqual(
            [c.name for c in calendar_sync.list_calendars(conn)], ["Family"]
        )
        calendar_sync.set_selected(conn, ["cal"])
        self.assertEqual(
            self.run_cli("sync-calendar", client=client, now=now)[0], 0
        )
        week = calendar_sync.events_by_day(conn, datetime.date(2030, 1, 7))
        titles = [e.title for e in week[datetime.date(2030, 1, 8)]]
        self.assertEqual(titles, ["Swimming"])

    def test_a_failed_sync_exits_non_zero_and_says_why(self) -> None:
        graph, _ = self.graph()
        client = outlook.GraphClient(SignedOutToken(), graph.client())
        code, text = self.run_cli("sync-calendar", client=client)
        self.assertEqual(code, 1)
        self.assertIn("sign", text.lower())
        self.assertNotIn("Swimming", text)


class LoginTest(_CliTestCase):
    """``diary-app login-outlook`` needs the app id to start."""

    def test_without_an_app_id_it_explains_and_fails(self) -> None:
        code, text = self.run_cli("login-outlook", MS_CLIENT_ID="")
        self.assertEqual(code, 2)
        self.assertIn("MS_CLIENT_ID", text)


if __name__ == "__main__":
    unittest.main()
