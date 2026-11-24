"""Tests for the diary_app.shopping public interface."""

import dataclasses
import datetime
import unittest
from fractions import Fraction

from diary_app import db, mealplan, pantry, recipes, shopping
from diary_app.ingredients import Amount

_MON = datetime.date(2030, 1, 7)
_TUE = _MON + datetime.timedelta(days=1)
_WED = _MON + datetime.timedelta(days=2)
_NEXT_MON = _MON + datetime.timedelta(days=7)


def _a(value: str | int, unit: str = "") -> Amount:
    return Amount(Fraction(value), unit)


class _ShoppingTestCase(unittest.TestCase):
    def setUp(self) -> None:
        self.conn = db.connect(":memory:")

    def plan(self, day: datetime.date, *lines: str) -> recipes.Recipe:
        recipe = recipes.add(
            self.conn,
            recipes.RecipeDraft(name=f"Dinner {day}", ingredients=lines),
        )
        mealplan.set_meal(self.conn, day, recipe.id)
        return recipe

    def stock(
        self, name: str, amount: Amount, shelf: str = "Cupboard"
    ) -> pantry.PantryItem:
        return pantry.add(self.conn, name, amount, shelf=shelf)

    def generate(self, *days: datetime.date) -> shopping.ShoppingList:
        return shopping.generate(self.conn, _MON, days)

    @staticmethod
    def to_buy(listing: shopping.ShoppingList) -> dict[str, str]:
        """Name -> amount written out, for every meal row still to buy."""
        return {
            item.name: item.amount.format() if item.amount else ""
            for aisle in listing.aisles
            for item in aisle.items
        }


class GenerateTest(_ShoppingTestCase):
    def test_only_the_chosen_days_count(self) -> None:
        self.plan(_MON, "2 onions")
        self.plan(_TUE, "3 onions")
        self.plan(_WED, "5 onions")
        self.assertEqual(
            self.to_buy(self.generate(_MON, _TUE)), {"Onions": "5"}
        )

    def test_amounts_add_up_across_units_of_the_same_kind(self) -> None:
        self.plan(_MON, "200g pasta")
        self.plan(_TUE, "8oz pasta")
        self.assertEqual(
            self.to_buy(self.generate(_MON, _TUE)), {"Pasta": "427 g"}
        )

    def test_the_same_thing_in_different_units_stays_separate(self) -> None:
        self.plan(_MON, "1 tin tomatoes")
        self.plan(_TUE, "200g tomatoes")
        got = self.generate(_MON, _TUE)
        listed = sorted(
            item.amount.format()
            for a in got.aisles
            for item in a.items
            if item.amount
        )
        self.assertEqual(listed, ["1 tin", "200 g"])

    def test_names_that_differ_only_by_plural_or_size_merge(self) -> None:
        self.plan(_MON, "2 onions")
        self.plan(_TUE, "1 large onion")
        self.assertEqual(
            self.to_buy(self.generate(_MON, _TUE)), {"Onions": "3"}
        )

    def test_items_are_grouped_by_aisle_in_shop_order_then_by_name(
        self,
    ) -> None:
        self.plan(
            _MON, "500g chicken breast", "2 onions", "1 loaf bread", "1 carrot"
        )
        got = self.generate(_MON)
        self.assertEqual(
            [a.name for a in got.aisles],
            ["Fruit & veg", "Meat & fish", "Bakery"],
        )
        self.assertEqual(
            [i.name for i in got.aisles[0].items], ["Carrot", "Onions"]
        )

    def test_lines_that_cannot_be_read_are_listed_as_written_once(self) -> None:
        self.plan(_MON, "salt and pepper")
        self.plan(_TUE, "salt and pepper", "Juice of 1 lemon")
        got = self.to_buy(self.generate(_MON, _TUE))
        self.assertEqual(got, {"Salt and pepper": "", "Juice of 1 lemon": ""})

    def test_an_empty_week_generates_an_empty_list(self) -> None:
        self.plan(_MON)  # a recipe with no ingredients
        got = self.generate(_MON)
        self.assertEqual((got.aisles, got.extras, got.covered), ((), (), ()))
        self.assertEqual(got.remaining, 0)

    def test_it_says_which_days_it_was_generated_for(self) -> None:
        self.plan(_MON, "1 onion")
        self.plan(_WED, "1 onion")
        got = self.generate(_WED, _MON, _WED)
        self.assertEqual(got.generated_for, (_MON, _WED))
        self.assertEqual(
            shopping.get_list(self.conn, _MON).generated_for, (_MON, _WED)
        )

    def test_bad_days_are_refused_and_change_nothing(self) -> None:
        self.plan(_MON, "2 onions")
        shopping.generate(self.conn, _MON, [_MON])
        mealplan.cook(self.conn, _MON)
        self.plan(_TUE, "1 leek")
        cases = {
            "no days": [],
            "outside the week": [_NEXT_MON],
            "no dinner planned": [_WED],
            "already cooked": [_MON],
        }
        for label, days in cases.items():
            with self.subTest(label), self.assertRaises(ValueError):
                shopping.generate(self.conn, _MON, days)
        # the earlier list is still there
        self.assertEqual(
            self.to_buy(shopping.get_list(self.conn, _MON)), {"Onions": "2"}
        )

    def test_any_date_in_the_week_stands_for_that_week(self) -> None:
        self.plan(_TUE, "2 onions")
        shopping.generate(
            self.conn, _WED, [_TUE]
        )  # a Wednesday, not the Monday
        shopping.add_extra(self.conn, _WED, "Honey")
        for any_day in (_MON, _TUE, _WED):
            got = shopping.get_list(self.conn, any_day)
            self.assertEqual(self.to_buy(got), {"Onions": "2"})
            self.assertEqual([i.name for i in got.extras], ["Honey"])
        self.assertEqual(shopping.get_list(self.conn, _NEXT_MON).aisles, ())

    def test_a_list_is_kept_per_week(self) -> None:
        self.plan(_MON, "2 onions")
        self.generate(_MON)
        other = shopping.get_list(self.conn, _NEXT_MON)
        self.assertEqual((other.aisles, other.generated_for), ((), ()))


