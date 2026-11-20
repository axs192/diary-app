"""Application settings, loaded from environment variables.

In production the variables come from a systemd ``EnvironmentFile`` that lives
outside the git checkout. For local development use
``uv run --env-file .env ...`` so the app itself never reads dotfiles.
"""

import pydantic
import pydantic_settings


class Settings(pydantic_settings.BaseSettings):
    """Runtime configuration.

    Construction fails fast with a ``pydantic.ValidationError`` when a
    required credential is missing or empty, so a misconfigured deployment
    never starts serving requests.

    Attributes:
        api_key: Placeholder credential used to practise secret handling.
            Stored as a ``SecretStr`` so it is masked in ``repr`` and logs.
        log_level: Standard library logging level name, e.g. ``"INFO"``.
    """

    api_key: pydantic.SecretStr = pydantic.Field(min_length=1)
    log_level: str = "INFO"
