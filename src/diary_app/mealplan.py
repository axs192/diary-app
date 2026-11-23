"""The dinner plan: one recipe per day, viewed a week at a time."""

import dataclasses
import datetime
import sqlite3

from diary_app import recipes

_DAYS_IN_WEEK = 7


@dataclasses.dataclass(frozen=True)
class PlannedDay:
    """One day of the plan.

    Attributes:
        day: The date.
        recipe: The planned dinner, or None when the day is empty.
    """

    day: datetime.date
    recipe: recipes.Recipe | None


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
    library = recipes.get_many(conn, set(planned.values()))
    days = [monday + datetime.timedelta(days=i) for i in range(_DAYS_IN_WEEK)]
    return [
        PlannedDay(d, library.get(planned.get(d.isoformat(), -1))) for d in days
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
    conn.execute(
        "INSERT INTO meal_plan (day, recipe_id) VALUES (?, ?)"
        " ON CONFLICT(day) DO UPDATE SET recipe_id = excluded.recipe_id",
        (day.isoformat(), recipe_id),
    )


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
