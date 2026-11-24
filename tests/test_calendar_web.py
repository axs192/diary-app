"""Tests for the Calendar page and the calendar section of Settings."""

import datetime
import pathlib
import re
import tempfile
import unittest

import fastapi
import pydantic
from fastapi import testclient

from diary_app import app as diary_app
from diary_app import config, outlook
from tests import support
from tests.graph_fake import (
    FakeGraph,
    SignedOutToken,
    StaticToken,
    graph_event,
)

_PIN = "4321"
_SESSION_SECRET = "calendar-test-session-secret-0123456789"  # noqa: S105
_TODAY = datetime.date(2030, 1, 8)  # a Tuesday
_MONDAY = datetime.date(2030, 1, 7)
_SETTINGS_CALENDAR = "/settings?section=calendar"
_MUM_BLUE = "#24508F"


def _events() -> list[dict[str, object]]:
    return [
        graph_event(
            "swim",
            "Mum : Swimming",
            "2030-01-08T17:00:00",
            "2030-01-08T18:00:00",
        ),
        graph_event(
            "bday",
            "Birthday : Nan",
            "2030-01-09T00:00:00",
            "2030-01-10T00:00:00",
            all_day=True,
        ),
        graph_event(
            "dentist",
            "Dentist",
            "2030-01-10T09:30:00",
            "2030-01-10T10:00:00",
        ),
        graph_event(
            "next",
            "Mum : Next week thing",
            "2030-01-15T09:00:00",
            "2030-01-15T10:00:00",
        ),
    ]


class _CalendarTestCase(unittest.TestCase):
    """An app on a temporary database wired to a fake Microsoft Graph."""

    def setUp(self) -> None:
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.graph = FakeGraph(
            calendars={"cal": "Family", "hols": "UK Holidays"},
            events={"cal": _events(), "hols": []},
        )
        self.app = self.make_app(
            tmp.name,
            outlook.GraphClient(
                StaticToken(), self.graph.client(), sleep=lambda _s: None
            ),
        )
        self.client = testclient.TestClient(self.app, follow_redirects=False)

    def make_app(
        self, folder: str, graph: outlook.GraphClient | None
    ) -> fastapi.FastAPI:
        settings = config.Settings(
            household_pin=pydantic.SecretStr(_PIN),
            session_secret=pydantic.SecretStr(_SESSION_SECRET),
            database_path=pathlib.Path(folder) / "diary.db",
        )
        return diary_app.create_app(settings, graph=graph, today=lambda: _TODAY)

    def log_in(self) -> None:
        response = self.client.post("/login", data={"pin": _PIN})
        self.assertEqual(response.status_code, 303)

    def add_mum(self) -> None:
        response = self.client.post(
            "/settings/people",
            data={"name": "Mum", "role": "Adult", "colour": _MUM_BLUE},
        )
        self.assertEqual(response.status_code, 303, response.text)

    def sync_now(self) -> None:
        response = self.client.post("/settings/calendar/sync")
        self.assertEqual(response.status_code, 303, response.text)

    def show_family_calendar(self) -> None:
        """Learns the calendars, ticks the family one, and syncs it."""
        self.sync_now()
        response = self.client.post(
            "/settings/calendars", data={"calendar": ["cal"]}
        )
        self.assertEqual(response.status_code, 303, response.text)
        self.sync_now()

    def page(self, week: str = "") -> str:
        url = f"/calendar?week={week}" if week else "/calendar"
        response = self.client.get(url)
        self.assertEqual(response.status_code, 200, response.text)
        return str(response.text)

    def day_card(self, html: str, day: datetime.date) -> str:
        found = re.search(
            rf'<article class="cal-day[^"]*" id="day-{day.isoformat()}"'
            r".*?</article>",
            html,
            re.DOTALL,
        )
        self.assertIsNotNone(found, f"no card for {day}")
        return found.group(0) if found else ""


class AccessTest(_CalendarTestCase):
    """Everything about the calendar needs the household PIN."""

    def test_calendar_routes_require_login(self) -> None:
        self.assertEqual(self.client.get("/calendar").status_code, 303)
        for path in ("/settings/calendar/sync", "/settings/calendars"):
            response = self.client.post(path, data={})
            self.assertEqual(response.status_code, 303, path)
            self.assertEqual(response.headers["location"], "/login", path)

    def test_the_menu_has_a_calendar_tab(self) -> None:
        self.log_in()
        html = self.client.get("/home").text
        self.assertIn('href="/calendar"', html)


