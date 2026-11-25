"""Tests for the day-by-day schedule: events plus where each adult is."""

import datetime
import unittest

from diary_app import calendar_sync, db, outlook, people, schedule
from tests.graph_fake import FakeGraph, StaticToken, graph_event

_MONDAY = datetime.date(2030, 1, 7)
_NOW = datetime.datetime(2030, 1, 8, 12, 0)


def _all_day(
    event_id: str, title: str, day: int, span: int = 1
) -> dict[str, object]:
    """An all-day event starting on 2030-01-<day> for ``span`` days."""
    return graph_event(
        event_id,
        title,
        f"2030-01-{day:02d}T00:00:00",
        f"2030-01-{day + span:02d}T00:00:00",
        all_day=True,
    )


class _ScheduleTestCase(unittest.TestCase):
    """A family (two adults, a child) and a fake calendar to sync."""

    def setUp(self) -> None:
        self.conn = db.connect(":memory:")
        self.addCleanup(self.conn.close)
        self.alex = people.add_person(self.conn, "Alex", "Adult", "#B04A17")
        self.cindy = people.add_person(self.conn, "Cindy", "Adult", "#24508F")
        self.sam = people.add_person(self.conn, "Sam", "Child", "#5B2E86")

    def sync(self, events: list[dict[str, object]]) -> None:
        graph = FakeGraph(calendars={"cal": "Family"}, events={"cal": events})
        client = outlook.GraphClient(
            StaticToken(), graph.client(), sleep=lambda _s: None
        )
        calendar_sync.sync(self.conn, client, _NOW)
        calendar_sync.set_selected(self.conn, ["cal"])
        calendar_sync.sync(self.conn, client, _NOW)

    def day(self, day: int) -> schedule.Day:
        found = schedule.by_day(self.conn, _MONDAY)
        return next(d for d in found if d.date.day == day)

    def places(self, day: int) -> dict[str, str]:
        return {w.person.name: w.place for w in self.day(day).where}


class WhereTest(_ScheduleTestCase):
    """The bracketed place in a title says where an adult is."""

    def test_a_marker_names_the_place(self) -> None:
        self.sync([_all_day("m", "Alex : [London]", 8)])
        self.assertEqual(self.places(8), {"Alex": "London", "Cindy": "WFH"})

    def test_a_weekday_with_no_marker_is_wfh(self) -> None:
        self.sync([_all_day("m", "Alex : [London]", 8)])
        self.assertEqual(self.places(9), {"Alex": "WFH", "Cindy": "WFH"})

    def test_weekends_say_nothing_unless_marked(self) -> None:
        self.sync([_all_day("m", "Cindy : [Leeds]", 12)])  # Saturday
        self.assertEqual(self.places(12), {"Cindy": "Leeds"})
        self.assertEqual(self.places(13), {})

    def test_a_multi_day_marker_covers_each_day(self) -> None:
        self.sync([_all_day("m", "Alex : [Paris]", 9, span=3)])
        for day in (9, 10, 11):
            self.assertEqual(self.places(day)["Alex"], "Paris", day)
        self.assertEqual(self.places(8)["Alex"], "WFH")
        self.assertNotIn("Alex", self.places(12))  # Saturday, unmarked

    def test_off_and_any_other_word_work(self) -> None:
        self.sync(
            [
                _all_day("a", "Alex : [Off]", 8),
                _all_day("b", "Cindy : [wfh]", 9),
            ]
        )
        self.assertEqual(self.places(8)["Alex"], "Off")
        self.assertEqual(self.places(9)["Cindy"], "wfh")

    def test_the_place_keeps_its_spelling_and_inner_spaces(self) -> None:
        self.sync([_all_day("a", "alex:[ King's Cross ]", 8)])
        self.assertEqual(self.places(8)["Alex"], "King's Cross")

    def test_a_timed_marker_counts_too(self) -> None:
        self.sync(
            [
                graph_event(
                    "t",
                    "Alex : [London]",
                    "2030-01-08T09:00:00",
                    "2030-01-08T17:00:00",
                )
            ]
        )
        self.assertEqual(self.places(8)["Alex"], "London")

    def test_the_first_marker_wins(self) -> None:
        self.sync(
            [
                graph_event(
                    "late",
                    "Alex : [Leeds]",
                    "2030-01-08T13:00:00",
                    "2030-01-08T17:00:00",
                ),
                graph_event(
                    "early",
                    "Alex : [London]",
                    "2030-01-08T09:00:00",
                    "2030-01-08T12:00:00",
                ),
            ]
        )
        self.assertEqual(self.places(8)["Alex"], "London")

    def test_only_adults_have_a_place(self) -> None:
        self.sync([_all_day("m", "Sam : [School trip]", 8)])
        self.assertNotIn("Sam", self.places(8))
        self.assertNotIn("Family", self.places(8))

    def test_where_follows_the_order_people_were_added(self) -> None:
        self.sync([_all_day("m", "Cindy : [London]", 8)])
        names = [w.person.name for w in self.day(8).where]
        self.assertEqual(names, ["Alex", "Cindy"])

    def test_no_adults_means_no_where_line(self) -> None:
        people.delete_person(self.conn, self.alex.id)
        people.delete_person(self.conn, self.cindy.id)
        self.sync([_all_day("m", "Alex : [London]", 8)])
        self.assertEqual(self.day(8).where, [])


