"""The dinner plan: one recipe per day, viewed a week at a time."""

import dataclasses
import datetime
import sqlite3
from fractions import Fraction

from diary_app import db, ingredients, pantry, recipes
from diary_app.ingredients import Amount

_DAYS_IN_WEEK = 7


@dataclasses.dataclass(frozen=True)
class PlannedDay:
    """One day of the plan.

    Attributes:
        day: The date.
        recipe: The planned dinner, or None when the day is empty.
        cooked: True once "Cooked it" has taken the dinner's ingredients out
            of the pantry (see ``cook``).
    """

    day: datetime.date
    recipe: recipes.Recipe | None
    cooked: bool = False


@dataclasses.dataclass(frozen=True)
class Bar:
    """One line of the week-balance panel.

    Attributes:
        label: What is counted, e.g. "Oily fish".
        count: How many planned dinners carry the tag this week.
        goal: The number to aim for (or not to exceed when ``at_most``).
        at_most: True when ``goal`` is a limit rather than a target.
    """

    label: str
    count: int
    goal: int
    at_most: bool = False


_BALANCE = (
    ("Veg-led dinners", "Veg-led", 3, False),
    ("Oily fish", "Oily fish", 1, False),
    ("Treat nights", "Treat night", 1, True),
)


def monday_of(day: datetime.date) -> datetime.date:
    """Returns the Monday of the week containing ``day``."""
    return day - datetime.timedelta(days=day.weekday())


def week(conn: sqlite3.Connection, day: datetime.date) -> list[PlannedDay]:
    """Returns the week containing ``day``.

    Args:
        conn: Open database connection.
        day: Any date; its Monday-to-Sunday week is returned.

    Returns:
        Exactly seven days, Monday first, empty days included.
    """
    monday = monday_of(day)
    sunday = monday + datetime.timedelta(days=_DAYS_IN_WEEK - 1)
    rows = conn.execute(
        "SELECT day, recipe_id FROM meal_plan WHERE day BETWEEN ? AND ?",
        (monday.isoformat(), sunday.isoformat()),
    )
    planned = {row["day"]: row["recipe_id"] for row in rows}
    cooked = {
        row["day"]
        for row in conn.execute(
            "SELECT day FROM cooked_day WHERE day BETWEEN ? AND ?",
            (monday.isoformat(), sunday.isoformat()),
        )
    }
    library = recipes.get_many(conn, set(planned.values()))
    days = [monday + datetime.timedelta(days=i) for i in range(_DAYS_IN_WEEK)]
    return [
        PlannedDay(
            d,
            library.get(planned.get(d.isoformat(), -1)),
            d.isoformat() in cooked,
        )
        for d in days
    ]


def set_meal(
    conn: sqlite3.Connection, day: datetime.date, recipe_id: int
) -> None:
    """Plans a recipe for a day, replacing whatever was there.

    Args:
        conn: Open database connection.
        day: The date.
        recipe_id: Recipe to cook.

    Raises:
        LookupError: If no such recipe exists.
    """
    recipes.get(conn, recipe_id)
    with db.transaction(conn):
        conn.execute(
            "INSERT INTO meal_plan (day, recipe_id) VALUES (?, ?)"
            " ON CONFLICT(day) DO UPDATE SET recipe_id = excluded.recipe_id",
            (day.isoformat(), recipe_id),
        )
        # A different dinner has not been cooked yet. What was taken from
        # the pantry stays taken: the earlier dinner was eaten.
        conn.execute("DELETE FROM cooked_day WHERE day = ?", (day.isoformat(),))


def clear_day(conn: sqlite3.Connection, day: datetime.date) -> None:
    """Empties one day.

    Args:
        conn: Open database connection.
        day: The date.
    """
    conn.execute("DELETE FROM meal_plan WHERE day = ?", (day.isoformat(),))


def clear_week(conn: sqlite3.Connection, day: datetime.date) -> None:
    """Empties the Monday-to-Sunday week containing ``day``.

    Args:
        conn: Open database connection.
        day: Any date in the week.
    """
    monday = monday_of(day)
    sunday = monday + datetime.timedelta(days=_DAYS_IN_WEEK - 1)
    conn.execute(
        "DELETE FROM meal_plan WHERE day BETWEEN ? AND ?",
        (monday.isoformat(), sunday.isoformat()),
    )


