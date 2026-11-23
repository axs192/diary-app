"""Tests for the meals pages: plan, library, recipes, import, Suggest."""

import datetime
import json
import pathlib
import re
import tempfile
import unittest
from collections.abc import Callable, Mapping

import httpx
import pydantic
from fastapi import testclient

from diary_app import app as diary_app
from diary_app import config

_PIN = "4321"
_SESSION_SECRET = "meals-test-session-secret-0123456789"  # noqa: S105
_MONDAY = datetime.date(2030, 1, 7)
_WEEK = f"/meals?week={_MONDAY.isoformat()}"
_DAYS = [_MONDAY + datetime.timedelta(days=i) for i in range(7)]
_RECIPE_LD = {
    "@context": "https://schema.org",
    "@type": "Recipe",
    "name": "Easy curry",
    "recipeIngredient": ["1 onion", "400g chicken"],
    "recipeInstructions": [
        {"@type": "HowToStep", "text": "Fry the onion."},
        {"@type": "HowToStep", "text": "Add the chicken."},
    ],
    "totalTime": "PT35M",
    "recipeYield": "4",
    "recipeCuisine": "Indian",
}


def _recipe_page(ld: Mapping[str, object] = _RECIPE_LD) -> str:
    block = json.dumps(ld)
    return f'<script type="application/ld+json">{block}</script>'


def _public_site(page: str) -> Callable[[httpx.Request], httpx.Response]:
    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/robots.txt":
            return httpx.Response(404)
        return httpx.Response(200, text=page)

    return handler


class _MealsTestCase(unittest.TestCase):
    """An app on a temporary database, with a fake web for imports."""

    page = _recipe_page()

    def setUp(self) -> None:
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        settings = config.Settings(
            household_pin=pydantic.SecretStr(_PIN),
            session_secret=pydantic.SecretStr(_SESSION_SECRET),
            database_path=pathlib.Path(tmp.name) / "diary.db",
        )
        self.requests: list[str] = []
        handler = _public_site(self.page)

        def record(request: httpx.Request) -> httpx.Response:
            self.requests.append(str(request.url))
            return handler(request)

        self.app = diary_app.create_app(
            settings,
            http_client=httpx.Client(transport=httpx.MockTransport(record)),
            resolve=lambda _host: ["93.184.216.34"],
        )
        self.client = testclient.TestClient(self.app, follow_redirects=False)

    def log_in(self) -> None:
        response = self.client.post("/login", data={"pin": _PIN})
        self.assertEqual(response.status_code, 303)

    def add_recipe(self, name: str = "Pasta bake", **fields: object) -> int:
        data: dict[str, object] = {
            "name": name,
            "style": "Italian",
            "mins": "40",
            "servings": "4",
            "ingredients": "200g pasta\n1 jar sauce",
            "steps": "Boil.\nBake.",
        }
        data.update(fields)
        response = self.client.post("/recipes", data=data)
        self.assertEqual(response.status_code, 303, response.text)
        return int(response.headers["location"].rsplit("/", 1)[1])

    def plan(self, day: datetime.date, recipe_id: int) -> None:
        response = self.client.post(
            "/meals/day", data={"day": day.isoformat(), "recipe_id": recipe_id}
        )
        self.assertEqual(response.status_code, 303, response.text)

    def day_card(self, html: str, day: datetime.date) -> str:
        """Returns the markup of one day's card on /meals."""
        pattern = (
            rf'<article class="day[^"]*" id="day-{day.isoformat()}"'
            r".*?</article>"
        )
        found = re.search(pattern, html, re.DOTALL)
        self.assertIsNotNone(found, f"no card for {day}")
        return found.group(0) if found else ""


class AccessTest(_MealsTestCase):
    """Everything about meals needs the household PIN."""

    def test_every_meals_route_requires_login(self) -> None:
        gets = [
            "/meals",
            "/recipes/new",
            "/recipes/import",
            "/recipes/1",
            "/recipes/1/edit",
        ]
        posts = [
            "/recipes",
            "/recipes/import",
            "/recipes/1",
            "/recipes/1/delete",
            "/recipes/1/favourite",
            "/meals/day",
            "/meals/day/remove",
            "/meals/suggest",
            "/meals/clear",
        ]
        for path in gets:
            response = self.client.get(path)
            self.assertEqual(response.status_code, 303, path)
            self.assertEqual(response.headers["location"], "/login", path)
        for path in posts:
            response = self.client.post(path, data={})
            self.assertEqual(response.status_code, 303, path)
            self.assertEqual(response.headers["location"], "/login", path)
        self.assertEqual(self.requests, [])

    def test_navigation_links_to_meals(self) -> None:
        self.log_in()
        self.assertIn('href="/meals"', self.client.get("/home").text)


