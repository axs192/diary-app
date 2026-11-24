"""Tests for the Shopping page, the pantry forms and "Cooked it" on Meals."""

import datetime
import re
import sqlite3
import urllib.parse
from fractions import Fraction

import httpx

from diary_app import db, pantry, shopping
from diary_app.ingredients import Amount
from tests import support
from tests.test_meals_web import _DAYS, _MONDAY, _MealsTestCase

_TODAY = datetime.date(2030, 1, 8)  # the Tuesday of the week of _MONDAY
_WEEK = _MONDAY.isoformat()
_PAGE = f"/shopping?week={_WEEK}"
_FRAGMENT = f"/shopping/fragment?week={_WEEK}"
_MON, _TUE, _WED = _DAYS[0], _DAYS[1], _DAYS[2]


def _a(value: str | int, unit: str = "") -> Amount:
    return Amount(Fraction(value), unit)


class _ShoppingWebTestCase(_MealsTestCase):
    """The meals test app, logged in, with a fixed 'today'."""

    def setUp(self) -> None:
        super().setUp()
        self.app.state.today = lambda: _TODAY
        self.log_in()

    def conn(self) -> sqlite3.Connection:
        conn = db.connect(self.app.state.database_path)
        self.addCleanup(conn.close)
        return conn

    def listing(self) -> shopping.ShoppingList:
        return shopping.get_list(self.conn(), _MONDAY)

    def meal(self, day: datetime.date, *lines: str) -> int:
        recipe_id = self.add_recipe(
            f"Dinner {day}", ingredients="\n".join(lines)
        )
        self.plan(day, recipe_id)
        return recipe_id

    def generate(self, *days: datetime.date, fragment: bool = False) -> None:
        data: dict[str, object] = {
            "week": _WEEK,
            "days": [d.isoformat() for d in days],
        }
        if fragment:
            data["_fragment"] = "1"
        response = self.client.post("/shopping/generate", data=data)
        self.assertEqual(response.status_code, 303, response.text)

    def stock(self, name: str, amount: str, unit: str, **fields: str) -> None:
        data = {"name": name, "amount": amount, "unit": unit, "week": _WEEK}
        data.update(fields)
        response = self.client.post("/pantry", data=data)
        self.assertEqual(response.status_code, 303, response.text)

    def get_page(self, url: str = _PAGE) -> str:
        response = self.client.get(url)
        self.assertEqual(response.status_code, 200, response.text)
        return str(response.text)

    @staticmethod
    def section(html: str, section_id: str) -> str:
        """The markup of one <details id=...> section."""
        found = re.search(
            rf'<details class="acc" id="{re.escape(section_id)}".*?</details>',
            html,
            re.DOTALL,
        )
        assert found, f"no section {section_id}"
        return found.group(0)


class AccessTest(_MealsTestCase):
    def test_every_route_needs_the_login(self) -> None:
        gets = [
            _PAGE,
            _FRAGMENT,
            f"/shopping/text?week={_WEEK}",
            "/pantry/1/edit",
        ]
        posts = [
            "/shopping/generate",
            "/shopping/tick",
            "/shopping/extras",
            "/shopping/extras/remove",
            "/shopping/done",
            "/pantry",
            "/pantry/row",
            "/pantry/1",
            "/pantry/1/delete",
            "/meals/day/cooked",
            "/meals/day/uncooked",
        ]
        for url in gets:
            with self.subTest(get=url):
                response = self.client.get(url)
                self.assertEqual(
                    (response.status_code, response.headers["location"]),
                    (303, "/login"),
                )
        for url in posts:
            with self.subTest(post=url):
                response = self.client.post(url, data={})
                self.assertEqual(
                    (response.status_code, response.headers["location"]),
                    (303, "/login"),
                )

    def test_the_item_editor_needs_the_login(self) -> None:
        for method, url in (
            ("get", "/shopping/item/1/edit"),
            ("post", "/shopping/item/1"),
        ):
            with self.subTest(url=url):
                response = getattr(self.client, method)(url)
                self.assertEqual(
                    (response.status_code, response.headers["location"]),
                    (303, "/login"),
                )

    def test_removing_a_row_needs_the_login(self) -> None:
        response = self.client.post("/shopping/item/1/delete", data={})
        self.assertEqual(
            (response.status_code, response.headers["location"]),
            (303, "/login"),
        )


