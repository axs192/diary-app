"""Tests for the Today screen and its range setting."""

import re
import unittest

from fastapi import testclient

from diary_app import mealplan, recipes
from tests import calendar_support as cal
from tests import support

_SETTINGS_DEVICE = "/settings?section=device"
_TODAY = cal.NOW.date()


class _TodayPageTestCase(cal.AppTestCase):
    def setUp(self) -> None:
        super().setUp()
        self.add_person("Alex", "Adult", "#B04A17")
        self.add_person("Cindy", "Adult", "#24508F")
        self.add_person("Sam", "Child", "#5B2E86")

    def home(self) -> str:
        return self.page("/home")

    def section(self, html: str, label: str) -> str:
        found = re.search(
            rf'<section[^>]*aria-label="{label}".*?</section>',
            html,
            re.DOTALL,
        )
        self.assertIsNotNone(found, f"no section {label}")
        return found.group(0) if found else ""


class AccessTest(_TodayPageTestCase):
    def test_home_needs_the_pin(self) -> None:
        anonymous = testclient.TestClient(self.app, follow_redirects=False)
        self.assertEqual(anonymous.get("/home").status_code, 303)

    def test_range_route_needs_the_pin(self) -> None:
        anonymous = testclient.TestClient(self.app, follow_redirects=False)
        response = anonymous.post("/settings/today-range", data={"range": "7"})
        self.assertEqual(response.status_code, 303)
        self.assertEqual(response.headers["location"], "/login")


class HeaderTest(_TodayPageTestCase):
    def test_it_shows_todays_date_and_week_number(self) -> None:
        html = self.home()
        self.assertIn("Tuesday 8 January", html)
        self.assertIn("Week 2", html)

    def test_it_still_refreshes_itself_every_five_minutes(self) -> None:
        self.assertIn('<meta http-equiv="refresh" content="300"', self.home())

    def test_only_the_app_script_is_loaded(self) -> None:
        support.assert_only_app_script(self, self.home(), "/home")


class KidsDiaryTest(_TodayPageTestCase):
    def test_a_child_shows_today_and_tomorrow(self) -> None:
        self.sync(
            [
                cal.timed("a", "Sam : Swimming", 8, "17:00", "18:00"),
                cal.timed("b", "Sam : Football", 9, "16:00", "17:00"),
            ]
        )
        kids = self.section(self.home(), "Kids' diary")
        self.assertIn("Sam", kids)
        today_part, tomorrow_part = kids.split("Tomorrow", maxsplit=1)
        self.assertIn("Swimming", today_part)
        self.assertIn("5pm", today_part)
        self.assertIn("Football", tomorrow_part)
        self.assertNotIn("Swimming", tomorrow_part)

    def test_all_day_events_say_all_day(self) -> None:
        self.sync([cal.all_day("a", "Sam : Own clothes day", 9)])
        self.assertIn("All day", self.section(self.home(), "Kids' diary"))

    def test_an_empty_day_says_nothing_on(self) -> None:
        kids = self.section(self.home(), "Kids' diary")
        self.assertIn("Nothing on.", kids)

    def test_adults_are_not_in_the_kids_diary(self) -> None:
        self.sync([cal.timed("a", "Alex : Review", 8, "14:00", "15:00")])
        self.assertNotIn("Review", self.section(self.home(), "Kids' diary"))

    def test_no_children_points_at_settings(self) -> None:
        for person in self.everyone():
            if person.role == "Child":
                self.client.post(f"/settings/people/{person.id}/delete")
        kids = self.section(self.home(), "Kids' diary")
        self.assertIn("Settings", kids)
        self.assertIn('href="/settings?section=people"', kids)


