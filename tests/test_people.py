"""Tests for the diary_app.people public interface."""

import pathlib
import tempfile
import unittest

from diary_app import db, people

_ORANGE = "#B04A17"
_BLUE = "#24508F"


class PeopleTest(unittest.TestCase):
    """people stores the family members shown on every screen."""

    def setUp(self) -> None:
        self.conn = db.connect(":memory:")

    def test_a_new_database_has_the_family_entry(self) -> None:
        names = [p.name for p in people.list_people(self.conn)]
        self.assertEqual(names, ["Family"])

    def test_add_person_appears_in_the_list_in_order(self) -> None:
        added = people.add_person(self.conn, "Alex", "Adult", _ORANGE, "Me")
        listed = people.list_people(self.conn)
        self.assertEqual([p.name for p in listed], ["Family", "Alex"])
        self.assertEqual(listed[-1], added)
        self.assertEqual(added.outlook_category, "Me")

    def test_update_person_changes_the_fields(self) -> None:
        person = people.add_person(self.conn, "Alex", "Adult", _ORANGE)
        updated = people.update_person(
            self.conn,
            person.id,
            name="Alexander",
            colour=_BLUE,
            outlook_category="Dad",
        )
        self.assertEqual(updated.name, "Alexander")
        self.assertEqual(updated.colour, _BLUE)
        self.assertEqual(updated.outlook_category, "Dad")
        self.assertEqual(updated.role, "Adult")

    def test_changes_persist_across_connections(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = pathlib.Path(tmp) / "diary.db"
            first = db.connect(path)
            people.add_person(first, "Alex", "Adult", _ORANGE)
            first.close()
            second = db.connect(path)
            names = [p.name for p in people.list_people(second)]
            second.close()
        self.assertEqual(names, ["Family", "Alex"])

    def test_colour_outside_the_palette_is_rejected(self) -> None:
        with self.assertRaises(people.InvalidPersonError):
            people.add_person(self.conn, "Alex", "Adult", "red;}</style>")

    def test_blank_name_is_rejected(self) -> None:
        with self.assertRaises(people.InvalidPersonError):
            people.add_person(self.conn, "   ", "Adult", _ORANGE)

    def test_unknown_role_is_rejected(self) -> None:
        with self.assertRaises(people.InvalidPersonError):
            people.add_person(self.conn, "Alex", "Wizard", _ORANGE)

    def test_names_are_trimmed(self) -> None:
        person = people.add_person(self.conn, "  Alex  ", "Adult", _ORANGE)
        self.assertEqual(person.name, "Alex")

    def test_update_of_unknown_person_raises_lookup_error(self) -> None:
        with self.assertRaises(LookupError):
            people.update_person(
                self.conn, 999, name="x", colour=_BLUE, outlook_category=""
            )


if __name__ == "__main__":
    unittest.main()
