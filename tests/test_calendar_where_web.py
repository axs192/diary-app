"""Tests for the Where line and event links on the Calendar week."""

import re
import unittest

from tests import calendar_support as cal


class _WeekTestCase(cal.AppTestCase):
    def setUp(self) -> None:
        super().setUp()
        self.add_person("Alex", "Adult", "#B04A17")
        self.add_person("Cindy", "Adult", "#24508F")
        self.add_person("Sam", "Child", "#5B2E86")

    def card(self, day: int) -> str:
        html = self.page("/calendar")
        found = re.search(
            rf'<article class="cal-day[^"]*" id="day-2030-01-{day:02d}"'
            r".*?</article>",
            html,
            re.DOTALL,
        )
        self.assertIsNotNone(found, f"no card for {day}")
        return found.group(0) if found else ""


class WhereRowTest(_WeekTestCase):
    def test_weekday_cards_show_where_each_adult_is(self) -> None:
        self.sync([cal.all_day("m", "Alex : [London]", 8)])
        card = self.card(8)
        self.assertRegex(card, r"Alex\s+London")
        self.assertRegex(card, r"Cindy\s+WFH")

    def test_a_marker_is_not_listed_as_an_event(self) -> None:
        self.sync([cal.all_day("m", "Alex : [London]", 8)])
        self.assertNotIn("[London]", self.card(8))
        self.assertNotIn('class="cal-event"', self.card(8))

    def test_weekends_show_no_line_unless_marked(self) -> None:
        self.sync([cal.all_day("m", "Cindy : [Leeds]", 12)])
        self.assertRegex(self.card(12), r"Cindy\s+Leeds")
        self.assertNotIn("WFH", self.card(13))

    def test_nothing_is_claimed_before_the_first_sync(self) -> None:
        self.assertNotIn("WFH", self.card(8))

    def test_a_marker_for_a_child_stays_visible_as_an_event(self) -> None:
        self.sync([cal.all_day("m", "Sam : [Trip]", 8)])
        self.assertIn("[Trip]", self.card(8))


class EventLinksTest(_WeekTestCase):
    def test_events_link_to_their_page_from_the_calendar(self) -> None:
        self.sync([cal.timed("swim", "Sam : Swimming", 8, "17:00", "18:00")])
        self.assertIn('href="/event?id=swim&amp;from=calendar"', self.card(8))


if __name__ == "__main__":
    unittest.main()