class WeekPageTest(_CalendarTestCase):
    """The week view."""

    def setUp(self) -> None:
        super().setUp()
        self.log_in()
        self.add_mum()
        self.show_family_calendar()

    def test_shows_the_week_with_seven_days(self) -> None:
        html = self.page(_MONDAY.isoformat())
        self.assertIn("Week of 7 January", html)
        for offset in range(7):
            self.day_card(html, _MONDAY + datetime.timedelta(days=offset))

    def test_this_week_is_the_default(self) -> None:
        self.assertIn("Week of 7 January", self.page())

    def test_any_day_shows_its_week(self) -> None:
        self.assertIn("Week of 7 January", self.page("2030-01-10"))

    def test_nonsense_falls_back_to_this_week(self) -> None:
        self.assertIn("Week of 7 January", self.page("not-a-date"))

    def test_an_event_shows_its_time_person_and_title(self) -> None:
        card = self.day_card(self.page(), _TODAY)
        self.assertIn("Swimming", card)
        self.assertNotIn("Mum :", card)
        self.assertIn("5pm", card)
        self.assertIn(">Mum<", card)
        self.assertIn(_MUM_BLUE, card)

    def test_a_kind_shows_as_a_tag_for_the_family(self) -> None:
        card = self.day_card(self.page(), datetime.date(2030, 1, 9))
        self.assertIn("Birthday", card)
        self.assertIn("Nan", card)
        self.assertIn("All day", card)
        self.assertIn(">Family<", card)

    def test_other_weeks_events_are_not_shown(self) -> None:
        self.assertNotIn("Next week thing", self.page())
        self.assertIn("Next week thing", self.page("2030-01-14"))

    def test_week_links_step_by_seven_days(self) -> None:
        html = self.page(_MONDAY.isoformat())
        self.assertIn('href="/calendar?week=2029-12-31"', html)
        self.assertIn('href="/calendar?week=2030-01-14"', html)
        self.assertIn('href="/calendar"', html)

    def test_today_is_marked(self) -> None:
        self.assertIn("cal-today", self.day_card(self.page(), _TODAY))
        self.assertNotIn("cal-today", self.day_card(self.page(), _MONDAY))

    def test_titles_are_escaped(self) -> None:
        self.graph.events["cal"].append(
            graph_event(
                "x",
                "Mum : <b>bold</b>",
                "2030-01-11T09:00:00",
                "2030-01-11T10:00:00",
            )
        )
        self.sync_now()
        html = self.page()
        self.assertNotIn("<b>bold</b>", html)
        self.assertIn("&lt;b&gt;bold&lt;/b&gt;", html)


class NeedsNameTest(_CalendarTestCase):
    """Events that break the ``Name : title`` convention are listed."""

    def setUp(self) -> None:
        super().setUp()
        self.log_in()
        self.add_mum()
        self.show_family_calendar()

    def test_lists_events_without_a_name(self) -> None:
        html = self.page()
        section = html.split('id="needs-name"', 1)[1].split("</details>")[0]
        listed = re.findall(r"<li>(.*?)</li>", section)
        self.assertEqual(listed, ["Thu 10 Jan: Dentist"])

    def test_absent_when_every_event_has_a_name(self) -> None:
        self.graph.events["cal"] = [
            e for e in _events() if e["id"] != "dentist"
        ]
        self.sync_now()
        self.assertNotIn('id="needs-name"', self.page())

    def test_only_this_weeks_events_are_listed(self) -> None:
        self.graph.events["cal"].append(
            graph_event(
                "late", "Plumber", "2030-01-15T09:00:00", "2030-01-15T10:00:00"
            )
        )
        self.sync_now()
        self.assertNotIn("Plumber", self.page())


class StatusLineTest(_CalendarTestCase):
    """The page says whether the calendar is connected and fresh."""

    def setUp(self) -> None:
        super().setUp()
        self.log_in()

    def test_not_connected_without_an_outlook_client(self) -> None:
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        client = testclient.TestClient(
            self.make_app(tmp.name, None), follow_redirects=False
        )
        client.post("/login", data={"pin": _PIN})
        html = client.get("/calendar").text
        self.assertIn("not connected", html.lower())
        self.assertIn("/settings?section=calendar", html)

    def test_connected_but_nothing_chosen_points_to_settings(self) -> None:
        html = self.page()
        self.assertIn("Not synced yet", html)

    def test_after_a_sync_it_says_when(self) -> None:
        self.show_family_calendar()
        self.assertRegex(self.page(), r"Synced (today )?\d{1,2}:\d{2}")

    def test_a_failed_sync_shows_the_reason(self) -> None:
        self.show_family_calendar()
        self.graph.failures = [503, 503, 503]
        self.sync_now()
        html = self.page()
        self.assertIn("Microsoft answered with an error (503)", html)
        self.assertIn("Swimming", html)  # the last good copy still shows

    def test_a_lost_sign_in_says_how_to_fix_it(self) -> None:
        self.show_family_calendar()
        client = outlook.GraphClient(SignedOutToken(), self.graph.client())
        self.app.state.graph = client
        self.sync_now()
        html = self.page()
        self.assertIn("signing in again", html)
        self.assertIn("diary-app login-outlook", html)