class EmptyLibraryTest(_MealsTestCase):
    """A new household starts with no meals."""

    def test_empty_state_invites_adding_a_first_meal(self) -> None:
        self.log_in()
        html = self.client.get(_WEEK).text
        self.assertIn("No meals yet", html)
        self.assertIn('href="/recipes/new"', html)
        self.assertIn('href="/recipes/import"', html)

    def test_week_shows_seven_empty_days(self) -> None:
        self.log_in()
        html = self.client.get(_WEEK).text
        for day in _DAYS:
            self.assertIn("Nothing planned", self.day_card(html, day))

    def test_week_links_to_neighbouring_weeks(self) -> None:
        self.log_in()
        html = self.client.get(_WEEK).text
        self.assertIn("week=2029-12-31", html)
        self.assertIn("week=2030-01-14", html)

    def test_a_date_inside_the_week_shows_that_week(self) -> None:
        self.log_in()
        html = self.client.get("/meals?week=2030-01-10").text
        self.assertIn('id="day-2030-01-07"', html)

    def test_a_bad_week_falls_back_to_the_current_week(self) -> None:
        self.log_in()
        self.assertEqual(
            self.client.get("/meals?week=nonsense").status_code, 200
        )

    def test_a_bad_tab_falls_back_to_ideas(self) -> None:
        self.log_in()
        self.assertEqual(self.client.get(f"{_WEEK}&tab=zzz").status_code, 200)

    def test_suggest_with_an_empty_library_says_to_add_meals(self) -> None:
        self.log_in()
        response = self.client.post(
            "/meals/suggest",
            data={"week": _MONDAY.isoformat(), "style": "Mixed"},
        )
        self.assertEqual(response.status_code, 303)
        html = self.client.get(response.headers["location"]).text
        self.assertIn("Add more meals to fill the week", html)


