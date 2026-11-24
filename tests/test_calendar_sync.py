"""Tests for reading the Outlook calendar into the diary and back out."""

import datetime
import sqlite3
import unittest

from diary_app import calendar_sync, db, outlook, people
from tests.graph_fake import (
    FakeGraph,
    SignedOutToken,
    StaticToken,
    graph_event,
)

_NOW = datetime.datetime(2030, 1, 8, 12, 0)  # a Tuesday
_MONDAY = datetime.date(2030, 1, 7)


def _swimming() -> dict[str, object]:
    return graph_event(
        "swim",
        "Mum : Swimming",
        "2030-01-08T17:00:00",
        "2030-01-08T18:00:00",
    )


class _DbTestCase(unittest.TestCase):
    """An in-memory database with a family in it."""

    def setUp(self) -> None:
        self.conn = db.connect(":memory:")
        self.addCleanup(self.conn.close)
        self.mum = people.add_person(self.conn, "Mum", "Adult", "#B04A17")
        self.ben = people.add_person(self.conn, "Ben", "Child", "#24508F")

    def family(self) -> people.Person:
        """The built-in Family person."""
        return next(
            p for p in people.list_people(self.conn) if p.role == "Everyone"
        )


class ParseTitleTest(_DbTestCase):
    """``<Name> : <what>`` says who an event is for."""

    def parse(self, raw: str) -> calendar_sync.ParsedTitle:
        return calendar_sync.parse_title(raw, people.list_people(self.conn))

    def test_a_family_members_name_before_the_colon_is_the_person(self) -> None:
        parsed = self.parse("Mum : Swimming")
        self.assertEqual(parsed.person, self.mum)
        self.assertEqual(parsed.title, "Swimming")
        self.assertEqual(parsed.kind, "")
        self.assertFalse(parsed.needs_name)

    def test_spaces_and_case_around_the_colon_do_not_matter(self) -> None:
        for raw in ("mum:Swimming", "  MUM  :  Swimming  ", "Mum: Swimming"):
            parsed = self.parse(raw)
            self.assertEqual(parsed.person, self.mum, raw)
            self.assertEqual(parsed.title, "Swimming", raw)

    def test_family_counts_as_a_person(self) -> None:
        parsed = self.parse("Family : Dinner out")
        self.assertEqual(parsed.person, self.family())
        self.assertEqual(parsed.kind, "")
        self.assertFalse(parsed.needs_name)

    def test_another_prefix_is_a_kind_for_the_family(self) -> None:
        parsed = self.parse("Birthday : Nan")
        self.assertEqual(parsed.person, self.family())
        self.assertEqual(parsed.kind, "Birthday")
        self.assertEqual(parsed.title, "Nan")
        self.assertFalse(parsed.needs_name)

    def test_no_colon_needs_a_name(self) -> None:
        parsed = self.parse("Dentist")
        self.assertEqual(parsed.person, self.family())
        self.assertEqual(parsed.title, "Dentist")
        self.assertTrue(parsed.needs_name)

    def test_empty_parts_need_a_name(self) -> None:
        for raw in (": Swimming", "Mum :", "Mum :  ", "", ":"):
            self.assertTrue(self.parse(raw).needs_name, raw)

    def test_only_the_first_colon_splits(self) -> None:
        parsed = self.parse("Ben : Lunch at 12:30")
        self.assertEqual(parsed.person, self.ben)
        self.assertEqual(parsed.title, "Lunch at 12:30")

    def test_renaming_a_person_changes_who_events_belong_to(self) -> None:
        people.update_person(
            self.conn,
            self.mum.id,
            name="Mummy",
            colour=self.mum.colour,
            outlook_category="",
        )
        self.assertEqual(self.parse("Mummy : Swimming").person.name, "Mummy")
        self.assertEqual(self.parse("Mum : Swimming").kind, "Mum")


