"""The shopping list: generated from the plan and the pantry, then shopped.

``generate`` adds up what the dinners on the chosen days need, takes away
what the pantry already holds, and stores the result for that week. After
that the list only changes when you tick things, add or remove your own
items, press Done shopping, or generate again.

Rows are one of:

* to buy, grouped by aisle (made from meals);
* covered, which the pantry already holds enough of (kept so a wrong match
  can be noticed); or
* your own items, added by hand or sent from the pantry.
"""

import dataclasses
import datetime
import sqlite3
from collections.abc import Collection
from fractions import Fraction

from diary_app import db, ingredients, mealplan, pantry
from diary_app.ingredients import Amount

_MAX_NAME_LENGTH = 60
_WEEK_DAYS = 7
_SHELF_FOR_AISLE = {
    "Dairy & eggs": "Fridge",
    "Meat & fish": "Fridge",
    "Frozen": "Freezer",
    "Herbs & spices": "Spices",
}


class InvalidItemError(ValueError):
    """Raised when a shopping item to add is not acceptable."""


@dataclasses.dataclass(frozen=True)
class ShoppingItem:
    """One row of the list.

    Attributes:
        id: Database id.
        name: What it is, as shown.
        amount: How much to buy, or None for a line that could not be read
            (or an item added without an amount). For a covered row, how
            much the meals need.
        have: What the pantry holds, written out ("4", "100 g"), or empty.
        ticked: True once crossed off.
        covered: True when the pantry holds enough and nothing needs buying.
        source: ``"meal"`` or ``"extra"`` (added by hand).
        aisle: Where in the shop it is found.
    """

    id: int
    name: str
    amount: Amount | None
    have: str
    ticked: bool
    covered: bool
    source: str
    aisle: str


@dataclasses.dataclass(frozen=True)
class Aisle:
    """The to-buy items found in one part of the shop.

    Attributes:
        name: E.g. ``"Meat & fish"``.
        items: Its rows, by name.
    """

    name: str
    items: tuple[ShoppingItem, ...]


@dataclasses.dataclass(frozen=True)
class ShoppingList:
    """One week's list.

    Attributes:
        aisles: Items to buy from meals, in shop order; empty aisles left out.
        extras: Your own items, in the order added.
        covered: Meal ingredients the pantry already covers.
        generated_for: The days the list was last generated for.
    """

    aisles: tuple[Aisle, ...]
    extras: tuple[ShoppingItem, ...]
    covered: tuple[ShoppingItem, ...]
    generated_for: tuple[datetime.date, ...]

    @property
    def _to_buy(self) -> list[ShoppingItem]:
        return [i for a in self.aisles for i in a.items] + list(self.extras)

    @property
    def remaining(self) -> int:
        """How many rows to buy are not yet ticked."""
        return sum(1 for item in self._to_buy if not item.ticked)

    @property
    def ticked(self) -> int:
        """How many rows to buy are ticked."""
        return sum(1 for item in self._to_buy if item.ticked)


def _week_key(day: datetime.date) -> str:
    """Names a week by its Monday, whichever date in it was given."""
    return mealplan.monday_of(day).isoformat()


def _display(name: str) -> str:
    return name[:1].upper() + name[1:]


def _from_row(row: sqlite3.Row) -> ShoppingItem:
    amount = (
        Amount(Fraction(row["amount"]), row["unit"])
        if row["amount"] is not None
        else None
    )
    return ShoppingItem(
        id=row["id"],
        name=row["name"],
        amount=amount,
        have=row["have"],
        ticked=bool(row["ticked"]),
        covered=bool(row["covered"]),
        source=row["source"],
        aisle=row["aisle"],
    )


def get_list(conn: sqlite3.Connection, monday: datetime.date) -> ShoppingList:
    """Reads a week's stored list.

    Args:
        conn: Open database connection.
        monday: Any date in the week.

    Returns:
        The list; empty (and ``generated_for`` empty) if nothing has been
        generated or added for that week.
    """
    week = _week_key(monday)
    rows = [
        _from_row(r)
        for r in conn.execute(
            "SELECT * FROM shopping_item WHERE week = ? ORDER BY id", (week,)
        )
    ]
    shop_order = {name: n for n, name in enumerate(ingredients.AISLES)}

    def by_aisle(item: ShoppingItem) -> tuple[int, str]:
        return (shop_order.get(item.aisle, len(shop_order)), item.name.lower())

    meals = sorted((r for r in rows if r.source == "meal"), key=by_aisle)
    aisles = [
        Aisle(
            name, tuple(i for i in meals if i.aisle == name and not i.covered)
        )
        for name in ingredients.AISLES
    ]
    found = conn.execute(
        "SELECT days FROM shopping_generation WHERE week = ?", (week,)
    ).fetchone()
    return ShoppingList(
        aisles=tuple(a for a in aisles if a.items),
        extras=tuple(r for r in rows if r.source == "extra"),
        covered=tuple(r for r in meals if r.covered),
        generated_for=tuple(
            datetime.date.fromisoformat(d) for d in found["days"].split(",")
        )
        if found and found["days"]
        else (),
    )