class RecipeTest(_MealsTestCase):
    """Adding, viewing, editing and deleting recipes."""

    def test_added_meal_has_a_page_and_is_in_the_library(self) -> None:
        self.log_in()
        recipe_id = self.add_recipe(tags=["Veg-led", "Quick"])
        page = self.client.get(f"/recipes/{recipe_id}").text
        self.assertIn("Pasta bake", page)
        self.assertIn("200g pasta", page)
        self.assertIn("<ol", page)
        self.assertIn("Boil.", page)
        self.assertIn("Veg-led", page)
        self.assertIn("Pasta bake", self.client.get(f"{_WEEK}&tab=mine").text)
        self.assertNotIn("No meals yet", self.client.get(_WEEK).text)

    def test_blank_name_is_refused_and_the_form_keeps_what_was_typed(
        self,
    ) -> None:
        self.log_in()
        response = self.client.post(
            "/recipes",
            data={
                "name": " ",
                "style": "Italian",
                "mins": "40",
                "servings": "4",
                "ingredients": "keep me",
            },
        )
        self.assertEqual(response.status_code, 400)
        self.assertIn("Give the meal a name", response.text)
        self.assertIn("keep me", response.text)
        self.assertIn("No meals yet", self.client.get(_WEEK).text)

    def test_bad_minutes_are_refused(self) -> None:
        self.log_in()
        for mins in ("", "abc", "0"):
            response = self.client.post(
                "/recipes",
                data={
                    "name": "X",
                    "style": "Italian",
                    "mins": mins,
                    "servings": "4",
                },
            )
            self.assertEqual(response.status_code, 400, mins)

    def test_unknown_recipe_is_not_found(self) -> None:
        self.log_in()
        self.assertEqual(self.client.get("/recipes/99").status_code, 404)
        self.assertEqual(self.client.get("/recipes/99/edit").status_code, 404)
        self.assertEqual(
            self.client.post("/recipes/99", data={"name": "x"}).status_code, 404
        )

    def test_edit_form_is_prefilled_and_saving_changes_the_recipe(self) -> None:
        self.log_in()
        recipe_id = self.add_recipe("Pasta bake")
        form = self.client.get(f"/recipes/{recipe_id}/edit").text
        self.assertIn('value="Pasta bake"', form)
        self.assertIn("200g pasta", form)
        response = self.client.post(
            f"/recipes/{recipe_id}",
            data={
                "name": "Better bake",
                "style": "Italian",
                "mins": "30",
                "servings": "2",
                "ingredients": "pasta",
                "steps": "Cook.",
            },
        )
        self.assertEqual(response.status_code, 303)
        page = self.client.get(f"/recipes/{recipe_id}").text
        self.assertIn("Better bake", page)
        self.assertNotIn("200g pasta", page)

    def test_delete_removes_the_recipe_and_its_planned_day(self) -> None:
        self.log_in()
        recipe_id = self.add_recipe()
        self.plan(_DAYS[1], recipe_id)
        response = self.client.post(f"/recipes/{recipe_id}/delete")
        self.assertEqual(response.status_code, 303)
        self.assertEqual(
            self.client.get(f"/recipes/{recipe_id}").status_code, 404
        )
        card = self.day_card(self.client.get(_WEEK).text, _DAYS[1])
        self.assertIn("Nothing planned", card)

    def test_source_is_credited_with_a_link(self) -> None:
        self.log_in()
        recipe_id = self.add_recipe(
            source_url="https://www.bbcgoodfood.com/recipes/x",
            source_name="BBC Good Food",
        )
        page = self.client.get(f"/recipes/{recipe_id}").text
        self.assertIn('href="https://www.bbcgoodfood.com/recipes/x"', page)
        self.assertIn("BBC Good Food", page)

    def test_a_non_web_source_is_refused(self) -> None:
        self.log_in()
        response = self.client.post(
            "/recipes",
            data={
                "name": "X",
                "style": "Italian",
                "mins": "5",
                "servings": "1",
                "source_url": "javascript:alert(1)",
            },
        )
        self.assertEqual(response.status_code, 400)

    def test_recipe_text_is_html_escaped(self) -> None:
        self.log_in()
        recipe_id = self.add_recipe(
            "<b>bold</b>", ingredients="<script>alert(1)</script>"
        )
        for url in (
            f"/recipes/{recipe_id}",
            f"/recipes/{recipe_id}/edit",
            f"{_WEEK}&tab=mine",
        ):
            html = self.client.get(url).text
            self.assertNotIn("<b>bold</b>", html, url)
            self.assertNotIn("<script>alert", html, url)


class ImportTest(_MealsTestCase):
    """Importing a recipe from a web address, reviewing it, then saving."""

    def test_import_prefills_the_form_and_saves_nothing(self) -> None:
        self.log_in()
        response = self.client.post(
            "/recipes/import", data={"url": "https://www.bbcgoodfood.com/r/1"}
        )
        self.assertEqual(response.status_code, 200)
        self.assertIn('value="Easy curry"', response.text)
        self.assertIn("1 onion", response.text)
        self.assertIn("Fry the onion.", response.text)
        self.assertIn("BBC Good Food", response.text)
        self.assertIn("No meals yet", self.client.get(_WEEK).text)

    def test_saving_the_reviewed_form_stores_the_recipe_with_its_source(
        self,
    ) -> None:
        self.log_in()
        recipe_id = self.add_recipe(
            "Easy curry",
            source_url="https://www.bbcgoodfood.com/r/1",
            source_name="BBC Good Food",
        )
        self.assertIn(
            "BBC Good Food", self.client.get(f"/recipes/{recipe_id}").text
        )

    def test_import_errors_are_shown_and_nothing_is_saved(self) -> None:
        self.log_in()
        response = self.client.post(
            "/recipes/import", data={"url": "file:///etc/passwd"}
        )
        self.assertEqual(response.status_code, 400)
        self.assertIn("http://", response.text)
        self.assertEqual(self.requests, [])
        self.assertIn("No meals yet", self.client.get(_WEEK).text)

    def test_a_blank_address_is_refused(self) -> None:
        self.log_in()
        response = self.client.post("/recipes/import", data={"url": "  "})
        self.assertEqual(response.status_code, 400)

    def test_import_text_from_the_page_is_escaped(self) -> None:
        self.__class__.page = _recipe_page(
            {**_RECIPE_LD, "name": "Curry <img src=x onerror=alert(1)>"}
        )
        self.addCleanup(setattr, self.__class__, "page", _recipe_page())
        self.setUp()
        self.log_in()
        response = self.client.post(
            "/recipes/import", data={"url": "https://example.org/r"}
        )
        self.assertNotIn("<img src=x", response.text)


