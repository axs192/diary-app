"""Tests for the "show notes" device setting."""

import re
import unittest

from fastapi import testclient

from diary_app import db, today
from tests import calendar_support as cal

_DEVICE = "/settings?section=device"


class SettingTest(unittest.TestCase):
    def setUp(self) -> None:
        self.conn = db.connect(":memory:")
        self.addCleanup(self.conn.close)

    def test_notes_are_shown_until_someone_turns_them_off(self) -> None:
        self.assertTrue(today.get_show_notes(self.conn))

    def test_the_choice_is_saved(self) -> None:
        today.set_show_notes(self.conn, show=False)
        self.assertFalse(today.get_show_notes(self.conn))
        today.set_show_notes(self.conn, show=True)
        self.assertTrue(today.get_show_notes(self.conn))

    def test_a_damaged_saved_value_means_shown(self) -> None:
        db.set_setting(self.conn, "show_notes", "banana")
        self.assertTrue(today.get_show_notes(self.conn))


class WebTest(cal.AppTestCase):
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
                    note="Door code 1234",
                )
            ]
        )

    def set_notes(self, *, show: bool) -> None:
        data = {"notes": "1"} if show else {}
        response = self.client.post("/settings/show-notes", data=data)
        self.assertEqual(response.status_code, 303)
        self.assertEqual(response.headers["location"], _DEVICE)

    def test_the_event_page_shows_the_note_by_default(self) -> None:
        self.assertIn("Door code 1234", self.page("/event?id=swim"))

    def test_turning_notes_off_hides_them_on_the_event_page(self) -> None:
        self.set_notes(show=False)
        html = self.page("/event?id=swim")
        self.assertNotIn("Door code 1234", html)
        self.assertNotIn("event-note", html)
        self.assertIn("Swimming", html)

    def test_turning_them_back_on_shows_them_again(self) -> None:
        self.set_notes(show=False)
        self.set_notes(show=True)
        self.assertIn("Door code 1234", self.page("/event?id=swim"))

    def test_settings_shows_a_checkbox_reflecting_the_choice(self) -> None:
        self.assertRegex(
            self.page(_DEVICE), r'<input[^>]*name="notes"[^>]*checked'
        )
        self.set_notes(show=False)
        found = re.search(r'<input[^>]*name="notes"[^>]*>', self.page(_DEVICE))
        self.assertIsNotNone(found)
        self.assertNotIn("checked", found.group(0) if found else "")

    def test_the_route_needs_the_pin(self) -> None:
        anonymous = testclient.TestClient(self.app, follow_redirects=False)
        response = anonymous.post("/settings/show-notes", data={})
        self.assertEqual(response.status_code, 303)
        self.assertEqual(response.headers["location"], "/login")
        self.assertIn("Door code 1234", self.page("/event?id=swim"))


class QuotesTest(cal.AppTestCase):
    def test_the_people_help_text_has_no_literal_escapes(self) -> None:
        html = self.page("/settings?section=people")
        self.assertNotIn("\\u20", html)
        self.assertIn("“Same as the name”", html)


if __name__ == "__main__":
    unittest.main()
