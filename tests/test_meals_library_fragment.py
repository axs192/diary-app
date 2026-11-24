"""Tests for the Meals library fragment, which the tabs swap in place."""

import html
import re
import unittest

from tests.test_meals_web import _DAYS, _MONDAY, _WEEK, _MealsTestCase

_FRAGMENT = f"/meals/library?week={_MONDAY.isoformat()}"
_TABS = ("ideas", "favourites", "mine")


def _recipe_ids(markup: str) -> list[int]:
    """The recipes listed in the library, in order."""
    return [
        int(found)
        for found in re.findall(
            r'class="lib-name" href="/recipes/(\d+)"', markup
        )
    ]


class FragmentAccessTest(_MealsTestCase):
    def test_it_needs_the_household_pin(self) -> None:
        response = self.client.get(_FRAGMENT)
        self.assertEqual(response.status_code, 303)
        self.assertEqual(response.headers["location"], "/login")


class FragmentContentTest(_MealsTestCase):
    def setUp(self) -> None:
        super().setUp()
        self.log_in()
        self.first = self.add_recipe("First dish", style="Italian")
        self.second = self.add_recipe("Second dish", style="Mexican")
        self.third = self.add_recipe("Third dish", style="Indian")
        self.plan(_DAYS[0], self.third)
        self.client.post(
            f"/recipes/{self.second}/favourite", data={"favourite": "1"}
        )

    def test_it_is_a_fragment_not_a_page(self) -> None:
        text = self.client.get(f"{_FRAGMENT}&tab=ideas").text
        for page_only in ("<html", "<head", "<body", "topbar", "<script"):
            self.assertNotIn(page_only, text)
        self.assertIn("First dish", text)

    def test_each_tab_lists_the_same_meals_as_the_full_page(self) -> None:
        for tab in _TABS:
            full = self.client.get(f"{_WEEK}&tab={tab}").text
            fragment = self.client.get(f"{_FRAGMENT}&tab={tab}").text
            self.assertEqual(_recipe_ids(fragment), _recipe_ids(full), tab)
            self.assertTrue(_recipe_ids(fragment) or tab == "favourites", tab)

    def test_the_tabs_filter_as_they_do_on_the_page(self) -> None:
        ideas = _recipe_ids(self.client.get(f"{_FRAGMENT}&tab=ideas").text)
        self.assertNotIn(self.third, ideas)  # already planned this week
        favourites = _recipe_ids(
            self.client.get(f"{_FRAGMENT}&tab=favourites").text
        )
        self.assertEqual(favourites, [self.second])
        mine = _recipe_ids(self.client.get(f"{_FRAGMENT}&tab=mine").text)
        self.assertCountEqual(mine, [self.first, self.second, self.third])

    def test_an_unknown_tab_falls_back_to_ideas(self) -> None:
        odd = self.client.get(f"{_FRAGMENT}&tab=zzz")
        ideas = self.client.get(f"{_FRAGMENT}&tab=ideas")
        self.assertEqual(odd.status_code, 200)
        self.assertEqual(_recipe_ids(odd.text), _recipe_ids(ideas.text))

    def test_without_a_week_it_uses_the_current_one(self) -> None:
        self.assertEqual(self.client.get("/meals/library").status_code, 200)

    def test_the_forms_send_you_back_to_the_requested_tab(self) -> None:
        for tab in _TABS:
            text = html.unescape(self.client.get(f"{_FRAGMENT}&tab={tab}").text)
            backs = re.findall(r'name="back" value="([^"]*)"', text)
            self.assertTrue(backs or tab == "favourites", tab)
            for back in backs:
                self.assertEqual(back, f"{_WEEK}&tab={tab}")

    def test_a_chosen_day_is_preselected(self) -> None:
        text = self.client.get(f"{_FRAGMENT}&tab=ideas&day=2030-01-10").text
        self.assertRegex(text, r'<option value="2030-01-10" selected')

    def test_empty_tabs_say_so(self) -> None:
        favourites = self.client.get(f"{_FRAGMENT}&tab=favourites").text
        self.assertNotIn("No favourites yet", favourites)  # one exists
        self.client.post(
            f"/recipes/{self.second}/favourite", data={"favourite": "0"}
        )
        favourites = self.client.get(f"{_FRAGMENT}&tab=favourites").text
        self.assertIn("No favourites yet", favourites)


class FragmentEmptyLibraryTest(_MealsTestCase):
    def test_an_empty_library_says_so(self) -> None:
        self.log_in()
        text = self.client.get(f"{_FRAGMENT}&tab=mine").text
        self.assertIn("Nothing here yet", text)


class TabLinkTest(_MealsTestCase):
    """The tabs stay real links, upgraded with the fragment's address."""

    def _tab_links(self, page: str) -> dict[str, str]:
        links = re.findall(r'<a class="btn btn-small tab"([^>]*)>', page)
        found = {}
        for attrs in links:
            href = re.search(r'href="([^"]*)"', attrs)
            fragment = re.search(r'data-fragment="([^"]*)"', attrs)
            self.assertIsNotNone(href)
            self.assertIsNotNone(fragment, attrs)
            if href and fragment:
                tab = re.search(r"tab=(\w+)", html.unescape(href.group(1)))
                assert tab is not None
                found[tab.group(1)] = html.unescape(fragment.group(1))
        return found

    def test_every_tab_keeps_its_href_and_gains_a_fragment_address(
        self,
    ) -> None:
        self.log_in()
        found = self._tab_links(self.client.get(f"{_WEEK}&tab=ideas").text)
        self.assertEqual(set(found), set(_TABS))
        for tab, fragment in found.items():
            self.assertEqual(fragment, f"{_FRAGMENT}&tab={tab}")

    def test_a_chosen_day_is_carried_into_the_fragment_address(self) -> None:
        self.log_in()
        page = self.client.get(f"{_WEEK}&tab=ideas&day=2030-01-10").text
        for tab, fragment in self._tab_links(page).items():
            self.assertEqual(fragment, f"{_FRAGMENT}&tab={tab}&day=2030-01-10")

    def test_the_list_sits_in_a_container_the_script_can_replace(self) -> None:
        self.log_in()
        self.add_recipe()
        page = self.client.get(f"{_WEEK}&tab=ideas").text
        container = re.search(
            r'<div id="library-list"[^>]*>(.*)</div>\s*</section>',
            page,
            re.DOTALL,
        )
        self.assertIsNotNone(container)
        self.assertIn("lib-row", container.group(1) if container else "")


if __name__ == "__main__":
    unittest.main()