class _SyncTestCase(_DbTestCase):
    """A fake Graph with one family calendar, wired to a real client."""

    def setUp(self) -> None:
        super().setUp()
        self.graph = FakeGraph(
            calendars={"cal": "Family", "hols": "UK Holidays"},
            events={"cal": [_swimming()], "hols": []},
        )
        self.client = outlook.GraphClient(
            StaticToken(), self.graph.client(), sleep=lambda _s: None
        )

    def sync(self, now: datetime.datetime = _NOW) -> calendar_sync.SyncResult:
        return calendar_sync.sync(self.conn, self.client, now)

    def week(self) -> dict[datetime.date, list[calendar_sync.Event]]:
        return calendar_sync.events_by_day(self.conn, _MONDAY)

    def choose(self, *ids: str) -> None:
        self.sync()  # learn the calendars first, as the real app does
        calendar_sync.set_selected(self.conn, ids)


class CalendarChoiceTest(_SyncTestCase):
    """Which of the account's calendars the diary shows."""

    def test_sync_learns_the_calendars_but_shows_none_by_default(self) -> None:
        result = self.sync()
        self.assertTrue(result.ok)
        self.assertEqual(
            [
                (c.name, c.selected)
                for c in calendar_sync.list_calendars(self.conn)
            ],
            [("Family", False), ("UK Holidays", False)],
        )
        self.assertEqual(self.graph.calendar_view_calls(), [])
        self.assertEqual(sum(len(v) for v in self.week().values()), 0)

    def test_only_chosen_calendars_are_read(self) -> None:
        self.choose("cal")
        self.sync()
        paths = {r.url.path for r in self.graph.calendar_view_calls()}
        self.assertEqual(paths, {"/v1.0/me/calendars/cal/calendarView"})

    def test_choosing_again_replaces_the_choice(self) -> None:
        self.choose("cal")
        calendar_sync.set_selected(self.conn, ["hols"])
        self.assertEqual(
            [
                c.id
                for c in calendar_sync.list_calendars(self.conn)
                if c.selected
            ],
            ["hols"],
        )

    def test_unchosen_calendars_events_disappear(self) -> None:
        self.choose("cal")
        self.sync()
        calendar_sync.set_selected(self.conn, [])
        self.sync()
        self.assertEqual(sum(len(v) for v in self.week().values()), 0)

    def test_a_calendar_that_goes_away_is_forgotten(self) -> None:
        self.choose("cal")
        del self.graph.calendars["cal"]
        self.sync()
        self.assertEqual(
            [c.id for c in calendar_sync.list_calendars(self.conn)], ["hols"]
        )


