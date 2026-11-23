"""Application settings.

Secrets come from systemd credentials: the unit's ``LoadCredentialEncrypted=``
lines make systemd decrypt each ``.cred`` file into a private directory and
point ``$CREDENTIALS_DIRECTORY`` at it, one file per credential, named after
the setting (see ``docs/systemd-credentials.md``). Plain settings come from
environment variables (a systemd ``EnvironmentFile`` in production). For local
development use ``uv run --env-file .env ...`` so the app itself never reads
dotfiles.
"""

import os

import pydantic
import pydantic_settings


class Settings(pydantic_settings.BaseSettings):
    """Runtime configuration.

    Construction fails fast with a ``pydantic.ValidationError`` when a
    required credential is missing or empty, so a misconfigured deployment
    never starts serving requests. Values are looked up in this order:
    constructor arguments, environment variables, then files in
    ``$CREDENTIALS_DIRECTORY``.

    Attributes:
        api_key: Placeholder credential used to practise secret handling.
            Stored as a ``SecretStr`` so it is masked in ``repr`` and logs.
        log_level: Standard library logging level name, e.g. ``"INFO"``.
    """

    api_key: pydantic.SecretStr = pydantic.Field(min_length=1)
    log_level: str = "INFO"

    @classmethod
    def settings_customise_sources(
        cls,
        settings_cls: type[pydantic_settings.BaseSettings],
        init_settings: pydantic_settings.PydanticBaseSettingsSource,
        env_settings: pydantic_settings.PydanticBaseSettingsSource,
        dotenv_settings: pydantic_settings.PydanticBaseSettingsSource,
        file_secret_settings: pydantic_settings.PydanticBaseSettingsSource,
    ) -> tuple[pydantic_settings.PydanticBaseSettingsSource, ...]:
        """Adds ``$CREDENTIALS_DIRECTORY`` as a lowest-priority source.

        The directory is read when ``Settings`` is built (not at import) so
        it reflects the environment the process was actually started in.

        Args:
            settings_cls: The settings class being built.
            init_settings: Constructor arguments.
            env_settings: Environment variables.
            dotenv_settings: Unused: the app never reads dotfiles itself.
            file_secret_settings: Unused: replaced by the source below.

        Returns:
            Sources in priority order, highest first.
        """
        del dotenv_settings, file_secret_settings
        credentials = pydantic_settings.SecretsSettingsSource(
            settings_cls,
            secrets_dir=os.environ.get("CREDENTIALS_DIRECTORY"),
        )
        return init_settings, env_settings, credentials
