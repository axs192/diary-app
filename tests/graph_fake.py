"""A fake Microsoft Graph server for tests (the one mocked boundary).

``FakeGraph`` answers the two calls the app makes, as real Graph does:
``GET /me/calendars`` and ``GET /me/calendars/{id}/calendarView`` (with
paging through ``@odata.nextLink``). It records every request so tests can
check headers and how often it was called.
"""

import dataclasses
import datetime
import zoneinfo

import httpx

from diary_app import outlook

_ROOT = "https://graph.microsoft.com/v1.0"


class StaticToken:
    """A token source that always hands out the same token."""

    def token(self) -> str:
        """Returns a fixed access token."""
        return "test-token"


class SignedOutToken:
    """A token source whose refresh token has gone."""

    def token(self) -> str:
        """Always fails, as MSAL does when sign-in is needed again."""
        raise outlook.NeedsSignInError


def graph_event(
    event_id: str,
    title: str,
    start: str,
    end: str,
    *,
    all_day: bool = False,
) -> dict[str, object]:
    """Builds one event as Graph returns it (times in the requested zone)."""
    return {
        "id": event_id,
        "subject": title,
        "isAllDay": all_day,
        "start": {"dateTime": f"{start}.0000000", "timeZone": "Europe/London"},
        "end": {"dateTime": f"{end}.0000000", "timeZone": "Europe/London"},
        "categories": [],
    }


@dataclasses.dataclass
class FakeGraph:
    """In-memory calendars and events, served as Graph would.

    Attributes:
        calendars: Calendar id -> display name.
        events: Calendar id -> events (as built by ``graph_event``).
        page_size: Events per page, to exercise paging.
        failures: Status codes to answer with first, one per request, before
            behaving normally (e.g. ``[429]``).
        retry_after: ``Retry-After`` header sent with a 429.
        requests: Every request seen, oldest first.
    """

    calendars: dict[str, str] = dataclasses.field(default_factory=dict)
    events: dict[str, list[dict[str, object]]] = dataclasses.field(
        default_factory=dict
    )
    page_size: int = 100
    failures: list[int] = dataclasses.field(default_factory=list)
    retry_after: str | None = None
    requests: list[httpx.Request] = dataclasses.field(default_factory=list)

    def client(self) -> httpx.Client:
        """Returns an ``httpx.Client`` that talks to this fake."""
        return httpx.Client(transport=httpx.MockTransport(self._handle))

    def calendar_view_calls(self) -> list[httpx.Request]:
        """The calendarView requests seen so far."""
        return [r for r in self.requests if "calendarView" in r.url.path]

    def _handle(self, request: httpx.Request) -> httpx.Response:
        self.requests.append(request)
        if self.failures:
            status = self.failures.pop(0)
            headers = {}
            if status == httpx.codes.TOO_MANY_REQUESTS and self.retry_after:
                headers["Retry-After"] = self.retry_after
            return httpx.Response(status, headers=headers, json={})
        path = request.url.path
        if path.endswith("/me/calendars"):
            return httpx.Response(
                200,
                json={
                    "value": [
                        {"id": cid, "name": name}
                        for cid, name in self.calendars.items()
                    ]
                },
            )
        if path.endswith("/calendarView"):
            return self._calendar_view(request)
        return httpx.Response(404, json={})

    def _calendar_view(self, request: httpx.Request) -> httpx.Response:
        calendar_id = request.url.path.split("/calendars/")[1].split("/")[0]
        if calendar_id not in self.events:
            return httpx.Response(404, json={})
        window_start = _london(request.url.params["startDateTime"])
        window_end = _london(request.url.params["endDateTime"])
        inside = [
            e
            for e in self.events[calendar_id]
            if _overlaps(e, window_start, window_end)
        ]
        offset = int(request.url.params.get("skip", "0"))
        page = inside[offset : offset + self.page_size]
        body: dict[str, object] = {"value": page}
        if offset + self.page_size < len(inside):
            more = request.url.copy_merge_params(
                {"skip": offset + self.page_size}
            )
            body["@odata.nextLink"] = str(more)
        return httpx.Response(200, json=body)


def _london(text: str) -> datetime.datetime:
    """Reads a query time as Graph does: no offset means UTC.

    Returns:
        The same moment as London wall-clock time (naive), to compare with
        the event times this fake serves.
    """
    moment = datetime.datetime.fromisoformat(text)
    if moment.tzinfo is None:
        moment = moment.replace(tzinfo=datetime.UTC)
    london = moment.astimezone(zoneinfo.ZoneInfo("Europe/London"))
    return london.replace(tzinfo=None)


def _overlaps(
    event: dict[str, object],
    window_start: datetime.datetime,
    window_end: datetime.datetime,
) -> bool:
    try:
        start = datetime.datetime.fromisoformat(_time(event, "start"))
        end = datetime.datetime.fromisoformat(_time(event, "end"))
    except (KeyError, ValueError):
        return True  # a broken event is still sent; the client must cope
    return start < window_end and end > window_start


def _time(event: dict[str, object], key: str) -> str:
    value = event[key]
    assert isinstance(value, dict)
    return str(value["dateTime"])