class GenerateFormTest(_ShoppingWebTestCase):
    def day_boxes(self, html: str) -> dict[str, tuple[bool, bool]]:
        """ISO date -> (checked, disabled) for each day box."""
        found = re.findall(
            r'<input type="checkbox" name="days" value="([^"]+)"([^>]*)>', html
        )
        return {
            day: ("checked" in attrs, "disabled" in attrs)
            for day, attrs in found
        }

    def test_a_week_with_no_dinners_has_every_day_disabled(self) -> None:
        boxes = self.day_boxes(self.get_page())
        self.assertEqual(len(boxes), 7)
        self.assertTrue(all(disabled for _checked, disabled in boxes.values()))
        self.assertIn("no meal", self.get_page())

    def test_days_from_today_with_a_dinner_start_ticked(self) -> None:
        self.meal(_MON, "1 onion")  # before today
        self.meal(_TUE, "1 onion")  # today
        self.meal(_WED, "1 onion")
        boxes = self.day_boxes(self.get_page())
        self.assertEqual(boxes[_MON.isoformat()], (False, False))
        self.assertEqual(boxes[_TUE.isoformat()], (True, False))
        self.assertEqual(boxes[_WED.isoformat()], (True, False))
        self.assertEqual(boxes[_DAYS[3].isoformat()], (False, True))  # no meal

    def test_a_cooked_day_cannot_be_chosen(self) -> None:
        self.meal(_TUE, "1 onion")
        self.client.post("/meals/day/cooked", data={"day": _TUE.isoformat()})
        html = self.get_page()
        self.assertEqual(self.day_boxes(html)[_TUE.isoformat()], (False, True))
        self.assertIn("cooked", html)

    def test_it_remembers_the_days_it_was_generated_for(self) -> None:
        self.meal(_TUE, "1 onion")
        self.meal(_WED, "1 leek")
        self.generate(_WED)
        html = self.get_page()
        self.assertEqual(self.day_boxes(html)[_WED.isoformat()], (True, False))
        self.assertEqual(self.day_boxes(html)[_TUE.isoformat()], (False, False))
        self.assertIn("Generated for Wed 9", html)


class GenerateTest(_ShoppingWebTestCase):
    def test_generating_makes_the_list_for_the_chosen_days_only(self) -> None:
        self.meal(_TUE, "2 onions", "400g pasta")
        self.meal(_WED, "5 leeks")
        self.generate(_TUE)
        html = self.get_page()
        self.assertIn("Onions", html)
        self.assertNotIn("Leeks", html)
        self.assertRegex(html, r"<strong>2</strong> left to buy")

    def test_rows_show_name_quantity_and_unit_and_no_days(self) -> None:
        self.meal(_TUE, "400g pasta", "2 x 400g tins chopped tomatoes")
        self.meal(_WED, "400g pasta")
        self.generate(_TUE, _WED)
        html = self.get_page()
        self.assertIn(
            '<span class="shop-name">Pasta</span>'
            '<span class="shop-qty">800 g</span>',
            html,
        )
        self.assertIn(">2 tins<", html)
        self.assertNotRegex(html, r"Tue\s*·\s*Wed")

    def test_each_aisle_is_a_closed_section_with_a_count(self) -> None:
        self.meal(_TUE, "2 onions", "1 leek", "400g pasta")
        self.generate(_TUE)
        html = self.get_page()
        veg = self.section(html, "aisle-fruit-veg")
        self.assertIn("2 left", veg)
        self.assertNotIn(" open", veg.split(">", 1)[0])
        self.assertIn("1 left", self.section(html, "aisle-tin-dry-good"))
        self.assertNotRegex(html, r'<details class="acc" id="[^"]*" open')

    def test_the_page_can_open_one_section(self) -> None:
        self.meal(_TUE, "2 onions", "400g pasta")
        self.generate(_TUE)
        html = self.get_page(_PAGE + "&open=aisle-fruit-veg")
        self.assertIn('id="aisle-fruit-veg" open', html)
        self.assertNotIn('id="aisle-tin-dry-good" open', html)

    def test_covered_items_sit_in_a_closed_section(self) -> None:
        self.meal(_TUE, "2 onions", "1 leek")
        self.stock("Onions", "4", "items")
        self.generate(_TUE)
        html = self.get_page()
        covered = self.section(html, "covered")
        self.assertIn("Onions", covered)
        self.assertIn("need 2", covered)
        self.assertIn("have 4", covered)
        self.assertNotIn("Onions", self.section(html, "aisle-fruit-veg"))

    def test_a_shortfall_says_what_you_have(self) -> None:
        self.meal(_TUE, "400g pasta")
        self.stock("Pasta", "100", "g")
        self.generate(_TUE)
        self.assertIn("have 100 g", self.get_page())
        self.assertIn(">300 g<", self.get_page())

    def test_choosing_no_days_says_so_and_keeps_the_list(self) -> None:
        self.meal(_TUE, "2 onions")
        self.generate(_TUE)
        response = self.client.post("/shopping/generate", data={"week": _WEEK})
        self.assertEqual(response.status_code, 303)
        html = self.get_page()
        self.assertIn("Pick at least one day", html)
        self.assertIn("Onions", html)
        self.assertNotIn("Pick at least one day", self.get_page())  # said once

    def test_a_day_that_is_not_a_date_or_has_no_meal_changes_nothing(
        self,
    ) -> None:
        self.meal(_TUE, "2 onions")
        self.generate(_TUE)
        for bad in ("nonsense", _DAYS[4].isoformat(), "2031-01-01"):
            with self.subTest(bad=bad):
                response = self.client.post(
                    "/shopping/generate", data={"week": _WEEK, "days": bad}
                )
                self.assertEqual(response.status_code, 303)
                self.assertEqual(len(self.listing().aisles), 1)


