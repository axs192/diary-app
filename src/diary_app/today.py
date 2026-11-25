"""What the kitchen screen shows: the kids' diary, coming up, and tonight.

``view`` gathers it for one day. How far ahead "Coming up" looks is a
household setting (``get_range`` / ``set_range``).
"""

import dataclasses
import datetime
import sqlite3
from typing import Final

from diary_app import db, mealplan, schedule
from diary_app.calendar_sync import Event
from diary_app.people import Person, list_people
from diary_app.recipes import Recipe

RANGES: Final = (
    ("sunday", "Until Sunday"),
    ("7", "Next 7 days"),
    ("14", "Next 14 days"),
)
_KEY = "today_range"
_NOTES_KEY = "show_notes"
_DEFAULT = "sunday"
_SUNDAY = 6  # date.weekday() counts Monday as 0


@dataclasses.dataclass(frozen=True)
class KidDay:
    """A child's today and tomorrow.

    Attributes:
        person: The child.
        today: Their events today (all-day first).
        tomorrow: Their events tomorrow.
    """

    person: Person
    today: list[Event]
    tomorrow: list[Event]


@dataclasses.dataclass(frozen=True)
class TodayView:
    """Everything the Today screen shows.

    Attributes:
        kids: One entry per child, in the order they were added.
        coming_up: Each day from tomorrow to ``until``.
        tonight: Today's planned dinner, or None.
        until: The last day of ``coming_up``.
    """

    kids: list[KidDay]
    coming_up: list[schedule.Day]
    tonight: Recipe | None
    until: datetime.date


def get_range(conn: sqlite3.Connection) -> str:
    """Reads how far ahead Coming up looks.

    Args:
        conn: Open database connection.

    Returns:
        A key from ``RANGES``; ``sunday`` if never chosen.
    """
    saved = db.get_setting(conn, _KEY, _DEFAULT)
    return saved if saved in dict(RANGES) else _DEFAULT


def set_range(conn: sqlite3.Connection, key: str) -> None:
    """Saves how far ahead Coming up looks.

    Args:
        conn: Open database connection.
        key: A key from ``RANGES``.

    Raises:
        ValueError: If ``key`` is not one of them (nothing is saved).
    """
    if key not in dict(RANGES):
        msg = "Pick one of the offered ranges."
        raise ValueError(msg)
    db.set_setting(conn, _KEY, key)


def get_show_notes(conn: sqlite3.Connection) -> bool:
    """Reads whether the event page shows an event's notes.

    Notes can hold private things (door codes, medical details), and this
    screen is on a wall, so a household can switch them off.

    Args:
        conn: Open database connection.

    Returns:
        False only if someone turned notes off; shown until then.
    """
    return db.get_setting(conn, _NOTES_KEY, "1") != "0"


def set_show_notes(conn: sqlite3.Connection, *, show: bool) -> None:
    """Saves whether the event page shows an event's notes.

    Args:
        conn: Open database connection.
        show: True to show notes, False to hide them.
    """
    db.set_setting(conn, _NOTES_KEY, "1" if show else "0")


def view(conn: sqlite3.Connection, today: datetime.date) -> TodayView:
    """Gathers the Today screen.

    "Until Sunday" means the coming Sunday, or the Sunday after when today
    is one, so the list is never empty on that day.

    Args:
        conn: Open database connection.
        today: The date to show.

    Returns:
        The kids' diary, the days to come, and tonight's dinner.
    """
    until = _until(today, get_range(conn))
    days = schedule.by_day(conn, today, (until - today).days + 1)
    kids = [
        KidDay(
            child,
            _of(child, days[0].events),
            _of(child, days[1].events),
        )
        for child in list_people(conn)
        if child.role == "Child"
    ]
    dinner = next(d for d in mealplan.week(conn, today) if d.day == today)
    return TodayView(kids, days[1:], dinner.recipe, until)


def _of(person: Person, events: list[Event]) -> list[Event]:
    return [e for e in events if e.person.id == person.id]


def _until(today: datetime.date, key: str) -> datetime.date:
    if key == "sunday":
        gap = (_SUNDAY - today.weekday()) % 7 or 7
        return today + datetime.timedelta(days=gap)
    return today + datetime.timedelta(days=int(key))
