"""Tests for mealplan.cook and uncook ("Cooked it" uses up pantry food)."""

import datetime
import unittest
from fractions import Fraction

from diary_app import db, mealplan, pantry, recipes
from diary_app.ingredients import Amount

_MON = datetime.date(2030, 1, 7)
_TUE = _MON + datetime.timedelta(days=1)


def _a(value: str | int, unit: str = "") -> Amount:
    return Amount(Fraction(value), unit)


class CookingTest(unittest.TestCase):
    def setUp(self) -> None:
        self.conn = db.connect(":memory:")

    def plan(self, *lines: str, day: datetime.date = _MON) -> recipes.Recipe:
        recipe = recipes.add(
            self.conn, recipes.RecipeDraft(name="Dinner", ingredients=lines)
        )
        mealplan.set_meal(self.conn, day, recipe.id)
        return recipe

    def stock(self, name: str, amount: Amount) -> pantry.PantryItem:
        return pantry.add(self.conn, name, amount)

    def have(self, item: pantry.PantryItem) -> Amount:
        return pantry.get(self.conn, item.id).amount

    def cooked(self, day: datetime.date = _MON) -> bool:
        return next(
            d for d in mealplan.week(self.conn, _MON) if d.day == day
        ).cooked

    # --- cook ---------------------------------------------------------

    def test_cooking_takes_what_the_recipe_uses_out_of_the_pantry(self) -> None:
        self.plan("2 large onions", "1 tin chopped tomatoes", "200g pasta")
        onions = self.stock("Onions", _a(3))
        tomatoes = self.stock("Chopped tomatoes", _a(4, "tin"))
        pasta = self.stock("Pasta", _a(500, "g"))
        mealplan.cook(self.conn, _MON)
        self.assertEqual(self.have(onions), _a(1))
        self.assertEqual(self.have(tomatoes), _a(3, "tin"))
        self.assertEqual(self.have(pasta), _a(300, "g"))
        self.assertTrue(self.cooked())

    def test_it_reports_what_it_took(self) -> None:
        self.plan("2 onions", "200g pasta")
        self.stock("Onions", _a(3))
        self.stock("Pasta", _a(500, "g"))
        took = mealplan.cook(self.conn, _MON)
        self.assertEqual(
            sorted((name, amount.format()) for name, amount in took),
            [("Onions", "2"), ("Pasta", "200 g")],
        )

    def test_imperial_lines_take_the_metric_equivalent(self) -> None:
        self.plan("8oz pasta")
        pasta = self.stock("Pasta", _a(500, "g"))
        mealplan.cook(self.conn, _MON)
        self.assertEqual(
            self.have(pasta), _a(500, "g").minus(_a("5670/25", "g"))
        )

    def test_lines_in_other_units_and_unreadable_lines_are_left_alone(
        self,
    ) -> None:
        self.plan("1 tin chopped tomatoes", "salt and pepper", "2 tbsp oil")
        tomatoes = self.stock("Chopped tomatoes", _a(2, "jar"))
        salt = self.stock("Salt", _a(1, "jar"))
        mealplan.cook(self.conn, _MON)
        self.assertEqual(
            self.have(tomatoes), _a(2, "jar")
        )  # a jar is not a tin
        self.assertEqual(self.have(salt), _a(1, "jar"))  # unreadable line
        self.assertTrue(self.cooked())

    def test_it_never_takes_more_than_there_is(self) -> None:
        self.plan("1 onion", "2 large onions")
        onions = self.stock("Onions", _a(2))
        mealplan.cook(self.conn, _MON)
        self.assertEqual(self.have(onions), _a(0))

    def test_cooking_twice_takes_nothing_more(self) -> None:
        self.plan("1 onion")
        onions = self.stock("Onions", _a(3))
        mealplan.cook(self.conn, _MON)
        self.assertEqual(mealplan.cook(self.conn, _MON), [])
        self.assertEqual(self.have(onions), _a(2))

    def test_a_day_with_no_meal_does_nothing(self) -> None:
        onions = self.stock("Onions", _a(3))
        self.assertEqual(mealplan.cook(self.conn, _MON), [])
        self.assertEqual(self.have(onions), _a(3))
        self.assertFalse(self.cooked())

    def test_only_the_cooked_day_is_marked(self) -> None:
        self.plan("1 onion")
        self.plan("1 onion", day=_TUE)
        mealplan.cook(self.conn, _TUE)
        self.assertFalse(self.cooked(_MON))
        self.assertTrue(self.cooked(_TUE))

    # --- uncook -------------------------------------------------------

    def test_undo_puts_back_exactly_what_was_taken(self) -> None:
        self.plan("1 onion", "2 large onions")
        onions = self.stock("Onions", _a(2))  # only 2 of the 3 wanted
        mealplan.cook(self.conn, _MON)
        mealplan.uncook(self.conn, _MON)
        self.assertEqual(self.have(onions), _a(2))  # not 3
        self.assertFalse(self.cooked())

    def test_undo_on_a_day_that_was_not_cooked_does_nothing(self) -> None:
        self.plan("1 onion")
        onions = self.stock("Onions", _a(3))
        mealplan.uncook(self.conn, _MON)
        self.assertEqual(self.have(onions), _a(3))

    def test_undo_copes_with_an_item_that_has_since_been_deleted(self) -> None:
        self.plan("1 onion")
        onions = self.stock("Onions", _a(3))
        mealplan.cook(self.conn, _MON)
        pantry.delete(self.conn, onions.id)
        mealplan.uncook(self.conn, _MON)
        self.assertFalse(self.cooked())

    def test_it_can_be_cooked_again_after_an_undo(self) -> None:
        self.plan("1 onion")
        onions = self.stock("Onions", _a(3))
        mealplan.cook(self.conn, _MON)
        mealplan.uncook(self.conn, _MON)
        mealplan.cook(self.conn, _MON)
        self.assertEqual(self.have(onions), _a(2))

    # --- changing the plan --------------------------------------------

    def test_changing_the_meal_clears_the_mark_but_not_the_stock(self) -> None:
        self.plan("1 onion")
        onions = self.stock("Onions", _a(3))
        mealplan.cook(self.conn, _MON)
        other = recipes.add(self.conn, recipes.RecipeDraft(name="Other"))
        mealplan.set_meal(self.conn, _MON, other.id)
        self.assertFalse(self.cooked())
        self.assertEqual(self.have(onions), _a(2))  # it was eaten

    def test_removing_the_day_or_the_week_clears_the_mark(self) -> None:
        self.plan("1 onion")
        self.plan("1 onion", day=_TUE)
        self.stock("Onions", _a(5))
        mealplan.cook(self.conn, _MON)
        mealplan.cook(self.conn, _TUE)
        mealplan.clear_day(self.conn, _MON)
        self.assertFalse(self.cooked(_MON))
        mealplan.clear_week(self.conn, _MON)
        self.assertFalse(self.cooked(_TUE))
        self.plan("1 onion")  # planned again: a fresh, uncooked day
        self.assertFalse(self.cooked(_MON))


if __name__ == "__main__":
    unittest.main()
