"""FastAPI application factory for the diary backend."""

import logging
import pathlib

import fastapi
import fastapi.responses
import fastapi.staticfiles
from starlette.middleware import sessions

from diary_app import config, security
from diary_app.web import pages

_logger = logging.getLogger(__name__)
_STATIC = pathlib.Path(__file__).parent / "web" / "static"
# The kitchen iPad should stay logged in, so the cookie lasts a year.
_SESSION_MAX_AGE_SECONDS = 365 * 24 * 60 * 60


def create_app(settings: config.Settings | None = None) -> fastapi.FastAPI:
    """Builds the FastAPI application.

    Run it with ``uvicorn --factory diary_app.app:create_app``.

    Args:
        settings: Configuration to use. When omitted, settings are loaded
            from the environment.

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

    app.include_router(pages.router)

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
