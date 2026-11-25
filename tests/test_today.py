"""Tests for the Today view: kids' diary, coming up, tonight."""

import datetime
import unittest

from diary_app import db, mealplan, people, recipes, today
from diary_app.calendar_sync import Event
from tests import calendar_support as cal

_TUE = datetime.date(2030, 1, 8)
_SAT = datetime.date(2030, 1, 12)
_SUN = datetime.date(2030, 1, 13)


class _TodayTestCase(unittest.TestCase):
    def setUp(self) -> None:
        self.conn = db.connect(":memory:")
        self.addCleanup(self.conn.close)
        self.alex = people.add_person(self.conn, "Alex", "Adult", "#B04A17")
        self.sam = people.add_person(self.conn, "Sam", "Child", "#24508F")
        self.kim = people.add_person(self.conn, "Kim", "Child", "#5B2E86")

    def view(self, day: datetime.date = _TUE) -> today.TodayView:
        return today.view(self.conn, day)

    def titles(self, events: list[Event]) -> list[str]:
        return [e.title for e in events]


class KidsTest(_TodayTestCase):
    def test_each_child_gets_today_and_tomorrow(self) -> None:
        cal.sync_events(
            self.conn,
            [
                cal.timed("a", "Sam : Swimming", 8, "17:00", "18:00"),
                cal.timed("b", "Sam : Football", 9, "16:00", "17:00"),
                cal.timed("c", "Kim : Piano", 9, "15:00", "16:00"),
            ],
        )
        sam, kim = self.view().kids
        self.assertEqual(sam.person, self.sam)
        self.assertEqual(self.titles(sam.today), ["Swimming"])
        self.assertEqual(self.titles(sam.tomorrow), ["Football"])
        self.assertEqual(kim.person, self.kim)
        self.assertEqual(kim.today, [])
        self.assertEqual(self.titles(kim.tomorrow), ["Piano"])

    def test_all_day_comes_first(self) -> None:
        cal.sync_events(
            self.conn,
            [
                cal.timed("a", "Sam : School", 9, "08:45", "15:15"),
                cal.all_day("b", "Sam : Own clothes day", 9),
            ],
        )
        self.assertEqual(
            self.titles(self.view().kids[0].tomorrow),
            ["Own clothes day", "School"],
        )

    def test_adults_and_family_events_are_not_a_childs(self) -> None:
        cal.sync_events(
            self.conn,
            [
                cal.timed("a", "Alex : Review", 8, "14:00", "15:00"),
                cal.all_day("b", "Birthday : Nan", 8),
                cal.timed("c", "Dentist", 8, "09:00", "10:00"),
            ],
        )
        for kid in self.view().kids:
            self.assertEqual((kid.today, kid.tomorrow), ([], []))

    def test_only_children_are_listed(self) -> None:
        self.assertEqual(
            [k.person.name for k in self.view().kids], ["Sam", "Kim"]
        )

    def test_no_children_gives_an_empty_list(self) -> None:
        people.delete_person(self.conn, self.sam.id)
        people.delete_person(self.conn, self.kim.id)
        self.assertEqual(self.view().kids, [])

    def test_a_multi_day_event_shows_on_both_days(self) -> None:
        cal.sync_events(self.conn, [cal.all_day("a", "Sam : Camp", 8, span=2)])
        sam = self.view().kids[0]
        self.assertEqual(self.titles(sam.today), ["Camp"])
        self.assertEqual(self.titles(sam.tomorrow), ["Camp"])


class RangeTest(_TodayTestCase):
    def days(self, day: datetime.date = _TUE) -> list[datetime.date]:
        return [d.date for d in self.view(day).coming_up]

    def test_the_default_is_until_sunday(self) -> None:
        self.assertEqual(today.get_range(self.conn), "sunday")
        self.assertEqual(
            self.days(),
            [_TUE + datetime.timedelta(days=n) for n in range(1, 6)],
        )
        self.assertEqual(self.view().until, _SUN)

    def test_until_sunday_on_a_saturday_is_just_sunday(self) -> None:
        self.assertEqual(self.days(_SAT), [_SUN])

    def test_until_sunday_on_a_sunday_runs_to_next_sunday(self) -> None:
        found = self.days(_SUN)
        self.assertEqual(len(found), 7)
        self.assertEqual(found[-1], _SUN + datetime.timedelta(days=7))
        self.assertEqual(self.view(_SUN).until, found[-1])

    def test_seven_days_starts_tomorrow(self) -> None:
        today.set_range(self.conn, "7")
        found = self.days()
        self.assertEqual(len(found), 7)
        self.assertEqual(found[0], _TUE + datetime.timedelta(days=1))
        self.assertEqual(self.view().until, _TUE + datetime.timedelta(days=7))

    def test_fourteen_days(self) -> None:
        today.set_range(self.conn, "14")
        self.assertEqual(len(self.days()), 14)

    def test_the_choice_is_saved(self) -> None:
        today.set_range(self.conn, "14")
        self.assertEqual(today.get_range(self.conn), "14")

    def test_an_unknown_range_is_rejected_and_nothing_changes(self) -> None:
        today.set_range(self.conn, "7")
        with self.assertRaises(ValueError):
            today.set_range(self.conn, "30")
        self.assertEqual(today.get_range(self.conn), "7")

    def test_a_damaged_saved_value_falls_back_to_sunday(self) -> None:
        db.set_setting(self.conn, "today_range", "banana")
        self.assertEqual(today.get_range(self.conn), "sunday")

    def test_coming_up_has_events_and_where_for_each_day(self) -> None:
        cal.sync_events(
            self.conn,
            [
                cal.timed("a", "Sam : Football", 9, "16:00", "17:00"),
                cal.all_day("b", "Alex : [London]", 10),
            ],
        )
        wed, thu = self.view().coming_up[0], self.view().coming_up[1]
        self.assertEqual(self.titles(wed.events), ["Football"])
        self.assertEqual(
            [(w.person.name, w.place) for w in thu.where], [("Alex", "London")]
        )


class TonightTest(_TodayTestCase):
    def test_tonight_is_todays_planned_dinner(self) -> None:
        recipe = recipes.add(
            self.conn, recipes.RecipeDraft(name="Baked salmon")
        )
        mealplan.set_meal(self.conn, _TUE, recipe.id)
        mealplan.set_meal(
            self.conn, _TUE + datetime.timedelta(days=1), recipe.id
        )
        tonight = self.view().tonight
        self.assertIsNotNone(tonight)
        self.assertEqual(tonight.name if tonight else "", "Baked salmon")

    def test_nothing_planned_gives_none(self) -> None:
        self.assertIsNone(self.view().tonight)

    def test_only_today_counts(self) -> None:
        recipe = recipes.add(self.conn, recipes.RecipeDraft(name="Soup"))
        mealplan.set_meal(
            self.conn, _TUE + datetime.timedelta(days=1), recipe.id
        )
        self.assertIsNone(self.view().tonight)


if __name__ == "__main__":
    unittest.main()
