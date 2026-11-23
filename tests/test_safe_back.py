"""Tests for meals.safe_back: where a form may send you back to."""

import unittest

from diary_app.web import meals


class SafeBackTest(unittest.TestCase):
    """safe_back rebuilds the address from validated parts."""

    def test_a_recipe_page_is_kept(self) -> None:
        self.assertEqual(meals.safe_back("/recipes/12"), "/recipes/12")

    def test_the_meals_page_with_week_and_tab_is_kept(self) -> None:
        for tab in ("ideas", "favourites", "mine"):
            url = f"/meals?week=2030-01-07&tab={tab}"
            self.assertEqual(meals.safe_back(url), url)

    def test_the_meals_page_with_just_a_week_or_nothing_is_kept(self) -> None:
        self.assertEqual(
            meals.safe_back("/meals?week=2030-01-07"), "/meals?week=2030-01-07"
        )
        self.assertEqual(meals.safe_back("/meals"), "/meals")

    def test_anything_else_goes_to_the_default(self) -> None:
        for bad in (
            "",
            "https://evil.example/",
            "//evil.example/",
            "/\\evil.example/",
            "/meals@evil.example",
            "/meals?week=2030-13-45",
            "/meals?week=2030-01-07&tab=<script>",
            "/meals?week=2030-01-07&tab=ideas&x=1",
            "/recipes/12/edit",
            "/recipes/abc",
            "/recipes/1234567890123",
            "/recipes/١٢",
            "/settings",
        ):
            self.assertEqual(meals.safe_back(bad), "/meals", repr(bad))

    def test_the_default_can_be_chosen(self) -> None:
        self.assertEqual(meals.safe_back("nope", default="/home"), "/home")


if __name__ == "__main__":
    unittest.main()
