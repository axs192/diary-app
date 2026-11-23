"""Tests for the web pages: login, Today shell, Settings, iOS 9 safety."""

import pathlib
import re
import tempfile
import unittest

import pydantic
from fastapi import testclient

from diary_app import app as diary_app
from diary_app import config

_PIN = "4321"
_SESSION_SECRET = "web-test-session-secret-0123456789"  # noqa: S105
_PAGES = ["/login", "/home", "/settings"]


class _WebTestCase(unittest.TestCase):
    """Builds an app on a temporary database file, with a fresh client."""

    def setUp(self) -> None:
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        settings = config.Settings(
            household_pin=pydantic.SecretStr(_PIN),
            session_secret=pydantic.SecretStr(_SESSION_SECRET),
            database_path=pathlib.Path(tmp.name) / "diary.db",
        )
        self.app = diary_app.create_app(settings)
        self.client = testclient.TestClient(self.app, follow_redirects=False)

    def log_in(self) -> None:
        response = self.client.post("/login", data={"pin": _PIN})
        self.assertEqual(response.status_code, 303)


class LoginTest(_WebTestCase):
    """Everything except /health needs the household PIN."""

    def test_home_redirects_to_login_when_logged_out(self) -> None:
        response = self.client.get("/home")
        self.assertEqual(response.status_code, 303)
        self.assertEqual(response.headers["location"], "/login")

    def test_login_page_asks_for_a_pin(self) -> None:
        html = self.client.get("/login").text
        self.assertIn('name="pin"', html)
        self.assertIn('type="password"', html)

    def test_correct_pin_logs_in_and_opens_home(self) -> None:
        response = self.client.post("/login", data={"pin": _PIN})
        self.assertEqual(response.status_code, 303)
        self.assertEqual(response.headers["location"], "/home")
        self.assertEqual(self.client.get("/home").status_code, 200)

    def test_wrong_pin_is_refused_and_stays_logged_out(self) -> None:
        response = self.client.post("/login", data={"pin": "0000"})
        self.assertEqual(response.status_code, 401)
        self.assertIn("Wrong PIN", response.text)
        self.assertEqual(self.client.get("/home").status_code, 303)

    def test_five_wrong_pins_lock_out_the_correct_one(self) -> None:
        for _ in range(5):
            self.client.post("/login", data={"pin": "0000"})
        response = self.client.post("/login", data={"pin": _PIN})
        self.assertEqual(response.status_code, 429)
        self.assertEqual(self.client.get("/home").status_code, 303)

    def test_logout_ends_the_session(self) -> None:
        self.log_in()
        response = self.client.post("/logout")
        self.assertEqual(response.status_code, 303)
        self.assertEqual(self.client.get("/home").status_code, 303)

    def test_health_stays_public(self) -> None:
        self.assertEqual(self.client.get("/health").status_code, 200)

    def test_settings_requires_login(self) -> None:
        self.assertEqual(self.client.get("/settings").status_code, 303)

    def test_post_routes_require_login(self) -> None:
        response = self.client.post("/settings/colour", data={"colour": "Blue"})
        self.assertEqual(response.status_code, 303)
        self.assertEqual(response.headers["location"], "/login")