@dataclasses.dataclass
class _Need:
    name: str
    amount: Amount | None
    aisle: str


def _needs(
    planned: list[mealplan.PlannedDay],
) -> dict[tuple[str, str | None], _Need]:
    """Adds up the ingredients of the given dinners.

    Keyed by item and unit, so the same thing in two units stays two rows,
    and by item alone (``None`` unit) for lines that could not be read.
    """
    needs: dict[tuple[str, str | None], _Need] = {}
    for day in planned:
        if day.recipe is None:
            continue
        for line in day.recipe.ingredients:
            parsed = ingredients.parse(line)
            key = (
                ingredients.item_key(parsed.name),
                parsed.amount.unit if parsed.amount else None,
            )
            found = needs.get(key)
            if found is None:
                needs[key] = _Need(
                    _display(parsed.name),
                    parsed.amount,
                    ingredients.aisle(parsed.name),
                )
            elif found.amount is not None and parsed.amount is not None:
                found.amount = found.amount + parsed.amount
    return needs


def _check_days(
    planned: list[mealplan.PlannedDay], days: Collection[datetime.date]
) -> list[mealplan.PlannedDay]:
    chosen = sorted(set(days))
    if not chosen:
        msg = "Pick at least one day."
        raise ValueError(msg)
    by_day = {p.day: p for p in planned}
    picked = []
    for day in chosen:
        found = by_day.get(day)
        if found is None:
            msg = f"{day} is not in this week."
            raise ValueError(msg)
        if found.recipe is None:
            msg = f"No dinner is planned for {day}."
            raise ValueError(msg)
        if found.cooked:
            msg = f"The dinner on {day} has already been cooked."
            raise ValueError(msg)
        picked.append(found)
    return picked


def generate(
    conn: sqlite3.Connection,
    monday: datetime.date,
    days: Collection[datetime.date],
) -> ShoppingList:
    """Works out what to buy for some of a week's dinners and stores it.

    Everything the dinners need is added up, then compared with the pantry:
    enough in stock means covered; some in stock means only the shortfall is
    listed; a different unit (a jar where a tin is wanted) counts as covered
    and the row says what is held. Any earlier generated rows for the week
    are replaced. Your own items stay, and a row that was ticked stays ticked
    if the same item is still needed in the same unit.

    Args:
        conn: Open database connection.
        monday: Any date in the week.
        days: The days to shop for.

    Returns:
        The stored list.

    Raises:
        ValueError: If no days are given, or a day is outside the week, has
            no dinner planned, or has already been cooked; nothing changes.
    """
    week = _week_key(monday)
    with db.transaction(conn):
        picked = _check_days(mealplan.week(conn, monday), days)
        stock = pantry.items(conn)
        ticked = {
            (ingredients.item_key(r["name"]), r["unit"])
            for r in conn.execute(
                "SELECT name, unit FROM shopping_item WHERE week = ?"
                " AND source = 'meal' AND ticked = 1 AND covered = 0",
                (week,),
            )
        }
        conn.execute(
            "DELETE FROM shopping_item WHERE week = ? AND source = 'meal'",
            (week,),
        )
        for (key, unit), need in _needs(picked).items():
            to_buy, have, covered = _compare(
                need, pantry.match(stock, need.name)
            )
            conn.execute(
                "INSERT INTO shopping_item (week, source, name, aisle, unit,"
                " amount, have, covered, ticked)"
                " VALUES (?, 'meal', ?, ?, ?, ?, ?, ?, ?)",
                (
                    week,
                    need.name,
                    need.aisle,
                    to_buy.unit if to_buy else "",
                    str(to_buy.value) if to_buy else None,
                    have,
                    int(covered),
                    int(not covered and (key, unit or "") in ticked),
                ),
            )
        conn.execute(
            "INSERT INTO shopping_generation (week, days) VALUES (?, ?)"
            " ON CONFLICT(week) DO UPDATE SET days = excluded.days",
            (week, ",".join(p.day.isoformat() for p in picked)),
        )
    return get_list(conn, monday)


def _compare(
    need: _Need, held: pantry.PantryItem | None
) -> tuple[Amount | None, str, bool]:
    """Returns (amount to show, note of what is held, whether covered)."""
    if held is None or held.amount.is_zero:
        return need.amount, "", False
    if need.amount is None:
        return None, held.amount.format(), True
    if not held.amount.comparable(need.amount):
        return need.amount, held.amount.format(), True
    if held.amount.value >= need.amount.value:
        return need.amount, held.amount.format(), True
    return need.amount.minus(held.amount), held.amount.format(), False