class SettingsSectionTest(_CalendarTestCase):
    """Choosing calendars and syncing from Settings."""

    def setUp(self) -> None:
        super().setUp()
        self.log_in()

    def section(self) -> str:
        html = str(self.client.get(_SETTINGS_CALENDAR).text)
        return html.split('id="section-calendar"', 1)[1].split(
            "</details>", maxsplit=1
        )[0]

    def test_the_section_is_open_when_asked(self) -> None:
        html = self.client.get(_SETTINGS_CALENDAR).text
        self.assertRegex(html, r'id="section-calendar"\s+open')

    def test_before_the_first_sync_it_says_to_sync(self) -> None:
        self.assertIn("Sync now", self.section())
        self.assertNotIn('name="calendar"', self.section())

    def test_sync_now_lists_the_calendars_to_choose_from(self) -> None:
        self.sync_now()
        section = self.section()
        self.assertIn("Family", section)
        self.assertIn("UK Holidays", section)
        self.assertNotIn("checked", section)

    def test_ticking_a_calendar_shows_it_and_unticking_hides_it(self) -> None:
        self.add_mum()
        self.show_family_calendar()
        self.assertRegex(
            self.section(), r'value="cal"[^>]*checked|checked[^>]*value="cal"'
        )
        self.assertIn("Swimming", self.page())
        self.client.post("/settings/calendars", data={})
        self.assertNotIn("Swimming", self.page())

    def test_the_sync_window_shows_its_defaults(self) -> None:
        section = self.section()
        self.assertRegex(section, r'name="weeks_back"[^>]*value="1"')
        self.assertRegex(section, r'name="weeks_ahead"[^>]*value="2"')

    def test_saving_the_sync_window_keeps_it(self) -> None:
        response = self.client.post(
            "/settings/calendar/window",
            data={"weeks_back": "2", "weeks_ahead": "4"},
        )
        self.assertEqual(response.status_code, 303)
        self.assertEqual(response.headers["location"], _SETTINGS_CALENDAR)
        section = self.section()
        self.assertRegex(section, r'name="weeks_back"[^>]*value="2"')
        self.assertRegex(section, r'name="weeks_ahead"[^>]*value="4"')

    def test_a_longer_window_is_used_by_the_next_sync(self) -> None:
        self.graph.events["cal"].append(
            graph_event(
                "far",
                "Mum : Far",
                "2030-01-22T09:00:00",
                "2030-01-22T10:00:00",
            )
        )
        self.show_family_calendar()
        self.assertNotIn("Far", self.page("2030-01-21"))
        self.client.post(
            "/settings/calendar/window",
            data={"weeks_back": "1", "weeks_ahead": "4"},
        )
        self.sync_now()
        self.assertIn("Far", self.page("2030-01-21"))

    def test_a_bad_sync_window_is_refused_and_not_saved(self) -> None:
        for back, ahead in (("1", "0"), ("x", "2"), ("", ""), ("9", "2")):
            response = self.client.post(
                "/settings/calendar/window",
                data={"weeks_back": back, "weeks_ahead": ahead},
            )
            self.assertEqual(response.status_code, 400, (back, ahead))
        self.assertRegex(self.section(), r'name="weeks_ahead"[^>]*value="2"')

    def test_the_title_convention_is_explained(self) -> None:
        self.assertIn("Mum : Swimming", self.section())

    def test_sync_now_returns_to_the_section(self) -> None:
        response = self.client.post("/settings/calendar/sync")
        self.assertEqual(response.headers["location"], _SETTINGS_CALENDAR)

    def test_a_failed_sync_now_is_shown_in_the_section(self) -> None:
        self.graph.failures = [503, 503, 503]
        self.sync_now()
        self.assertIn("Microsoft answered with an error (503)", self.section())

    def test_without_outlook_configured_it_says_so(self) -> None:
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        client = testclient.TestClient(
            self.make_app(tmp.name, None), follow_redirects=False
        )
        client.post("/login", data={"pin": _PIN})
        html = client.get(_SETTINGS_CALENDAR).text
        self.assertIn("MS_CLIENT_ID", html)
        response = client.post("/settings/calendar/sync")
        self.assertEqual(response.status_code, 400)

    def test_unknown_calendar_ids_are_ignored(self) -> None:
        self.sync_now()
        response = self.client.post(
            "/settings/calendars", data={"calendar": ["nope"]}
        )
        self.assertEqual(response.status_code, 303)


