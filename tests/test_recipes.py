"""Tests for the diary_app.recipes public interface."""

import unittest

from diary_app import db, recipes


def _draft(
    name: str = "Chicken curry", **fields: object
) -> recipes.RecipeDraft:
    base: dict[str, object] = {
        "name": name,
        "style": "Indian",
        "mins": 40,
        "ingredients": ("1 onion", "500g chicken"),
        "steps": ("Fry the onion.", "Add the chicken."),
        "tags": ("Kid-friendly",),
    }
    base.update(fields)
    return recipes.RecipeDraft(**base)  # type: ignore[arg-type]


class RecipesTest(unittest.TestCase):
    """recipes stores the household's meal library."""

    def setUp(self) -> None:
        self.conn = db.connect(":memory:")

    def test_a_new_library_is_empty(self) -> None:
        self.assertEqual(recipes.search(self.conn), [])

    def test_add_then_get_round_trips_every_field(self) -> None:
        added = recipes.add(
            self.conn,
            _draft(
                servings=6,
                source_url="https://example.com/curry",
                source_name="Example",
            ),
        )
        fetched = recipes.get(self.conn, added.id)
        self.assertEqual(fetched, added)
        self.assertEqual(fetched.name, "Chicken curry")
        self.assertEqual(fetched.style, "Indian")
        self.assertEqual(fetched.mins, 40)
        self.assertEqual(fetched.servings, 6)
        self.assertEqual(fetched.ingredients, ("1 onion", "500g chicken"))
        self.assertEqual(fetched.steps, ("Fry the onion.", "Add the chicken."))
        self.assertEqual(fetched.tags, ("Kid-friendly",))
        self.assertEqual(fetched.source_url, "https://example.com/curry")
        self.assertEqual(fetched.source_name, "Example")
        self.assertFalse(fetched.is_favourite)

    def test_get_unknown_recipe_raises_lookup_error(self) -> None:
        with self.assertRaises(LookupError):
            recipes.get(self.conn, 99)

    def test_update_replaces_fields_ingredients_and_tags(self) -> None:
        added = recipes.add(self.conn, _draft())
        updated = recipes.update(
            self.conn,
            added.id,
            _draft(
                "Veg curry",
                ingredients=("2 carrots",),
                tags=("Veg-led", "Quick"),
            ),
        )
        self.assertEqual(updated.name, "Veg curry")
        self.assertEqual(updated.ingredients, ("2 carrots",))
        self.assertEqual(set(updated.tags), {"Veg-led", "Quick"})
        self.assertEqual(recipes.get(self.conn, added.id), updated)

    def test_update_keeps_the_favourite_flag(self) -> None:
        added = recipes.add(self.conn, _draft())
        recipes.set_favourite(self.conn, added.id, is_favourite=True)
        updated = recipes.update(self.conn, added.id, _draft("Renamed"))
        self.assertTrue(updated.is_favourite)

    def test_update_unknown_recipe_raises_lookup_error(self) -> None:
        with self.assertRaises(LookupError):
            recipes.update(self.conn, 99, _draft())

    def test_delete_removes_the_recipe(self) -> None:
        added = recipes.add(self.conn, _draft())
        recipes.delete(self.conn, added.id)
        self.assertEqual(recipes.search(self.conn), [])
        with self.assertRaises(LookupError):
            recipes.get(self.conn, added.id)

    def test_delete_removes_its_ingredients_and_tags(self) -> None:
        added = recipes.add(self.conn, _draft())
        recipes.delete(self.conn, added.id)
        for table in ("recipe_ingredient", "recipe_tag"):
            count = self.conn.execute(
                f"SELECT COUNT(*) FROM {table}"  # noqa: S608
            ).fetchone()[0]
            self.assertEqual(count, 0, table)

    def test_get_many_returns_those_found_keyed_by_id(self) -> None:
        first = recipes.add(self.conn, _draft("First"))
        recipes.add(self.conn, _draft("Second"))
        found = recipes.get_many(self.conn, {first.id, 99})
        self.assertEqual(found, {first.id: first})
        self.assertEqual(recipes.get_many(self.conn, set()), {})

    def test_set_favourite_toggles_both_ways(self) -> None:
        added = recipes.add(self.conn, _draft())
        recipes.set_favourite(self.conn, added.id, is_favourite=True)
        self.assertTrue(recipes.get(self.conn, added.id).is_favourite)
        recipes.set_favourite(self.conn, added.id, is_favourite=False)
        self.assertFalse(recipes.get(self.conn, added.id).is_favourite)

    def test_set_favourite_on_unknown_recipe_raises(self) -> None:
        with self.assertRaises(LookupError):
            recipes.set_favourite(self.conn, 99, is_favourite=True)

    def test_search_returns_recipes_by_name(self) -> None:
        recipes.add(self.conn, _draft("Tacos", style="Mexican"))
        recipes.add(self.conn, _draft("Bolognese", style="Italian"))
        names = [r.name for r in recipes.search(self.conn)]
        self.assertEqual(names, ["Bolognese", "Tacos"])

    def test_search_by_style(self) -> None:
        recipes.add(self.conn, _draft("Tacos", style="Mexican"))
        recipes.add(self.conn, _draft("Bolognese", style="Italian"))
        found = recipes.search(self.conn, style="Mexican")
        self.assertEqual([r.name for r in found], ["Tacos"])

    def test_search_by_tag(self) -> None:
        recipes.add(self.conn, _draft("Salmon", tags=("Oily fish", "Quick")))
        recipes.add(self.conn, _draft("Burger", tags=("Treat night",)))
        found = recipes.search(self.conn, tag="Oily fish")
        self.assertEqual([r.name for r in found], ["Salmon"])

    def test_search_favourites_only(self) -> None:
        loved = recipes.add(self.conn, _draft("Loved"))
        recipes.add(self.conn, _draft("Other"))
        recipes.set_favourite(self.conn, loved.id, is_favourite=True)
        found = recipes.search(self.conn, favourites_only=True)
        self.assertEqual([r.name for r in found], ["Loved"])

    def test_search_excludes_ids(self) -> None:
        first = recipes.add(self.conn, _draft("First"))
        recipes.add(self.conn, _draft("Second"))
        found = recipes.search(self.conn, exclude_ids=(first.id,))
        self.assertEqual([r.name for r in found], ["Second"])

    def test_search_filters_combine(self) -> None:
        recipes.add(self.conn, _draft("A", style="Italian", tags=("Quick",)))
        recipes.add(self.conn, _draft("B", style="Italian", tags=()))
        recipes.add(self.conn, _draft("C", style="Indian", tags=("Quick",)))
        found = recipes.search(self.conn, style="Italian", tag="Quick")
        self.assertEqual([r.name for r in found], ["A"])

    def test_text_is_trimmed_and_blank_lines_dropped(self) -> None:
        added = recipes.add(
            self.conn,
            _draft(
                "  Soup  ",
                ingredients=("  1 leek ", "", "   "),
                steps=("\tChop. ", ""),
            ),
        )
        self.assertEqual(added.name, "Soup")
        self.assertEqual(added.ingredients, ("1 leek",))
        self.assertEqual(added.steps, ("Chop.",))

    def test_duplicate_tags_are_stored_once(self) -> None:
        added = recipes.add(self.conn, _draft(tags=("Quick", "Quick")))
        self.assertEqual(added.tags, ("Quick",))

    def test_ingredient_order_is_kept(self) -> None:
        lines = ("z first", "a second", "m third")
        added = recipes.add(self.conn, _draft(ingredients=lines))
        self.assertEqual(recipes.get(self.conn, added.id).ingredients, lines)

    def test_blank_name_is_rejected(self) -> None:
        with self.assertRaises(recipes.InvalidRecipeError):
            recipes.add(self.conn, _draft("   "))

    def test_very_long_name_is_rejected(self) -> None:
        with self.assertRaises(recipes.InvalidRecipeError):
            recipes.add(self.conn, _draft("x" * 200))

    def test_unknown_style_is_rejected(self) -> None:
        with self.assertRaises(recipes.InvalidRecipeError):
            recipes.add(self.conn, _draft(style="Martian"))

    def test_unknown_tag_is_rejected(self) -> None:
        with self.assertRaises(recipes.InvalidRecipeError):
            recipes.add(self.conn, _draft(tags=("Spicy",)))

    def test_minutes_must_be_between_1_and_1440(self) -> None:
        for bad in (0, -5, 1441):
            with self.assertRaises(recipes.InvalidRecipeError, msg=str(bad)):
                recipes.add(self.conn, _draft(mins=bad))

    def test_servings_must_be_positive(self) -> None:
        with self.assertRaises(recipes.InvalidRecipeError):
            recipes.add(self.conn, _draft(servings=0))

    def test_source_url_must_be_http_or_https(self) -> None:
        for bad in ("javascript:alert(1)", "ftp://example.com/x", "example"):
            with self.assertRaises(recipes.InvalidRecipeError, msg=bad):
                recipes.add(self.conn, _draft(source_url=bad))

    def test_rejected_update_changes_nothing(self) -> None:
        added = recipes.add(self.conn, _draft())
        with self.assertRaises(recipes.InvalidRecipeError):
            recipes.update(self.conn, added.id, _draft("", mins=10))
        self.assertEqual(recipes.get(self.conn, added.id), added)

    def test_vocabularies_are_exposed_for_forms(self) -> None:
        self.assertIn("Italian", recipes.STYLES)
        self.assertIn("Veg-led", recipes.TAGS)
        self.assertIn("Oily fish", recipes.TAGS)


if __name__ == "__main__":
    unittest.main()
