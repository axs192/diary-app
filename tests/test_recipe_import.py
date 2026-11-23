"""Tests for the diary_app.recipe_import public interface."""

import json
import unittest
from collections.abc import Callable

import httpx

from diary_app import recipe_import

_URL = "https://www.bbcgoodfood.com/recipes/easy-curry"


def _page(*blocks: object) -> str:
    scripts = "".join(
        f'<script type="application/ld+json">{json.dumps(b)}</script>'
        for b in blocks
    )
    return f"<html><head><title>x</title>{scripts}</head><body></body></html>"


_RECIPE = {
    "@context": "https://schema.org",
    "@type": "Recipe",
    "name": "Easy curry",
    "recipeIngredient": ["1 onion", "400g chicken", "2 tbsp curry paste"],
    "recipeInstructions": [
        {"@type": "HowToStep", "text": "Fry the onion."},
        {"@type": "HowToStep", "text": "Add the chicken &amp; paste."},
    ],
    "totalTime": "PT35M",
    "recipeYield": "Serves 4",
    "recipeCuisine": "Indian",
}


class DraftFromHtmlTest(unittest.TestCase):
    """draft_from_html reads schema.org Recipe data from a page."""

    def test_reads_a_plain_recipe(self) -> None:
        draft = recipe_import.draft_from_html(_page(_RECIPE), _URL)
        self.assertEqual(draft.name, "Easy curry")
        self.assertEqual(
            list(draft.ingredients),
            ["1 onion", "400g chicken", "2 tbsp curry paste"],
        )
        self.assertEqual(
            list(draft.steps), ["Fry the onion.", "Add the chicken & paste."]
        )
        self.assertEqual(draft.mins, 35)
        self.assertEqual(draft.servings, 4)
        self.assertEqual(draft.style, "Indian")
        self.assertEqual(draft.source_url, _URL)

    def test_finds_a_recipe_inside_a_graph(self) -> None:
        graph = {"@graph": [{"@type": "WebSite"}, _RECIPE]}
        draft = recipe_import.draft_from_html(_page(graph), _URL)
        self.assertEqual(draft.name, "Easy curry")

    def test_finds_a_recipe_in_a_list_and_with_several_types(self) -> None:
        typed = {**_RECIPE, "@type": ["Recipe", "NewsArticle"]}
        draft = recipe_import.draft_from_html(
            _page([{"@type": "Person"}, typed]), _URL
        )
        self.assertEqual(draft.name, "Easy curry")

    def test_uses_the_recipe_block_when_several_scripts_exist(self) -> None:
        draft = recipe_import.draft_from_html(
            _page({"@type": "Organization"}, _RECIPE), _URL
        )
        self.assertEqual(draft.name, "Easy curry")

    def test_reads_how_to_sections(self) -> None:
        recipe = {
            **_RECIPE,
            "recipeInstructions": [
                {
                    "@type": "HowToSection",
                    "name": "Sauce",
                    "itemListElement": [
                        {"@type": "HowToStep", "text": "Chop."},
                        {"@type": "HowToStep", "text": "Simmer."},
                    ],
                },
                {"@type": "HowToStep", "text": "Serve."},
            ],
        }
        draft = recipe_import.draft_from_html(_page(recipe), _URL)
        self.assertEqual(list(draft.steps), ["Chop.", "Simmer.", "Serve."])

    def test_splits_instructions_given_as_one_string(self) -> None:
        recipe = {**_RECIPE, "recipeInstructions": "Chop.\nSimmer.\n\nServe."}
        draft = recipe_import.draft_from_html(_page(recipe), _URL)
        self.assertEqual(list(draft.steps), ["Chop.", "Simmer.", "Serve."])

    def test_strips_markup_from_text(self) -> None:
        recipe = {
            **_RECIPE,
            "recipeIngredient": ["1 <b>onion</b> &amp; garlic"],
        }
        draft = recipe_import.draft_from_html(_page(recipe), _URL)
        self.assertEqual(list(draft.ingredients), ["1 onion & garlic"])

    def test_durations_are_converted_to_minutes(self) -> None:
        cases = {"PT1H20M": 80, "PT45M": 45, "PT2H": 120, "P0DT1H30M": 90}
        for iso, mins in cases.items():
            recipe = {**_RECIPE, "totalTime": iso}
            draft = recipe_import.draft_from_html(_page(recipe), _URL)
            self.assertEqual(draft.mins, mins, iso)

    def test_adds_prep_and_cook_when_there_is_no_total(self) -> None:
        recipe = {k: v for k, v in _RECIPE.items() if k != "totalTime"}
        recipe |= {"prepTime": "PT10M", "cookTime": "PT25M"}
        draft = recipe_import.draft_from_html(_page(recipe), _URL)
        self.assertEqual(draft.mins, 35)

    def test_missing_time_falls_back_to_a_default_for_review(self) -> None:
        recipe = {k: v for k, v in _RECIPE.items() if k != "totalTime"}
        draft = recipe_import.draft_from_html(_page(recipe), _URL)
        self.assertGreaterEqual(draft.mins, 1)

    def test_yield_formats(self) -> None:
        for value, servings in (
            (6, 6),
            ("6", 6),
            ("Makes 8 portions", 8),
            (["4", "4 servings"], 4),
            ("a few", 4),
        ):
            recipe = {**_RECIPE, "recipeYield": value}
            draft = recipe_import.draft_from_html(_page(recipe), _URL)
            self.assertEqual(draft.servings, servings, value)

    def test_quick_tag_for_thirty_minutes_or_less(self) -> None:
        quick = {**_RECIPE, "totalTime": "PT30M"}
        slow = {**_RECIPE, "totalTime": "PT31M"}
        self.assertIn(
            "Quick", recipe_import.draft_from_html(_page(quick), _URL).tags
        )
        self.assertNotIn(
            "Quick", recipe_import.draft_from_html(_page(slow), _URL).tags
        )

    def test_oily_fish_tag_from_ingredients(self) -> None:
        recipe = {**_RECIPE, "recipeIngredient": ["2 salmon fillets", "lemon"]}
        draft = recipe_import.draft_from_html(_page(recipe), _URL)
        self.assertIn("Oily fish", draft.tags)
        plain = recipe_import.draft_from_html(_page(_RECIPE), _URL)
        self.assertNotIn("Oily fish", plain.tags)

    def test_cuisine_maps_onto_our_styles(self) -> None:
        cases = {
            "Italian": "Italian",
            "thai": "Asian",
            "Greek": "Mediterranean",
            "English": "British",
            "Martian": "Other",
        }
        for cuisine, style in cases.items():
            recipe = {**_RECIPE, "recipeCuisine": cuisine}
            draft = recipe_import.draft_from_html(_page(recipe), _URL)
            self.assertEqual(draft.style, style, cuisine)

    def test_source_names(self) -> None:
        cases = {
            "https://www.bbcgoodfood.com/recipes/x": "BBC Good Food",
            "https://www.example.org/r/1": "example.org",
        }
        for url, name in cases.items():
            draft = recipe_import.draft_from_html(_page(_RECIPE), url)
            self.assertEqual(draft.source_name, name, url)

    def test_the_draft_can_be_stored_as_is(self) -> None:
        from diary_app import db, recipes  # noqa: PLC0415

        draft = recipe_import.draft_from_html(_page(_RECIPE), _URL)
        stored = recipes.add(db.connect(":memory:"), draft)
        self.assertEqual(stored.name, "Easy curry")

    def test_overlong_name_is_shortened_so_it_can_be_saved(self) -> None:
        recipe = {**_RECIPE, "name": "x" * 300}
        draft = recipe_import.draft_from_html(_page(recipe), _URL)
        self.assertLessEqual(len(draft.name), 100)

    def test_page_without_structured_data_is_an_error(self) -> None:
        with self.assertRaises(recipe_import.RecipeImportError):
            recipe_import.draft_from_html("<html><body>Hi</body></html>", _URL)

    def test_structured_data_that_is_not_a_recipe_is_an_error(self) -> None:
        with self.assertRaises(recipe_import.RecipeImportError):
            recipe_import.draft_from_html(_page({"@type": "Article"}), _URL)

    def test_broken_json_is_an_error_not_a_crash(self) -> None:
        html = '<script type="application/ld+json">{nope</script>'
        with self.assertRaises(recipe_import.RecipeImportError):
            recipe_import.draft_from_html(html, _URL)

    def test_recipe_without_a_name_is_an_error(self) -> None:
        recipe = {k: v for k, v in _RECIPE.items() if k != "name"}
        with self.assertRaises(recipe_import.RecipeImportError):
            recipe_import.draft_from_html(_page(recipe), _URL)


