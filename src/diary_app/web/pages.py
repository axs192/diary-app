"""Routes for the login page, the Today screen and Settings.

Every action is a plain HTML form post that answers with a redirect, so the
pages work on iOS 9 Safari without JavaScript.
"""

import datetime
import pathlib
import sqlite3
from collections.abc import Iterator
from typing import Annotated

import fastapi
from fastapi import responses, templating

from diary_app import db, people, security, theme

_TEMPLATES = templating.Jinja2Templates(
    directory=pathlib.Path(__file__).parent / "templates"
)
_NAV = (
    ("Today", "/home"),
    ("Settings", "/settings"),
)
_APP_COLOUR_KEY = "app_colour"

router = fastapi.APIRouter()
protected = fastapi.APIRouter(
    dependencies=[fastapi.Depends(security.require_login)]
)


def _get_db(request: fastapi.Request) -> Iterator[sqlite3.Connection]:
    conn = db.connect(request.app.state.database_path)
    try:
        yield conn
    finally:
        conn.close()


Db = Annotated[sqlite3.Connection, fastapi.Depends(_get_db)]
FormText = Annotated[str, fastapi.Form()]


def _render(
    request: fastapi.Request,
    conn: sqlite3.Connection,
    template: str,
    status_code: int = 200,
    **context: object,
) -> responses.HTMLResponse:
    colour = db.get_setting(conn, _APP_COLOUR_KEY, theme.DEFAULT)
    context.setdefault("show_nav", True)
    return _TEMPLATES.TemplateResponse(
        request,
        template,
        {
            "theme_css": theme.css(colour),
            "nav": _NAV,
            "path": request.url.path,
            **context,
        },
        status_code=status_code,
    )


def _back_to(url: str) -> responses.RedirectResponse:
    return responses.RedirectResponse(url, status_code=303)


def _rejected(
    request: fastapi.Request, conn: sqlite3.Connection, message: str
) -> responses.HTMLResponse:
    return _render(
        request,
        conn,
        "message.html",
        status_code=400,
        message=message,
        back="/settings",
    )


@router.get("/login", response_model=None)
def show_login(request: fastapi.Request, conn: Db) -> responses.Response:
    """Shows the PIN form (or goes straight on if already logged in)."""
    if request.session.get("logged_in"):
        return _back_to("/home")
    return _render(request, conn, "login.html", show_nav=False, error="")


@router.post("/login", response_model=None)
def submit_login(
    request: fastapi.Request, conn: Db, pin: FormText = ""
) -> responses.Response:
    """Checks the PIN and starts a session."""
    result = request.app.state.pin_checker.check(pin)
    if result is security.PinResult.OK:
        request.session.clear()  # never reuse a pre-login session
        request.session["logged_in"] = True
        return _back_to("/home")
    if result is security.PinResult.LOCKED:
        return _render(
            request,
            conn,
            "login.html",
            status_code=429,
            show_nav=False,
            error="Too many wrong tries. Please wait a few minutes.",
        )
    return _render(
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
    return _back_to("/login")


@protected.get("/home")
def show_today(request: fastapi.Request, conn: Db) -> responses.HTMLResponse:
    """Shows the Today screen (the kitchen iPad's home page)."""
    now = datetime.datetime.now()  # server local time
    return _render(
        request,
        conn,
        "today.html",
        long_date=f"{now:%A} {now.day} {now:%B}",
        week=now.isocalendar().week,
    )


@protected.get("/settings")
def show_settings(request: fastapi.Request, conn: Db) -> responses.HTMLResponse:
    """Shows app colour and people."""
    return _render(
        request,
        conn,
        "settings.html",
        app_colour=db.get_setting(conn, _APP_COLOUR_KEY, theme.DEFAULT),
        app_colours=[
            (name, colour.main) for name, colour in theme.APP_COLOURS.items()
        ],
        people=people.list_people(conn),
        palette=list(theme.PERSON_COLOURS.items()),
        roles=people.ROLES,
    )


@protected.post("/settings/colour", response_model=None)
def submit_app_colour(
    request: fastapi.Request, conn: Db, colour: FormText = ""
) -> responses.Response:
    """Saves the app colour."""
    if colour not in theme.APP_COLOURS:
        return _rejected(request, conn, "Pick one of the offered colours.")
    db.set_setting(conn, _APP_COLOUR_KEY, colour)
    return _back_to("/settings")


@protected.post("/settings/people", response_model=None)
def submit_new_person(  # noqa: PLR0913
    request: fastapi.Request,
    conn: Db,
    *,
    name: FormText = "",
    role: FormText = "",
    colour: FormText = "",
    outlook_category: FormText = "",
) -> responses.Response:
    """Adds a person."""
    try:
        people.add_person(conn, name, role, colour, outlook_category)
    except people.InvalidPersonError as exc:
        return _rejected(request, conn, str(exc))
    return _back_to("/settings")


@protected.post("/settings/people/{person_id}", response_model=None)
def submit_person_update(  # noqa: PLR0913
    request: fastapi.Request,
    conn: Db,
    person_id: int,
    *,
    name: FormText = "",
    colour: FormText = "",
    outlook_category: FormText = "",
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
    return _back_to("/settings")


router.include_router(protected)