class NotSyncedTest(_ScheduleTestCase):
    """Without a calendar we know nothing, so we do not claim WFH."""

    def test_no_where_line_before_the_first_sync(self) -> None:
        for day in schedule.by_day(self.conn, _MONDAY):
            self.assertEqual(day.where, [], day.date)

    def test_the_days_are_still_returned(self) -> None:
        found = schedule.by_day(self.conn, _MONDAY, count=3)
        self.assertEqual(
            [d.date for d in found],
            [_MONDAY + datetime.timedelta(days=n) for n in range(3)],
        )


class EventsTest(_ScheduleTestCase):
    """Markers are not events; everything else is."""

    def test_markers_are_not_listed_as_events(self) -> None:
        self.sync(
            [
                _all_day("m", "Alex : [London]", 8),
                graph_event(
                    "s",
                    "Sam : Swimming",
                    "2030-01-08T17:00:00",
                    "2030-01-08T18:00:00",
                ),
            ]
        )
        self.assertEqual([e.title for e in self.day(8).events], ["Swimming"])

    def test_a_marker_on_a_child_is_shown_as_an_ordinary_event(self) -> None:
        self.sync([_all_day("m", "Sam : [School trip]", 8)])
        self.assertEqual(
            [e.title for e in self.day(8).events], ["[School trip]"]
        )

    def test_a_title_with_more_than_the_bracket_is_an_ordinary_event(
        self,
    ) -> None:
        self.sync([_all_day("m", "Alex : [London] meeting", 8)])
        self.assertEqual(
            [e.title for e in self.day(8).events], ["[London] meeting"]
        )
        self.assertEqual(self.places(8)["Alex"], "WFH")

    def test_a_bracket_with_nothing_in_it_is_not_a_marker(self) -> None:
        self.sync([_all_day("m", "Alex : []", 8)])
        self.assertEqual(self.places(8)["Alex"], "WFH")

    def test_events_keep_calendar_sync_order(self) -> None:
        self.sync(
            [
                graph_event(
                    "b", "Sam : B", "2030-01-08T10:00:00", "2030-01-08T11:00:00"
                ),
                _all_day("a", "Sam : A", 8),
            ]
        )
        self.assertEqual([e.title for e in self.day(8).events], ["A", "B"])

    def test_it_is_always_the_days_asked_for(self) -> None:
        found = schedule.by_day(self.conn, _MONDAY, count=10)
        self.assertEqual(len(found), 10)
        self.assertIsInstance(found[0].events, list)


if __name__ == "__main__":
    unittest.main()
