"""Tests for choosing Adult or Child and removing people in Settings."""

import pathlib
import re
import tempfile
import unittest

import pydantic
from fastapi import testclient

from diary_app import app as diary_app
from diary_app import config, db, people
from tests import support

_PIN = "4321"
_SESSION_SECRET = "people-web-session-secret-0123456789"  # noqa: S105
_BLUE = "#24508F"
_ORANGE = "#B04A17"
_PEOPLE_URL = "/settings?section=people"


class _PeopleWebTestCase(unittest.TestCase):
    def setUp(self) -> None:
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.database = pathlib.Path(tmp.name) / "diary.db"
        settings = config.Settings(
            household_pin=pydantic.SecretStr(_PIN),
            session_secret=pydantic.SecretStr(_SESSION_SECRET),
            database_path=self.database,
        )
        self.client = testclient.TestClient(
            diary_app.create_app(settings), follow_redirects=False
        )
        self.client.post("/login", data={"pin": _PIN})

    def everyone(self) -> list[people.Person]:
        conn = db.connect(self.database)
        try:
            return people.list_people(conn)
        finally:
            conn.close()

    def add(self, name: str, role: str) -> people.Person:
        response = self.client.post(
            "/settings/people",
            data={"name": name, "role": role, "colour": _BLUE},
        )
        self.assertEqual(response.status_code, 303, response.text)
        return next(p for p in self.everyone() if p.name == name)

    def card(self, name: str) -> str:
        html = self.client.get(_PEOPLE_URL).text
        found = re.search(
            r'<div class="card person"[^>]*>(?:(?!<div class="card person")'
            rf".)*?Save {name}</button>.*?</div>\s*(?=<(?:div|form)|</div>)",
            html,
            re.DOTALL,
        )
        self.assertIsNotNone(found, f"no card for {name}")
        return found.group(0) if found else ""


class WhoDropdownTest(_PeopleWebTestCase):
    """Each person has an Adult / Child dropdown that saves."""

    def test_the_dropdown_offers_adult_and_child_with_the_current_chosen(
        self,
    ) -> None:
        self.add("Sam", "Child")
        select = re.search(
            r'<select[^>]*name="role"[^>]*>(.*?)</select>',
            self.card("Sam"),
            re.DOTALL,
        )
        self.assertIsNotNone(select)
        options = select.group(1) if select else ""
        self.assertIn('value="Adult"', options)
        self.assertRegex(options, r'value="Child"\s+selected')
        self.assertNotIn('value="Everyone"', options)

    def test_the_dropdown_has_a_visible_label(self) -> None:
        self.add("Sam", "Child")
        self.assertRegex(self.card("Sam"), r'<label[^>]*for="role-\d+"')

    def test_saving_a_new_role_changes_it(self) -> None:
        sam = self.add("Sam", "Adult")
        response = self.client.post(
            f"/settings/people/{sam.id}",
            data={
                "name": "Sam",
                "colour": _BLUE,
                "outlook_category": "",
                "role": "Child",
            },
        )
        self.assertEqual(response.status_code, 303)
        self.assertEqual(response.headers["location"], _PEOPLE_URL)
        role = next(p.role for p in self.everyone() if p.name == "Sam")
        self.assertEqual(role, "Child")

    def test_a_post_without_a_role_keeps_it(self) -> None:
        sam = self.add("Sam", "Child")
        response = self.client.post(
            f"/settings/people/{sam.id}",
            data={"name": "Samuel", "colour": _ORANGE, "outlook_category": ""},
        )
        self.assertEqual(response.status_code, 303)
        changed = next(p for p in self.everyone() if p.id == sam.id)
        self.assertEqual((changed.name, changed.role), ("Samuel", "Child"))

    def test_a_bad_role_is_refused_with_a_message(self) -> None:
        sam = self.add("Sam", "Adult")
        response = self.client.post(
            f"/settings/people/{sam.id}",
            data={
                "name": "Sam",
                "colour": _BLUE,
                "outlook_category": "",
                "role": "Pet",
            },
        )
        self.assertEqual(response.status_code, 400)
        self.assertIn("Role must be", response.text)

    def test_family_shows_everyone_but_no_dropdown_or_remove(self) -> None:
        html = self.client.get(_PEOPLE_URL).text
        found = re.search(
            r'<div class="card person"[^>]*>(?:(?!<div class="card person").)*?'
            r"Save Family</button>.*?</div>",
            html,
            re.DOTALL,
        )
        self.assertIsNotNone(found)
        card = found.group(0) if found else ""
        self.assertIn("Everyone", card)
        self.assertNotIn('name="role"', card)
        self.assertNotIn("/delete", card)


class RemoveTest(_PeopleWebTestCase):
    """People can be removed after a second tap."""

    def test_each_person_has_a_two_step_remove(self) -> None:
        sam = self.add("Sam", "Child")
        card = self.card("Sam")
        self.assertIn("<details", card)
        self.assertIn(f'action="/settings/people/{sam.id}/delete"', card)
        self.assertIn("Yes, remove", card)

    def test_the_remove_form_is_not_inside_the_save_form(self) -> None:
        self.add("Sam", "Child")
        html = self.client.get(_PEOPLE_URL).text
        save = re.search(
            r'<form[^>]*action="/settings/people/\d+"[^>]*>.*?</form>',
            html,
            re.DOTALL,
        )
        self.assertIsNotNone(save)
        self.assertNotIn("/delete", save.group(0) if save else "")

    def test_remove_deletes_and_returns_to_people(self) -> None:
        sam = self.add("Sam", "Child")
        response = self.client.post(f"/settings/people/{sam.id}/delete")
        self.assertEqual(response.status_code, 303)
        self.assertEqual(response.headers["location"], _PEOPLE_URL)
        self.assertEqual([p.name for p in self.everyone()], ["Family"])

    def test_family_cannot_be_removed(self) -> None:
        family = self.everyone()[0]
        response = self.client.post(f"/settings/people/{family.id}/delete")
        self.assertEqual(response.status_code, 400)
        self.assertEqual(len(self.everyone()), 1)

    def test_removing_someone_who_is_gone_is_a_404(self) -> None:
        response = self.client.post("/settings/people/999/delete")
        self.assertEqual(response.status_code, 404)

    def test_the_warning_says_what_happens_to_their_events(self) -> None:
        self.add("Sam", "Child")
        self.assertIn("calendar", self.card("Sam").lower())


class AccessAndSafetyTest(_PeopleWebTestCase):
    def test_remove_needs_the_pin(self) -> None:
        sam = self.add("Sam", "Child")
        anonymous = testclient.TestClient(
            self.client.app, follow_redirects=False
        )
        response = anonymous.post(f"/settings/people/{sam.id}/delete")
        self.assertEqual(response.status_code, 303)
        self.assertEqual(response.headers["location"], "/login")
        self.assertEqual(len(self.everyone()), 2)

    def test_settings_still_loads_only_the_app_script(self) -> None:
        self.add("Sam", "Child")
        support.assert_only_app_script(
            self, self.client.get(_PEOPLE_URL).text, "/settings"
        )


if __name__ == "__main__":
    unittest.main()
