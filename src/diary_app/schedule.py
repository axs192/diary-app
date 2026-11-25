"""The family's days: what is on, and where each adult is working.

``by_day`` wraps ``calendar_sync.events_by_day`` for the Today and Calendar
screens. It also reads the family's convention for where an adult is: an
event titled ``Alex : [London]`` puts Alex in London that day, and a weekday
with no such event means working from home (``WFH``). Those marker events
are not shown as events.
"""

import dataclasses
import datetime
import re
import sqlite3

from diary_app import calendar_sync
from diary_app.calendar_sync import Event
from diary_app.people import Person, list_people

DEFAULT_PLACE = "WFH"
_FIRST_WEEKEND_DAY = 5  # Saturday; date.weekday() counts Monday as 0
_MARKER = re.compile(r"^\[\s*(?P<place>[^\[\]]+?)\s*\]$")


@dataclasses.dataclass(frozen=True)
class Where:
    """Where one adult is on a day.

    Attributes:
        person: The adult.
        place: The place as written in the marker, or ``WFH``.
    """

    person: Person
    place: str


@dataclasses.dataclass(frozen=True)
class Day:
    """One day of the family calendar.

    Attributes:
        date: The day.
        events: Its events (all-day first, then by time), without the
            ``[Place]`` markers.
        where: One entry per adult, in the order they were added; empty at
            weekends with no marker, and empty everywhere until the calendar
            has synced once (so a diary that is not connected does not claim
            everyone is working from home).
    """

    date: datetime.date
    events: list[Event]
    where: list[Where]


def by_day(
    conn: sqlite3.Connection, first: datetime.date, count: int = 7
) -> list[Day]:
    """Lays out consecutive days with their events and where adults are.

    A marker is an event whose title, after the person's name, is only a
    place in square brackets (``Alex : [London]``), for an adult. A marker
    for anyone else, or a title with more than the bracket, is an ordinary
    event so that the mistake is visible. If an adult has two markers on a
    day, the earlier one wins.

    Args:
        conn: Open database connection.
        first: The first day.
        count: How many days.

    Returns:
        ``count`` days from ``first``, in order.
    """
    adults = [p for p in list_people(conn) if p.role == "Adult"]
    synced = calendar_sync.status(conn).synced_at is not None
    raw = calendar_sync.events_by_day(conn, first, count)
    days = []
    for date, events in raw.items():
        places: dict[int, str] = {}
        shown = []
        for event in events:  # already in time order, so the first one wins
            place = _marker_place(event)
            if place is None:
                shown.append(event)
            else:
                places.setdefault(event.person.id, place)
        days.append(
            Day(
                date,
                shown,
                _where(adults, places, date) if synced else [],
            )
        )
    return days


def _marker_place(event: Event) -> str | None:
    if event.person.role != "Adult" or event.kind:
        return None
    found = _MARKER.match(event.title)
    return found.group("place") if found else None


def _where(
    adults: list[Person], places: dict[int, str], date: datetime.date
) -> list[Where]:
    weekday = date.weekday() < _FIRST_WEEKEND_DAY
    result = []
    for adult in adults:
        place = places.get(adult.id, DEFAULT_PLACE if weekday else "")
        if place:
            result.append(Where(adult, place))
    return result
