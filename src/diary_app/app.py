"""FastAPI application factory for the diary backend."""

import logging

import fastapi
import fastapi.responses

from diary_app import config

_logger = logging.getLogger(__name__)

# Plain HTML with no JavaScript: Safari on iOS 9 (iPad mini 1st gen) is the
# target. The apple-mobile-web-app-* tags only take effect when the page is
# added to the Home Screen, where they hide Safari's address bar and tabs.
_HOME_HTML = """<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8">
<title>Diary</title>
<meta name="viewport" content="width=device-width, initial-scale=1">
<meta name="apple-mobile-web-app-capable" content="yes">
<meta name="apple-mobile-web-app-status-bar-style" content="black">
<meta name="apple-mobile-web-app-title" content="Diary">
<style>
html, body { height: 100%; margin: 0; }
body { background: #102a43; color: #f0f4f8; font-family: -apple-system,
  Helvetica, Arial, sans-serif; text-align: center; }
h1 { font-size: 64px; margin: 0; padding-top: 30%; }
</style>
</head>
<body>
<h1>Hello from diary-app</h1>
</body>
</html>
"""


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

    @app.get("/home", response_class=fastapi.responses.HTMLResponse)
    def read_home() -> str:
        """Returns the iPad-friendly home page as HTML."""
        return _HOME_HTML

    @app.get("/health")
    def read_health() -> dict[str, str]:
        """Returns liveness status for deploy checks."""
        return {"status": "ok"}

    @app.get("/config-check")
    def read_config_check() -> dict[str, bool]:
        """Reports whether credentials are loaded, never their value."""
        return {"api_key_configured": bool(settings.api_key.get_secret_value())}

    return app