class PlanTest(_MealsTestCase):
    """Building a week by hand."""

    def test_adding_a_meal_to_a_day_shows_it_on_that_card(self) -> None:
        self.log_in()
        recipe_id = self.add_recipe("Pasta bake", tags=["Quick"])
        self.plan(_DAYS[2], recipe_id)
        card = self.day_card(self.client.get(_WEEK).text, _DAYS[2])
        self.assertIn("Pasta bake", card)
        self.assertIn(f'href="/recipes/{recipe_id}"', card)
        self.assertIn("40 min", card)
        self.assertIn("Quick", card)
        self.assertIn(
            "Nothing planned",
            self.day_card(self.client.get(_WEEK).text, _DAYS[3]),
        )

    def test_planning_another_meal_replaces_the_first(self) -> None:
        self.log_in()
        first = self.add_recipe("First")
        second = self.add_recipe("Second")
        self.plan(_DAYS[0], first)
        self.plan(_DAYS[0], second)
        card = self.day_card(self.client.get(_WEEK).text, _DAYS[0])
        self.assertIn("Second", card)
        self.assertNotIn("First", card)

    def test_planning_redirects_back_to_that_week(self) -> None:
        self.log_in()
        recipe_id = self.add_recipe()
        response = self.client.post(
            "/meals/day", data={"day": "2030-01-09", "recipe_id": recipe_id}
        )
        self.assertEqual(response.headers["location"], "/meals?week=2030-01-07")

    def test_remove_empties_the_day(self) -> None:
        self.log_in()
        recipe_id = self.add_recipe()
        self.plan(_DAYS[0], recipe_id)
        response = self.client.post(
            "/meals/day/remove", data={"day": _DAYS[0].isoformat()}
        )
        self.assertEqual(response.status_code, 303)
        card = self.day_card(self.client.get(_WEEK).text, _DAYS[0])
        self.assertIn("Nothing planned", card)

    def test_bad_day_or_unknown_recipe_is_refused(self) -> None:
        self.log_in()
        recipe_id = self.add_recipe()
        bad_day = self.client.post(
            "/meals/day", data={"day": "soon", "recipe_id": recipe_id}
        )
        self.assertEqual(bad_day.status_code, 400)
        no_recipe = self.client.post(
            "/meals/day", data={"day": _DAYS[0].isoformat(), "recipe_id": 99}
        )
        self.assertEqual(no_recipe.status_code, 404)

    def test_recipe_page_can_add_the_meal_to_a_day(self) -> None:
        self.log_in()
        recipe_id = self.add_recipe()
        page = self.client.get(f"/recipes/{recipe_id}").text
        self.assertIn('action="/meals/day"', page)
        self.assertIn('name="day"', page)

    def test_clear_week_empties_that_week_only(self) -> None:
        self.log_in()
        recipe_id = self.add_recipe()
        self.plan(_DAYS[0], recipe_id)
        next_monday = _MONDAY + datetime.timedelta(days=7)
        self.plan(next_monday, recipe_id)
        response = self.client.post(
            "/meals/clear", data={"week": _MONDAY.isoformat()}
        )
        self.assertEqual(response.status_code, 303)
        this = self.client.get(_WEEK).text
        self.assertIn("Nothing planned", self.day_card(this, _DAYS[0]))
        later = self.client.get(f"/meals?week={next_monday.isoformat()}").text
        self.assertNotIn("Nothing planned", self.day_card(later, next_monday))