class PantryCoverTest(_ShoppingTestCase):
    def test_enough_in_the_pantry_means_nothing_to_buy(self) -> None:
        self.plan(_MON, "2 onions")
        self.stock("Onions", _a(4))
        got = self.generate(_MON)
        self.assertEqual(got.aisles, ())
        (row,) = got.covered
        self.assertEqual(
            (row.name, row.amount, row.have), ("Onions", _a(2), "4")
        )

    def test_some_in_the_pantry_means_buy_the_shortfall(self) -> None:
        self.plan(_MON, "400g pasta")
        self.stock("Pasta", _a(100, "g"))
        got = self.generate(_MON)
        (row,) = got.aisles[0].items
        self.assertEqual((row.amount, row.have), (_a(300, "g"), "100 g"))
        self.assertEqual(got.covered, ())

    def test_what_is_needed_over_several_days_is_added_before_comparing(
        self,
    ) -> None:
        self.plan(_MON, "2 onions")
        self.plan(_TUE, "2 onions")
        self.stock("Onions", _a(3))
        (row,) = self.generate(_MON, _TUE).aisles[0].items
        self.assertEqual(row.amount, _a(1))

    def test_a_different_unit_counts_as_covered_and_says_what_you_have(
        self,
    ) -> None:
        self.plan(_MON, "1 tin chopped tomatoes")
        self.stock("Chopped tomatoes", _a(1, "jar"))
        got = self.generate(_MON)
        self.assertEqual(got.aisles, ())
        (row,) = got.covered
        self.assertEqual((row.amount, row.have), (_a(1, "tin"), "1 jar"))

    def test_nothing_in_the_pantry_or_none_left_means_buy_it_all(self) -> None:
        self.plan(_MON, "500g chicken breast", "200g flour")
        self.stock("Flour", _a(0, "g"))
        got = self.generate(_MON)
        self.assertEqual(
            self.to_buy(got), {"Chicken breast": "500 g", "Flour": "200 g"}
        )
        self.assertEqual(got.covered, ())

    def test_an_unreadable_line_is_covered_when_you_have_some(self) -> None:
        self.plan(_MON, "salt and pepper")
        self.stock("Salt", _a(1, "jar"))
        got = self.generate(_MON)
        self.assertEqual(got.aisles, ())
        self.assertEqual([r.name for r in got.covered], ["Salt and pepper"])

    def test_covered_rows_do_not_count_as_left_to_buy(self) -> None:
        self.plan(_MON, "2 onions", "1 leek")
        self.stock("Onions", _a(4))
        self.assertEqual(self.generate(_MON).remaining, 1)