class SwapProtocolTest(_ShoppingWebTestCase):
    """With the script a post is answered by the fragment; without, the page."""

    def test_a_post_from_the_script_redirects_to_the_fragment(self) -> None:
        self.meal(_TUE, "2 onions")
        response = self.client.post(
            "/shopping/generate",
            data={"week": _WEEK, "days": _TUE.isoformat(), "_fragment": "1"},
        )
        self.assertEqual(response.headers["location"], _FRAGMENT)

    def test_a_plain_post_redirects_to_the_page(self) -> None:
        self.meal(_TUE, "2 onions")
        response = self.client.post(
            "/shopping/generate", data={"week": _WEEK, "days": _TUE.isoformat()}
        )
        self.assertEqual(response.headers["location"], _PAGE)

    def test_the_fragment_is_the_page_without_the_shell(self) -> None:
        self.meal(_TUE, "2 onions")
        self.generate(_TUE)
        fragment = self.get_page(_FRAGMENT)
        self.assertNotIn("<html", fragment)
        self.assertNotIn("<header", fragment)
        self.assertIn("Onions", fragment)
        self.assertIn('data-swap="shopping-main"', fragment)
        page = self.get_page()
        self.assertIn('<div id="shopping-main">', page)
        self.assertIn(fragment.strip(), page)

    def test_every_form_that_changes_the_list_swaps_in_place(self) -> None:
        self.meal(_TUE, "2 onions")
        self.generate(_TUE)
        self.stock("Rice", "1", "pack")
        forms = re.findall(r"<form[^>]*>", self.get_page(_FRAGMENT))
        self.assertGreaterEqual(len(forms), 5)
        for form in forms:
            self.assertIn('method="post"', form)
            self.assertIn('data-swap="shopping-main"', form, form)


class TickingTest(_ShoppingWebTestCase):
    def setUp(self) -> None:
        super().setUp()
        self.meal(_TUE, "2 onions", "1 leek", "400g pasta")
        self.generate(_TUE)
        self.leek = next(
            i
            for a in self.listing().aisles
            for i in a.items
            if i.name == "Leek"
        )

    def tick(self, item: object, **extra: str) -> httpx.Response:
        data = {"week": _WEEK, "item": str(item), **extra}
        response: httpx.Response = self.client.post("/shopping/tick", data=data)
        return response

    def test_ticking_crosses_the_row_out_and_returns_to_that_aisle(
        self,
    ) -> None:
        response = self.tick(self.leek.id, open="aisle-fruit-veg")
        self.assertEqual(
            response.headers["location"],
            f"{_PAGE}&open=aisle-fruit-veg#item-{self.leek.id}",
        )
        html = self.get_page()
        self.assertRegex(
            html, rf'id="item-{self.leek.id}"><button[^>]*shop-ticked'
        )
        self.assertRegex(html, r"<strong>2</strong> left to buy · 1 ticked")

    def test_ticking_again_unticks(self) -> None:
        self.tick(self.leek.id)
        self.tick(self.leek.id)
        self.assertEqual(self.listing().ticked, 0)

    def test_the_fragment_redirect_keeps_no_page_state(self) -> None:
        response = self.tick(self.leek.id, _fragment="1")
        self.assertEqual(response.headers["location"], _FRAGMENT)

    def test_an_odd_open_value_is_dropped_not_echoed(self) -> None:
        response = self.tick(self.leek.id, open='"><script>x</script>')
        self.assertEqual(
            response.headers["location"], f"{_PAGE}#item-{self.leek.id}"
        )

    def test_an_item_that_has_gone_is_said_not_crashed_on(self) -> None:
        for gone in ("9999", "abc", "", "²"):
            with self.subTest(gone=gone):
                self.assertEqual(self.tick(gone).status_code, 303)
        self.assertIn("no longer on the list", self.get_page())