class LibraryTabsTest(_MealsTestCase):
    """Ideas, Favourites and My meals."""

    def test_ideas_exclude_meals_already_planned_this_week(self) -> None:
        self.log_in()
        planned = self.add_recipe("Planned dish")
        spare = self.add_recipe("Spare dish")
        self.plan(_DAYS[0], planned)
        html = self.client.get(f"{_WEEK}&tab=ideas").text
        library = html.split('id="library"', 1)[1]
        self.assertIn("Spare dish", library)
        self.assertNotIn("Planned dish", library)
        self.assertIn(f'value="{spare}"', library)

    def test_ideas_follow_the_chosen_style(self) -> None:
        self.log_in()
        self.add_recipe("Pizza", style="Italian")
        self.add_recipe("Tacos", style="Mexican")
        self.client.post(
            "/meals/suggest",
            data={"week": _MONDAY.isoformat(), "style": "Mexican"},
        )
        self.client.post("/meals/clear", data={"week": _MONDAY.isoformat()})
        library = self.client.get(f"{_WEEK}&tab=ideas").text.split(
            'id="library"', 1
        )[1]
        self.assertIn("Tacos", library)
        self.assertNotIn("Pizza", library)

    def test_swap_preselects_the_day(self) -> None:
        self.log_in()
        self.add_recipe()
        html = self.client.get(f"{_WEEK}&tab=ideas&day=2030-01-10").text
        self.assertRegex(html, r'<option value="2030-01-10" selected')

    def test_hearting_adds_to_favourites_and_unhearting_removes(self) -> None:
        self.log_in()
        recipe_id = self.add_recipe("Loved dish")
        self.add_recipe("Other dish")
        response = self.client.post(
            f"/recipes/{recipe_id}/favourite", data={"favourite": "1"}
        )
        self.assertEqual(response.status_code, 303)
        favourites = self.client.get(f"{_WEEK}&tab=favourites").text
        library = favourites.split('id="library"', 1)[1]
        self.assertIn("Loved dish", library)
        self.assertNotIn("Other dish", library)
        self.client.post(
            f"/recipes/{recipe_id}/favourite", data={"favourite": "0"}
        )
        library = self.client.get(f"{_WEEK}&tab=favourites").text.split(
            'id="library"', 1
        )[1]
        self.assertNotIn("Loved dish", library)

    def test_favourite_redirect_only_goes_to_our_own_pages(self) -> None:
        self.log_in()
        recipe_id = self.add_recipe()
        for back, expected in (
            (f"/recipes/{recipe_id}", f"/recipes/{recipe_id}"),
            ("https://evil.example/", "/meals"),
            ("//evil.example/", "/meals"),
        ):
            response = self.client.post(
                f"/recipes/{recipe_id}/favourite",
                data={"favourite": "1", "back": back},
            )
            self.assertEqual(response.headers["location"], expected, back)

    def test_my_meals_lists_everything(self) -> None:
        self.log_in()
        self.add_recipe("One", style="Italian")
        self.add_recipe("Two", style="Mexican")
        html = self.client.get(f"{_WEEK}&tab=mine").text
        self.assertIn("One", html)
        self.assertIn("Two", html)


class SuggestTest(_MealsTestCase):
    """Suggest a week fills empty days only."""

    def _library(self, count: int = 9) -> list[int]:
        return [self.add_recipe(f"Dish {i}") for i in range(count)]

    def test_fills_every_empty_day(self) -> None:
        self.log_in()
        self._library()
        response = self.client.post(
            "/meals/suggest",
            data={"week": _MONDAY.isoformat(), "style": "Mixed"},
        )
        self.assertEqual(response.status_code, 303)
        html = self.client.get(response.headers["location"]).text
        for day in _DAYS:
            self.assertNotIn("Nothing planned", self.day_card(html, day))

    def test_never_overwrites_a_meal_you_chose(self) -> None:
        self.log_in()
        self._library()
        chosen = self.add_recipe("My choice")
        self.plan(_DAYS[3], chosen)
        self.client.post(
            "/meals/suggest",
            data={"week": _MONDAY.isoformat(), "style": "Mixed"},
        )
        html = self.client.get(_WEEK).text
        self.assertIn("My choice", self.day_card(html, _DAYS[3]))
        self.assertEqual(html.count("My choice"), 1)

    def test_a_small_library_fills_what_it_can_and_says_so(self) -> None:
        self.log_in()
        self._library(3)
        response = self.client.post(
            "/meals/suggest",
            data={"week": _MONDAY.isoformat(), "style": "Mixed"},
        )
        html = self.client.get(response.headers["location"]).text
        self.assertIn("Add more meals to fill the week", html)
        empty = [
            d for d in _DAYS if "Nothing planned" in self.day_card(html, d)
        ]
        self.assertEqual(len(empty), 4)
        # The note is shown once, not on every later visit.
        self.assertNotIn(
            "Add more meals to fill the week", self.client.get(_WEEK).text
        )

    def test_preferences_are_saved_and_shown_again(self) -> None:
        self.log_in()
        self._library()
        self.client.post(
            "/meals/suggest",
            data={
                "week": _MONDAY.isoformat(),
                "style": "Italian",
                "priorities": ["quick", "healthy"],
            },
        )
        html = self.client.get(_WEEK).text
        self.assertRegex(html, r'<option value="Italian" selected')
        self.assertRegex(html, r'value="quick" checked')
        self.assertRegex(html, r'value="healthy" checked')
        self.assertNotRegex(html, r'value="kid-friendly" checked')

    def test_unknown_preferences_are_refused(self) -> None:
        self.log_in()
        bad_style = self.client.post(
            "/meals/suggest",
            data={"week": _MONDAY.isoformat(), "style": "Klingon"},
        )
        self.assertEqual(bad_style.status_code, 400)
        bad_priority = self.client.post(
            "/meals/suggest",
            data={
                "week": _MONDAY.isoformat(),
                "style": "Mixed",
                "priorities": ["vibes"],
            },
        )
        self.assertEqual(bad_priority.status_code, 400)

    def test_recently_cooked_meals_are_not_suggested_again(self) -> None:
        self.log_in()
        ids = self._library(16)
        last_week = _MONDAY - datetime.timedelta(days=7)
        for i in range(7):
            self.plan(last_week + datetime.timedelta(days=i), ids[i])
        self.client.post(
            "/meals/suggest",
            data={"week": _MONDAY.isoformat(), "style": "Mixed"},
        )
        plan = self.client.get(_WEEK).text.split('id="library"', 1)[0]
        for i in range(7):
            self.assertNotIn(f'href="/recipes/{ids[i]}"', plan, i)


