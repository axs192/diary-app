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
import pathlib

import pydantic
import pydantic_settings


class JobSettings(pydantic_settings.BaseSettings):
    """The settings the web app and the background jobs share.

    None of these is a secret, so the sync job (a systemd timer) can read
    them from the environment without any credentials.

    Attributes:
        database_path: SQLite file. Production sets this to a path inside
            ``/var/lib/diary-app``; the default suits local development.
        log_level: Standard library logging level name, e.g. ``"INFO"``.
        ms_client_id: Application (client) id of the Microsoft app
            registration. Blank means Outlook is not connected: the
            calendar pages say so and nothing else changes. It is not a
            secret, but the real value is kept out of the public repo.
        outlook_token_path: Private file holding the Outlook sign-in.
            Production keeps it in ``/var/lib/diary-app``.
        timezone: IANA time zone the household lives in; Outlook event
            times are shown in it.
    """

    database_path: pathlib.Path = pathlib.Path("data/diary.db")
    log_level: str = "INFO"
    ms_client_id: str = ""
    outlook_token_path: pathlib.Path = pathlib.Path("data/outlook_token.json")
    timezone: str = "Europe/London"


class Settings(JobSettings):
    """Runtime configuration for the web app.

    Construction fails fast with a ``pydantic.ValidationError`` when a
    required credential is missing or empty, so a misconfigured deployment
    never starts serving requests. Values are looked up in this order:
    constructor arguments, environment variables, then files in
    ``$CREDENTIALS_DIRECTORY``.

    Attributes:
        household_pin: PIN the household types to open the app. Stored as a
            ``SecretStr`` so it is masked in ``repr`` and logs.
        session_secret: Key that signs the login cookie. Anyone holding it
            can forge a login, so treat it like a password.
        error_banner: Whether pages show a small dismissible banner when
            their JavaScript fails. The iPad has no Web Inspector, so this is
            on by default; set ``ERROR_BANNER=false`` to hide it.
    """

    household_pin: pydantic.SecretStr = pydantic.Field(min_length=1)
    session_secret: pydantic.SecretStr = pydantic.Field(min_length=16)
    error_banner: bool = True

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