class OwnItemsTest(_ShoppingWebTestCase):
    def add(self, text: str, amount: str = "", unit: str = "items") -> None:
        response = self.client.post(
            "/shopping/extras",
            data={"week": _WEEK, "text": text, "amount": amount, "unit": unit},
        )
        self.assertEqual(response.status_code, 303, response.text)

    def test_an_item_with_an_amount_appears_under_your_items(self) -> None:
        self.add("Kitchen roll", "2", "pack")
        html = self.get_page()
        self.assertIn("Your items", html)
        self.assertIn("Kitchen roll", html)
        self.assertIn("2 packs", html)
        self.assertEqual(
            [i.name for i in self.listing().extras], ["Kitchen roll"]
        )

    def test_an_item_without_an_amount_is_fine(self) -> None:
        self.add("Honey")
        self.assertIsNone(self.listing().extras[0].amount)

    def test_blank_names_and_odd_amounts_are_said_not_stored(self) -> None:
        self.add("   ")
        self.assertIn("Say what to add", self.get_page())
        self.add("Honey", "lots", "g")
        self.assertIn("Enter an amount as a number", self.get_page())
        self.add("Honey", "2", "furlongs")
        self.assertIn("Pick one of the units", self.get_page())
        self.assertEqual(self.listing().extras, ())

    def test_remove_takes_it_off(self) -> None:
        self.add("Honey")
        item = self.listing().extras[0]
        response = self.client.post(
            "/shopping/extras/remove",
            data={"week": _WEEK, "item": str(item.id)},
        )
        self.assertEqual(response.status_code, 303)
        self.assertEqual(self.listing().extras, ())

    def test_each_item_has_a_tick_and_a_remove_button(self) -> None:
        self.add("Honey")
        html = self.get_page()
        self.assertIn('formaction="/shopping/extras/remove"', html)
        self.assertRegex(html, r'name="item" value="\d+" class="shop-row')


class DoneShoppingTest(_ShoppingWebTestCase):
    def test_done_moves_ticked_items_into_the_pantry(self) -> None:
        self.meal(_TUE, "400g pasta", "1 leek")
        self.generate(_TUE)
        pasta = next(
            i
            for a in self.listing().aisles
            for i in a.items
            if i.name == "Pasta"
        )
        self.client.post(
            "/shopping/tick", data={"week": _WEEK, "item": str(pasta.id)}
        )
        response = self.client.post("/shopping/done", data={"week": _WEEK})
        self.assertEqual(response.status_code, 303)
        self.assertEqual(
            [(i.name, i.amount) for i in pantry.items(self.conn())],
            [("Pasta", _a(400, "g"))],
        )
        html = self.get_page()
        self.assertIn("Added 1 item to the pantry", html)
        self.assertEqual(self.listing().ticked, 0)

    def test_done_with_nothing_ticked_says_so(self) -> None:
        self.client.post("/shopping/done", data={"week": _WEEK})
        self.assertIn("Nothing is ticked", self.get_page())

    def test_the_button_only_shows_when_something_is_ticked(self) -> None:
        self.meal(_TUE, "1 leek")
        self.generate(_TUE)
        self.assertNotIn("Done shopping", self.get_page())
        leek = self.listing().aisles[0].items[0]
        self.client.post(
            "/shopping/tick", data={"week": _WEEK, "item": str(leek.id)}
        )
        self.assertIn("Done shopping", self.get_page())