def cook(
    conn: sqlite3.Connection, day: datetime.date
) -> list[tuple[str, Amount]]:
    """Marks a day's dinner as cooked and takes its food out of the pantry.

    Each readable ingredient that matches a pantry item in the same unit is
    taken from it, never below zero. Lines in other units (a jar where the
    recipe says a tin) and lines that could not be read are left alone. What
    was taken is recorded so ``uncook`` can put back exactly that.

    Args:
        conn: Open database connection.
        day: The date.

    Returns:
        ``(pantry item name, amount taken)`` for each item used; empty when
        the day has no dinner, or was already cooked (nothing is taken twice).
    """
    with db.transaction(conn):
        planned = conn.execute(
            "SELECT recipe_id FROM meal_plan WHERE day = ?", (day.isoformat(),)
        ).fetchone()
        cooked = conn.execute(
            "SELECT 1 FROM cooked_day WHERE day = ?", (day.isoformat(),)
        ).fetchone()
        if planned is None or cooked is not None:
            return []
        stock = pantry.items(conn)
        left = {item.id: item.amount.value for item in stock}
        taken: dict[int, Fraction] = {}
        for line in recipes.get(conn, planned["recipe_id"]).ingredients:
            wanted = ingredients.parse(line)
            item = pantry.match(stock, wanted.name)
            if (
                wanted.amount is None
                or item is None
                or not item.amount.comparable(wanted.amount)
            ):
                continue
            use = min(left[item.id], wanted.amount.value)
            if use > 0:
                left[item.id] -= use
                taken[item.id] = taken.get(item.id, Fraction(0)) + use
        conn.execute(
            "INSERT INTO cooked_day (day) VALUES (?)", (day.isoformat(),)
        )
        used = {item.id: item for item in stock}
        for item_id, value in taken.items():
            pantry.adjust(conn, item_id, -value)
            conn.execute(
                "INSERT INTO cooked_deduction (day, pantry_id, amount)"
                " VALUES (?, ?, ?)",
                (day.isoformat(), item_id, str(value)),
            )
        return [
            (used[item_id].name, Amount(value, used[item_id].amount.unit))
            for item_id, value in taken.items()
        ]


def uncook(conn: sqlite3.Connection, day: datetime.date) -> None:
    """Undoes ``cook``: puts back exactly what it took and clears the mark.

    Items that have been deleted from the pantry since are skipped. Does
    nothing for a day that was not cooked.

    Args:
        conn: Open database connection.
        day: The date.
    """
    with db.transaction(conn):
        rows = conn.execute(
            "SELECT pantry_id, amount FROM cooked_deduction WHERE day = ?",
            (day.isoformat(),),
        ).fetchall()
        for row in rows:
            pantry.adjust(conn, row["pantry_id"], Fraction(row["amount"]))
        conn.execute("DELETE FROM cooked_day WHERE day = ?", (day.isoformat(),))


def recent_recipe_ids(
    conn: sqlite3.Connection, before: datetime.date, weeks: int = 2
) -> set[int]:
    """Finds recipes cooked in the weeks just before a date.

    Args:
        conn: Open database connection.
        before: Start of the period being planned (not included).
        weeks: How many weeks back to look.

    Returns:
        Ids of recipes planned on any day in that look-back window.
    """
    start = before - datetime.timedelta(weeks=weeks)
    rows = conn.execute(
        "SELECT DISTINCT recipe_id FROM meal_plan WHERE day >= ? AND day < ?",
        (start.isoformat(), before.isoformat()),
    )
    return {row["recipe_id"] for row in rows}


def balance(days: list[PlannedDay]) -> list[Bar]:
    """Counts how well the week is balanced.

    Args:
        days: A week from ``week``.

    Returns:
        One bar each for veg-led dinners, oily fish and treat nights.
    """
    return [
        Bar(
            label,
            sum(1 for d in days if d.recipe and tag in d.recipe.tags),
            goal,
            at_most,
        )
        for label, tag, goal, at_most in _BALANCE
    ]
