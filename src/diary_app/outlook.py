"""Talking to Microsoft: signing in, and reading calendars through Graph.

This is the only module that knows about Microsoft. The rest of the app sees
``GraphClient`` (calendars and events), ``MsalTokenSource`` (an access token
that refreshes itself) and three errors. Nothing here logs tokens or event
titles.

The family calendar lives in a personal Outlook.com account, so sign-in is
the device-code flow against the ``consumers`` authority with delegated
permissions (checked by a spike in November 2026).
"""

import contextlib
import dataclasses
import datetime
import fcntl
import logging
import os
import pathlib
import time
import zoneinfo
from collections.abc import Callable, Iterator
from typing import Protocol

import httpx
import msal

_logger = logging.getLogger(__name__)

AUTHORITY = "https://login.microsoftonline.com/consumers"
# Mail.Send is for the reminder emails; asking now means signing in once.
SCOPES = ("Calendars.Read", "Mail.Send")
_GRAPH = "https://graph.microsoft.com/v1.0"
_PAGE_SIZE = 100
_ATTEMPTS = 3
_MAX_WAIT_SECONDS = 30.0
_RETRY_STATUSES = frozenset({429, 502, 503, 504})
_NEEDS_SIGN_IN_ERRORS = frozenset({"invalid_grant", "interaction_required"})


class OutlookError(Exception):
    """Raised when Microsoft cannot be reached or refuses a request."""


class NeedsSignInError(OutlookError):
    """Raised when the saved sign-in no longer works: sign in again."""


@dataclasses.dataclass(frozen=True)
class CalendarInfo:
    """One calendar the account can read.

    Attributes:
        id: Graph's id for the calendar.
        name: Its display name.
    """

    id: str
    name: str


@dataclasses.dataclass(frozen=True)
class RawEvent:
    """One event as Outlook has it, before the diary interprets the title.

    Attributes:
        id: Graph's id; recurring events get one id per occurrence.
        title: The subject line (empty if none).
        start: Start in the client's time zone (midnight for all-day).
        end: End in the same zone (exclusive; the next midnight for a
            one-day all-day event).
        all_day: Whether Outlook marks it all-day.
    """

    id: str
    title: str
    start: datetime.datetime
    end: datetime.datetime
    all_day: bool


class TokenSource(Protocol):
    """Anything that can hand out a current Graph access token."""

    def token(self) -> str:
        """Returns an access token.

        Raises:
            NeedsSignInError: If the person has to sign in again.
            OutlookError: If Microsoft could not be reached.
        """
        ...