class RegenerateTest(_ShoppingTestCase):
    def test_a_generated_list_does_not_follow_later_changes(self) -> None:
        self.plan(_MON, "2 onions")
        self.generate(_MON)
        self.plan(_MON, "9 leeks")  # the meal changes
        self.stock("Onions", _a(9))  # and so does the pantry
        self.assertEqual(
            self.to_buy(shopping.get_list(self.conn, _MON)), {"Onions": "2"}
        )

    def test_generating_again_replaces_the_generated_rows(self) -> None:
        self.plan(_MON, "2 onions")
        self.generate(_MON)
        self.plan(_MON, "9 leeks")
        self.assertEqual(self.to_buy(self.generate(_MON)), {"Leeks": "9"})

    def test_your_own_items_survive(self) -> None:
        self.plan(_MON, "2 onions")
        shopping.add_extra(self.conn, _MON, "Kitchen roll", _a(2, "pack"))
        got = self.generate(_MON)
        self.assertEqual([i.name for i in got.extras], ["Kitchen roll"])

    def test_ticks_survive_for_items_still_needed_in_the_same_unit(
        self,
    ) -> None:
        self.plan(_MON, "2 onions", "200g pasta")
        first = self.generate(_MON)
        for item in first.aisles[0].items + first.aisles[1].items:
            shopping.toggle(self.conn, item.id)
        self.plan(_MON, "5 onions", "1 tin pasta", "1 leek")
        got = self.generate(_MON)
        ticked = {i.name: i.ticked for a in got.aisles for i in a.items}
        self.assertEqual(
            ticked, {"Onions": True, "Pasta": False, "Leek": False}
        )


class OwnItemsTest(_ShoppingTestCase):
    def test_an_item_can_have_an_amount_or_not(self) -> None:
        shopping.add_extra(self.conn, _MON, "Kitchen roll", _a(2, "pack"))
        shopping.add_extra(self.conn, _MON, "  Honey ")
        got = shopping.get_list(self.conn, _MON).extras
        self.assertEqual(
            [(i.name, i.amount) for i in got],
            [("Kitchen roll", _a(2, "pack")), ("Honey", None)],
        )
        self.assertEqual(got[0].source, "extra")

    def test_blank_or_long_names_are_refused(self) -> None:
        for name in ("", "   ", "x" * 61):
            with (
                self.subTest(name=name),
                self.assertRaises(shopping.InvalidItemError),
            ):
                shopping.add_extra(self.conn, _MON, name)
        self.assertEqual(shopping.get_list(self.conn, _MON).extras, ())

    def test_items_belong_to_their_week(self) -> None:
        shopping.add_extra(self.conn, _MON, "Honey")
        self.assertEqual(shopping.get_list(self.conn, _NEXT_MON).extras, ())

    def test_remove_takes_it_off_and_is_harmless_twice(self) -> None:
        item = shopping.add_extra(self.conn, _MON, "Honey")
        shopping.remove_extra(self.conn, item.id)
        shopping.remove_extra(self.conn, item.id)
        self.assertEqual(shopping.get_list(self.conn, _MON).extras, ())

    def test_remove_cannot_delete_a_generated_row(self) -> None:
        self.plan(_MON, "2 onions")
        (row,) = self.generate(_MON).aisles[0].items
        shopping.remove_extra(self.conn, row.id)
        self.assertEqual(
            self.to_buy(shopping.get_list(self.conn, _MON)), {"Onions": "2"}
        )