class BalanceTest(_MealsTestCase):
    """The week-balance panel."""

    def test_panel_counts_tags_in_the_week(self) -> None:
        self.log_in()
        veg = self.add_recipe("Veg", tags=["Veg-led"])
        self.plan(_DAYS[0], veg)
        self.plan(_DAYS[1], veg)
        html = self.client.get(_WEEK).text
        self.assertIn("Veg-led dinners", html)
        self.assertIn("Oily fish", html)
        self.assertIn("Treat nights", html)
        self.assertRegex(html, r"Veg-led dinners.*?2 of 3")


class IconAndKioskTest(_MealsTestCase):
    """The Home Screen icon and the kitchen screen's self-refresh."""

    def test_pages_link_an_apple_touch_icon_that_is_served(self) -> None:
        self.log_in()
        html = self.client.get("/home").text
        found = re.search(
            r'<link rel="apple-touch-icon"[^>]*href="([^"]+)"', html
        )
        self.assertIsNotNone(found)
        href = found.group(1) if found else ""
        response = self.client.get(href)
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.headers["content-type"], "image/png")
        self.assertTrue(response.content.startswith(b"\x89PNG"))

    def test_icon_urls_ios_guesses_are_served_without_login(self) -> None:
        for path in (
            "/apple-touch-icon.png",
            "/apple-touch-icon-precomposed.png",
        ):
            response = self.client.get(path)
            self.assertEqual(response.status_code, 200, path)
            self.assertEqual(
                response.headers["content-type"], "image/png", path
            )

    def test_only_home_refreshes_itself(self) -> None:
        self.log_in()
        home = self.client.get("/home").text
        self.assertRegex(home, r'<meta http-equiv="refresh" content="300"')
        for page in ("/settings", _WEEK, "/recipes/new", "/recipes/import"):
            self.assertNotIn("http-equiv", self.client.get(page).text, page)


class Ios9SafetyTest(_MealsTestCase):
    """The meals pages obey the same iOS 9 rules as the rest of the app."""

    def test_no_javascript_grid_or_flex_gap(self) -> None:
        self.log_in()
        recipe_id = self.add_recipe(tags=["Quick"])
        self.plan(_DAYS[0], recipe_id)
        pages = [
            _WEEK,
            f"{_WEEK}&tab=favourites",
            f"{_WEEK}&tab=mine",
            "/recipes/new",
            "/recipes/import",
            f"/recipes/{recipe_id}",
            f"/recipes/{recipe_id}/edit",
            "/static/app.css",
        ]
        for page in pages:
            text = self.client.get(page).text
            self.assertNotIn("<script", text, page)
            self.assertNotRegex(text, r"display:\s*(inline-)?grid", page)
            self.assertNotIn("grid-template", text, page)
            self.assertNotRegex(text, r"(?<![\w-])(row-|column-)?gap\s*:", page)

    def test_forms_are_plain_posts(self) -> None:
        self.log_in()
        html = self.client.get("/recipes/new").text
        self.assertIn('method="post"', html)
        self.assertNotIn("onclick", html)


if __name__ == "__main__":
    unittest.main()
