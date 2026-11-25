"""Tests for an event's note and for looking one event up."""

import datetime
import unittest

from diary_app import calendar_sync, db, outlook, people
from tests.graph_fake import FakeGraph, StaticToken, graph_event

_NOW = datetime.datetime(2030, 1, 8, 12, 0)
_START = datetime.datetime(2030, 1, 7)
_END = datetime.datetime(2030, 1, 21)


def _swim(note: str | None) -> dict[str, object]:
    return graph_event(
        "swim",
        "Sam : Swimming",
        "2030-01-08T17:00:00",
        "2030-01-08T18:00:00",
        note=note,
    )


class _Synced(unittest.TestCase):
    """A database synced from a fake Graph with one event."""

    note: str | None = "Bring a towel and goggles."

    def setUp(self) -> None:
        self.conn = db.connect(":memory:")
        self.addCleanup(self.conn.close)
        self.sam = people.add_person(self.conn, "Sam", "Child", "#24508F")
        self.graph = FakeGraph(
            calendars={"cal": "Family"}, events={"cal": [_swim(self.note)]}
        )
        self.client = outlook.GraphClient(
            StaticToken(), self.graph.client(), sleep=lambda _s: None
        )
        calendar_sync.sync(self.conn, self.client, _NOW)  # learns calendars
        calendar_sync.set_selected(self.conn, ["cal"])
        calendar_sync.sync(self.conn, self.client, _NOW)


class NoteFromGraphTest(_Synced):
    def test_the_graph_client_returns_the_note(self) -> None:
        events = self.client.events("cal", _START, _END)
        self.assertEqual(events[0].note, "Bring a towel and goggles.")

    def test_the_note_is_requested_from_graph(self) -> None:
        self.client.events("cal", _START, _END)
        selects = [
            r.url.params["$select"]
            for r in self.graph.requests
            if "$select" in r.url.params
        ]
        self.assertTrue(selects)
        self.assertIn("bodyPreview", selects[-1])


class NoteMissingTest(_Synced):
    note = None

    def test_no_note_reads_as_empty(self) -> None:
        events = self.client.events("cal", _START, _END)
        self.assertEqual(events[0].note, "")


class GetEventTest(_Synced):
    def test_get_event_returns_the_stored_event_with_its_note(self) -> None:
        event = calendar_sync.get_event(self.conn, "swim")
        self.assertIsNotNone(event)
        assert event is not None
        self.assertEqual(event.title, "Swimming")
        self.assertEqual(event.person, self.sam)
        self.assertEqual(event.note, "Bring a towel and goggles.")
        self.assertEqual(event.calendar, "Family")
        self.assertEqual(event.start, datetime.datetime(2030, 1, 8, 17))

    def test_an_unknown_id_gives_none(self) -> None:
        self.assertIsNone(calendar_sync.get_event(self.conn, "nope"))

    def test_events_by_day_carries_the_note_too(self) -> None:
        week = calendar_sync.events_by_day(self.conn, datetime.date(2030, 1, 7))
        found = week[datetime.date(2030, 1, 8)][0]
        self.assertEqual(found.note, "Bring a towel and goggles.")

    def test_the_event_is_gone_after_a_sync_that_no_longer_has_it(self) -> None:
        self.graph.events["cal"] = []
        calendar_sync.sync(self.conn, self.client, _NOW)
        self.assertIsNone(calendar_sync.get_event(self.conn, "swim"))


if __name__ == "__main__":
    unittest.main()
