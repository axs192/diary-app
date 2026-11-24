"""The family calendar: copied from Outlook, then read back by the week.

``sync`` copies the chosen Outlook calendars into the database (the web pages
never talk to Microsoft). ``events_by_day`` reads a week back, working out
who each event is for from its title at that moment, so renaming a person
in Settings changes the calendar at once.

Titles follow the family's convention ``<Name> : <what>``, for example
``Mum : Swimming``. A prefix that is not a family member is a kind of event
(``Birthday : Nan``). Outlook categories are not used: the iPhone app cannot
set them.
"""

import dataclasses
import datetime
import logging
import sqlite3
from collections.abc import Collection, Sequence

from diary_app import db, outlook
from diary_app.people import Person, list_people

_logger = logging.getLogger(__name__)

_WEEKS_BEFORE = 1
_WEEKS_AFTER = 8
_SYNCED_AT = "calendar_synced_at"
_ERROR = "calendar_error"
_NEEDS_SIGN_IN = "calendar_needs_sign_in"
_SIGN_IN_AGAIN = "Outlook needs signing in again."
_ONE_DAY = datetime.timedelta(days=1)


@dataclasses.dataclass(frozen=True)
class ParsedTitle:
    """What a calendar title says.

    Attributes:
        person: Who it is for; ``Family`` when no one is named.
        kind: A kind of event such as ``Birthday``; empty if none.
        title: The title to show, without the ``Name :`` prefix.
        needs_name: True when the title does not follow the convention.
    """

    person: Person
    kind: str
    title: str
    needs_name: bool


@dataclasses.dataclass(frozen=True)
class Event:
    """One event on the family calendar.

    Attributes:
        id: Outlook's id (one per occurrence of a recurring event).
        title: The title to show, without any ``Name :`` prefix.
        kind: A kind such as ``Birthday``; empty if none.
        start: Local start time (midnight for an all-day event).
        end: Local end time, exclusive.
        all_day: Whether Outlook marks it all-day.
        calendar: Name of the Outlook calendar it came from.
        person: Who it is for; ``Family`` when no one is named.
        needs_name: True when the title does not follow the convention.
    """

    id: str
    title: str
    kind: str
    start: datetime.datetime
    end: datetime.datetime
    all_day: bool
    calendar: str
    person: Person
    needs_name: bool


@dataclasses.dataclass(frozen=True)
class Calendar:
    """One Outlook calendar and whether the diary shows it.

    Attributes:
        id: Outlook's id.
        name: Display name.
        selected: Whether its events are shown.
    """

    id: str
    name: str
    selected: bool


@dataclasses.dataclass(frozen=True)
class SyncResult:
    """How a sync went.

    Attributes:
        ok: Whether it completed.
        events: Events stored (0 on failure).
        error: A sentence for the household when it failed.
    """

    ok: bool
    events: int = 0
    error: str = ""


@dataclasses.dataclass(frozen=True)
class SyncStatus:
    """What the pages say about the last sync.

    Attributes:
        synced_at: When the last good sync finished, or None.
        error: Why the latest attempt failed; empty if it did not.
        needs_sign_in: Whether someone must sign in to Outlook again.
    """

    synced_at: datetime.datetime | None
    error: str
    needs_sign_in: bool


def parse_title(raw: str, people: Sequence[Person]) -> ParsedTitle:
    """Works out who an event is for from its title.

    The text before the first colon is compared with the family's names,
    ignoring case and spaces. A match names the person; any other prefix is
    a kind of event (for the whole family). With no usable prefix the event
    is for the family and ``needs_name`` is set.

    Args:
        raw: The title as written in Outlook.
        people: Everyone in the diary, including ``Family``.

    Returns:
        The person, kind and the title to show.

    Raises:
        LookupError: If ``people`` has no ``Family`` (``Everyone``) person.
    """
    family = next((p for p in people if p.role == "Everyone"), None)
    if family is None:
        msg = "The diary has no Family person."
        raise LookupError(msg)
    prefix, colon, rest = raw.partition(":")
    prefix, rest = prefix.strip(), rest.strip()
    if not colon or not prefix or not rest:
        return ParsedTitle(family, "", raw.strip(), needs_name=True)
    for person in people:
        if person.name.casefold() == prefix.casefold():
            return ParsedTitle(person, "", rest, needs_name=False)
    return ParsedTitle(family, prefix, rest, needs_name=False)


