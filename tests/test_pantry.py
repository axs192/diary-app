"""Tests for the diary_app.pantry public interface."""

import dataclasses
import datetime
import unittest
from fractions import Fraction

from diary_app import db, pantry, recipes
from diary_app.ingredients import Amount

_TODAY = datetime.date(2026, 11, 24)


def _a(value: str | int, unit: str = "") -> Amount:
    return Amount(Fraction(value), unit)


class _PantryTestCase(unittest.TestCase):
    def setUp(self) -> None:
        self.conn = db.connect(":memory:")

    def stock(
        self,
        name: str,
        amount: Amount | None = None,
        *,
        shelf: str = "Cupboard",
        days_left: int | None = None,
    ) -> pantry.PantryItem:
        expires = (
            None
            if days_left is None
            else _TODAY + datetime.timedelta(days=days_left)
        )
        return pantry.add(
            self.conn,
            name,
            amount or _a(1),
            shelf=shelf,
            expires_on=expires,
        )


class StoringTest(_PantryTestCase):
    def test_an_item_keeps_everything_it_was_given(self) -> None:
        item = pantry.add(
            self.conn,
            "  Chopped tomatoes ",
            _a(4, "tin"),
            shelf="Cupboard",
            expires_on=datetime.date(2027, 3, 1),
        )
        self.assertEqual(pantry.get(self.conn, item.id), item)
        self.assertEqual(item.name, "Chopped tomatoes")
        self.assertEqual(item.amount, _a(4, "tin"))
        self.assertEqual(item.shelf, "Cupboard")
        self.assertEqual(item.expires_on, datetime.date(2027, 3, 1))

    def test_fractions_and_grams_are_kept_exactly(self) -> None:
        item = self.stock("Pasta", _a("1135/2", "g"))
        self.assertEqual(
            pantry.get(self.conn, item.id).amount, _a("1135/2", "g")
        )

    def test_the_shelf_defaults_to_the_cupboard_and_the_date_to_none(
        self,
    ) -> None:
        item = pantry.add(self.conn, "Rice", _a(500, "g"))
        self.assertEqual(item.shelf, "Cupboard")
        self.assertIsNone(item.expires_on)

    def test_none_left_is_a_valid_amount(self) -> None:
        item = self.stock("Flour", _a(0, "g"))
        self.assertTrue(item.amount.is_zero)

    def test_bad_details_are_refused_and_nothing_is_stored(self) -> None:
        bad = [
            {"name": "   ", "shelf": "Cupboard"},
            {"name": "x" * 61, "shelf": "Cupboard"},
            {"name": "Rice", "shelf": "Garage"},
        ]
        for fields in bad:
            with (
                self.subTest(fields=fields),
                self.assertRaises(pantry.InvalidPantryItemError),
            ):
                pantry.add(
                    self.conn, fields["name"], _a(1), shelf=fields["shelf"]
                )
        self.assertEqual(pantry.items(self.conn), [])

    def test_update_replaces_the_details_and_keeps_the_id(self) -> None:
        item = self.stock("Rice", _a(500, "g"))
        changed = pantry.update(
            self.conn,
            dataclasses.replace(
                item,
                name="Basmati rice",
                amount=_a(1, "pack"),
                shelf="Baking",
                expires_on=_TODAY,
            ),
        )
        self.assertEqual(changed.id, item.id)
        self.assertEqual(pantry.get(self.conn, item.id), changed)
        self.assertEqual(changed.name, "Basmati rice")
        self.assertEqual(changed.shelf, "Baking")
        self.assertEqual(changed.amount, _a(1, "pack"))

    def test_update_validates_like_add(self) -> None:
        item = self.stock("Rice")
        with self.assertRaises(pantry.InvalidPantryItemError):
            pantry.update(self.conn, dataclasses.replace(item, name=""))
        self.assertEqual(pantry.get(self.conn, item.id).name, "Rice")

    def test_a_missing_item_is_a_lookup_error(self) -> None:
        ghost = pantry.PantryItem(99, "x", "Cupboard", _a(1), None)
        with self.assertRaises(LookupError):
            pantry.get(self.conn, 99)
        with self.assertRaises(LookupError):
            pantry.update(self.conn, ghost)
        with self.assertRaises(LookupError):
            pantry.adjust(self.conn, 99, Fraction(1))

    def test_delete_removes_it_and_is_harmless_twice(self) -> None:
        item = self.stock("Rice")
        pantry.delete(self.conn, item.id)
        pantry.delete(self.conn, item.id)
        self.assertEqual(pantry.items(self.conn), [])


class AdjustTest(_PantryTestCase):
    def test_adjust_adds_and_takes_away_in_the_items_own_unit(self) -> None:
        item = self.stock("Tomatoes", _a(4, "tin"))
        self.assertEqual(
            pantry.adjust(self.conn, item.id, Fraction(1)).amount, _a(5, "tin")
        )
        self.assertEqual(
            pantry.adjust(self.conn, item.id, Fraction(-2)).amount, _a(3, "tin")
        )
        self.assertEqual(pantry.get(self.conn, item.id).amount, _a(3, "tin"))

    def test_it_stops_at_zero(self) -> None:
        item = self.stock("Tomatoes", _a(1, "tin"))
        self.assertEqual(
            pantry.adjust(self.conn, item.id, Fraction(-5)).amount, _a(0, "tin")
        )

    def test_it_works_with_fractions(self) -> None:
        item = self.stock("Cheese", _a(100, "g"))
        got = pantry.adjust(self.conn, item.id, Fraction(-567, 20))
        self.assertEqual(got.amount, _a(100, "g").minus(_a("567/20", "g")))


