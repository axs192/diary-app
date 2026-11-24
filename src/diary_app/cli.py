"""The ``diary-app`` command: Outlook sign-in and the calendar sync job.

``diary-app login-outlook`` signs in once (the device-code flow: it shows a
page and a code to enter on any phone or laptop). ``diary-app sync-calendar``
is what the systemd timer runs every few minutes. Neither needs the
household PIN or session secret.
"""

import argparse
import datetime
import logging
import sys
from collections.abc import Sequence

import httpx

from diary_app import calendar_sync, config, db, outlook

_HTTP_TIMEOUT_SECONDS = 20.0
_NOT_CONFIGURED = (
    "MS_CLIENT_ID is not set. Put the app registration's client id in "
    "/etc/diary-app/diary-app.env (see docs/outlook-setup.md)."
)


def main(
    argv: Sequence[str] | None = None,
    *,
    client: outlook.GraphClient | None = None,
    now: datetime.datetime | None = None,
) -> int:
    """Runs one ``diary-app`` command.

    Args:
        argv: Arguments after the program name; defaults to ``sys.argv``.
        client: Graph client to use for ``sync-calendar``. Tests pass one
            wired to a fake; by default a real one is built from settings.
        now: The current local time for ``sync-calendar``; tests fix it.

    Returns:
        The exit status: 0 on success, 1 if the sync or sign-in failed,
        2 if Outlook is not configured.
    """
    parser = argparse.ArgumentParser(prog="diary-app")
    commands = parser.add_subparsers(dest="command", required=True)
    commands.add_parser(
        "login-outlook", help="sign in to Outlook (once, or when asked to)"
    )
    commands.add_parser(
        "sync-calendar", help="copy the chosen Outlook calendars into the diary"
    )
    args = parser.parse_args(argv)

    settings = config.JobSettings()
    logging.basicConfig(level=settings.log_level)
    if not settings.ms_client_id:
        print(_NOT_CONFIGURED)
        return 2
    if args.command == "login-outlook":
        return _login(settings)
    return _sync(settings, client, now or datetime.datetime.now())


def _login(settings: config.JobSettings) -> int:
    try:
        outlook.login_device_code(
            settings.ms_client_id, settings.outlook_token_path, print
        )
    except outlook.OutlookError as exc:
        print(f"Sign-in failed: {exc}")
        return 1
    print("Signed in. The calendar will sync on the next timer run.")
    return 0


def _sync(
    settings: config.JobSettings,
    client: outlook.GraphClient | None,
    now: datetime.datetime,
) -> int:
    graph = client or outlook.GraphClient(
        outlook.MsalTokenSource(
            settings.ms_client_id, settings.outlook_token_path
        ),
        httpx.Client(timeout=_HTTP_TIMEOUT_SECONDS),
        timezone=settings.timezone,
    )
    conn = db.connect(settings.database_path)
    try:
        result = calendar_sync.sync(conn, graph, now)
    finally:
        conn.close()
    if result.ok:
        print(f"Synced {result.events} events.")
        return 0
    print(f"Calendar sync failed: {result.error}")
    return 1


if __name__ == "__main__":  # pragma: no cover
    sys.exit(main())