class PantryTest(_ShoppingWebTestCase):
    def only(self) -> pantry.PantryItem:
        (item,) = pantry.items(self.conn())
        return item

    def test_adding_an_item_keeps_amount_unit_shelf_and_date(self) -> None:
        self.stock(
            "Chopped tomatoes",
            "4",
            "tin",
            shelf="Cupboard",
            expires_on="2030-03-01",
        )
        item = self.only()
        self.assertEqual(
            (item.name, item.amount, item.shelf, item.expires_on),
            (
                "Chopped tomatoes",
                _a(4, "tin"),
                "Cupboard",
                datetime.date(2030, 3, 1),
            ),
        )

    def test_kilograms_are_kept_as_grams(self) -> None:
        self.stock("Flour", "1.5", "kg")
        self.assertEqual(self.only().amount, _a(1500, "g"))

    def test_shelves_are_closed_sections_with_counts(self) -> None:
        self.stock("Milk", "1", "bottle", shelf="Fridge")
        self.stock("Pasta", "500", "g")
        self.stock("Rice", "1", "pack")
        html = self.get_page()
        self.assertIn("2 items", self.section(html, "shelf-cupboard"))
        self.assertIn("1 item", self.section(html, "shelf-fridge"))
        self.assertNotIn('id="shelf-freezer"', html)  # nothing kept there

    def test_rows_show_the_amount_and_use_by_chip(self) -> None:
        self.stock(
            "Milk", "1", "bottle", shelf="Fridge", expires_on="2030-01-09"
        )
        html = self.section(self.get_page(), "shelf-fridge")
        self.assertIn("1 bottle", html)
        self.assertIn("Use by 9 Jan", html)
        self.assertIn("Tomorrow", html)

    def test_buttons_change_the_amount_never_below_zero(self) -> None:
        self.stock("Tomatoes", "1", "tin")
        item = self.only()
        for action in ("plus", "plus", "minus"):
            self.client.post(
                "/pantry/row",
                data={"week": _WEEK, "action": f"{item.id}:{action}"},
            )
        self.assertEqual(self.only().amount, _a(2, "tin"))
        for _ in range(5):
            self.client.post(
                "/pantry/row",
                data={"week": _WEEK, "action": f"{item.id}:minus"},
            )
        self.assertTrue(self.only().amount.is_zero)
        self.assertIn("None left", self.get_page())

    def test_grams_move_in_steps_of_a_hundred(self) -> None:
        self.stock("Pasta", "500", "g")
        item = self.only()
        self.client.post(
            "/pantry/row", data={"week": _WEEK, "action": f"{item.id}:minus"}
        )
        self.assertEqual(self.only().amount, _a(400, "g"))

    def test_add_to_list_puts_it_under_your_items(self) -> None:
        self.stock("Pasta", "500", "g")
        item = self.only()
        response = self.client.post(
            "/pantry/row", data={"week": _WEEK, "action": f"{item.id}:list"}
        )
        self.assertEqual(response.status_code, 303)
        self.assertEqual([i.name for i in self.listing().extras], ["Pasta"])
        self.assertIn("Added Pasta to the list", self.get_page())

    def test_the_row_form_redirects_to_that_shelf(self) -> None:
        self.stock("Pasta", "500", "g")
        item = self.only()
        response = self.client.post(
            "/pantry/row",
            data={
                "week": _WEEK,
                "action": f"{item.id}:plus",
                "open": "shelf-cupboard",
            },
        )
        self.assertEqual(
            response.headers["location"], f"{_PAGE}&open=shelf-cupboard#pantry"
        )

    def test_bad_input_is_said_not_stored(self) -> None:
        cases = {
            "Give the item a name": {"name": " ", "amount": "1", "unit": "g"},
            "Enter an amount": {"name": "Rice", "amount": "lots", "unit": "g"},
            "Pick one of the shelves": {
                "name": "Rice",
                "amount": "1",
                "unit": "g",
                "shelf": "Garage",
            },
            "Use a date like": {
                "name": "Rice",
                "amount": "1",
                "unit": "g",
                "expires_on": "soon",
            },
        }
        for message, data in cases.items():
            with self.subTest(message=message):
                response = self.client.post(
                    "/pantry", data={"week": _WEEK, **data}
                )
                self.assertEqual(response.status_code, 303)
                self.assertIn(message, self.get_page())
        self.assertEqual(pantry.items(self.conn()), [])

    def test_a_row_for_an_item_that_has_gone_is_said_not_crashed_on(
        self,
    ) -> None:
        for action in ("99:plus", "x:plus", "", "1:explode"):
            with self.subTest(action=action):
                response = self.client.post(
                    "/pantry/row", data={"week": _WEEK, "action": action}
                )
                self.assertEqual(response.status_code, 303)

    def test_use_soon_lists_what_is_due_and_the_meals_that_use_it(self) -> None:
        self.stock(
            "Milk", "1", "bottle", shelf="Fridge", expires_on="2030-01-09"
        )
        self.stock("Rice", "1", "pack", expires_on="2030-06-01")
        recipe_id = self.add_recipe(
            "Rice pudding", ingredients="100g rice\n500ml milk"
        )
        html = self.get_page()
        soon = html[html.index("Use soon") :]
        self.assertIn("Milk", soon)
        self.assertIn(f'href="/recipes/{recipe_id}"', soon)
        self.assertNotIn("Rice</strong>", soon.split("Meals that use", 1)[0])

    def test_no_use_soon_box_when_nothing_is_due(self) -> None:
        self.stock("Rice", "1", "pack", expires_on="2030-06-01")
        self.assertNotIn("Use soon", self.get_page())


class EditPantryTest(_ShoppingWebTestCase):
    def setUp(self) -> None:
        super().setUp()
        self.stock("Pasta", "500", "g", expires_on="2030-03-01")
        self.item = pantry.items(self.conn())[0]
        self.url = f"/pantry/{self.item.id}/edit?week={_WEEK}"

    def test_the_form_is_filled_in(self) -> None:
        html = self.get_page(self.url)
        self.assertIn('value="Pasta"', html)
        self.assertIn('value="500"', html)
        self.assertIn('value="2030-03-01"', html)
        self.assertRegex(html, r"<option[^>]*selected[^>]*>g</option>")

    def test_saving_changes_the_item_and_goes_back(self) -> None:
        response = self.client.post(
            f"/pantry/{self.item.id}",
            data={
                "week": _WEEK,
                "name": "Penne",
                "amount": "1.2",
                "unit": "kg",
                "shelf": "Baking",
                "expires_on": "",
            },
        )
        self.assertEqual(
            (response.status_code, response.headers["location"]),
            (303, f"{_PAGE}#pantry"),
        )
        item = pantry.get(self.conn(), self.item.id)
        self.assertEqual(
            (item.name, item.amount, item.shelf, item.expires_on),
            ("Penne", _a(1200, "g"), "Baking", None),
        )

    def test_bad_values_show_a_message_and_change_nothing(self) -> None:
        response = self.client.post(
            f"/pantry/{self.item.id}",
            data={
                "week": _WEEK,
                "name": "",
                "amount": "1",
                "unit": "g",
                "shelf": "Cupboard",
            },
        )
        self.assertEqual(response.status_code, 400)
        self.assertIn("Give the item a name", response.text)
        self.assertEqual(pantry.get(self.conn(), self.item.id).name, "Pasta")

    def test_delete_removes_it(self) -> None:
        response = self.client.post(
            f"/pantry/{self.item.id}/delete", data={"week": _WEEK}
        )
        self.assertEqual(response.status_code, 303)
        self.assertEqual(pantry.items(self.conn()), [])

    def test_an_unknown_item_is_a_404(self) -> None:
        self.assertEqual(self.client.get("/pantry/999/edit").status_code, 404)
        self.assertEqual(
            self.client.post(
                "/pantry/999",
                data={
                    "name": "x",
                    "amount": "1",
                    "unit": "g",
                    "shelf": "Cupboard",
                },
            ).status_code,
            404,
        )