class ListingTest(_PantryTestCase):
    def test_soonest_use_by_first_then_undated_then_none_left(self) -> None:
        self.stock("Undated b")
        self.stock("Later", days_left=30)
        self.stock("Empty", _a(0, "g"), days_left=1)
        self.stock("Soon", days_left=2)
        self.stock("Undated a")
        names = [i.name for i in pantry.items(self.conn)]
        self.assertEqual(
            names, ["Soon", "Later", "Undated a", "Undated b", "Empty"]
        )

    def test_by_shelf_follows_the_shelf_order_and_skips_empty_shelves(
        self,
    ) -> None:
        self.stock("Milk", shelf="Fridge")
        self.stock("Cumin", shelf="Spices")
        self.stock("Pasta", shelf="Cupboard")
        self.stock("Rice", shelf="Cupboard")
        grouped = pantry.by_shelf(pantry.items(self.conn))
        self.assertEqual(
            [shelf for shelf, _ in grouped], ["Fridge", "Cupboard", "Spices"]
        )
        self.assertEqual([i.name for i in grouped[1][1]], ["Pasta", "Rice"])


class UseByTest(_PantryTestCase):
    def check(
        self,
        days_left: int,
        text: str,
        chip: str,
        urgency: str,
        shelf: str = "Fridge",
    ) -> None:
        item = self.stock("Thing", shelf=shelf, days_left=days_left)
        got = pantry.use_by(item, _TODAY)
        assert got is not None
        self.assertEqual(
            (got.text, got.chip, got.urgency), (text, chip, urgency)
        )

    def test_fridge_items_say_use_by_with_a_chip_that_gets_calmer(self) -> None:
        self.check(-2, "Use by 22 Nov", "Expired", "expired")
        self.check(0, "Use by 24 Nov", "Today", "expired")
        self.check(1, "Use by 25 Nov", "Tomorrow", "soon")
        self.check(3, "Use by 27 Nov", "3 days", "soon")
        self.check(4, "Use by 28 Nov", "4 days", "later")
        self.check(14, "Use by 8 Dec", "14 days", "later")
        self.check(15, "Use by 9 Dec", "", "none")

    def test_other_shelves_say_best_before(self) -> None:
        self.check(
            10, "Best before 4 Dec", "10 days", "later", shelf="Cupboard"
        )

    def test_a_date_in_another_year_shows_the_year(self) -> None:
        item = pantry.add(
            self.conn, "Rice", _a(1), expires_on=datetime.date(2027, 3, 12)
        )
        got = pantry.use_by(item, _TODAY)
        assert got is not None
        self.assertEqual(got.text, "Best before 12 Mar 2027")

    def test_no_date_means_nothing_to_show(self) -> None:
        self.assertIsNone(pantry.use_by(self.stock("Rice"), _TODAY))

    def test_use_soon_is_expired_or_due_within_three_days_in_date_order(
        self,
    ) -> None:
        self.stock("Fine", days_left=10)
        self.stock("Undated")
        self.stock("Gone", _a(0), days_left=1)  # nothing left to use up
        self.stock("Three", days_left=3)
        self.stock("Four", days_left=4)
        self.stock("Old", days_left=-1)
        soon = pantry.use_soon(pantry.items(self.conn), _TODAY)
        self.assertEqual([i.name for i in soon], ["Old", "Three"])


class MatchTest(_PantryTestCase):
    def test_finds_the_item_an_ingredient_calls_for(self) -> None:
        onions = self.stock("Onions")
        self.stock("Pasta")
        self.assertEqual(
            pantry.match(pantry.items(self.conn), "large red onions"), onions
        )

    def test_no_match_is_none(self) -> None:
        self.stock("Onions")
        self.assertIsNone(pantry.match(pantry.items(self.conn), "garlic"))

    def test_the_more_specific_item_wins(self) -> None:
        self.stock("Milk")
        coconut = self.stock("Coconut milk")
        self.assertEqual(
            pantry.match(pantry.items(self.conn), "coconut milk"), coconut
        )

    def test_an_item_with_none_left_still_matches(self) -> None:
        gone = self.stock("Onions", _a(0))
        self.assertEqual(pantry.match(pantry.items(self.conn), "onions"), gone)


class MealsUsingTest(_PantryTestCase):
    def recipe(self, name: str, *lines: str) -> recipes.Recipe:
        return recipes.add(
            self.conn, recipes.RecipeDraft(name=name, ingredients=lines)
        )

    def test_recipes_are_ranked_by_how_many_of_the_items_they_use(self) -> None:
        self.recipe("Soup", "2 onions", "1 litre stock")
        self.recipe("Pasta bake", "200g pasta", "1 onion", "1 tin tomatoes")
        self.recipe("Salad", "lettuce")
        wanted = [
            self.stock("Onions"),
            self.stock("Tomatoes"),
            self.stock("Pasta"),
        ]
        got = pantry.meals_using(self.conn, wanted)
        self.assertEqual([r.name for r in got], ["Pasta bake", "Soup"])

    def test_the_limit_applies(self) -> None:
        for n in range(4):
            self.recipe(f"Meal {n}", "2 onions")
        got = pantry.meals_using(self.conn, [self.stock("Onions")], limit=2)
        self.assertEqual(len(got), 2)

    def test_items_with_none_left_are_not_counted(self) -> None:
        self.recipe("Soup", "2 onions")
        gone = self.stock("Onions", _a(0))
        self.assertEqual(pantry.meals_using(self.conn, [gone]), [])

    def test_no_items_means_no_suggestions(self) -> None:
        self.recipe("Soup", "2 onions")
        self.assertEqual(pantry.meals_using(self.conn, []), [])


if __name__ == "__main__":
    unittest.main()
