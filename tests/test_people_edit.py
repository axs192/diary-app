"""Tests for changing a person's role and removing a person."""

import unittest

from diary_app import db, people

_ORANGE = "#B04A17"
_BLUE = "#24508F"


class RoleTest(unittest.TestCase):
    """A person can be switched between Adult and Child."""

    def setUp(self) -> None:
        self.conn = db.connect(":memory:")
        self.alex = people.add_person(self.conn, "Alex", "Adult", _ORANGE)
        self.family = people.list_people(self.conn)[0]

    def _update(self, person: people.Person, **extra: str) -> people.Person:
        return people.update_person(
            self.conn,
            person.id,
            name=person.name,
            colour=person.colour,
            outlook_category=person.outlook_category,
            **extra,
        )

    def test_role_can_be_changed(self) -> None:
        updated = self._update(self.alex, role="Child")
        self.assertEqual(updated.role, "Child")
        self.assertEqual(people.list_people(self.conn)[1].role, "Child")

    def test_leaving_the_role_out_keeps_it(self) -> None:
        self.assertEqual(self._update(self.alex).role, "Adult")

    def test_an_unknown_role_is_rejected(self) -> None:
        with self.assertRaises(people.InvalidPersonError):
            self._update(self.alex, role="Pet")
        self.assertEqual(people.list_people(self.conn)[1].role, "Adult")

    def test_nobody_can_be_made_everyone(self) -> None:
        with self.assertRaises(people.InvalidPersonError):
            self._update(self.alex, role="Everyone")

    def test_family_keeps_its_role(self) -> None:
        with self.assertRaises(people.InvalidPersonError):
            self._update(self.family, role="Child")
        self.assertEqual(self._update(self.family).role, "Everyone")

    def test_family_can_still_be_renamed_and_recoloured(self) -> None:
        updated = people.update_person(
            self.conn,
            self.family.id,
            name="Household",
            colour=_BLUE,
            outlook_category="",
        )
        self.assertEqual(updated.name, "Household")
        self.assertEqual(updated.role, "Everyone")


class DeleteTest(unittest.TestCase):
    """A person can be removed; Family cannot."""

    def setUp(self) -> None:
        self.conn = db.connect(":memory:")

    def test_delete_removes_the_person(self) -> None:
        alex = people.add_person(self.conn, "Alex", "Adult", _ORANGE)
        sam = people.add_person(self.conn, "Sam", "Child", _BLUE)
        people.delete_person(self.conn, alex.id)
        names = [p.name for p in people.list_people(self.conn)]
        self.assertEqual(names, ["Family", "Sam"])
        self.assertEqual(people.list_people(self.conn)[1].id, sam.id)

    def test_family_cannot_be_deleted(self) -> None:
        family = people.list_people(self.conn)[0]
        with self.assertRaises(people.InvalidPersonError):
            people.delete_person(self.conn, family.id)
        self.assertEqual(len(people.list_people(self.conn)), 1)

    def test_deleting_an_unknown_person_raises_lookup_error(self) -> None:
        with self.assertRaises(LookupError):
            people.delete_person(self.conn, 999)

    def test_a_removed_name_can_be_added_again(self) -> None:
        alex = people.add_person(self.conn, "Alex", "Adult", _ORANGE)
        people.delete_person(self.conn, alex.id)
        again = people.add_person(self.conn, "Alex", "Child", _BLUE)
        self.assertEqual(again.role, "Child")


if __name__ == "__main__":
    unittest.main()