class OutlookNameDropdownTest(_CalendarTestCase):
    """Settings offers the words seen before the colon as each person's name."""

    def person_select(self, html: str, name: str) -> str:
        found = re.search(
            r'action="/settings/people/\d+"(?:(?!</form>).)*?'
            rf"Save {name}</button>",
            html,
            re.DOTALL,
        )
        self.assertIsNotNone(found, f"no form for {name}")
        form = found.group(0) if found else ""
        chosen = re.search(
            r'<select[^>]*name="outlook_category"[^>]*>.*?</select>',
            form,
            re.DOTALL,
        )
        self.assertIsNotNone(chosen, f"no dropdown for {name}")
        return chosen.group(0) if chosen else ""

    def options(self, select: str) -> list[str]:
        return re.findall(r'<option value="([^"]*)"', select)

    def settings_html(self) -> str:
        return str(self.client.get("/settings?section=people").text)

    def setUp(self) -> None:
        super().setUp()
        self.log_in()
        self.add_mum()

    def test_before_a_sync_the_only_choice_is_the_persons_own_name(
        self,
    ) -> None:
        select = self.person_select(self.settings_html(), "Mum")
        self.assertEqual(self.options(select), [""])

    def test_it_offers_the_words_found_in_the_calendar(self) -> None:
        self.show_family_calendar()
        select = self.person_select(self.settings_html(), "Mum")
        self.assertEqual(self.options(select), ["", "Birthday", "Mum"])

    def test_adding_a_person_offers_them_too(self) -> None:
        self.show_family_calendar()
        html = self.settings_html()
        add = html.split('action="/settings/people"', maxsplit=1)[1]
        self.assertIn('<option value="Birthday"', add)

    def test_a_chosen_word_is_selected_and_kept_even_if_not_seen(self) -> None:
        self.show_family_calendar()
        mum_id = re.search(
            r'action="/settings/people/(\d+)"(?:(?!</form>).)*?Save Mum',
            self.settings_html(),
            re.DOTALL,
        )
        assert mum_id is not None
        response = self.client.post(
            f"/settings/people/{mum_id.group(1)}",
            data={
                "name": "Mum",
                "colour": _MUM_BLUE,
                "outlook_category": "Mummy",
            },
        )
        self.assertEqual(response.status_code, 303)
        select = self.person_select(self.settings_html(), "Mum")
        self.assertIn('<option value="Mummy" selected', select)

    def test_choosing_a_word_moves_those_events_to_that_person(self) -> None:
        self.graph.events["cal"].append(
            graph_event(
                "yoga",
                "Mummy : Yoga",
                "2030-01-09T10:00:00",
                "2030-01-09T11:00:00",
            )
        )
        self.show_family_calendar()
        card = self.day_card(self.page(), datetime.date(2030, 1, 9))
        self.assertIn(">Mummy<", card)  # a tag for the family, no person yet
        mum_id = re.search(
            r'action="/settings/people/(\d+)"(?:(?!</form>).)*?Save Mum',
            self.settings_html(),
            re.DOTALL,
        )
        assert mum_id is not None
        self.client.post(
            f"/settings/people/{mum_id.group(1)}",
            data={
                "name": "Mum",
                "colour": _MUM_BLUE,
                "outlook_category": "Mummy",
            },
        )
        card = self.day_card(self.page(), datetime.date(2030, 1, 9))
        self.assertIn(">Mum<", card)
        self.assertNotIn(">Mummy<", card)
        self.assertIn("Yoga", card)


class Ios9SafetyTest(_CalendarTestCase):
    """The new pages follow the kitchen iPad's rules."""

    def markup(self) -> list[tuple[str, str]]:
        self.log_in()
        self.add_mum()
        self.show_family_calendar()
        pages = ["/calendar", _SETTINGS_CALENDAR]
        return [(p, self.client.get(p).text) for p in pages]

    def test_only_the_app_script(self) -> None:
        for page, text in self.markup():
            support.assert_only_app_script(self, text, page)

    def test_no_css_grid_or_flex_gap(self) -> None:
        for page, text in self.markup():
            self.assertNotRegex(text, r"display:\s*(inline-)?grid", page)
            self.assertNotIn("grid-template", text, page)
            self.assertNotRegex(text, r"(?<![\w-])(row-|column-)?gap\s*:", page)

    def test_the_stylesheet_has_no_grid_or_gap_for_the_calendar(self) -> None:
        css = self.client.get("/static/app.css").text
        self.assertNotRegex(css, r"display:\s*(inline-)?grid")
        self.assertNotRegex(css, r"(?<![\w-])(row-|column-)?gap\s*:")


if __name__ == "__main__":
    unittest.main()
