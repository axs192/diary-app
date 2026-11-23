"""Routes for the login page, the Today screen and Settings."""

import datetime
import sqlite3

import fastapi
from fastapi import responses

from diary_app import db, people, security, theme
from diary_app.web import common

router = fastapi.APIRouter()
protected = common.protected_router()


def _rejected(
    request: fastapi.Request, conn: sqlite3.Connection, message: str
) -> responses.HTMLResponse:
    return common.rejected(request, conn, message, back="/settings")


@router.get("/login", response_model=None)
def show_login(request: fastapi.Request, conn: common.Db) -> responses.Response:
    """Shows the PIN form (or goes straight on if already logged in)."""
    if request.session.get("logged_in"):
        return common.back_to("/home")
    return common.render(request, conn, "login.html", show_nav=False, error="")


@router.post("/login", response_model=None)
def submit_login(
    request: fastapi.Request, conn: common.Db, pin: common.FormText = ""
) -> responses.Response:
    """Checks the PIN and starts a session."""
    result = request.app.state.pin_checker.check(pin)
    if result is security.PinResult.OK:
        request.session.clear()  # never reuse a pre-login session
        request.session["logged_in"] = True
        return common.back_to("/home")
    if result is security.PinResult.LOCKED:
        return common.render(
            request,
            conn,
            "login.html",
            status_code=429,
            show_nav=False,
            error="Too many wrong tries. Please wait a few minutes.",
        )
    return common.render(
        request,
        conn,
        "login.html",
        status_code=401,
        show_nav=False,
        error="Wrong PIN. Try again.",
    )


@router.post("/logout")
def submit_logout(request: fastapi.Request) -> responses.RedirectResponse:
    """Ends the session."""
    request.session.clear()
    return common.back_to("/login")


@protected.get("/home")
def show_today(
    request: fastapi.Request, conn: common.Db
) -> responses.HTMLResponse:
    """Shows the Today screen (the kitchen iPad's home page)."""
    now = datetime.datetime.now()  # server local time
    return common.render(
        request,
        conn,
        "today.html",
        long_date=f"{now:%A} {now.day} {now:%B}",
        week=now.isocalendar().week,
    )


@protected.get("/settings")
def show_settings(
    request: fastapi.Request, conn: common.Db
) -> responses.HTMLResponse:
    """Shows app colour and people."""
    return common.render(
        request,
        conn,
        "settings.html",
        app_colour=db.get_setting(conn, common.APP_COLOUR_KEY, theme.DEFAULT),
        app_colours=[
            (name, colour.main) for name, colour in theme.APP_COLOURS.items()
        ],
        people=people.list_people(conn),
        palette=list(theme.PERSON_COLOURS.items()),
        roles=people.ADDABLE_ROLES,
    )


@protected.post("/settings/colour", response_model=None)
def submit_app_colour(
    request: fastapi.Request, conn: common.Db, colour: common.FormText = ""
) -> responses.Response:
    """Saves the app colour."""
    if colour not in theme.APP_COLOURS:
        return _rejected(request, conn, "Pick one of the offered colours.")
    db.set_setting(conn, common.APP_COLOUR_KEY, colour)
    return common.back_to("/settings")


@protected.post("/settings/people", response_model=None)
def submit_new_person(  # noqa: PLR0913
    request: fastapi.Request,
    conn: common.Db,
    *,
    name: common.FormText = "",
    role: common.FormText = "",
    colour: common.FormText = "",
    outlook_category: common.FormText = "",
) -> responses.Response:
    """Adds a person."""
    try:
        people.add_person(conn, name, role, colour, outlook_category)
    except people.InvalidPersonError as exc:
        return _rejected(request, conn, str(exc))
    return common.back_to("/settings")


@protected.post("/settings/people/{person_id}", response_model=None)
def submit_person_update(  # noqa: PLR0913
    request: fastapi.Request,
    conn: common.Db,
    person_id: int,
    *,
    name: common.FormText = "",
    colour: common.FormText = "",
    outlook_category: common.FormText = "",
) -> responses.Response:
    """Changes a person's name, colour and Outlook category."""
    try:
        people.update_person(
            conn,
            person_id,
            name=name,
            colour=colour,
            outlook_category=outlook_category,
        )
    except people.InvalidPersonError as exc:
        return _rejected(request, conn, str(exc))
    except LookupError as exc:
        raise fastapi.HTTPException(status_code=404) from exc
    return common.back_to("/settings")


router.include_router(protected)