_PUBLIC = ["93.184.216.34"]


def _resolver(
    table: dict[str, list[str]] | None = None,
) -> Callable[[str], list[str]]:
    table = table or {}
    return lambda host: table.get(host, _PUBLIC)


def _client(
    handler: Callable[[httpx.Request], httpx.Response],
) -> tuple[httpx.Client, list[str]]:
    seen: list[str] = []

    def record(request: httpx.Request) -> httpx.Response:
        seen.append(str(request.url))
        return handler(request)

    return httpx.Client(transport=httpx.MockTransport(record)), seen


def _site(
    page: str = _page(_RECIPE), robots: str = "User-agent: *\nAllow: /"
) -> Callable[[httpx.Request], httpx.Response]:
    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/robots.txt":
            return httpx.Response(200, text=robots)
        return httpx.Response(
            200, text=page, headers={"content-type": "text/html"}
        )

    return handler


class FetchDraftTest(unittest.TestCase):
    """fetch_draft downloads one page safely and reads its recipe."""

    def test_fetches_and_parses_a_recipe(self) -> None:
        client, _seen = _client(_site())
        draft = recipe_import.fetch_draft(_URL, client, _resolver())
        self.assertEqual(draft.name, "Easy curry")

    def test_sends_a_generic_user_agent(self) -> None:
        agents: list[str] = []

        def handler(request: httpx.Request) -> httpx.Response:
            agents.append(request.headers["user-agent"])
            return _site()(request)

        client, _seen = _client(handler)
        recipe_import.fetch_draft(_URL, client, _resolver())
        self.assertTrue(agents)
        self.assertTrue(all("diary-app" in a for a in agents))

    def test_refuses_non_web_schemes(self) -> None:
        client, seen = _client(_site())
        for url in (
            "file:///etc/passwd",
            "ftp://example.com/x",
            "javascript:1",
        ):
            with self.assertRaises(recipe_import.RecipeImportError, msg=url):
                recipe_import.fetch_draft(url, client, _resolver())
        self.assertEqual(seen, [])

    def test_refuses_private_and_loopback_addresses(self) -> None:
        client, seen = _client(_site())
        for address in (
            "127.0.0.1",
            "10.0.0.5",
            "192.168.1.20",
            "172.16.0.9",
            "169.254.169.254",
            "::1",
            "fd00::1",
            "0.0.0.0",  # noqa: S104
        ):
            resolver = _resolver({"www.bbcgoodfood.com": [address]})
            with self.assertRaises(
                recipe_import.RecipeImportError, msg=address
            ):
                recipe_import.fetch_draft(_URL, client, resolver)
        self.assertEqual(seen, [])

    def test_refuses_a_host_if_any_address_is_private(self) -> None:
        client, _seen = _client(_site())
        resolver = _resolver(
            {"www.bbcgoodfood.com": ["93.184.216.34", "10.0.0.1"]}
        )
        with self.assertRaises(recipe_import.RecipeImportError):
            recipe_import.fetch_draft(_URL, client, resolver)

    def test_refuses_an_ip_address_in_the_url(self) -> None:
        client, seen = _client(_site())
        with self.assertRaises(recipe_import.RecipeImportError):
            recipe_import.fetch_draft(
                "http://192.168.1.1/recipe", client, _resolver()
            )
        self.assertEqual(seen, [])

    def test_unresolvable_host_is_an_error(self) -> None:
        client, _seen = _client(_site())

        def resolver(_host: str) -> list[str]:
            return []

        with self.assertRaises(recipe_import.RecipeImportError):
            recipe_import.fetch_draft(_URL, client, resolver)

    def test_robots_txt_disallow_is_respected(self) -> None:
        client, seen = _client(_site(robots="User-agent: *\nDisallow: /"))
        with self.assertRaises(recipe_import.RecipeImportError) as caught:
            recipe_import.fetch_draft(_URL, client, _resolver())
        self.assertIn("robots", str(caught.exception).lower())
        self.assertFalse([u for u in seen if "/recipes/" in u])

    def test_missing_robots_txt_allows_the_fetch(self) -> None:
        def handler(request: httpx.Request) -> httpx.Response:
            if request.url.path == "/robots.txt":
                return httpx.Response(404)
            return _site()(request)

        client, _seen = _client(handler)
        draft = recipe_import.fetch_draft(_URL, client, _resolver())
        self.assertEqual(draft.name, "Easy curry")

    def test_unreadable_robots_txt_refuses_the_fetch(self) -> None:
        def handler(request: httpx.Request) -> httpx.Response:
            if request.url.path == "/robots.txt":
                return httpx.Response(503)
            return _site()(request)

        client, _seen = _client(handler)
        with self.assertRaises(recipe_import.RecipeImportError):
            recipe_import.fetch_draft(_URL, client, _resolver())

    def test_oversize_pages_are_refused(self) -> None:
        big = "x" * (3 * 1024 * 1024)
        client, _seen = _client(_site(page=big))
        with self.assertRaises(recipe_import.RecipeImportError):
            recipe_import.fetch_draft(_URL, client, _resolver())

    def test_timeouts_are_reported_not_raised(self) -> None:
        def handler(request: httpx.Request) -> httpx.Response:
            if request.url.path == "/robots.txt":
                return httpx.Response(404)
            raise httpx.ReadTimeout("slow", request=request)

        client, _seen = _client(handler)
        with self.assertRaises(recipe_import.RecipeImportError):
            recipe_import.fetch_draft(_URL, client, _resolver())

    def test_http_errors_are_reported(self) -> None:
        def handler(request: httpx.Request) -> httpx.Response:
            if request.url.path == "/robots.txt":
                return httpx.Response(404)
            return httpx.Response(500)

        client, _seen = _client(handler)
        with self.assertRaises(recipe_import.RecipeImportError):
            recipe_import.fetch_draft(_URL, client, _resolver())

    def test_follows_a_redirect_to_another_public_page(self) -> None:
        def handler(request: httpx.Request) -> httpx.Response:
            if request.url.path == "/old":
                return httpx.Response(
                    301, headers={"location": "https://www.bbcgoodfood.com/new"}
                )
            return _site()(request)

        client, seen = _client(handler)
        draft = recipe_import.fetch_draft(
            "https://www.bbcgoodfood.com/old", client, _resolver()
        )
        self.assertEqual(draft.name, "Easy curry")
        self.assertIn("https://www.bbcgoodfood.com/new", seen)

    def test_redirect_to_a_private_host_is_refused(self) -> None:
        def handler(request: httpx.Request) -> httpx.Response:
            if request.url.path == "/robots.txt":
                return httpx.Response(404)
            return httpx.Response(
                302, headers={"location": "http://internal.lan/admin"}
            )

        client, seen = _client(handler)
        resolver = _resolver({"internal.lan": ["192.168.1.5"]})
        with self.assertRaises(recipe_import.RecipeImportError):
            recipe_import.fetch_draft(_URL, client, resolver)
        self.assertFalse([u for u in seen if "internal.lan" in u])

    def test_redirect_to_a_non_web_scheme_is_refused(self) -> None:
        def handler(request: httpx.Request) -> httpx.Response:
            if request.url.path == "/robots.txt":
                return httpx.Response(404)
            return httpx.Response(
                302, headers={"location": "file:///etc/passwd"}
            )

        client, _seen = _client(handler)
        with self.assertRaises(recipe_import.RecipeImportError):
            recipe_import.fetch_draft(_URL, client, _resolver())

    def test_redirect_loops_stop_after_three_hops(self) -> None:
        def handler(request: httpx.Request) -> httpx.Response:
            if request.url.path == "/robots.txt":
                return httpx.Response(404)
            return httpx.Response(302, headers={"location": _URL})

        client, seen = _client(handler)
        with self.assertRaises(recipe_import.RecipeImportError):
            recipe_import.fetch_draft(_URL, client, _resolver())
        self.assertLessEqual(len([u for u in seen if u == _URL]), 4)


if __name__ == "__main__":
    unittest.main()