def sync(
    conn: sqlite3.Connection,
    client: outlook.GraphClient,
    now: datetime.datetime,
) -> SyncResult:
    """Copies the chosen Outlook calendars into the database.

    Reads everything first and only then replaces the stored events in one
    step, so a failure part-way leaves the last good copy untouched. Also
    refreshes the list of calendars to choose from. Covers last week to
    eight weeks ahead. Never raises for Microsoft problems: they are
    recorded in ``status`` and returned.

    Args:
        conn: Open database connection.
        client: Microsoft Graph client.
        now: The current local time.

    Returns:
        How it went.
    """
    monday = now.date() - datetime.timedelta(days=now.weekday())
    window_start = datetime.datetime.combine(
        monday - datetime.timedelta(weeks=_WEEKS_BEFORE), datetime.time.min
    )
    window_end = datetime.datetime.combine(
        monday + datetime.timedelta(weeks=_WEEKS_AFTER), datetime.time.min
    )
    chosen = {c.id for c in list_calendars(conn) if c.selected}
    try:
        found = client.calendars()
        fetched = {
            c.id: client.events(c.id, window_start, window_end)
            for c in found
            if c.id in chosen
        }
    except outlook.NeedsSignInError:
        _record_failure(conn, _SIGN_IN_AGAIN, needs_sign_in=True)
        return SyncResult(ok=False, error=_SIGN_IN_AGAIN)
    except outlook.OutlookError as exc:
        _record_failure(conn, str(exc), needs_sign_in=False)
        return SyncResult(ok=False, error=str(exc))
    with db.transaction(conn):
        _store_calendars(conn, found)
        _store_events(conn, fetched, window_start, window_end)
        db.set_setting(conn, _SYNCED_AT, now.isoformat(timespec="seconds"))
        db.set_setting(conn, _ERROR, "")
        db.set_setting(conn, _NEEDS_SIGN_IN, "0")
    total = sum(len(events) for events in fetched.values())
    _logger.info(
        "Calendar sync: %d calendars shown, %d events", len(fetched), total
    )
    return SyncResult(ok=True, events=total)


def list_calendars(conn: sqlite3.Connection) -> list[Calendar]:
    """Lists the calendars the last sync found.

    Args:
        conn: Open database connection.

    Returns:
        Calendars in name order; empty until the first sync.
    """
    rows = conn.execute(
        "SELECT graph_id, name, selected FROM calendar_source"
        " ORDER BY name COLLATE NOCASE, graph_id"
    )
    return [
        Calendar(r["graph_id"], r["name"], bool(r["selected"])) for r in rows
    ]


def set_selected(conn: sqlite3.Connection, ids: Collection[str]) -> None:
    """Chooses which calendars the diary shows.

    Events of calendars no longer chosen are removed straight away.

    Args:
        conn: Open database connection.
        ids: Calendar ids to show; every other calendar is hidden. Unknown
            ids are ignored.
    """
    with db.transaction(conn):
        for calendar in list_calendars(conn):
            conn.execute(
                "UPDATE calendar_source SET selected = ? WHERE graph_id = ?",
                (int(calendar.id in ids), calendar.id),
            )
        _drop_unselected_events(conn)


def status(conn: sqlite3.Connection) -> SyncStatus:
    """Reports how the last sync went.

    Args:
        conn: Open database connection.

    Returns:
        When the last good sync was, and any current problem.
    """
    synced = db.get_setting(conn, _SYNCED_AT, "")
    return SyncStatus(
        synced_at=datetime.datetime.fromisoformat(synced) if synced else None,
        error=db.get_setting(conn, _ERROR, ""),
        needs_sign_in=db.get_setting(conn, _NEEDS_SIGN_IN, "0") == "1",
    )