def toggle(conn: sqlite3.Connection, item_id: int) -> None:
    """Ticks an item, or unticks it if it was ticked.

    Args:
        conn: Open database connection.
        item_id: The row's id.

    Raises:
        LookupError: If there is no such row.
    """
    changed = conn.execute(
        "UPDATE shopping_item SET ticked = 1 - ticked WHERE id = ?", (item_id,)
    ).rowcount
    if not changed:
        msg = f"No shopping item {item_id}"
        raise LookupError(msg)


def add_extra(
    conn: sqlite3.Connection,
    monday: datetime.date,
    name: str,
    amount: Amount | None = None,
) -> ShoppingItem:
    """Adds an item of your own to a week's list.

    Args:
        conn: Open database connection.
        monday: Any date in the week.
        name: What to buy. Surrounding space is trimmed.
        amount: How much, if you want to say.

    Returns:
        The new row.

    Raises:
        InvalidItemError: If the name is blank or too long.
    """
    clean = " ".join(name.split())
    if not clean:
        msg = "Say what to add."
        raise InvalidItemError(msg)
    if len(clean) > _MAX_NAME_LENGTH:
        msg = f"Keep the name under {_MAX_NAME_LENGTH} characters."
        raise InvalidItemError(msg)
    cursor = conn.execute(
        "INSERT INTO shopping_item (week, source, name, aisle, unit, amount)"
        " VALUES (?, 'extra', ?, ?, ?, ?)",
        (
            _week_key(monday),
            clean,
            ingredients.aisle(clean),
            amount.unit if amount else "",
            str(amount.value) if amount else None,
        ),
    )
    row = conn.execute(
        "SELECT * FROM shopping_item WHERE id = ?", (cursor.lastrowid,)
    ).fetchone()
    return _from_row(row)


def remove_extra(conn: sqlite3.Connection, item_id: int) -> None:
    """Removes one of your own items. Does nothing if it is already gone.

    Rows made from meals cannot be removed this way; generate again instead.

    Args:
        conn: Open database connection.
        item_id: The row's id.
    """
    conn.execute(
        "DELETE FROM shopping_item WHERE id = ? AND source = 'extra'",
        (item_id,),
    )


def done_shopping(conn: sqlite3.Connection, monday: datetime.date) -> int:
    """Moves everything ticked into the pantry and off the list.

    A ticked row with an amount is added to the pantry item of the same name
    and unit, or becomes a new item on the shelf that suits its aisle. A
    ticked row with no amount just leaves the list. Covered rows are never
    touched.

    Args:
        conn: Open database connection.
        monday: Any date in the week.

    Returns:
        How many rows were moved off the list.
    """
    week = _week_key(monday)
    with db.transaction(conn):
        rows = [
            _from_row(r)
            for r in conn.execute(
                "SELECT * FROM shopping_item"
                " WHERE week = ? AND ticked = 1 AND covered = 0 ORDER BY id",
                (week,),
            )
        ]
        stock = pantry.items(conn)
        for row in rows:
            if row.amount is not None:
                key = ingredients.item_key(row.name)
                same = next(
                    (
                        i
                        for i in stock
                        if ingredients.item_key(i.name) == key
                        and i.amount.comparable(row.amount)
                    ),
                    None,
                )
                if same:
                    pantry.adjust(conn, same.id, row.amount.value)
                else:
                    stock.append(
                        pantry.add(
                            conn,
                            row.name[:_MAX_NAME_LENGTH],
                            row.amount,
                            shelf=_SHELF_FOR_AISLE.get(row.aisle, "Cupboard"),
                        )
                    )
            conn.execute("DELETE FROM shopping_item WHERE id = ?", (row.id,))
    return len(rows)


def as_text(listing: ShoppingList) -> str:
    """Writes the list out as plain text, for copying into an online order.

    Args:
        listing: A list from ``get_list`` or ``generate``.

    Returns:
        What is still to buy (not ticked, not covered), by aisle, then your
        own items. Empty when there is nothing to buy.
    """

    def line(item: ShoppingItem) -> str:
        amount = f" - {item.amount.format()}" if item.amount else ""
        return f"- {item.name}{amount}"

    sections = [
        "\n".join([aisle.name, *(line(i) for i in aisle.items if not i.ticked)])
        for aisle in listing.aisles
        if any(not i.ticked for i in aisle.items)
    ]
    extras = [i for i in listing.extras if not i.ticked]
    if extras:
        sections.append("\n".join(["Your items", *(line(i) for i in extras)]))
    return "\n\n".join(sections)
