"""The family members shown across the diary, with their colours."""

import dataclasses
import sqlite3

from diary_app import theme

ROLES = ("Adult", "Child", "Everyone")
# "Everyone" (Family) is created once by the database, never by hand.
ADDABLE_ROLES = ("Adult", "Child")
_MAX_NAME_LENGTH = 50


class InvalidPersonError(ValueError):
    """Raised when a person's details are not acceptable."""


@dataclasses.dataclass(frozen=True)
class Person:
    """One family member (or ``Everyone``).

    Attributes:
        id: Database id.
        name: Display name.
        role: One of ``ROLES``.
        colour: A hex colour from ``theme.PERSON_COLOURS``.
        outlook_category: The Outlook category that marks this person's
            events; empty until set.
    """

    id: int
    name: str
    role: str
    colour: str
    outlook_category: str


def list_people(conn: sqlite3.Connection) -> list[Person]:
    """Returns everyone, in the order they were added.

    Args:
        conn: Open database connection.

    Returns:
        All people; a new database holds just ``Family``.
    """
    rows = conn.execute(
        "SELECT id, name, role, colour, outlook_category"
        " FROM person ORDER BY id"
    )
    return [Person(**dict(row)) for row in rows]


def add_person(
    conn: sqlite3.Connection,
    name: str,
    role: str,
    colour: str,
    outlook_category: str = "",
) -> Person:
    """Adds a person.

    Args:
        conn: Open database connection.
        name: Display name; surrounding spaces are removed.
        role: One of ``ROLES``.
        colour: A colour from ``theme.PERSON_COLOURS``.
        outlook_category: Outlook category marking their events.

    Returns:
        The stored person.

    Raises:
        InvalidPersonError: If any detail is not acceptable.
    """
    name, outlook_category = _validate(name, colour, outlook_category)
    if role not in ADDABLE_ROLES:
        msg = f"Role must be one of {', '.join(ADDABLE_ROLES)}."
        raise InvalidPersonError(msg)
    cursor = conn.execute(
        "INSERT INTO person (name, role, colour, outlook_category)"
        " VALUES (?, ?, ?, ?)",
        (name, role, colour, outlook_category),
    )
    return _get(conn, cursor.lastrowid)


def update_person(  # noqa: PLR0913
    conn: sqlite3.Connection,
    person_id: int,
    *,
    name: str,
    colour: str,
    outlook_category: str,
    role: str | None = None,
) -> Person:
    """Changes a person's name, colour, Outlook category and role.

    Args:
        conn: Open database connection.
        person_id: Id of the person to change.
        name: New display name.
        colour: New colour from ``theme.PERSON_COLOURS``.
        outlook_category: New Outlook category.
        role: ``Adult`` or ``Child``; ``None`` (or blank) keeps the current
            role. ``Family`` always stays ``Everyone``.

    Returns:
        The updated person.

    Raises:
        InvalidPersonError: If any detail is not acceptable, including a
            role change for ``Family`` or a role other than Adult or Child.
        LookupError: If no such person exists.
    """
    name, outlook_category = _validate(name, colour, outlook_category)
    current = _get(conn, person_id)
    if role:
        if role != current.role and (
            current.role == "Everyone" or role not in ADDABLE_ROLES
        ):
            msg = f"Role must be one of {', '.join(ADDABLE_ROLES)}."
            raise InvalidPersonError(msg)
    else:
        role = current.role
    conn.execute(
        "UPDATE person SET name = ?, colour = ?, outlook_category = ?,"
        " role = ? WHERE id = ?",
        (name, colour, outlook_category, role, person_id),
    )
    return _get(conn, person_id)


def delete_person(conn: sqlite3.Connection, person_id: int) -> None:
    """Removes a person.

    Nothing else in the database refers to a person: events are matched to
    people by title when they are read, so an event that named them simply
    stops matching (add the name again and it matches again).

    Args:
        conn: Open database connection.
        person_id: Id of the person to remove.

    Raises:
        InvalidPersonError: If the person is ``Family``, which stays.
        LookupError: If no such person exists.
    """
    person = _get(conn, person_id)
    if person.role == "Everyone":
        msg = "Family cannot be removed."
        raise InvalidPersonError(msg)
    conn.execute("DELETE FROM person WHERE id = ?", (person_id,))


def _validate(name: str, colour: str, outlook_category: str) -> tuple[str, str]:
    name = name.strip()
    outlook_category = outlook_category.strip()
    if not name:
        msg = "Name cannot be blank."
        raise InvalidPersonError(msg)
    if len(name) > _MAX_NAME_LENGTH or len(outlook_category) > _MAX_NAME_LENGTH:
        msg = f"Names must be {_MAX_NAME_LENGTH} characters or fewer."
        raise InvalidPersonError(msg)
    if not theme.is_person_colour(colour):
        msg = "Pick one of the offered colours."
        raise InvalidPersonError(msg)
    return name, outlook_category


def _get(conn: sqlite3.Connection, person_id: int | None) -> Person:
    row = conn.execute(
        "SELECT id, name, role, colour, outlook_category"
        " FROM person WHERE id = ?",
        (person_id,),
    ).fetchone()
    if row is None:
        msg = f"No person with id {person_id}"
        raise LookupError(msg)
    return Person(**dict(row))
