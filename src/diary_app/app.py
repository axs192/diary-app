"""FastAPI application factory for the diary backend."""

import logging

import fastapi

from diary_app import config

_logger = logging.getLogger(__name__)


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
    # Log only that the key exists: the value must never reach the logs.
    _logger.info("Starting diary-app (api key configured)")

    app = fastapi.FastAPI(title="diary-app")

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
        return {"api_key_configured": bool(settings.api_key.get_secret_value())}

    return app