class EditShoppingItemTest(_ShoppingWebTestCase):
    def setUp(self) -> None:
        super().setUp()
        self.meal(_TUE, "2 onions", "1 leek")
        self.generate(_TUE)
        self.client.post(
            "/shopping/extras",
            data={
                "week": _WEEK,
                "text": "Honey",
                "amount": "",
                "unit": "items",
            },
        )
        listing = self.listing()
        self.onions = next(
            i for a in listing.aisles for i in a.items if i.name == "Onions"
        )
        self.honey = listing.extras[0]

    def url(self, item: shopping.ShoppingItem) -> str:
        return f"/shopping/item/{item.id}/edit?week={_WEEK}"

    def save(
        self, item: shopping.ShoppingItem, **fields: str
    ) -> httpx.Response:
        data = {
            "week": _WEEK,
            "name": item.name,
            "amount": "",
            "unit": "items",
            **fields,
        }
        response: httpx.Response = self.client.post(
            f"/shopping/item/{item.id}", data=data
        )
        return response

    def test_every_row_on_the_list_has_an_edit_link(self) -> None:
        html = self.get_page()
        self.assertIn(f'href="{self.url(self.onions)}"', html)
        self.assertIn(f'href="{self.url(self.honey)}"', html)

    def test_covered_rows_are_not_editable(self) -> None:
        self.client.post(
            "/pantry",
            data={
                "week": _WEEK,
                "name": "Leek",
                "amount": "5",
                "unit": "items",
            },
        )
        self.generate(_TUE)
        covered = self.listing().covered[0]
        self.assertNotIn(f"/shopping/item/{covered.id}/edit", self.get_page())

    def test_the_form_is_filled_in(self) -> None:
        html = self.get_page(self.url(self.onions))
        self.assertIn('value="Onions"', html)
        self.assertIn('value="2"', html)
        self.assertRegex(html, r"<option[^>]*selected[^>]*>items</option>")

    def test_saving_changes_a_row_and_returns_to_its_aisle(self) -> None:
        response = self.save(
            self.onions, name="Red onions", amount="3", unit="items"
        )
        self.assertEqual(
            (response.status_code, response.headers["location"]),
            (
                303,
                f"{_PAGE}&open=aisle-fruit-veg#item-{self.onions.id}",
            ),
        )
        got = shopping.get_item(self.conn(), self.onions.id)
        self.assertEqual((got.name, got.amount), ("Red onions", _a(3)))
        self.assertIn("Red onions", self.get_page())

    def test_one_of_your_own_items_returns_to_the_page(self) -> None:
        response = self.save(
            self.honey, name="Runny honey", amount="2", unit="jar"
        )
        self.assertEqual(
            response.headers["location"], f"{_PAGE}#item-{self.honey.id}"
        )
        got = shopping.get_item(self.conn(), self.honey.id)
        self.assertEqual((got.name, got.amount), ("Runny honey", _a(2, "jar")))

    def test_the_amount_may_be_left_blank_and_kilos_become_grams(self) -> None:
        self.save(self.onions, amount="")
        self.assertIsNone(shopping.get_item(self.conn(), self.onions.id).amount)
        self.save(self.onions, amount="1.5", unit="kg")
        self.assertEqual(
            shopping.get_item(self.conn(), self.onions.id).amount, _a(1500, "g")
        )

    def test_bad_values_show_a_message_and_change_nothing(self) -> None:
        cases = {
            "Say what to add": {"name": "  "},
            "Enter an amount as a number": {"amount": "lots"},
            "Pick one of the units": {"amount": "2", "unit": "furlongs"},
        }
        for message, fields in cases.items():
            with self.subTest(message=message):
                response = self.save(self.onions, **fields)
                self.assertEqual(response.status_code, 400)
                self.assertIn(message, response.text)
        got = shopping.get_item(self.conn(), self.onions.id)
        self.assertEqual((got.name, got.amount), ("Onions", _a(2)))

    def test_an_unknown_row_is_a_404(self) -> None:
        self.assertEqual(
            self.client.get("/shopping/item/999/edit").status_code, 404
        )
        response = self.client.post("/shopping/item/999", data={"name": "x"})
        self.assertEqual(response.status_code, 404)

    def test_the_editor_offers_to_remove_the_row(self) -> None:
        html = self.get_page(self.url(self.onions))
        self.assertIn(f'action="/shopping/item/{self.onions.id}/delete"', html)
        self.assertIn("Remove from the list", html)
        self.assertIn("Generating the list again", html)  # it can come back
        own = self.get_page(self.url(self.honey))
        self.assertIn("Remove from the list", own)
        self.assertNotIn("Generating the list again", own)

    def test_removing_a_row_made_from_a_meal_returns_to_its_aisle(self) -> None:
        response = self.client.post(
            f"/shopping/item/{self.onions.id}/delete", data={"week": _WEEK}
        )
        self.assertEqual(
            (response.status_code, response.headers["location"]),
            (303, f"{_PAGE}&open=aisle-fruit-veg"),
        )
        html = self.get_page()
        self.assertIn("Removed Onions from the list", html)
        self.assertNotIn(f'id="item-{self.onions.id}"', html)
        self.assertEqual(
            [i.name for a in self.listing().aisles for i in a.items], ["Leek"]
        )

    def test_removing_one_of_your_own_items(self) -> None:
        response = self.client.post(
            f"/shopping/item/{self.honey.id}/delete", data={"week": _WEEK}
        )
        self.assertEqual(response.headers["location"], _PAGE)
        self.assertEqual(self.listing().extras, ())

    def test_removing_a_row_that_has_gone_is_said_not_crashed_on(self) -> None:
        url = f"/shopping/item/{self.honey.id}/delete"
        self.client.post(url, data={"week": _WEEK})
        response = self.client.post(url, data={"week": _WEEK})
        self.assertEqual(response.status_code, 303)
        self.assertIn("already gone", self.get_page())

    def test_the_editor_is_a_plain_page_for_the_ipad(self) -> None:
        html = self.get_page(self.url(self.onions))
        support.assert_only_app_script(self, html, "item editor")
        for banned in ("display: grid", "gap:", "onclick"):
            self.assertNotIn(banned, html.lower())
        action = f'action="/shopping/item/{self.onions.id}"'
        self.assertIn('method="post" ' + action, html)


