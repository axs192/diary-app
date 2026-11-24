"""Tests for the diary_app.ingredients public interface."""

import unittest
from fractions import Fraction

from diary_app import ingredients
from diary_app.ingredients import Amount


def _a(value: str | int | Fraction, unit: str = "") -> Amount:
    return Amount(Fraction(value), unit)


class ParseTest(unittest.TestCase):
    """parse reads a recipe line into a name and an amount in metric."""

    def assert_parsed(
        self, line: str, name: str, value: str | int | Fraction, unit: str
    ) -> None:
        got = ingredients.parse(line)
        self.assertEqual(got.name, name, line)
        self.assertEqual(got.amount, _a(value, unit), line)
        self.assertEqual(got.text, line.strip())

    def test_metric_amounts_with_or_without_a_space(self) -> None:
        self.assert_parsed("200g pasta", "pasta", 200, "g")
        self.assert_parsed("200 g pasta", "pasta", 200, "g")
        self.assert_parsed("1.5kg potatoes", "potatoes", 1500, "g")
        self.assert_parsed("500ml chicken stock", "chicken stock", 500, "ml")
        self.assert_parsed("1 litre water", "water", 1000, "ml")

    def test_imperial_amounts_are_converted_to_metric(self) -> None:
        self.assert_parsed("8oz mince", "mince", Fraction(5670, 25), "g")
        self.assert_parsed("1 lb potatoes", "potatoes", Fraction(2268, 5), "g")
        self.assert_parsed("1 pint milk", "milk", 568, "ml")
        self.assert_parsed("2 fl oz cream", "cream", Fraction(5682, 100), "ml")
        self.assert_parsed("1 cup rice", "rice", 250, "ml")

    def test_spoons_become_millilitres(self) -> None:
        self.assert_parsed("2 tbsp olive oil", "olive oil", 30, "ml")
        self.assert_parsed("1 tsp salt", "salt", 5, "ml")
        self.assert_parsed(
            "1/2 tsp ground cumin", "ground cumin", Fraction(5, 2), "ml"
        )

    def test_fractions_in_every_written_form(self) -> None:
        self.assert_parsed("½ tsp salt", "salt", Fraction(5, 2), "ml")
        self.assert_parsed("1½ tsp salt", "salt", Fraction(15, 2), "ml")
        self.assert_parsed("1 1/2 cups milk", "milk", 375, "ml")
        self.assert_parsed("1.5 tbsp honey", "honey", Fraction(45, 2), "ml")

    def test_a_range_uses_the_larger_number(self) -> None:
        self.assert_parsed("2-3 tbsp olive oil", "olive oil", 45, "ml")
        self.assert_parsed("2 to 3 tbsp olive oil", "olive oil", 45, "ml")

    def test_counted_things(self) -> None:
        self.assert_parsed("2 eggs", "eggs", 2, "")
        self.assert_parsed("2 large onions", "onions", 2, "")
        self.assert_parsed(
            "1 red pepper, deseeded and sliced", "red pepper", 1, ""
        )
        self.assert_parsed("3 garlic cloves, crushed", "garlic cloves", 3, "")

    def test_containers_are_counted_not_weighed(self) -> None:
        self.assert_parsed(
            "2 x 400g tins chopped tomatoes", "chopped tomatoes", 2, "tin"
        )
        self.assert_parsed(
            "400g can chopped tomatoes", "chopped tomatoes", 1, "tin"
        )
        self.assert_parsed("2 tins of tomatoes", "tomatoes", 2, "tin")
        self.assert_parsed("1 jar curry paste", "curry paste", 1, "jar")
        self.assert_parsed("2 packs bacon", "bacon", 2, "pack")

    def test_a_multiplier_without_a_container_multiplies_the_amount(
        self,
    ) -> None:
        self.assert_parsed(
            "2 x 400g chicken breast", "chicken breast", 800, "g"
        )

    def test_alternative_measures_and_brackets_are_ignored(self) -> None:
        self.assert_parsed(
            "400g/14oz can chickpeas, drained", "chickpeas", 1, "tin"
        )
        self.assert_parsed("250g (9oz) pasta", "pasta", 250, "g")
        self.assert_parsed("100g/3½oz cheese", "cheese", 100, "g")

    def test_pinches_and_handfuls(self) -> None:
        self.assert_parsed("pinch of salt", "salt", 1, "pinch")
        self.assert_parsed("a handful of parsley", "parsley", 1, "handful")

    def test_a_line_it_cannot_read_has_no_amount(self) -> None:
        for line in ("salt and pepper", "Juice of 1 lemon", "To serve: bread"):
            with self.subTest(line=line):
                got = ingredients.parse(line)
                self.assertIsNone(got.amount)
                self.assertEqual(got.text, line)
                self.assertEqual(got.name, line.lower())

    def test_a_bare_quantity_is_not_an_ingredient(self) -> None:
        got = ingredients.parse("400g")
        self.assertIsNone(got.amount)


