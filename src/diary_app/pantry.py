"""The household pantry: what is in the cupboard, how much, and for how long.

Each item holds a real amount (4 tins, 3 onions, 500 g pasta, 1 jar of
cumin), an optional use-by date and a shelf. ``match`` says which item an
ingredient is, which the shopping list and "cooked it" use to compare what
is wanted with what is there.
"""

import dataclasses
import datetime
import sqlite3
from fractions import Fraction

from diary_app import db, ingredients, recipes
from diary_app.ingredients import Amount

SHELVES = ("Fridge", "Cupboard", "Freezer", "Spices", "Baking")
_MAX_NAME_LENGTH = 60
_USE_SOON_DAYS = 3
_LATER_DAYS = 14


class InvalidPantryItemError(ValueError):
    """Raised when a pantry item's details are not acceptable."""


@dataclasses.dataclass(frozen=True)
class PantryItem:
    """One thing in the pantry.

    Attributes:
        id: Database id.
        name: What it is, e.g. ``"Chopped tomatoes"``.
        shelf: One of ``SHELVES``.
        amount: How much is left (zero means none left).
        expires_on: Use-by or best-before date, if known.
    """

    id: int
    name: str
    shelf: str
    amount: Amount
    expires_on: datetime.date | None


@dataclasses.dataclass(frozen=True)
class UseBy:
    """How to show an item's date.

    Attributes:
        text: ``"Use by 24 Nov"`` (fridge) or ``"Best before 4 Dec"``.
        chip: A short label for the days left ("Expired", "Today",
            "Tomorrow", "3 days"), or empty when it is far off.
        urgency: ``"expired"``, ``"soon"`` (within 3 days), ``"later"``
            (within 14) or ``"none"``; for colouring the chip.
    """

    text: str
    chip: str
    urgency: str


def _validated_name(name: str, shelf: str) -> str:
    clean = " ".join(name.split())
    if not clean:
        msg = "Give the item a name."
        raise InvalidPantryItemError(msg)
    if len(clean) > _MAX_NAME_LENGTH:
        msg = f"Keep the name under {_MAX_NAME_LENGTH} characters."
        raise InvalidPantryItemError(msg)
    if shelf not in SHELVES:
        msg = "Pick one of the shelves."
        raise InvalidPantryItemError(msg)
    return clean


def _from_row(row: sqlite3.Row) -> PantryItem:
    expires = row["expires_on"]
    return PantryItem(
        id=row["id"],
        name=row["name"],
        shelf=row["shelf"],
        amount=Amount(Fraction(row["amount"]), row["unit"]),
        expires_on=datetime.date.fromisoformat(expires) if expires else None,
    )


def add(
    conn: sqlite3.Connection,
    name: str,
    amount: Amount,
    *,
    shelf: str = "Cupboard",
    expires_on: datetime.date | None = None,
) -> PantryItem:
    """Puts something in the pantry.

    Args:
        conn: Open database connection.
        name: What it is. Surrounding space is trimmed.
        amount: How much there is (zero is allowed: none left).
        shelf: One of ``SHELVES``.
        expires_on: Use-by or best-before date, if any.

    Returns:
        The stored item.

    Raises:
        InvalidPantryItemError: If the name is blank or too long, or the
            shelf is unknown; nothing is stored.
    """
    clean = _validated_name(name, shelf)
    cursor = conn.execute(
        "INSERT INTO pantry_item (name, shelf, unit, amount, expires_on)"
        " VALUES (?, ?, ?, ?, ?)",
        (
            clean,
            shelf,
            amount.unit,
            str(amount.value),
            expires_on.isoformat() if expires_on else None,
        ),
    )
    return get(conn, int(cursor.lastrowid or 0))


def get(conn: sqlite3.Connection, item_id: int) -> PantryItem:
    """Finds one item.

    Args:
        conn: Open database connection.
        item_id: The item's id.

    Returns:
        The item.

    Raises:
        LookupError: If there is no such item.
    """
    row = conn.execute(
        "SELECT * FROM pantry_item WHERE id = ?", (item_id,)
    ).fetchone()
    if row is None:
        msg = f"No pantry item {item_id}"
        raise LookupError(msg)
    return _from_row(row)


def update(conn: sqlite3.Connection, item: PantryItem) -> PantryItem:
    """Replaces a stored item's details with those of ``item``.

    Typical use: ``update(conn, dataclasses.replace(old, name="Rice"))``.

    Args:
        conn: Open database connection.
        item: The item as it should now be; ``item.id`` says which one.

    Returns:
        The changed item.

    Raises:
        InvalidPantryItemError: As for ``add``; nothing is changed.
        LookupError: If there is no item with that id.
    """
    clean = _validated_name(item.name, item.shelf)
    get(conn, item.id)
    conn.execute(
        "UPDATE pantry_item SET name = ?, shelf = ?, unit = ?, amount = ?,"
        " expires_on = ? WHERE id = ?",
        (
            clean,
            item.shelf,
            item.amount.unit,
            str(item.amount.value),
            item.expires_on.isoformat() if item.expires_on else None,
            item.id,
        ),
    )
    return get(conn, item.id)


