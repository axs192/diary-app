"""Helpers for tests that need a synced family calendar."""

import datetime
import http
import pathlib
import sqlite3
import tempfile
import unittest

import pydantic
from fastapi import testclient

from diary_app import app as diary_app
from diary_app import calendar_sync, config, db, outlook, people
from tests.graph_fake import FakeGraph, StaticToken, graph_event

NOW = datetime.datetime(2030, 1, 8, 12, 0)  # a Tuesday
CALENDAR_ID = "cal"


def all_day(
    event_id: str, title: str, day: int, span: int = 1, note: str | None = None
) -> dict[str, object]:
    """An all-day Graph event starting on 2030-01-<day> for ``span`` days."""
    return graph_event(
        event_id,
        title,
        f"2030-01-{day:02d}T00:00:00",
        f"2030-01-{day + span:02d}T00:00:00",
        all_day=True,
        note=note,
    )


def timed(  # noqa: PLR0913, PLR0917 (a test helper; reads best as is)
    event_id: str,
    title: str,
    day: int,
    start: str,
    end: str,
    note: str | None = None,
) -> dict[str, object]:
    """A timed Graph event on 2030-01-<day>, e.g. ``start="17:00"``."""
    return graph_event(
        event_id,
        title,
        f"2030-01-{day:02d}T{start}:00",
        f"2030-01-{day:02d}T{end}:00",
        note=note,
    )


def sync_events(
    conn: sqlite3.Connection, events: list[dict[str, object]]
) -> FakeGraph:
    """Syncs ``events`` into ``conn`` through a fake Graph and ticks it.

    Returns:
        The fake, so a test can change the events and sync again.
    """
    graph = FakeGraph(
        calendars={CALENDAR_ID: "Family"}, events={CALENDAR_ID: events}
    )
    client = outlook.GraphClient(
        StaticToken(), graph.client(), sleep=lambda _s: None
    )
    calendar_sync.sync(conn, client, NOW)
    calendar_sync.set_selected(conn, [CALENDAR_ID])
    calendar_sync.sync(conn, client, NOW)
    return graph


PIN = "4321"
_SESSION_SECRET = "calendar-support-session-secret-0123456789"  # noqa: S105


class AppTestCase(unittest.TestCase):
    """A logged-in app on a temporary database, wired to a fake Graph.

    Today is ``NOW``'s date (Tuesday 8 January 2030). The family is empty
    until a test adds people; ``sync`` copies events in through the fake.
    """

    def setUp(self) -> None:
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.database = pathlib.Path(tmp.name) / "diary.db"
        self.graph = FakeGraph(
            calendars={CALENDAR_ID: "Family"}, events={CALENDAR_ID: []}
        )
        client = outlook.GraphClient(
            StaticToken(), self.graph.client(), sleep=lambda _s: None
        )
        settings = config.Settings(
            household_pin=pydantic.SecretStr(PIN),
            session_secret=pydantic.SecretStr(_SESSION_SECRET),
            database_path=self.database,
        )
        self.app = diary_app.create_app(settings, graph=client, today=NOW.date)
        self.client = testclient.TestClient(self.app, follow_redirects=False)
        response = self.client.post("/login", data={"pin": PIN})
        if response.status_code != http.HTTPStatus.SEE_OTHER:
            msg = f"Login failed: {response.status_code}"
            raise AssertionError(msg)

    def add_person(self, name: str, role: str, colour: str = "#24508F") -> None:
        response = self.client.post(
            "/settings/people",
            data={"name": name, "role": role, "colour": colour},
        )
        self.assertEqual(response.status_code, 303, response.text)

    def sync(self, events: list[dict[str, object]]) -> None:
        """Replaces the fake calendar's events and syncs them in."""
        self.graph.events[CALENDAR_ID] = events
        self.assertEqual(
            self.client.post("/settings/calendar/sync").status_code, 303
        )
        self.client.post(
            "/settings/calendars", data={"calendar": [CALENDAR_ID]}
        )
        self.assertEqual(
            self.client.post("/settings/calendar/sync").status_code, 303
        )

    def page(self, path: str) -> str:
        response = self.client.get(path)
        self.assertEqual(response.status_code, 200, response.text)
        return str(response.text)

    def connection(self) -> sqlite3.Connection:
        conn = db.connect(self.database)
        self.addCleanup(conn.close)
        return conn

    def everyone(self) -> list[people.Person]:
        return people.list_people(self.connection())
