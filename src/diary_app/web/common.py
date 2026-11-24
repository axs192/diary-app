"""Helpers shared by every page router: database access, rendering, redirects.

Every action in the app is a plain HTML form post that answers with a 303
redirect, so the pages work on iOS 9 Safari without form scripting. The only
script is static/app.js, which keeps link taps inside the Home Screen app.
"""

import pathlib
import sqlite3
import urllib.parse
from collections.abc import Iterator
from typing import Annotated

import fastapi
from fastapi import responses, templating

from diary_app import db, security, theme

TEMPLATES = templating.Jinja2Templates(
    directory=pathlib.Path(__file__).parent / "templates"
)
TEMPLATES.env.globals["tag_style"] = theme.tag_style
NAV = (
    ("Today", "/home"),
    ("Meals", "/meals"),
    ("Settings", "/settings"),
)
APP_COLOUR_KEY = "app_colour"


def protected_router() -> fastapi.APIRouter:
    """Returns a router whose routes all need the household PIN."""
    return fastapi.APIRouter(
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
FormList = Annotated[list[str] | None, fastapi.Form()]


def render(
    request: fastapi.Request,
    conn: sqlite3.Connection,
    template: str,
    status_code: int = 200,
    **context: object,
) -> responses.HTMLResponse:
    """Renders a page inside the app shell.

    Args:
        request: The current request.
        conn: Open database connection (the theme colour is read from it).
        template: Template file name.
        status_code: HTTP status for the response.
        **context: Values for the template. ``show_nav=False`` hides the
            menu (the login page).

    Returns:
        The rendered page.
    """
    colour = db.get_setting(conn, APP_COLOUR_KEY, theme.DEFAULT)
    context.setdefault("show_nav", True)
    return TEMPLATES.TemplateResponse(
        request,
        template,
        {
            "theme_css": theme.css(colour),
            "nav": NAV,
            "path": request.url.path,
            "error_banner": request.app.state.error_banner,
            **context,
        },
        status_code=status_code,
    )


def back_to(url: str) -> responses.RedirectResponse:
    """Redirects after a form post (303, so the browser re-fetches by GET).

    Args:
        url: A path on this site, such as ``/meals?week=2030-01-07``.

    Returns:
        The redirect response.

    Raises:
        ValueError: If ``url`` could lead off this site (so a request value
            can never turn a redirect into an open redirect).
    """
    safe_url = url.replace("\\", "")
    parts = urllib.parse.urlsplit(safe_url)
    # Browsers read backslashes as slashes in redirect targets, so validate
    # and redirect using the same canonical value.
    if (
        parts.scheme
        or parts.netloc
        or not safe_url.startswith("/")
        or safe_url.startswith("//")
    ):
        msg = f"Not a local path: {url!r}"
        raise ValueError(msg)
    return responses.RedirectResponse(safe_url, status_code=303)


def rejected(
    request: fastapi.Request,
    conn: sqlite3.Connection,
    message: str,
    back: str,
    status_code: int = 400,
) -> responses.HTMLResponse:
    """Shows a short "that didn't work" page with a way back.

    Args:
        request: The current request.
        conn: Open database connection.
        message: What went wrong, in plain words.
        back: Where the "Go back" button leads.
        status_code: HTTP status for the response.

    Returns:
        The rendered message page.
    """
    return render(
        request,
        conn,
        "message.html",
        status_code=status_code,
        message=message,
        back=back,
    )