class AmountTest(unittest.TestCase):
    """Amounts add, subtract and print in the units people use."""

    def test_formats(self) -> None:
        cases = [
            (_a(750, "g"), "750 g"),
            (_a(1600, "g"), "1.6 kg"),
            (_a(1000, "g"), "1 kg"),
            (_a(1250, "g"), "1.25 kg"),
            (_a(30, "ml"), "30 ml"),
            (_a(1200, "ml"), "1.2 l"),
            (_a(4), "4"),
            (_a("1/2"), "½"),
            (_a("3/2"), "1½"),
            (_a("10/3"), "3⅓"),
            (_a("7/6"), "1.17"),
            (_a(2, "tin"), "2 tins"),
            (_a(1, "tin"), "1 tin"),
            (_a(2, "bunch"), "2 bunches"),
            (_a(1, "jar"), "1 jar"),
            (_a(0, "tin"), "0 tins"),
        ]
        for amount, text in cases:
            with self.subTest(text=text):
                self.assertEqual(amount.format(), text)

    def test_add_same_units(self) -> None:
        self.assertEqual(_a(200, "g") + _a(300, "g"), _a(500, "g"))

    def test_adding_different_units_is_refused(self) -> None:
        with self.assertRaises(ValueError):
            _a(1, "tin") + _a(1, "jar")

    def test_minus_never_goes_below_zero(self) -> None:
        self.assertEqual(_a(5, "tin").minus(_a(2, "tin")), _a(3, "tin"))
        self.assertEqual(_a(1, "tin").minus(_a(2, "tin")), _a(0, "tin"))
        with self.assertRaises(ValueError):
            _a(1, "tin").minus(_a(2, "jar"))

    def test_comparable_means_same_unit(self) -> None:
        self.assertTrue(_a(1, "g").comparable(_a(5, "g")))
        self.assertFalse(_a(1, "g").comparable(_a(1, "ml")))
        self.assertFalse(_a(1, "tin").comparable(_a(1, "jar")))
        self.assertFalse(_a(1).comparable(_a(1, "tin")))

    def test_is_zero_and_steps(self) -> None:
        self.assertTrue(_a(0, "g").is_zero)
        self.assertFalse(_a(1, "g").is_zero)
        self.assertEqual(_a(500, "g").step, _a(100, "g"))
        self.assertEqual(_a(500, "ml").step, _a(100, "ml"))
        self.assertEqual(_a(4, "tin").step, _a(1, "tin"))
        self.assertEqual(_a(3).step, _a(1))

    def test_from_unit_converts_and_normalises(self) -> None:
        self.assertEqual(Amount.from_unit(Fraction(2), "kg"), _a(2000, "g"))
        self.assertEqual(Amount.from_unit(Fraction(1), "l"), _a(1000, "ml"))
        self.assertEqual(Amount.from_unit(Fraction(3), "tins"), _a(3, "tin"))
        self.assertEqual(Amount.from_unit(Fraction(3), "items"), _a(3))
        self.assertEqual(Amount.from_unit(Fraction(3), ""), _a(3))

    def test_from_unit_refuses_an_unknown_unit(self) -> None:
        with self.assertRaises(ValueError):
            Amount.from_unit(Fraction(1), "furlongs")