class SyncStorageTest(_SyncTestCase):
    """What a sync stores, and that repeating it changes nothing."""

    def test_events_are_stored_with_who_they_are_for(self) -> None:
        self.choose("cal")
        self.assertTrue(self.sync().ok)
        tuesday = self.week()[datetime.date(2030, 1, 8)]
        self.assertEqual(len(tuesday), 1)
        event = tuesday[0]
        self.assertEqual(event.title, "Swimming")
        self.assertEqual(event.person, self.mum)
        self.assertEqual(event.calendar, "Family")
        self.assertEqual(event.start, datetime.datetime(2030, 1, 8, 17))
        self.assertEqual(event.end, datetime.datetime(2030, 1, 8, 18))
        self.assertFalse(event.all_day)

    def test_syncing_twice_gives_the_same_events(self) -> None:
        self.choose("cal")
        self.sync()
        first = self.week()
        self.sync()
        self.assertEqual(self.week(), first)
        count = self.conn.execute("SELECT COUNT(*) FROM event").fetchone()[0]
        self.assertEqual(count, 1)

    def test_the_result_counts_events(self) -> None:
        self.choose("cal")
        self.assertEqual(self.sync().events, 1)

    def test_a_changed_event_is_updated(self) -> None:
        self.choose("cal")
        self.sync()
        self.graph.events["cal"][0]["subject"] = "Mum : Gym"
        self.sync()
        self.assertEqual(self.week()[datetime.date(2030, 1, 8)][0].title, "Gym")

    def test_an_event_deleted_in_outlook_disappears(self) -> None:
        self.choose("cal")
        self.sync()
        self.graph.events["cal"].clear()
        self.sync()
        self.assertEqual(sum(len(v) for v in self.week().values()), 0)

    def test_recurring_occurrences_are_separate_events(self) -> None:
        self.graph.events["cal"] = [
            graph_event(
                f"club-{day}",
                "Ben : Club",
                f"2030-01-{day:02d}T16:00:00",
                f"2030-01-{day:02d}T17:00:00",
            )
            for day in (8, 15)
        ]
        self.choose("cal")
        self.sync()
        count = self.conn.execute("SELECT COUNT(*) FROM event").fetchone()[0]
        self.assertEqual(count, 2)

    def test_old_events_are_pruned(self) -> None:
        self.graph.events["cal"].append(
            graph_event(
                "old", "Mum : Old", "2029-06-01T09:00:00", "2029-06-01T10:00:00"
            )
        )
        self.choose("cal")
        self.sync()
        self.conn.execute(
            "INSERT INTO event (calendar_id, id, title, starts_at, ends_at,"
            " all_day) VALUES ('cal', 'ancient', 'x', '2029-06-01T09:00:00',"
            " '2029-06-01T10:00:00', 0)"
        )
        self.sync()
        ids = [r[0] for r in self.conn.execute("SELECT id FROM event")]
        self.assertEqual(ids, ["swim"])

    def test_events_beyond_the_window_are_not_fetched(self) -> None:
        self.graph.events["cal"].append(
            graph_event(
                "far", "Mum : Far", "2030-09-01T09:00:00", "2030-09-01T10:00:00"
            )
        )
        self.choose("cal")
        self.sync()
        ids = [r[0] for r in self.conn.execute("SELECT id FROM event")]
        self.assertEqual(ids, ["swim"])


class WeekViewTest(_SyncTestCase):
    """Placing events on the days of a week."""

    def add(self, *events: dict[str, object]) -> None:
        self.graph.events["cal"] = list(events)
        self.choose("cal")
        self.sync()

    def test_the_week_has_seven_days_even_when_empty(self) -> None:
        self.assertEqual(
            list(self.week()),
            [_MONDAY + datetime.timedelta(d) for d in range(7)],
        )

    def test_all_day_events_come_before_timed_ones(self) -> None:
        self.add(
            graph_event(
                "late",
                "Mum : Late",
                "2030-01-08T19:00:00",
                "2030-01-08T20:00:00",
            ),
            graph_event(
                "early",
                "Ben : Early",
                "2030-01-08T08:00:00",
                "2030-01-08T09:00:00",
            ),
            graph_event(
                "all",
                "Birthday : Nan",
                "2030-01-08T00:00:00",
                "2030-01-09T00:00:00",
                all_day=True,
            ),
        )
        self.assertEqual(
            [e.id for e in self.week()[datetime.date(2030, 1, 8)]],
            ["all", "early", "late"],
        )

    def test_a_one_day_all_day_event_stays_on_its_own_day(self) -> None:
        self.add(
            graph_event(
                "all",
                "Birthday : Nan",
                "2030-01-08T00:00:00",
                "2030-01-09T00:00:00",
                all_day=True,
            )
        )
        week = self.week()
        self.assertEqual(len(week[datetime.date(2030, 1, 8)]), 1)
        self.assertEqual(week[datetime.date(2030, 1, 9)], [])

    def test_a_multi_day_event_shows_on_every_day(self) -> None:
        self.add(
            graph_event(
                "trip",
                "Family : Cornwall",
                "2030-01-09T00:00:00",
                "2030-01-12T00:00:00",
                all_day=True,
            )
        )
        week = self.week()
        shown = [d.day for d, events in week.items() if events]
        self.assertEqual(shown, [9, 10, 11])

    def test_an_event_past_midnight_shows_on_both_days(self) -> None:
        self.add(
            graph_event(
                "party",
                "Ben : Party",
                "2030-01-08T22:00:00",
                "2030-01-09T01:00:00",
            )
        )
        week = self.week()
        self.assertEqual(len(week[datetime.date(2030, 1, 8)]), 1)
        self.assertEqual(len(week[datetime.date(2030, 1, 9)]), 1)

    def test_events_outside_the_week_are_left_out(self) -> None:
        self.add(
            graph_event(
                "next",
                "Mum : Next",
                "2030-01-14T09:00:00",
                "2030-01-14T10:00:00",
            )
        )
        self.assertEqual(sum(len(v) for v in self.week().values()), 0)
        later = calendar_sync.events_by_day(
            self.conn, datetime.date(2030, 1, 14)
        )
        self.assertEqual(len(later[datetime.date(2030, 1, 14)]), 1)

    def test_untitled_by_convention_is_flagged(self) -> None:
        self.add(
            graph_event(
                "dentist",
                "Dentist",
                "2030-01-08T09:00:00",
                "2030-01-08T10:00:00",
            )
        )
        event = self.week()[datetime.date(2030, 1, 8)][0]
        self.assertTrue(event.needs_name)
        self.assertEqual(event.person, self.family())

    def test_renaming_a_person_applies_without_another_sync(self) -> None:
        self.add(_swimming())
        people.update_person(
            self.conn,
            self.mum.id,
            name="Mummy",
            colour=self.mum.colour,
            outlook_category="",
        )
        event = self.week()[datetime.date(2030, 1, 8)][0]
        self.assertEqual(event.kind, "Mum")
        self.assertEqual(event.person, self.family())


