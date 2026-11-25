"""Routes for the login page and Settings."""

import sqlite3

import fastapi
from fastapi import responses

from diary_app import (
    db,
    import_sites,
    people,
    recipe_import,
    security,
    theme,
    today,
)
from diary_app.web import calendar as calendar_web
from diary_app.web import common

router = fastapi.APIRouter()
protected = common.protected_router()


_SECTIONS = (
    ("colour", "App colour"),
    ("people", "People & colours"),
    ("calendar", "Calendar"),
    ("sites", "Recipe sites"),
    ("device", "This device"),
)


def _settings_url(section: str) -> str:
    return f"/settings?section={section}"


def _rejected(
    request: fastapi.Request,
    conn: sqlite3.Connection,
    message: str,
    section: str,
) -> responses.HTMLResponse:
    return common.rejected(request, conn, message, back=_settings_url(section))


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


@protected.get("/settings")
def show_settings(
    request: fastapi.Request, conn: common.Db, section: str = ""
) -> responses.HTMLResponse:
    """Shows the settings rows, with the section named by ``section`` open."""
    return common.render(
        request,
        conn,
        "settings.html",
        sections=_SECTIONS,
        section=section if section in dict(_SECTIONS) else "",
        builtin_sites=sorted(recipe_import.ALLOWED_HOSTS),
        added_sites=import_sites.added(conn),
        app_colour=db.get_setting(conn, common.APP_COLOUR_KEY, theme.DEFAULT),
        app_colours=[
            (name, colour.main) for name, colour in theme.APP_COLOURS.items()
        ],
        people=people.list_people(conn),
        palette=list(theme.PERSON_COLOURS.items()),
        roles=people.ADDABLE_ROLES,
        today_ranges=today.RANGES,
        today_range=today.get_range(conn),
        **calendar_web.settings_context(request, conn),
    )


@protected.post("/settings/colour", response_model=None)
def submit_app_colour(
    request: fastapi.Request, conn: common.Db, colour: common.FormText = ""
) -> responses.Response:
    """Saves the app colour."""
    if colour not in theme.APP_COLOURS:
        return _rejected(
            request, conn, "Pick one of the offered colours.", "colour"
        )
    db.set_setting(conn, common.APP_COLOUR_KEY, colour)
    return common.back_to(_settings_url("colour"))


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
        return _rejected(request, conn, str(exc), "people")
    return common.back_to(_settings_url("people"))


@protected.post("/settings/people/{person_id}", response_model=None)
def submit_person_update(  # noqa: PLR0913
    request: fastapi.Request,
    conn: common.Db,
    person_id: int,
    *,
    name: common.FormText = "",
    colour: common.FormText = "",
    outlook_category: common.FormText = "",
    role: common.FormText = "",
) -> responses.Response:
    """Changes a person's name, colour, Outlook name and role.

    A blank ``role`` leaves it as it is.
    """
    try:
        people.update_person(
            conn,
            person_id,
            name=name,
            colour=colour,
            outlook_category=outlook_category,
            role=role,
        )
    except people.InvalidPersonError as exc:
        return _rejected(request, conn, str(exc), "people")
    except LookupError as exc:
        raise fastapi.HTTPException(status_code=404) from exc
    return common.back_to(_settings_url("people"))


@protected.post("/settings/people/{person_id}/delete", response_model=None)
def submit_person_delete(
    request: fastapi.Request, conn: common.Db, person_id: int
) -> responses.Response:
    """Removes a person (Family stays)."""
    try:
        people.delete_person(conn, person_id)
    except people.InvalidPersonError as exc:
        return _rejected(request, conn, str(exc), "people")
    except LookupError as exc:
        raise fastapi.HTTPException(status_code=404) from exc
    return common.back_to(_settings_url("people"))


@protected.post("/settings/sites", response_model=None)
def submit_new_site(
    request: fastapi.Request, conn: common.Db, site: common.FormText = ""
) -> responses.Response:
    """Allows another recipe site for import."""
    try:
        import_sites.add(conn, site)
    except import_sites.InvalidSiteError as exc:
        return _rejected(request, conn, str(exc), "sites")
    return common.back_to(_settings_url("sites"))


@protected.post("/settings/sites/remove")
def submit_remove_site(
    conn: common.Db, host: common.FormText = ""
) -> responses.RedirectResponse:
    """Stops allowing a site that was added (built-in sites stay)."""
    import_sites.remove(conn, host)
    return common.back_to(_settings_url("sites"))


router.include_router(protected)