class GraphClient:
    """Reads calendars and events from Microsoft Graph.

    Paging, retries after rate limits, and the time zone are handled here,
    so callers just ask for calendars and events.
    """

    def __init__(
        self,
        token_source: TokenSource,
        http: httpx.Client,
        *,
        timezone: str = "Europe/London",
        sleep: Callable[[float], None] = time.sleep,
    ) -> None:
        """Creates a client.

        Args:
            token_source: Supplies the bearer token for each call.
            http: HTTP client to use (tests pass one with a fake transport).
            timezone: IANA zone Graph should report event times in.
            sleep: Waits between retries; tests pass a recorder.
        """
        self._tokens = token_source
        self._http = http
        self._timezone = timezone
        self._sleep = sleep

    def calendars(self) -> list[CalendarInfo]:
        """Lists the calendars the account can read.

        Returns:
            Every calendar, including shared ones.

        Raises:
            NeedsSignInError: If the saved sign-in no longer works.
            OutlookError: If Microsoft fails or cannot be reached.
        """
        rows = self._get_all(f"{_GRAPH}/me/calendars", {"$top": _PAGE_SIZE})
        return [CalendarInfo(str(r["id"]), str(r["name"])) for r in rows]

    def events(
        self,
        calendar_id: str,
        start: datetime.datetime,
        end: datetime.datetime,
    ) -> list[RawEvent]:
        """Reads every event in a calendar that overlaps a time range.

        Recurring events come back as one event per occurrence.

        Args:
            calendar_id: A ``CalendarInfo.id``.
            start: Start of the range; a time with no zone is taken to be in
                the client's time zone.
            end: End of the range (exclusive), read the same way.

        Returns:
            The events, in Graph's order.

        Raises:
            NeedsSignInError: If the saved sign-in no longer works.
            OutlookError: If the calendar is missing, or Microsoft fails or
                cannot be reached.
        """
        rows = self._get_all(
            f"{_GRAPH}/me/calendars/{calendar_id}/calendarView",
            {
                "startDateTime": self._with_offset(start),
                "endDateTime": self._with_offset(end),
                "$select": "id,subject,start,end,isAllDay",
                "$top": _PAGE_SIZE,
            },
        )
        return [_raw_event(row) for row in rows]

    def _with_offset(self, moment: datetime.datetime) -> str:
        # Graph reads a time with no offset as UTC, which is an hour out in
        # summer, so say which zone the caller meant.
        if moment.tzinfo is None:
            moment = moment.replace(tzinfo=zoneinfo.ZoneInfo(self._timezone))
        return moment.isoformat()

    def _get_all(
        self, url: str, params: dict[str, str | int]
    ) -> list[dict[str, object]]:
        rows: list[dict[str, object]] = []
        next_url: str | None = url
        first_params: dict[str, str | int] | None = params
        while next_url:
            body = self._get(next_url, first_params)
            value = body.get("value")
            if isinstance(value, list):
                rows.extend(value)
            link = body.get("@odata.nextLink")
            next_url = str(link) if link else None
            first_params = None  # a next link already carries its query
        return rows

    def _get(
        self, url: str, params: dict[str, str | int] | None
    ) -> dict[str, object]:
        headers = {
            "Authorization": f"Bearer {self._tokens.token()}",
            "Prefer": f'outlook.timezone="{self._timezone}"',
        }
        for attempt in range(1, _ATTEMPTS + 1):
            try:
                response = self._http.get(url, params=params, headers=headers)
            except httpx.HTTPError as exc:
                msg = f"Could not reach Microsoft ({type(exc).__name__})."
                raise OutlookError(msg) from exc
            if response.status_code in _RETRY_STATUSES and attempt < _ATTEMPTS:
                self._sleep(_wait_seconds(response, attempt))
                continue
            return _checked_json(response)
        msg = "Microsoft kept refusing; try again later."  # pragma: no cover
        raise OutlookError(msg)  # pragma: no cover


def _wait_seconds(response: httpx.Response, attempt: int) -> float:
    try:
        asked = float(response.headers["Retry-After"])
    except (KeyError, ValueError):
        asked = float(attempt)
    return min(asked, _MAX_WAIT_SECONDS)


def _checked_json(response: httpx.Response) -> dict[str, object]:
    status = response.status_code
    if status == httpx.codes.UNAUTHORIZED:
        raise NeedsSignInError
    if status == httpx.codes.NOT_FOUND:
        msg = "Microsoft could not find that calendar."
        raise OutlookError(msg)
    if status >= httpx.codes.BAD_REQUEST:
        msg = f"Microsoft answered with an error ({status})."
        raise OutlookError(msg)
    try:
        body = response.json()
    except ValueError as exc:
        msg = "Microsoft sent something unexpected."
        raise OutlookError(msg) from exc
    if not isinstance(body, dict):
        msg = "Microsoft sent something unexpected."
        raise OutlookError(msg)
    return body


def _raw_event(row: dict[str, object]) -> RawEvent:
    try:
        return RawEvent(
            id=str(row["id"]),
            title=str(row.get("subject") or ""),
            start=_graph_time(row["start"]),
            end=_graph_time(row["end"]),
            all_day=bool(row.get("isAllDay")),
        )
    except (KeyError, ValueError) as exc:
        msg = "Microsoft sent an event the diary could not read."
        raise OutlookError(msg) from exc


def _graph_time(value: object) -> datetime.datetime:
    if not isinstance(value, dict):
        msg = "Microsoft sent an event without times."
        raise OutlookError(msg)
    # Graph writes seven fractional digits; fromisoformat takes them.
    return datetime.datetime.fromisoformat(str(value["dateTime"]))