def delete(conn: sqlite3.Connection, item_id: int) -> None:
    """Removes an item. Does nothing if it is already gone.

    Args:
        conn: Open database connection.
        item_id: The item to remove.
    """
    conn.execute("DELETE FROM pantry_item WHERE id = ?", (item_id,))


def adjust(
    conn: sqlite3.Connection, item_id: int, delta: Fraction
) -> PantryItem:
    """Adds to or takes from an item, in its own unit.

    Args:
        conn: Open database connection.
        item_id: The item to change.
        delta: How much more (positive) or less (negative). The amount
            stops at zero rather than going below.

    Returns:
        The changed item.

    Raises:
        LookupError: If there is no such item.
    """
    with db.transaction(conn):
        item = get(conn, item_id)
        left = max(item.amount.value + delta, Fraction(0))
        conn.execute(
            "UPDATE pantry_item SET amount = ? WHERE id = ?",
            (str(left), item_id),
        )
    return get(conn, item_id)


def items(conn: sqlite3.Connection) -> list[PantryItem]:
    """Lists everything in the pantry, most urgent first.

    Args:
        conn: Open database connection.

    Returns:
        Items with a date, soonest first; then items without one, by name;
        then items with none left, by name.
    """
    everything = [
        _from_row(row)
        for row in conn.execute("SELECT * FROM pantry_item ORDER BY name, id")
    ]

    def order(item: PantryItem) -> tuple[int, str, str]:
        if item.amount.is_zero:
            return (2, "", item.name.lower())
        if item.expires_on:
            return (0, item.expires_on.isoformat(), item.name.lower())
        return (1, "", item.name.lower())

    return sorted(everything, key=order)


def by_shelf(stock: list[PantryItem]) -> list[tuple[str, list[PantryItem]]]:
    """Groups items by shelf, in the order of ``SHELVES``.

    Args:
        stock: Items, in the order they should appear within a shelf.

    Returns:
        ``(shelf, items)`` pairs; a shelf with nothing on it is left out.
    """
    return [
        (shelf, mine)
        for shelf in SHELVES
        if (mine := [i for i in stock if i.shelf == shelf])
    ]


def use_by(item: PantryItem, today: datetime.date) -> UseBy | None:
    """Works out how to show an item's date.

    Args:
        item: The item.
        today: The date to count from.

    Returns:
        How to show the date, or None when the item has no date.
    """
    if item.expires_on is None:
        return None
    left = (item.expires_on - today).days
    prefix = "Use by" if item.shelf == "Fridge" else "Best before"
    date = f"{item.expires_on.day} {item.expires_on:%b}"
    if item.expires_on.year != today.year:
        date += f" {item.expires_on.year}"
    if left < 0:
        chip, urgency = "Expired", "expired"
    elif left == 0:
        chip, urgency = "Today", "expired"
    elif left == 1:
        chip, urgency = "Tomorrow", "soon"
    elif left <= _USE_SOON_DAYS:
        chip, urgency = f"{left} days", "soon"
    elif left <= _LATER_DAYS:
        chip, urgency = f"{left} days", "later"
    else:
        chip, urgency = "", "none"
    return UseBy(f"{prefix} {date}", chip, urgency)


def use_soon(
    stock: list[PantryItem],
    today: datetime.date,
    days: int = _USE_SOON_DAYS,
) -> list[PantryItem]:
    """Picks the items that should be used up first.

    Args:
        stock: Items to look through.
        today: The date to count from.
        days: How many days ahead counts as soon.

    Returns:
        Items that are expired or due within ``days`` days, soonest first.
        Items with none left are not included.
    """
    due = [
        i
        for i in stock
        if i.expires_on
        and not i.amount.is_zero
        and (i.expires_on - today).days <= days
    ]
    return sorted(due, key=lambda i: (i.expires_on or today, i.name.lower()))


def match(stock: list[PantryItem], ingredient_name: str) -> PantryItem | None:
    """Finds the pantry item an ingredient calls for.

    Uses ``ingredients.same_item``, so it goes by words. When several items
    fit (Milk and Coconut milk, for "coconut milk"), the one with the most
    words in its name wins. Items with none left still match.

    Args:
        stock: Items to look through.
        ingredient_name: The ingredient's name.

    Returns:
        The matching item, or None.
    """
    fits = [i for i in stock if ingredients.same_item(i.name, ingredient_name)]
    if not fits:
        return None
    return max(
        fits,
        key=lambda i: (len(ingredients.item_key(i.name).split("-")), -i.id),
    )


def meals_using(
    conn: sqlite3.Connection, stock: list[PantryItem], limit: int = 5
) -> list[recipes.Recipe]:
    """Suggests recipes that use up the given items.

    Args:
        conn: Open database connection.
        stock: The items to use up. Items with none left are ignored.
        limit: The most recipes to return.

    Returns:
        Recipes that use at least one of the items, those using the most
        first (then by name).
    """
    available = [i for i in stock if not i.amount.is_zero]
    if not available:
        return []
    scored: list[tuple[int, recipes.Recipe]] = []
    for recipe in recipes.search(conn):
        used = {
            found.id
            for line in recipe.ingredients
            if (found := match(available, ingredients.parse(line).name))
        }
        if used:
            scored.append((len(used), recipe))
    scored.sort(key=lambda pair: (-pair[0], pair[1].name.lower()))
    return [recipe for _count, recipe in scored[:limit]]
