"""The Today screen (the kitchen iPad's home page) and the event page."""

import datetime
import urllib.parse
from typing import Annotated

import fastapi
from fastapi import responses

from diary_app import calendar_sync, today
from diary_app.calendar_sync import Event
from diary_app.web import calendar as calendar_web
from diary_app.web import common

router = common.protected_router()

_HOME = "/home"
_DEVICE_SETTINGS = "/settings?section=device"


def _day(moment: datetime.date) -> str:
    return f"{moment:%A} {moment.day} {moment:%B}"


def _when(event: Event) -> str:
    """Says when an event is, e.g. ``Tuesday 8 January · 5pm to 6pm``."""
    start = event.start
    last = (event.end - datetime.timedelta(microseconds=1)).date()
    if event.all_day:
        if last > start.date():
            return f"{_day(start)} to {_day(last)} · all day"
        return f"{_day(start)} · all day"
    clock = calendar_web.clock
    if event.end.date() > start.date():
        return (
            f"{_day(start)} {clock(start)} to "
            f"{_day(event.end)} {clock(event.end)}"
        )
    return f"{_day(start)} · {clock(start)}\N{EN DASH}{clock(event.end)}"


def event_url(event_id: str, source: str) -> str:
    """Builds the address of an event's page.

    Args:
        event_id: Outlook's id for the event.
        source: ``home`` or ``calendar``: which page the Back button
            returns to.

    Returns:
        A local path, with the id encoded.
    """
    return f"/event?id={urllib.parse.quote(event_id)}&from={source}"


common.TEMPLATES.env.globals["event_url"] = event_url


@router.get(_HOME)
def show_today(
    request: fastapi.Request, conn: common.Db
) -> responses.HTMLResponse:
    """Shows the kids' diary, what is coming up, and tonight's dinner."""
    day = request.app.state.today()
    return common.render(
        request,
        conn,
        "today.html",
        long_date=_day(day),
        week=day.isocalendar().week,
        view=today.view(conn, day),
        banner=calendar_web.banner(request, conn),
    )


@router.get("/event", response_model=None)
def show_event(
    request: fastapi.Request,
    conn: common.Db,
    event_id: str = fastapi.Query("", alias="id"),
    source: str = fastapi.Query("", alias="from"),
) -> responses.Response:
    """Shows one event: who it is for, when, and its notes."""
    event = calendar_sync.get_event(conn, event_id) if event_id else None
    if event is None:
        return common.rejected(
            request,
            conn,
            "That event is no longer in the diary. It may have been "
            "changed or deleted in Outlook.",
            back=_HOME,
            status_code=404,
        )
    back = _HOME
    if source == "calendar":
        monday = event.start.date() - datetime.timedelta(
            days=event.start.weekday()
        )
        back = f"/calendar?week={monday.isoformat()}"
    return common.render(
        request,
        conn,
        "event.html",
        event=event,
        note=event.note if today.get_show_notes(conn) else "",
        when=_when(event),
        back=back,
    )


@router.post("/settings/today-range", response_model=None)
def submit_range(
    request: fastapi.Request,
    conn: common.Db,
    choice: Annotated[str, fastapi.Form(alias="range")] = "",
) -> responses.Response:
    """Saves how far ahead Coming up looks."""
    try:
        today.set_range(conn, choice)
    except ValueError as exc:
        return common.rejected(request, conn, str(exc), _DEVICE_SETTINGS)
    return common.back_to(_DEVICE_SETTINGS)


@router.post("/settings/show-notes")
def submit_show_notes(
    conn: common.Db,
    notes: Annotated[str, fastapi.Form()] = "",
) -> responses.RedirectResponse:
    """Saves whether event pages show notes (a ticked box sends ``1``)."""
    today.set_show_notes(conn, show=notes == "1")
    return common.back_to(_DEVICE_SETTINGS)