class ComingUpTest(_TodayPageTestCase):
    def up(self) -> str:
        return self.section(self.home(), "Coming up")

    def test_it_lists_later_days_not_today(self) -> None:
        self.sync(
            [
                cal.timed("a", "Alex : Todays thing", 8, "10:00", "11:00"),
                cal.timed("b", "Alex : Team lunch", 9, "12:00", "13:00"),
                cal.timed("c", "Cindy : Gym", 11, "18:00", "19:00"),
            ]
        )
        up = self.up()
        self.assertIn("Team lunch", up)
        self.assertIn("Gym", up)
        self.assertNotIn("Todays thing", up)

    def test_each_event_names_who_it_is_for(self) -> None:
        self.sync([cal.timed("b", "Alex : Team lunch", 9, "12:00", "13:00")])
        self.assertRegex(self.up(), r"Team lunch(?s:.*?)Alex")

    def test_days_are_labelled_and_the_range_end_is_shown(self) -> None:
        up = self.up()
        self.assertIn("Tomorrow", up)
        self.assertIn("Wed 9", up)
        self.assertIn("Sun 13 Jan", up)
        self.assertNotIn("Mon 14", up)

    def test_where_each_adult_is_shows_for_each_day(self) -> None:
        self.sync([cal.all_day("m", "Alex : [London]", 10)])
        up = self.up()
        self.assertRegex(up, r"Alex\s+London")
        self.assertRegex(up, r"Cindy\s+WFH")
        self.assertNotIn("[London]", up)

    def test_no_where_line_before_the_first_sync(self) -> None:
        self.assertNotIn("WFH", self.up())

    def test_a_quiet_day_says_nothing_on(self) -> None:
        self.assertIn("Nothing on.", self.up())

    def test_titles_are_escaped(self) -> None:
        self.sync([cal.timed("x", "Alex : <b>Hi</b>", 9, "12:00", "13:00")])
        up = self.up()
        self.assertIn("&lt;b&gt;Hi&lt;/b&gt;", up)
        self.assertNotIn("<b>Hi</b>", up)


class EventLinksTest(_TodayPageTestCase):
    def test_events_link_to_their_page_and_remember_where_from(self) -> None:
        self.sync([cal.timed("swim", "Sam : Swimming", 8, "17:00", "18:00")])
        self.assertIn('href="/event?id=swim&amp;from=home"', self.home())

    def test_awkward_ids_are_encoded(self) -> None:
        self.sync([cal.timed("AAMk+x=/y&z", "Sam : Odd", 8, "17:00", "18:00")])
        html = self.home()
        self.assertIn("id=AAMk%2Bx%3D/y%26z&amp;from=home", html)
        response = self.client.get("/event?id=AAMk%2Bx%3D/y%26z&from=home")
        self.assertEqual(response.status_code, 200)
        self.assertIn("Odd", response.text)


class TonightTest(_TodayPageTestCase):
    def test_tonights_dinner_links_to_its_recipe(self) -> None:
        conn = self.connection()
        recipe = recipes.add(conn, recipes.RecipeDraft(name="Baked salmon"))
        mealplan.set_meal(conn, _TODAY, recipe.id)
        html = self.home()
        self.assertIn("Baked salmon", html)
        self.assertIn(f'href="/recipes/{recipe.id}"', html)

    def test_nothing_planned_says_so_and_links_to_meals(self) -> None:
        html = self.home()
        self.assertIn("No dinner planned", html)
        self.assertIn('href="/meals"', html)


class SyncStatusTest(_TodayPageTestCase):
    def test_before_a_sync_the_page_says_so(self) -> None:
        self.assertIn("Not synced yet", self.home())

    def test_after_a_sync_it_says_when(self) -> None:
        self.sync([])
        self.assertRegex(self.home(), r"Synced today \d\d:\d\d")

    def test_a_diary_without_outlook_says_so(self) -> None:
        self.app.state.graph = None
        self.assertIn("not connected", self.home().lower())


class RangeSettingTest(_TodayPageTestCase):
    def day_count(self) -> int:
        return len(re.findall(r'class="up-day', self.home()))

    def test_the_default_is_until_sunday(self) -> None:
        self.assertEqual(self.day_count(), 5)

    def test_choosing_fourteen_days_shows_fourteen(self) -> None:
        response = self.client.post(
            "/settings/today-range", data={"range": "14"}
        )
        self.assertEqual(response.status_code, 303)
        self.assertEqual(response.headers["location"], _SETTINGS_DEVICE)
        self.assertEqual(self.day_count(), 14)

    def test_an_unknown_range_is_refused(self) -> None:
        response = self.client.post(
            "/settings/today-range", data={"range": "30"}
        )
        self.assertEqual(response.status_code, 400)
        self.assertEqual(self.day_count(), 5)

    def test_settings_offers_the_three_ranges_with_the_current_ticked(
        self,
    ) -> None:
        self.client.post("/settings/today-range", data={"range": "7"})
        html = self.page(_SETTINGS_DEVICE)
        for value in ("sunday", "7", "14"):
            self.assertRegex(html, rf'name="range" value="{value}"')
        self.assertRegex(html, r'name="range" value="7"\s+checked')
        self.assertNotRegex(html, r'name="range" value="14"\s+checked')


if __name__ == "__main__":
    unittest.main()
