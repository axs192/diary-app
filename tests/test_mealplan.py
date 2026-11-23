"""Tests for the diary_app.mealplan public interface."""

import datetime
import unittest

from diary_app import db, mealplan, recipes

_MON = datetime.date(2026, 11, 23)  # a Monday
_TUE = _MON + datetime.timedelta(days=1)
_SUN = _MON + datetime.timedelta(days=6)


class MealPlanTest(unittest.TestCase):
    """mealplan holds one dinner per day."""

    def setUp(self) -> None:
        self.conn = db.connect(":memory:")

    def _recipe(self, name: str, *tags: str) -> recipes.Recipe:
        return recipes.add(self.conn, recipes.RecipeDraft(name=name, tags=tags))

    def test_a_week_always_has_seven_days_monday_to_sunday(self) -> None:
        days = mealplan.week(self.conn, _MON)
        self.assertEqual(len(days), 7)
        self.assertEqual(days[0].day, _MON)
        self.assertEqual(days[6].day, _SUN)
        self.assertTrue(all(d.recipe is None for d in days))

    def test_any_date_selects_its_monday_to_sunday_week(self) -> None:
        days = mealplan.week(self.conn, _MON + datetime.timedelta(days=3))
        self.assertEqual(days[0].day, _MON)

    def test_set_meal_appears_on_that_day(self) -> None:
        pasta = self._recipe("Pasta")
        mealplan.set_meal(self.conn, _TUE, pasta.id)
        days = mealplan.week(self.conn, _MON)
        self.assertIsNone(days[0].recipe)
        self.assertEqual(days[1].recipe, pasta)

    def test_set_meal_replaces_the_day(self) -> None:
        pasta = self._recipe("Pasta")
        curry = self._recipe("Curry")
        mealplan.set_meal(self.conn, _TUE, pasta.id)
        mealplan.set_meal(self.conn, _TUE, curry.id)
        self.assertEqual(mealplan.week(self.conn, _MON)[1].recipe, curry)

    def test_set_meal_with_unknown_recipe_raises_lookup_error(self) -> None:
        with self.assertRaises(LookupError):
            mealplan.set_meal(self.conn, _TUE, 99)

    def test_clear_day_empties_only_that_day(self) -> None:
        pasta = self._recipe("Pasta")
        mealplan.set_meal(self.conn, _MON, pasta.id)
        mealplan.set_meal(self.conn, _TUE, pasta.id)
        mealplan.clear_day(self.conn, _TUE)
        days = mealplan.week(self.conn, _MON)
        self.assertEqual(days[0].recipe, pasta)
        self.assertIsNone(days[1].recipe)

    def test_clear_week_leaves_other_weeks_alone(self) -> None:
        pasta = self._recipe("Pasta")
        next_monday = _MON + datetime.timedelta(days=7)
        mealplan.set_meal(self.conn, _MON, pasta.id)
        mealplan.set_meal(self.conn, next_monday, pasta.id)
        mealplan.clear_week(self.conn, _MON)
        self.assertTrue(
            all(d.recipe is None for d in mealplan.week(self.conn, _MON))
        )
        self.assertEqual(mealplan.week(self.conn, next_monday)[0].recipe, pasta)

    def test_deleting_a_recipe_empties_its_days(self) -> None:
        pasta = self._recipe("Pasta")
        mealplan.set_meal(self.conn, _MON, pasta.id)
        recipes.delete(self.conn, pasta.id)
        self.assertIsNone(mealplan.week(self.conn, _MON)[0].recipe)

    def test_recent_recipe_ids_covers_the_weeks_before_a_date(self) -> None:
        old = self._recipe("Old")
        recent = self._recipe("Recent")
        current = self._recipe("Current")
        mealplan.set_meal(self.conn, _MON - datetime.timedelta(days=15), old.id)
        mealplan.set_meal(
            self.conn, _MON - datetime.timedelta(days=14), recent.id
        )
        mealplan.set_meal(self.conn, _MON, current.id)
        found = mealplan.recent_recipe_ids(self.conn, _MON, weeks=2)
        self.assertEqual(found, {recent.id})

    def test_balance_counts_tags_across_the_week(self) -> None:
        veg = self._recipe("Veg", "Veg-led")
        fish = self._recipe("Fish", "Oily fish", "Quick")
        treat = self._recipe("Burger", "Treat night")
        mealplan.set_meal(self.conn, _MON, veg.id)
        mealplan.set_meal(self.conn, _TUE, veg.id)
        mealplan.set_meal(self.conn, _TUE + datetime.timedelta(1), fish.id)
        mealplan.set_meal(self.conn, _SUN, treat.id)
        bars = {
            b.label: b.count
            for b in mealplan.balance(mealplan.week(self.conn, _MON))
        }
        self.assertEqual(
            bars, {"Veg-led dinners": 2, "Oily fish": 1, "Treat nights": 1}
        )

    def test_balance_of_an_empty_week_is_all_zero(self) -> None:
        bars = mealplan.balance(mealplan.week(self.conn, _MON))
        self.assertEqual([b.count for b in bars], [0, 0, 0])

    def test_treat_nights_are_a_limit_the_others_are_goals(self) -> None:
        bars = {
            b.label: b for b in mealplan.balance(mealplan.week(self.conn, _MON))
        }
        self.assertTrue(bars["Treat nights"].at_most)
        self.assertFalse(bars["Veg-led dinners"].at_most)


if __name__ == "__main__":
    unittest.main()