class SettingsPageTest(_WebTestCase):
    """Settings holds the app colour and the people on the diary."""

    def setUp(self) -> None:
        super().setUp()
        self.log_in()

    def test_settings_lists_every_app_colour(self) -> None:
        html = self.client.get("/settings").text
        for name in (
            "Green",
            "Blue",
            "Teal",
            "Purple",
            "Pink",
            "Orange",
            "Slate",
        ):
            self.assertIn(name, html)

    def test_default_app_colour_is_green(self) -> None:
        self.assertIn("#2F7D4F", self.client.get("/home").text)

    def test_chosen_app_colour_persists_into_every_page(self) -> None:
        response = self.client.post("/settings/colour", data={"colour": "Blue"})
        self.assertEqual(response.status_code, 303)
        home = self.client.get("/home").text
        self.assertIn("#24508F", home)
        self.assertNotIn("#2F7D4F", home)
        # Settings also lists every colour as a swatch, so green appears there.
        self.assertIn("#24508F", self.client.get("/settings").text)

    def test_unknown_app_colour_is_rejected(self) -> None:
        response = self.client.post("/settings/colour", data={"colour": "Nope"})
        self.assertEqual(response.status_code, 400)

    def test_added_person_is_listed(self) -> None:
        response = self.client.post(
            "/settings/people",
            data={
                "name": "Alex",
                "role": "Adult",
                "colour": "#B04A17",
                "outlook_category": "Me",
            },
        )
        self.assertEqual(response.status_code, 303)
        html = self.client.get("/settings").text
        self.assertIn('value="Alex"', html)
        self.assertIn('value="Me"', html)

    def test_person_colour_change_persists(self) -> None:
        self.client.post(
            "/settings/people",
            data={"name": "Alex", "role": "Adult", "colour": "#B04A17"},
        )
        html = self.client.get("/settings").text
        person_id = re.findall(r'action="/settings/people/(\d+)"', html)[-1]
        response = self.client.post(
            f"/settings/people/{person_id}",
            data={"name": "Alex", "colour": "#24508F", "outlook_category": ""},
        )
        self.assertEqual(response.status_code, 303)
        after = self.client.get("/settings").text
        form = after.split(f'action="/settings/people/{person_id}"')[1]
        checked = re.search(r'value="(#[0-9A-Fa-f]{6})"[^>]*checked', form)
        self.assertIsNotNone(checked)
        self.assertEqual(checked.group(1), "#24508F")  # type: ignore[union-attr]

    def test_colour_outside_the_palette_is_rejected(self) -> None:
        response = self.client.post(
            "/settings/people",
            data={"name": "Alex", "role": "Adult", "colour": "red;}"},
        )
        self.assertEqual(response.status_code, 400)

    def test_everyone_role_is_not_offered_or_accepted(self) -> None:
        html = self.client.get("/settings").text
        self.assertNotIn('<option value="Everyone">', html)
        response = self.client.post(
            "/settings/people",
            data={"name": "Second", "role": "Everyone", "colour": "#B04A17"},
        )
        self.assertEqual(response.status_code, 400)

    def test_updating_an_unknown_person_is_not_found(self) -> None:
        response = self.client.post(
            "/settings/people/999",
            data={"name": "x", "colour": "#B04A17", "outlook_category": ""},
        )
        self.assertEqual(response.status_code, 404)

    def test_person_names_are_html_escaped(self) -> None:
        self.client.post(
            "/settings/people",
            data={"name": "<b>x</b>", "role": "Adult", "colour": "#B04A17"},
        )
        html = self.client.get("/settings").text
        self.assertNotIn("<b>x</b>", html)


class LayoutTest(_WebTestCase):
    """The shell works on the iPad and on a phone from the same page."""

    def test_pages_have_main_navigation(self) -> None:
        self.log_in()
        html = self.client.get("/home").text
        self.assertIn('<nav aria-label="Main"', html)
        self.assertIn('href="/settings"', html)

    def test_stylesheet_has_phone_rules(self) -> None:
        css = self.client.get("/static/app.css").text
        self.assertIn("@media (max-width: 600px)", css)

    def test_touch_targets_are_at_least_44px(self) -> None:
        css = self.client.get("/static/app.css").text
        self.assertIn("min-height: 44px", css)


class Ios9SafetyTest(_WebTestCase):
    """The kitchen iPad runs iOS 9 Safari: no JS, no grid, no flex gap."""

    def _all_markup(self) -> list[tuple[str, str]]:
        self.log_in()
        markup = [(p, self.client.get(p).text) for p in _PAGES]
        markup.append(
            ("/static/app.css", self.client.get("/static/app.css").text)
        )
        return markup

    def test_no_javascript(self) -> None:
        for page, text in self._all_markup():
            self.assertNotIn("<script", text, page)

    def test_no_css_grid(self) -> None:
        for page, text in self._all_markup():
            self.assertNotRegex(text, r"display:\s*(inline-)?grid", page)
            self.assertNotIn("grid-template", text, page)

    def test_no_flex_gap(self) -> None:
        for page, text in self._all_markup():
            self.assertNotRegex(text, r"(?<![\w-])(row-|column-)?gap\s*:", page)

    def test_fonts_are_ttf_and_served(self) -> None:
        css = self.client.get("/static/app.css").text
        urls = re.findall(r"url\(([^)]+)\)", css)
        self.assertTrue(urls)
        for url in urls:
            self.assertTrue(url.strip("'\"").endswith(".ttf"), url)
            response = self.client.get(url.strip("'\""))
            self.assertEqual(response.status_code, 200, url)
            self.assertGreater(len(response.content), 10_000, url)

    def test_font_licence_is_shipped_with_the_fonts(self) -> None:
        response = self.client.get("/static/fonts/LICENCE.txt")
        self.assertEqual(response.status_code, 200)
        self.assertIn("UBUNTU FONT LICENCE", response.text)


if __name__ == "__main__":
    unittest.main()
