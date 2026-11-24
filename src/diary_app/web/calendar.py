"""The Calendar page, and the calendar section of Settings."""

import dataclasses
import datetime
import sqlite3
from typing import Any

import fastapi
from fastapi import responses

from diary_app import calendar_sync, mealplan
from diary_app.web import common, meals

router = common.protected_router()

_SETTINGS_URL = "/settings?section=calendar"
_NOT_CONNECTED = (
    "Outlook is not connected: MS_CLIENT_ID is not set on the server."
)
_DAYS = 7


@dataclasses.dataclass(frozen=True)
class Banner:
    """What the pages say about the link to Outlook.

    Attributes:
        connected: Whether the server has an Outlook app id at all.
        problem: What went wrong with the latest sync; empty if nothing.
        needs_sign_in: Whether someone has to sign in to Outlook again.
        synced: A sentence such as ``Synced today 14:05``.
    """

    connected: bool
    problem: str
    needs_sign_in: bool
    synced: str


def _clock(moment: datetime.datetime) -> str:
    """Formats a time the way the family says it: ``5pm``, ``9:30am``."""
    hour = moment.hour % 12 or 12
    minutes = f":{moment.minute:02d}" if moment.minute else ""
    return f"{hour}{minutes}{'am' if moment.hour < 12 else 'pm'}"  # noqa: PLR2004


common.TEMPLATES.env.filters["clock"] = _clock


def _now(request: fastapi.Request) -> datetime.datetime:
    # The date comes from the injectable "today" so tests can fix it.
    today = request.app.state.today()
    return datetime.datetime.combine(
        today,
        datetime.datetime.now().time(),
    )


def _banner(request: fastapi.Request, conn: sqlite3.Connection) -> Banner:
    status = calendar_sync.status(conn)
    today = request.app.state.today()
    if status.synced_at is None:
        synced = "Not synced yet"
    else:
        when = status.synced_at
        day = (
            "today"
            if when.date() == today
            else f"{when:%a} {when.day} {when:%b}"
        )
        synced = f"Synced {day} {when:%H:%M}"
    return Banner(
        connected=request.app.state.graph is not None,
        problem=status.error,
        needs_sign_in=status.needs_sign_in,
        synced=synced,
    )


def settings_context(
    request: fastapi.Request, conn: sqlite3.Connection
) -> dict[str, Any]:
    """Returns what the Settings page needs for its Calendar section.

    Args:
        request: The current request.
        conn: Open database connection.

    Returns:
        Template values to merge into the Settings context.
    """
    return {
        "cal_banner": _banner(request, conn),
        "cal_choices": calendar_sync.list_calendars(conn),
    }


@router.get("/calendar")
def show_calendar(
    request: fastapi.Request, conn: common.Db, week: str = ""
) -> responses.HTMLResponse:
    """Shows one week of the family calendar."""
    today = request.app.state.today()
    monday = mealplan.monday_of(meals.parse_day(week) or today)
    days = calendar_sync.events_by_day(conn, monday, _DAYS)
    seen: set[str] = set()
    needs_name = []
    for events in days.values():
        for event in events:
            if event.needs_name and event.id not in seen:
                seen.add(event.id)
                needs_name.append(event)
    step = datetime.timedelta(days=_DAYS)
    return common.render(
        request,
        conn,
        "calendar.html",
        monday=monday,
        today=today,
        days=list(days.items()),
        needs_name=needs_name,
        banner=_banner(request, conn),
        prev_week=f"/calendar?week={(monday - step).isoformat()}",
        next_week=f"/calendar?week={(monday + step).isoformat()}",
    )


@router.post("/settings/calendars")
def submit_calendar_choice(
    conn: common.Db, calendar: common.FormList = None
) -> responses.RedirectResponse:
    """Chooses which Outlook calendars the diary shows."""
    calendar_sync.set_selected(conn, calendar or [])
    return common.back_to(_SETTINGS_URL)


@router.post("/settings/calendar/sync", response_model=None)
def submit_sync_now(
    request: fastapi.Request, conn: common.Db
) -> responses.Response:
    """Copies the chosen calendars from Outlook right now."""
    graph = request.app.state.graph
    if graph is None:
        return common.rejected(request, conn, _NOT_CONNECTED, _SETTINGS_URL)
    calendar_sync.sync(conn, graph, _now(request))
    return common.back_to(_SETTINGS_URL)
