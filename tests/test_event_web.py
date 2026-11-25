"""Tests for the event page (/event)."""

import re
import unittest

from fastapi import testclient

from tests import calendar_support as cal
from tests import support


class _EventPageTestCase(cal.AppTestCase):
    def setUp(self) -> None:
        super().setUp()
        self.add_person("Sam", "Child", "#5B2E86")
        self.sync(
            [
                cal.timed(
                    "swim",
                    "Sam : Swimming",
                    8,
                    "17:00",
                    "18:00",
                    note="Bring a towel.\nGoggles too.",
                ),
                cal.all_day("camp", "Sam : Camp", 10, span=2),
                cal.all_day("bday", "Birthday : Nan", 9),
                cal.timed("plain", "Dentist", 9, "09:30", "10:00"),
                cal.timed(
                    "xss",
                    "Sam : <i>x</i>",
                    9,
                    "11:00",
                    "12:00",
                    note="<script>alert(1)</script>",
                ),
            ]
        )

    def event(self, event_id: str, **query: str) -> str:
        extra = "".join(f"&{k}={v}" for k, v in query.items())
        return self.page(f"/event?id={event_id}{extra}")


class EventPageTest(_EventPageTestCase):
    def test_it_shows_who_what_and_when(self) -> None:
        html = self.event("swim")
        self.assertIn("Swimming", html)
        self.assertIn("Sam", html)
        self.assertIn("Tuesday 8 January", html)
        self.assertIn("5pm", html)
        self.assertIn("6pm", html)

    def test_it_shows_the_note_with_its_line_breaks_kept(self) -> None:
        html = self.event("swim")
        self.assertIn("Bring a towel.", html)
        self.assertIn("Goggles too.", html)
        self.assertIn("event-note", html)

    def test_no_note_means_no_note_box(self) -> None:
        self.assertNotIn("event-note", self.event("plain"))

    def test_it_names_the_calendar(self) -> None:
        self.assertIn("Family", self.event("swim"))

    def test_an_all_day_event_says_so(self) -> None:
        self.assertIn("all day", self.event("bday").lower())

    def test_a_multi_day_event_gives_both_ends(self) -> None:
        html = self.event("camp")
        self.assertIn("Thursday 10 January", html)
        self.assertIn("Friday 11 January", html)

    def test_a_kind_is_shown_as_a_tag(self) -> None:
        html = self.event("bday")
        self.assertIn("Birthday", html)
        self.assertIn("Nan", html)

    def test_there_is_no_reminder_form_yet(self) -> None:
        html = self.event("swim").lower()
        self.assertNotIn("<form", html.split("<main", maxsplit=1)[1])
        self.assertNotIn("reminder", html)

    def test_title_and_note_are_escaped(self) -> None:
        html = self.event("xss")
        self.assertIn("&lt;i&gt;x&lt;/i&gt;", html)
        self.assertIn("&lt;script&gt;alert(1)&lt;/script&gt;", html)
        support.assert_only_app_script(self, html, "/event")


class BackLinkTest(_EventPageTestCase):
    def back(self, html: str) -> str:
        found = re.search(r'<a class="btn" href="([^"]+)"[^>]*>[^<]*Back', html)
        self.assertIsNotNone(found, "no Back link")
        return found.group(1) if found else ""

    def test_from_home_goes_back_to_today(self) -> None:
        self.assertEqual(
            self.back(self.event("swim", **{"from": "home"})), "/home"
        )

    def test_from_calendar_goes_back_to_that_week(self) -> None:
        html = self.event("swim", **{"from": "calendar"})
        self.assertEqual(self.back(html), "/calendar?week=2030-01-07")

    def test_the_week_follows_the_event_not_today(self) -> None:
        html = self.event("camp", **{"from": "calendar"})
        self.assertEqual(self.back(html), "/calendar?week=2030-01-07")

    def test_anything_else_falls_back_to_today(self) -> None:
        for value in ("", "https://evil.test", "//evil.test", "meals"):
            html = self.event("swim", **{"from": value})
            self.assertEqual(self.back(html), "/home", value)


class MissingAndAccessTest(_EventPageTestCase):
    def test_an_unknown_event_gets_a_friendly_404(self) -> None:
        response = self.client.get("/event?id=nope&from=home")
        self.assertEqual(response.status_code, 404)
        self.assertIn("no longer", response.text)
        self.assertIn('href="/home"', response.text)

    def test_no_id_is_also_a_friendly_404(self) -> None:
        self.assertEqual(self.client.get("/event").status_code, 404)

    def test_the_event_page_needs_the_pin(self) -> None:
        anonymous = testclient.TestClient(self.app, follow_redirects=False)
        response = anonymous.get("/event?id=swim")
        self.assertEqual(response.status_code, 303)
        self.assertEqual(response.headers["location"], "/login")


if __name__ == "__main__":
    unittest.main()