def events_by_day(
    conn: sqlite3.Connection, first: datetime.date, days: int = 7
) -> dict[datetime.date, list[Event]]:
    """Lays the calendar out day by day.

    An event that spans several days appears on each of them. Within a day,
    all-day events come first, then the rest by start time.

    Args:
        conn: Open database connection.
        first: The first day to show (a Monday for a week view).
        days: How many days to show.

    Returns:
        Every day from ``first`` mapped to its events (possibly empty).
    """
    last = first + datetime.timedelta(days=days)
    everyone = list_people(conn)
    rows = conn.execute(
        "SELECT e.id, e.title, e.starts_at, e.ends_at, e.all_day,"
        " c.name AS calendar FROM event e"
        " JOIN calendar_source c ON c.graph_id = e.calendar_id"
        " WHERE e.starts_at < ? AND e.ends_at >= ?",
        (_iso(last), _iso(first)),
    )
    week: dict[datetime.date, list[Event]] = {
        first + datetime.timedelta(days=n): [] for n in range(days)
    }
    for row in rows:
        parsed = parse_title(row["title"], everyone)
        event = Event(
            id=row["id"],
            title=parsed.title,
            kind=parsed.kind,
            start=datetime.datetime.fromisoformat(row["starts_at"]),
            end=datetime.datetime.fromisoformat(row["ends_at"]),
            all_day=bool(row["all_day"]),
            calendar=row["calendar"],
            person=parsed.person,
            needs_name=parsed.needs_name,
        )
        for day in _days_of(event):
            if day in week:
                week[day].append(event)
    for events in week.values():
        events.sort(key=lambda e: (not e.all_day, e.start, e.title.casefold()))
    return week


def _days_of(event: Event) -> list[datetime.date]:
    last = event.start.date()
    if event.end > event.start:
        last = (event.end - datetime.timedelta(microseconds=1)).date()
    count = (last - event.start.date()).days + 1
    return [
        event.start.date() + datetime.timedelta(days=n) for n in range(count)
    ]


def _iso(moment: datetime.date | datetime.datetime) -> str:
    if not isinstance(moment, datetime.datetime):
        moment = datetime.datetime.combine(moment, datetime.time.min)
    return moment.isoformat(timespec="seconds")


def _record_failure(
    conn: sqlite3.Connection, message: str, *, needs_sign_in: bool
) -> None:
    with db.transaction(conn):
        db.set_setting(conn, _ERROR, message)
        db.set_setting(conn, _NEEDS_SIGN_IN, "1" if needs_sign_in else "0")
    _logger.warning("Calendar sync failed: %s", message)


def _store_calendars(
    conn: sqlite3.Connection, found: Sequence[outlook.CalendarInfo]
) -> None:
    for calendar in found:
        conn.execute(
            "INSERT INTO calendar_source (graph_id, name) VALUES (?, ?)"
            " ON CONFLICT(graph_id) DO UPDATE SET name = excluded.name",
            (calendar.id, calendar.name),
        )
    keep = {c.id for c in found}
    # Events of a calendar that has gone are removed by ON DELETE CASCADE.
    for known in list_calendars(conn):
        if known.id not in keep:
            conn.execute(
                "DELETE FROM calendar_source WHERE graph_id = ?", (known.id,)
            )


def _store_events(
    conn: sqlite3.Connection,
    fetched: dict[str, list[outlook.RawEvent]],
    window_start: datetime.datetime,
    window_end: datetime.datetime,
) -> None:
    _drop_unselected_events(conn)
    # The choice may have changed while we were waiting on Microsoft.
    shown = {c.id for c in list_calendars(conn) if c.selected}
    conn.execute(
        "DELETE FROM event WHERE ends_at <= ?"
        " OR (starts_at < ? AND ends_at > ?)",
        (_iso(window_start), _iso(window_end), _iso(window_start)),
    )
    for calendar_id, events in fetched.items():
        if calendar_id not in shown:
            continue
        conn.executemany(
            "INSERT OR REPLACE INTO event"
            " (calendar_id, id, title, starts_at, ends_at, all_day)"
            " VALUES (?, ?, ?, ?, ?, ?)",
            [
                (
                    calendar_id,
                    e.id,
                    e.title,
                    _iso(e.start),
                    _iso(e.end),
                    int(e.all_day),
                )
                for e in events
            ],
        )


def _drop_unselected_events(conn: sqlite3.Connection) -> None:
    conn.execute(
        "DELETE FROM event WHERE calendar_id NOT IN"
        " (SELECT graph_id FROM calendar_source WHERE selected = 1)"
    )
