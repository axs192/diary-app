"""FastAPI application factory for the diary backend."""

import datetime
import logging
import pathlib
from collections.abc import Callable

import fastapi
import fastapi.responses
import fastapi.staticfiles
import httpx
from starlette.middleware import sessions

from diary_app import config, outlook, planner, security
from diary_app.web import calendar as calendar_web
from diary_app.web import meals, pages, recipe_pages, shopping
from diary_app.web import today as today_web

_logger = logging.getLogger(__name__)
_STATIC = pathlib.Path(__file__).parent / "web" / "static"
# The kitchen iPad should stay logged in, so the cookie lasts a year.
_SESSION_MAX_AGE_SECONDS = 365 * 24 * 60 * 60
_GRAPH_TIMEOUT_SECONDS = 20.0


# iOS asks for these paths when a page has no (usable) icon link, and sends
# no cookie for some of them, so they are public.
_ICON_GUESSES = (
    "apple-touch-icon.png",
    "apple-touch-icon-precomposed.png",
    "apple-touch-icon-152x152.png",
    "apple-touch-icon-152x152-precomposed.png",
    "apple-touch-icon-180x180.png",
    "apple-touch-icon-180x180-precomposed.png",
)


def _serve_icon_guesses(app: fastapi.FastAPI) -> None:
    def icon() -> fastapi.responses.FileResponse:
        return fastapi.responses.FileResponse(
            _STATIC / "apple-touch-icon.png", media_type="image/png"
        )

    for name in _ICON_GUESSES:
        app.add_api_route(f"/{name}", icon, include_in_schema=False)


def _graph_from(settings: config.Settings) -> outlook.GraphClient | None:
    if not settings.ms_client_id:
        return None
    return outlook.GraphClient(
        outlook.MsalTokenSource(
            settings.ms_client_id, settings.outlook_token_path
        ),
        httpx.Client(timeout=_GRAPH_TIMEOUT_SECONDS),
        timezone=settings.timezone,
    )


def create_app(
    settings: config.Settings | None = None,
    *,
    http_client: httpx.Client | None = None,
    resolve: Callable[[str], list[str]] | None = None,
    today: Callable[[], datetime.date] = datetime.date.today,
    graph: outlook.GraphClient | None = None,
) -> fastapi.FastAPI:
    """Builds the FastAPI application.

    Run it with ``uvicorn --factory diary_app.app:create_app``.

    Args:
        settings: Configuration to use. When omitted, settings are loaded
            from the environment.
        http_client: Client for recipe imports. Tests pass one with a mock
            transport; when omitted, a real client is made on first use.
        resolve: Turns a host name into IP addresses for the import
            safety check. Defaults to the system resolver.
        today: Returns today's date, for the shopping pages. Tests pass a
            fixed date; the default is the real one.
        graph: Microsoft Graph client for the calendar. Tests pass one wired
            to a fake; when omitted, a real one is made if ``MS_CLIENT_ID``
            is set, and otherwise the calendar pages say Outlook is not
            connected.

    Returns:
        A configured FastAPI application.

    Raises:
        pydantic.ValidationError: If ``settings`` is omitted and required
            environment variables are missing.
    """
    if settings is None:
        settings = config.Settings()

    logging.basicConfig(level=settings.log_level)
    # Log only that credentials exist: values must never reach the logs.
    _logger.info("Starting diary-app (credentials configured)")

    app = fastapi.FastAPI(title="diary-app")
    app.state.database_path = settings.database_path
    app.state.error_banner = settings.error_banner
    app.state.http_client = http_client
    app.state.resolve = resolve
    app.state.today = today
    app.state.graph = graph or _graph_from(settings)
    # The one place to swap in a different (e.g. AI-backed) suggester.
    app.state.suggester = planner.RuleBasedSuggester()
    app.state.pin_checker = security.PinChecker(
        settings.household_pin.get_secret_value()
    )
    # The home network is plain HTTP, so the cookie cannot be marked Secure;
    # SameSite=Lax keeps it off cross-site form posts.
    app.add_middleware(
        sessions.SessionMiddleware,
        secret_key=settings.session_secret.get_secret_value(),
        session_cookie="diary_session",
        max_age=_SESSION_MAX_AGE_SECONDS,
        same_site="lax",
        https_only=False,
    )
    app.mount(
        "/static",
        fastapi.staticfiles.StaticFiles(directory=_STATIC),
        name="static",
    )

    @app.exception_handler(security.NotLoggedInError)
    def redirect_to_login(
        _request: fastapi.Request, _exc: security.NotLoggedInError
    ) -> fastapi.responses.RedirectResponse:
        return fastapi.responses.RedirectResponse("/login", status_code=303)

    _serve_icon_guesses(app)
    app.include_router(pages.router)
    app.include_router(meals.router)
    app.include_router(recipe_pages.router)
    app.include_router(shopping.router)
    app.include_router(calendar_web.router)
    app.include_router(today_web.router)

    @app.get("/")
    def read_root() -> dict[str, str]:
        """Returns a greeting."""
        return {"message": "Hello from diary-app"}

    @app.get("/health")
    def read_health() -> dict[str, str]:
        """Returns liveness status for deploy checks."""
        return {"status": "ok"}

    @app.get("/config-check")
    def read_config_check() -> dict[str, bool]:
        """Reports whether credentials are loaded, never their value."""
        return {
            "household_pin_configured": bool(
                settings.household_pin.get_secret_value()
            ),
            "session_secret_configured": bool(
                settings.session_secret.get_secret_value()
            ),
        }

    return app