class TextPageTest(_ShoppingWebTestCase):
    def test_the_list_is_plain_text_ready_to_copy(self) -> None:
        self.meal(_TUE, "2 onions", "400g pasta")
        self.generate(_TUE)
        html = self.get_page(f"/shopping/text?week={_WEEK}")
        found = re.search(r"<textarea[^>]*>(.*?)</textarea>", html, re.DOTALL)
        assert found
        self.assertEqual(
            found.group(1).strip(),
            "2 Onions\n400 g Pasta",
        )
        self.assertIn("readonly", html)
        self.assertIn("data-select-all", html)

    def test_the_page_links_to_it(self) -> None:
        self.assertIn(f'href="/shopping/text?week={_WEEK}"', self.get_page())


class NavigationTest(_ShoppingWebTestCase):
    def test_the_week_has_previous_this_and_next_links(self) -> None:
        html = self.get_page()
        prev = (_MONDAY - datetime.timedelta(days=7)).isoformat()
        nxt = (_MONDAY + datetime.timedelta(days=7)).isoformat()
        self.assertIn(f'href="/shopping?week={prev}"', html)
        self.assertIn(f'href="/shopping?week={nxt}"', html)
        self.assertIn('href="/shopping"', html)

    def test_today_decides_the_default_week(self) -> None:
        self.meal(_TUE, "1 onion")
        self.assertIn(f'value="{_WEEK}"', self.get_page("/shopping"))

    def test_shopping_is_marked_as_the_current_menu_item(self) -> None:
        html = self.get_page()
        self.assertRegex(
            html, r'<a class="nav-item" href="/shopping" aria-current="page">'
        )
        self.assertNotRegex(html, r'href="/meals" aria-current="page"')


class RecipeChipsTest(_ShoppingWebTestCase):
    def test_ingredients_say_what_the_pantry_has(self) -> None:
        recipe_id = self.add_recipe(
            "Soup", ingredients="2 onions\n1 tin tomatoes\n1 leek\n200g pasta"
        )
        self.stock("Onions", "4", "items")
        self.stock("Pasta", "0", "g")
        html = self.get_page(f"/recipes/{recipe_id}")
        self.assertRegex(html, r"2 onions</span>\s*<span[^>]*>Have 4<")
        self.assertRegex(html, r"200g pasta</span>\s*<span[^>]*>None left<")
        self.assertNotRegex(html, r"1 leek</span>\s*<span")

    def test_a_recipe_with_an_empty_pantry_has_no_chips(self) -> None:
        recipe_id = self.add_recipe("Soup", ingredients="2 onions")
        self.assertNotIn("Have", self.get_page(f"/recipes/{recipe_id}"))