def write_private_file(path: pathlib.Path, text: str) -> None:
    """Writes a file only its owner can read, never briefly world-readable.

    Args:
        path: File to write; its folder is created (mode 0700) if missing.
        text: Contents.
    """
    path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    # Write beside the target, then rename over it: a reader sees the old
    # file or the new one, never a half-written one.
    scratch = path.with_name(f"{path.name}.{os.getpid()}.tmp")
    descriptor = os.open(scratch, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8") as handle:
            handle.write(text)
            handle.flush()
            os.fsync(handle.fileno())
        scratch.replace(path)
    finally:
        scratch.unlink(missing_ok=True)


@contextlib.contextmanager
def sign_in_lock(cache_path: pathlib.Path) -> Iterator[None]:
    """Holds a lock while the saved sign-in is read, refreshed and rewritten.

    The timer job and "Sync now" can run together. Without this, both could
    refresh the same token and one would save over the other's newer one.

    Args:
        cache_path: The saved sign-in file; the lock file sits beside it.

    Yields:
        Nothing; the lock is released when the block ends.
    """
    cache_path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    lock_path = cache_path.with_name(f"{cache_path.name}.lock")
    descriptor = os.open(lock_path, os.O_WRONLY | os.O_CREAT, 0o600)
    try:
        fcntl.flock(descriptor, fcntl.LOCK_EX)
        yield
    finally:
        os.close(descriptor)  # closing releases the lock


class MsalTokenSource:
    """Hands out access tokens from the saved sign-in, refreshing as needed.

    The sign-in (including the refresh token) lives in one private file;
    the sync job keeps it fresh by using it every few minutes.
    """

    def __init__(self, client_id: str, cache_path: pathlib.Path) -> None:
        """Creates a token source.

        Args:
            client_id: The app registration's application (client) id.
            cache_path: Where ``login_device_code`` saved the sign-in.
        """
        self._client_id = client_id
        self._path = cache_path

    def token(self) -> str:
        """Returns a current access token.

        Raises:
            NeedsSignInError: If nobody has signed in, or the saved sign-in
                has expired or been revoked.
            OutlookError: If Microsoft could not be reached.
        """
        with sign_in_lock(self._path):
            return self._token_locked()

    def _token_locked(self) -> str:
        if not self._path.exists():
            raise NeedsSignInError
        cache = msal.SerializableTokenCache()
        cache.deserialize(self._path.read_text(encoding="utf-8"))
        try:
            app = msal.PublicClientApplication(
                self._client_id, authority=AUTHORITY, token_cache=cache
            )
            accounts = app.get_accounts()
            if not accounts:
                raise NeedsSignInError
            result = app.acquire_token_silent(list(SCOPES), account=accounts[0])
        except OSError as exc:  # requests' errors derive from OSError
            msg = f"Could not reach Microsoft ({type(exc).__name__})."
            raise OutlookError(msg) from exc
        if cache.has_state_changed:
            write_private_file(self._path, cache.serialize())
        if not result:
            raise NeedsSignInError
        if "access_token" not in result:
            if result.get("error") in _NEEDS_SIGN_IN_ERRORS:
                raise NeedsSignInError
            msg = f"Microsoft refused the sign-in ({result.get('error')})."
            raise OutlookError(msg)
        return str(result["access_token"])


def login_device_code(
    client_id: str,
    cache_path: pathlib.Path,
    say: Callable[[str], None],
) -> None:
    """Signs in with the device-code flow and saves the result.

    Args:
        client_id: The app registration's application (client) id.
        cache_path: Where to save the sign-in (a private file).
        say: Shows the person the page and code to enter.

    Raises:
        OutlookError: If sign-in could not start or was not completed.
    """
    cache = msal.SerializableTokenCache()
    if cache_path.exists():
        cache.deserialize(cache_path.read_text(encoding="utf-8"))
    app = msal.PublicClientApplication(
        client_id, authority=AUTHORITY, token_cache=cache
    )
    flow = app.initiate_device_flow(scopes=list(SCOPES))
    if "user_code" not in flow:
        msg = f"Sign-in could not start ({flow.get('error')})."
        raise OutlookError(msg)
    say(str(flow["message"]))
    result = app.acquire_token_by_device_flow(flow)
    if "access_token" not in result:
        msg = f"Sign-in was not completed ({result.get('error')})."
        raise OutlookError(msg)
    write_private_file(cache_path, cache.serialize())
    _logger.info("Signed in to Outlook")