class EditItemTest(_ShoppingTestCase):
    """Any row on the list can be corrected: its name and its amount."""

    def test_get_item_finds_a_row_by_id(self) -> None:
        item = shopping.add_extra(self.conn, _MON, "Honey", _a(1, "jar"))
        self.assertEqual(shopping.get_item(self.conn, item.id), item)
        with self.assertRaises(LookupError):
            shopping.get_item(self.conn, 999)

    def test_an_own_item_can_be_renamed_and_given_an_amount(self) -> None:
        item = shopping.add_extra(self.conn, _MON, "Honey")
        shopping.toggle(self.conn, item.id)
        got = shopping.update_item(
            self.conn,
            dataclasses.replace(
                item, name="  Runny honey ", amount=_a(2, "jar")
            ),
        )
        self.assertEqual((got.name, got.amount), ("Runny honey", _a(2, "jar")))
        self.assertEqual(shopping.get_item(self.conn, item.id), got)
        self.assertTrue(got.ticked)  # editing does not untick it

    def test_a_row_made_from_a_meal_can_be_edited_too(self) -> None:
        self.plan(_MON, "2 onions", "1 leek")
        row = next(
            i
            for a in self.generate(_MON).aisles
            for i in a.items
            if i.name == "Onions"
        )
        shopping.update_item(
            self.conn, dataclasses.replace(row, name="Red onions", amount=_a(3))
        )
        self.assertEqual(
            self.to_buy(shopping.get_list(self.conn, _MON)),
            {"Red onions": "3", "Leek": "1"},
        )

    def test_a_new_name_can_move_it_to_another_aisle(self) -> None:
        self.plan(_MON, "2 onions")
        (row,) = self.generate(_MON).aisles[0].items
        shopping.update_item(self.conn, dataclasses.replace(row, name="Milk"))
        got = shopping.get_list(self.conn, _MON)
        self.assertEqual([a.name for a in got.aisles], ["Dairy & eggs"])

    def test_the_amount_can_be_cleared(self) -> None:
        item = shopping.add_extra(self.conn, _MON, "Honey", _a(2, "jar"))
        got = shopping.update_item(
            self.conn, dataclasses.replace(item, amount=None)
        )
        self.assertIsNone(got.amount)

    def test_bad_names_are_refused_and_nothing_changes(self) -> None:
        item = shopping.add_extra(self.conn, _MON, "Honey")
        for name in ("", "   ", "x" * 61):
            with (
                self.subTest(name=name),
                self.assertRaises(shopping.InvalidItemError),
            ):
                shopping.update_item(
                    self.conn, dataclasses.replace(item, name=name)
                )
        self.assertEqual(shopping.get_item(self.conn, item.id).name, "Honey")

    def test_a_missing_item_is_a_lookup_error(self) -> None:
        item = shopping.add_extra(self.conn, _MON, "Honey")
        shopping.remove_extra(self.conn, item.id)
        with self.assertRaises(LookupError):
            shopping.update_item(self.conn, item)


class TickingTest(_ShoppingTestCase):
    def test_toggle_flips_the_tick_and_the_counts_follow(self) -> None:
        self.plan(_MON, "2 onions", "1 leek")
        shopping.add_extra(self.conn, _MON, "Honey")
        got = self.generate(_MON)
        self.assertEqual((got.remaining, got.ticked), (3, 0))
        shopping.toggle(self.conn, got.aisles[0].items[0].id)
        shopping.toggle(self.conn, got.extras[0].id)
        after = shopping.get_list(self.conn, _MON)
        self.assertEqual((after.remaining, after.ticked), (1, 2))
        shopping.toggle(self.conn, got.aisles[0].items[0].id)
        self.assertEqual(shopping.get_list(self.conn, _MON).ticked, 1)

    def test_an_unknown_item_is_a_lookup_error(self) -> None:
        with self.assertRaises(LookupError):
            shopping.toggle(self.conn, 999)