class CookedItTest(_ShoppingWebTestCase):
    def setUp(self) -> None:
        super().setUp()
        self.meal(_TUE, "2 onions")
        self.stock("Onions", "5", "items")
        self.week = f"/meals?week={_WEEK}"

    def card(self) -> str:
        return self.day_card(self.get_page(self.week), _TUE)

    def cook(self, what: str = "cooked") -> httpx.Response:
        response: httpx.Response = self.client.post(
            f"/meals/day/{what}", data={"day": _TUE.isoformat()}
        )
        return response

    def test_the_card_offers_cooked_it(self) -> None:
        self.assertIn("Cooked it", self.card())
        self.assertNotIn("Undo", self.card())

    def test_cooked_it_uses_the_pantry_and_says_what_it_took(self) -> None:
        response = self.cook()
        self.assertEqual(
            (response.status_code, response.headers["location"]),
            (303, self.week),
        )
        self.assertEqual(pantry.items(self.conn())[0].amount, _a(3))
        html = self.get_page(self.week)
        self.assertIn("Took 2 Onions from the pantry", html)

    def test_a_cooked_day_shows_cooked_and_undo(self) -> None:
        self.cook()
        card = self.card()
        self.assertIn("Cooked", card)
        self.assertIn("Undo", card)
        self.assertNotIn("Cooked it", card)

    def test_undo_puts_it_back(self) -> None:
        self.cook()
        self.cook("uncooked")
        self.assertEqual(pantry.items(self.conn())[0].amount, _a(5))
        self.assertIn("Cooked it", self.card())

    def test_bad_days_are_refused_politely(self) -> None:
        for what in ("cooked", "uncooked"):
            response = self.client.post(
                f"/meals/day/{what}", data={"day": "nope"}
            )
            self.assertEqual(response.status_code, 400)


class Ios9SafetyTest(_ShoppingWebTestCase):
    """The shopping pages follow the rules for the kitchen iPad (iOS 9)."""

    def pages(self) -> dict[str, str]:
        self.meal(_TUE, "2 onions", "400g pasta")
        self.generate(_TUE)
        self.stock(
            "Milk", "1", "bottle", shelf="Fridge", expires_on="2030-01-09"
        )
        item = pantry.items(self.conn())[0]
        urls = [
            _PAGE,
            _PAGE + "&open=aisle-fruit-veg",
            _FRAGMENT,
            f"/shopping/text?week={_WEEK}",
            f"/pantry/{item.id}/edit?week={_WEEK}",
            f"/meals?week={_WEEK}",
        ]
        return {url: self.get_page(url) for url in urls}

    def test_only_the_one_app_script_and_plain_css(self) -> None:
        for url, html in self.pages().items():
            with self.subTest(url=url):
                if "<html" in html:
                    support.assert_only_app_script(self, html, url)
                else:
                    self.assertNotIn("<script", html.lower())
                for banned in (
                    "display: grid",
                    "display:grid",
                    "grid-template",
                    "gap:",
                    "onclick",
                ):
                    self.assertNotIn(banned, html.lower(), url)

    def test_the_stylesheet_has_no_grid_gap_or_custom_properties(self) -> None:
        css = self.client.get("/static/app.css").text
        for banned in (
            "display: grid",
            "grid-template",
            "gap:",
            "var(--",
            "position: sticky",
        ):
            self.assertNotIn(banned, css)

    def test_every_form_is_a_plain_post_so_it_works_without_the_script(
        self,
    ) -> None:
        for url, html in self.pages().items():
            for form in re.findall(r"<form[^>]*>", html):
                with self.subTest(url=url, form=form):
                    self.assertIn('method="post"', form)
                    self.assertIn('action="', form)

    def test_the_text_never_leaks_into_attributes_unescaped(self) -> None:
        self.client.post(
            "/shopping/extras",
            data={
                "week": _WEEK,
                "text": '"><b>x</b>',
                "amount": "",
                "unit": "items",
            },
        )
        html = self.get_page()
        self.assertNotIn("<b>x</b>", html)
        self.assertIn("&lt;b&gt;x&lt;/b&gt;", html)

    def test_the_urls_in_redirects_stay_on_this_site(self) -> None:
        response = self.client.post(
            "/shopping/tick",
            data={"week": "//evil.example", "item": "1", "open": "aisle-x"},
        )
        location = urllib.parse.urlsplit(response.headers["location"])
        self.assertEqual((location.scheme, location.netloc), ("", ""))