class ParseAmountTest(unittest.TestCase):
    """parse_amount reads what someone typed into an amount box."""

    def test_reads_numbers_and_units(self) -> None:
        self.assertEqual(ingredients.parse_amount("4", "tin"), _a(4, "tin"))
        self.assertEqual(ingredients.parse_amount("1.5", "kg"), _a(1500, "g"))
        self.assertEqual(ingredients.parse_amount(" 1/2 ", "items"), _a("1/2"))

    def test_refuses_what_is_not_a_sensible_amount(self) -> None:
        for number in ("", "abc", "-1", "1e9", "1000001", "nan", "1/0"):
            with self.subTest(number=number), self.assertRaises(ValueError):
                ingredients.parse_amount(number, "g")
        with self.assertRaises(ValueError):
            ingredients.parse_amount("1", "furlongs")

    def test_zero_is_allowed(self) -> None:
        self.assertTrue(ingredients.parse_amount("0", "g").is_zero)

    def test_the_unit_choices_are_all_accepted(self) -> None:
        for unit in ingredients.UNIT_CHOICES:
            with self.subTest(unit=unit):
                ingredients.parse_amount("1", unit)


class NamesTest(unittest.TestCase):
    """item_key, same_item and aisle: how names are compared and sorted."""

    def test_keys_ignore_case_plurals_and_size_words(self) -> None:
        same = [
            ("Onions", "onion"),
            ("large onions", "Onion"),
            ("Tomatoes", "tomato"),
            ("Potatoes", "potato"),
            ("Berries", "berry"),
            ("Chickpeas", "chickpea"),
        ]
        for a, b in same:
            with self.subTest(a=a):
                self.assertEqual(
                    ingredients.item_key(a), ingredients.item_key(b)
                )

    def test_keys_are_safe_slugs(self) -> None:
        self.assertEqual(
            ingredients.item_key("Chopped Tomatoes"), "chopped-tomato"
        )
        self.assertEqual(
            ingredients.item_key("  Crème fraîche! "), "creme-fraiche"
        )

    def test_words_ending_in_s_that_are_not_plurals_are_kept(self) -> None:
        for word in ("hummus", "couscous", "asparagus", "glass", "swiss"):
            with self.subTest(word=word):
                self.assertEqual(ingredients.item_key(word), word)

    def test_same_item_needs_every_pantry_word_in_the_ingredient(self) -> None:
        yes = [
            ("Onions", "2 large red onions"),
            ("Tinned tomatoes", "chopped tomatoes"),
            ("Chopped tomatoes", "chopped tomatoes"),
            ("Greek yoghurt", "greek yoghurt"),
        ]
        no = [
            ("Red onions", "onions"),
            ("Onions", "garlic"),
            ("Frozen peas", "peas"),
            ("", "anything"),
        ]
        for pantry_name, ingredient in yes:
            with self.subTest(pantry_name=pantry_name):
                self.assertTrue(ingredients.same_item(pantry_name, ingredient))
        for pantry_name, ingredient in no:
            with self.subTest(pantry_name=pantry_name):
                self.assertFalse(ingredients.same_item(pantry_name, ingredient))

    def test_same_item_accepts_the_known_false_positives(self) -> None:
        # Documented limitation: matching is by words, not meaning. The
        # shopping list shows covered items so a wrong match can be spotted.
        self.assertTrue(ingredients.same_item("Milk", "coconut milk"))
        self.assertTrue(ingredients.same_item("Pasta", "pasta sauce"))

    def test_aisles(self) -> None:
        cases = {
            "onions": "Fruit & veg",
            "red pepper": "Fruit & veg",
            "green beans": "Fruit & veg",
            "chicken breast": "Meat & fish",
            "salmon fillets": "Meat & fish",
            "milk": "Dairy & eggs",
            "eggs": "Dairy & eggs",
            "cheddar": "Dairy & eggs",
            "tortillas": "Bakery",
            "pasta": "Tins & dry goods",
            "chopped tomatoes": "Tins & dry goods",
            "coconut milk": "Tins & dry goods",
            "red lentils": "Tins & dry goods",
            "olive oil": "Tins & dry goods",
            "ground cumin": "Herbs & spices",
            "black pepper": "Herbs & spices",
            "frozen peas": "Frozen",
            "toilet roll": "Other",
        }
        for name, aisle in cases.items():
            with self.subTest(name=name):
                self.assertEqual(ingredients.aisle(name), aisle)

    def test_aisles_come_in_shop_order(self) -> None:
        self.assertEqual(ingredients.AISLES[0], "Fruit & veg")
        self.assertEqual(ingredients.AISLES[-1], "Other")
        self.assertIn(ingredients.aisle("anything at all"), ingredients.AISLES)


if __name__ == "__main__":
    unittest.main()