class DoneShoppingTest(_ShoppingTestCase):
    def tick_all(self) -> shopping.ShoppingList:
        got = shopping.get_list(self.conn, _MON)
        for item in [i for a in got.aisles for i in a.items] + list(got.extras):
            shopping.toggle(self.conn, item.id)
        return got

    def test_ticked_items_join_the_pantry_and_leave_the_list(self) -> None:
        self.plan(_MON, "400g pasta", "2 onions")
        self.generate(_MON)
        self.tick_all()
        self.assertEqual(shopping.done_shopping(self.conn, _MON), 2)
        stocked = {i.name: i.amount for i in pantry.items(self.conn)}
        self.assertEqual(stocked, {"Pasta": _a(400, "g"), "Onions": _a(2)})
        self.assertEqual(shopping.get_list(self.conn, _MON).aisles, ())

    def test_what_is_bought_is_added_to_a_matching_item_in_the_same_unit(
        self,
    ) -> None:
        self.plan(_MON, "400g pasta")
        pasta = self.stock("Pasta", _a(100, "g"))
        self.generate(_MON)  # shortfall of 300 g
        self.tick_all()
        shopping.done_shopping(self.conn, _MON)
        self.assertEqual(pantry.get(self.conn, pasta.id).amount, _a(400, "g"))
        self.assertEqual(len(pantry.items(self.conn)), 1)

    def test_a_different_unit_or_name_makes_a_new_item(self) -> None:
        self.plan(_MON, "1 tin tomatoes", "1 tin coconut milk")
        self.generate(_MON)  # nothing in the pantry yet, so both are to buy
        self.stock("Tomatoes", _a(300, "g"))
        self.stock("Milk", _a(1, "tin"))
        self.tick_all()
        shopping.done_shopping(self.conn, _MON)
        listed = sorted(
            (i.name, i.amount.format()) for i in pantry.items(self.conn)
        )
        self.assertEqual(
            listed,
            [
                ("Coconut milk", "1 tin"),
                ("Milk", "1 tin"),
                ("Tomatoes", "1 tin"),
                ("Tomatoes", "300 g"),
            ],
        )

    def test_a_new_item_goes_on_the_shelf_for_its_aisle(self) -> None:
        self.plan(
            _MON,
            "300g chicken",
            "200g cheddar",
            "1 bag frozen peas",
            "1 tsp cumin",
            "1 loaf bread",
        )
        self.generate(_MON)
        self.tick_all()
        shopping.done_shopping(self.conn, _MON)
        shelves = {i.name: i.shelf for i in pantry.items(self.conn)}
        self.assertEqual(
            shelves,
            {
                "Chicken": "Fridge",
                "Cheddar": "Fridge",
                "Frozen peas": "Freezer",
                "Cumin": "Spices",
                "Loaf bread": "Cupboard",
            },
        )

    def test_your_own_items_with_an_amount_are_stocked_too(self) -> None:
        shopping.add_extra(self.conn, _MON, "Kitchen roll", _a(2, "pack"))
        self.tick_all()
        shopping.done_shopping(self.conn, _MON)
        (item,) = pantry.items(self.conn)
        self.assertEqual(
            (item.name, item.amount), ("Kitchen roll", _a(2, "pack"))
        )

    def test_a_very_long_ingredient_name_still_stocks_the_pantry(self) -> None:
        long_name = "very " * 30 + "tasty pasta"
        self.plan(_MON, f"400g {long_name}")
        self.generate(_MON)
        self.tick_all()
        self.assertEqual(shopping.done_shopping(self.conn, _MON), 1)
        (item,) = pantry.items(self.conn)
        self.assertEqual(item.amount, _a(400, "g"))
        self.assertLessEqual(len(item.name), 60)
        self.assertTrue(item.name.startswith("Very very"))

    def test_ticked_rows_with_no_amount_just_leave_the_list(self) -> None:
        self.plan(_MON, "salt and pepper")
        shopping.add_extra(self.conn, _MON, "Honey")
        self.generate(_MON)
        self.tick_all()
        self.assertEqual(shopping.done_shopping(self.conn, _MON), 2)
        self.assertEqual(pantry.items(self.conn), [])
        self.assertEqual(shopping.get_list(self.conn, _MON).extras, ())

    def test_unticked_and_covered_rows_stay(self) -> None:
        self.plan(_MON, "2 onions", "1 leek", "400g pasta")
        self.stock("Pasta", _a(1, "pack"))
        got = self.generate(_MON)
        shopping.toggle(self.conn, got.aisles[0].items[0].id)  # the leek
        self.assertEqual(shopping.done_shopping(self.conn, _MON), 1)
        after = shopping.get_list(self.conn, _MON)
        self.assertEqual(self.to_buy(after), {"Onions": "2"})
        self.assertEqual([r.name for r in after.covered], ["Pasta"])

    def test_nothing_ticked_changes_nothing(self) -> None:
        self.plan(_MON, "2 onions")
        self.generate(_MON)
        self.assertEqual(shopping.done_shopping(self.conn, _MON), 0)
        self.assertEqual(
            self.to_buy(shopping.get_list(self.conn, _MON)), {"Onions": "2"}
        )


class AsTextTest(_ShoppingTestCase):
    def test_lists_what_is_still_to_buy_one_item_a_line_in_shop_order(
        self,
    ) -> None:
        self.plan(_MON, "400g pasta", "2 onions", "1 leek", "salt and pepper")
        shopping.add_extra(self.conn, _MON, "Kitchen roll", _a(2, "pack"))
        shopping.add_extra(self.conn, _MON, "Honey")
        got = self.generate(_MON)
        shopping.toggle(self.conn, got.aisles[0].items[0].id)  # the leek
        text = shopping.as_text(shopping.get_list(self.conn, _MON))
        # Amount first, like typing it into a shop's search. No headings: the
        # text is pasted into an order, where "Fruit & veg" is not an item.
        self.assertEqual(
            text,
            "2 Onions\n400 g Pasta\nSalt and pepper\n"
            "2 packs Kitchen roll\nHoney",
        )

    def test_an_empty_list_is_empty_text(self) -> None:
        self.assertEqual(
            shopping.as_text(shopping.get_list(self.conn, _MON)), ""
        )

    def test_covered_items_are_not_in_the_text(self) -> None:
        self.plan(_MON, "2 onions")
        self.stock("Onions", _a(4))
        self.assertEqual(shopping.as_text(self.generate(_MON)), "")


if __name__ == "__main__":
    unittest.main()