class StatusTest(_SyncTestCase):
    """What the pages say about the last sync."""

    def test_before_any_sync(self) -> None:
        status = calendar_sync.status(self.conn)
        self.assertIsNone(status.synced_at)
        self.assertEqual(status.error, "")
        self.assertFalse(status.needs_sign_in)

    def test_a_good_sync_records_when(self) -> None:
        self.sync()
        status = calendar_sync.status(self.conn)
        self.assertEqual(status.synced_at, _NOW)
        self.assertEqual(status.error, "")

    def test_a_failed_sync_keeps_events_and_says_why(self) -> None:
        self.choose("cal")
        self.sync()
        self.graph.failures = [503, 503, 503]
        later = _NOW + datetime.timedelta(minutes=15)
        result = self.sync(later)
        self.assertFalse(result.ok)
        self.assertNotEqual(result.error, "")
        status = calendar_sync.status(self.conn)
        self.assertEqual(status.synced_at, _NOW)  # the last good one
        self.assertEqual(status.error, result.error)
        self.assertEqual(len(self.week()[datetime.date(2030, 1, 8)]), 1)

    def test_a_good_sync_clears_an_earlier_error(self) -> None:
        self.graph.failures = [503, 503, 503]
        self.sync()
        self.assertTrue(self.sync().ok)
        self.assertEqual(calendar_sync.status(self.conn).error, "")

    def test_a_lost_sign_in_is_reported_separately(self) -> None:
        client = outlook.GraphClient(SignedOutToken(), self.graph.client())
        result = calendar_sync.sync(self.conn, client, _NOW)
        self.assertFalse(result.ok)
        self.assertTrue(calendar_sync.status(self.conn).needs_sign_in)
        self.sync()
        self.assertFalse(calendar_sync.status(self.conn).needs_sign_in)

    def test_a_failed_fetch_of_one_calendar_changes_nothing(self) -> None:
        self.choose("cal", "hols")
        self.sync()
        del self.graph.events["hols"]  # now a 404
        self.graph.events["cal"].clear()
        self.assertFalse(self.sync().ok)
        self.assertEqual(len(self.week()[datetime.date(2030, 1, 8)]), 1)


class MigrationTest(unittest.TestCase):
    """The calendar tables exist on a fresh database."""

    def test_tables_exist(self) -> None:
        conn: sqlite3.Connection = db.connect(":memory:")
        self.addCleanup(conn.close)
        names = {
            r[0]
            for r in conn.execute(
                "SELECT name FROM sqlite_master WHERE type = 'table'"
            )
        }
        self.assertLessEqual({"calendar_source", "event"}, names)


if __name__ == "__main__":
    unittest.main()
