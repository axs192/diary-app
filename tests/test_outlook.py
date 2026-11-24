"""Tests for the Microsoft Graph client (only Graph's HTTP is faked)."""

import datetime
import pathlib
import stat
import tempfile
import threading
import unittest

import httpx

from diary_app import outlook
from tests.graph_fake import (
    FakeGraph,
    SignedOutToken,
    StaticToken,
    graph_event,
)

_START = datetime.datetime(2030, 1, 7)
_END = datetime.datetime(2030, 1, 14)


def _client(
    graph: FakeGraph, sleeps: list[float] | None = None
) -> outlook.GraphClient:
    record = sleeps if sleeps is not None else []
    return outlook.GraphClient(
        StaticToken(), graph.client(), sleep=record.append
    )


class CalendarsTest(unittest.TestCase):
    """Listing the calendars the account can see."""

    def test_lists_ids_and_names(self) -> None:
        graph = FakeGraph(calendars={"a1": "Calendar", "b2": "Family"})
        self.assertEqual(
            _client(graph).calendars(),
            [
                outlook.CalendarInfo("a1", "Calendar"),
                outlook.CalendarInfo("b2", "Family"),
            ],
        )

    def test_sends_the_bearer_token(self) -> None:
        graph = FakeGraph(calendars={"a1": "Calendar"})
        _client(graph).calendars()
        self.assertEqual(
            graph.requests[0].headers["Authorization"], "Bearer test-token"
        )


class EventsTest(unittest.TestCase):
    """Reading one calendar's events for a date range."""

    def test_returns_timed_and_all_day_events(self) -> None:
        graph = FakeGraph(
            calendars={"a1": "Family"},
            events={
                "a1": [
                    graph_event(
                        "e1",
                        "Mum : Swimming",
                        "2030-01-08T17:00:00",
                        "2030-01-08T18:00:00",
                    ),
                    graph_event(
                        "e2",
                        "Birthday : Nan",
                        "2030-01-09T00:00:00",
                        "2030-01-10T00:00:00",
                        all_day=True,
                    ),
                ]
            },
        )
        events = _client(graph).events("a1", _START, _END)
        self.assertEqual(
            events,
            [
                outlook.RawEvent(
                    "e1",
                    "Mum : Swimming",
                    datetime.datetime(2030, 1, 8, 17),
                    datetime.datetime(2030, 1, 8, 18),
                    all_day=False,
                ),
                outlook.RawEvent(
                    "e2",
                    "Birthday : Nan",
                    datetime.datetime(2030, 1, 9),
                    datetime.datetime(2030, 1, 10),
                    all_day=True,
                ),
            ],
        )

    def test_asks_for_local_times_not_utc(self) -> None:
        graph = FakeGraph(calendars={"a1": "F"}, events={"a1": []})
        outlook.GraphClient(
            StaticToken(),
            graph.client(),
            timezone="Europe/London",
            sleep=lambda _s: None,
        ).events("a1", _START, _END)
        sent = graph.calendar_view_calls()[0]
        self.assertEqual(
            sent.headers["Prefer"], 'outlook.timezone="Europe/London"'
        )

    def test_the_range_is_sent_with_the_local_utc_offset(self) -> None:
        graph = FakeGraph(calendars={"a1": "F"}, events={"a1": []})
        _client(graph).events(
            "a1",
            datetime.datetime(2030, 7, 1),  # summer time
            datetime.datetime(2030, 7, 8),
        )
        sent = graph.calendar_view_calls()[0].url.params
        self.assertEqual(sent["startDateTime"], "2030-07-01T00:00:00+01:00")
        self.assertEqual(sent["endDateTime"], "2030-07-08T00:00:00+01:00")

    def test_an_evening_event_in_summer_is_not_missed(self) -> None:
        graph = FakeGraph(
            calendars={"a1": "F"},
            events={
                "a1": [
                    graph_event(
                        "late",
                        "Mum : Choir",
                        "2030-07-07T23:30:00",
                        "2030-07-08T00:30:00",
                    )
                ]
            },
        )
        found = _client(graph).events(
            "a1", datetime.datetime(2030, 7, 8), datetime.datetime(2030, 7, 15)
        )
        self.assertEqual([e.id for e in found], ["late"])

    def test_follows_paging_to_the_end(self) -> None:
        many = [
            graph_event(
                f"e{n}",
                f"Mum : Thing {n}",
                "2030-01-08T09:00:00",
                "2030-01-08T10:00:00",
            )
            for n in range(5)
        ]
        graph = FakeGraph(
            calendars={"a1": "F"}, events={"a1": many}, page_size=2
        )
        events = _client(graph).events("a1", _START, _END)
        self.assertEqual([e.id for e in events], [f"e{n}" for n in range(5)])
        self.assertEqual(len(graph.calendar_view_calls()), 3)

    def test_missing_title_becomes_empty(self) -> None:
        raw = graph_event(
            "e1", "x", "2030-01-08T09:00:00", "2030-01-08T10:00:00"
        )
        raw["subject"] = None
        graph = FakeGraph(calendars={"a1": "F"}, events={"a1": [raw]})
        self.assertEqual(_client(graph).events("a1", _START, _END)[0].title, "")


class FailureTest(unittest.TestCase):
    """Retries, and the errors a caller can tell apart."""

    def test_rate_limit_is_retried_after_the_requested_wait(self) -> None:
        graph = FakeGraph(
            calendars={"a1": "F"}, failures=[429], retry_after="3"
        )
        sleeps: list[float] = []
        self.assertEqual(len(_client(graph, sleeps).calendars()), 1)
        self.assertEqual(sleeps, [3.0])

    def test_server_errors_are_retried_then_given_up_on(self) -> None:
        graph = FakeGraph(failures=[503, 503, 503, 503])
        with self.assertRaises(outlook.OutlookError):
            _client(graph).calendars()
        self.assertEqual(len(graph.requests), 3)

    def test_a_rejected_token_means_sign_in_again(self) -> None:
        graph = FakeGraph(failures=[401])
        with self.assertRaises(outlook.NeedsSignInError):
            _client(graph).calendars()

    def test_a_lost_refresh_token_means_sign_in_again(self) -> None:
        graph = FakeGraph(calendars={"a1": "F"})
        client = outlook.GraphClient(SignedOutToken(), graph.client())
        with self.assertRaises(outlook.NeedsSignInError):
            client.calendars()
        self.assertEqual(graph.requests, [])

    def test_a_missing_calendar_is_an_outlook_error(self) -> None:
        graph = FakeGraph(calendars={"a1": "F"}, events={})
        with self.assertRaises(outlook.OutlookError):
            _client(graph).events("gone", _START, _END)

    def test_a_network_failure_is_an_outlook_error(self) -> None:
        def refuse(_request: httpx.Request) -> httpx.Response:
            msg = "no route"
            raise httpx.ConnectError(msg)

        client = outlook.GraphClient(
            StaticToken(),
            httpx.Client(transport=httpx.MockTransport(refuse)),
            sleep=lambda _s: None,
        )
        with self.assertRaises(outlook.OutlookError):
            client.calendars()

    def test_a_reply_that_is_not_json_is_an_outlook_error(self) -> None:
        client = self._client_answering(
            httpx.Response(200, text="<html>Sign in to the Wi-Fi</html>")
        )
        with self.assertRaises(outlook.OutlookError):
            client.calendars()

    def test_an_event_without_times_is_an_outlook_error(self) -> None:
        raw = graph_event(
            "e1", "x", "2030-01-08T09:00:00", "2030-01-08T10:00:00"
        )
        del raw["start"]
        graph = FakeGraph(calendars={"a1": "F"}, events={"a1": [raw]})
        with self.assertRaises(outlook.OutlookError):
            _client(graph).events("a1", _START, _END)

    def test_an_event_without_an_id_is_an_outlook_error(self) -> None:
        raw = graph_event(
            "e1", "x", "2030-01-08T09:00:00", "2030-01-08T10:00:00"
        )
        del raw["id"]
        graph = FakeGraph(calendars={"a1": "F"}, events={"a1": [raw]})
        with self.assertRaises(outlook.OutlookError):
            _client(graph).events("a1", _START, _END)

    def test_an_unreadable_time_is_an_outlook_error(self) -> None:
        raw = graph_event(
            "e1", "x", "2030-01-08T09:00:00", "2030-01-08T10:00:00"
        )
        raw["start"] = {"dateTime": "tomorrow-ish", "timeZone": "UTC"}
        graph = FakeGraph(calendars={"a1": "F"}, events={"a1": [raw]})
        with self.assertRaises(outlook.OutlookError):
            _client(graph).events("a1", _START, _END)

    def _client_answering(self, answer: httpx.Response) -> outlook.GraphClient:
        return outlook.GraphClient(
            StaticToken(),
            httpx.Client(transport=httpx.MockTransport(lambda _r: answer)),
            sleep=lambda _s: None,
        )


class TokenFileTest(unittest.TestCase):
    """The saved sign-in is private, and absent until someone signs in."""

    def setUp(self) -> None:
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.folder = pathlib.Path(tmp.name)

    def test_nobody_signed_in_means_sign_in(self) -> None:
        source = outlook.MsalTokenSource("client", self.folder / "token.json")
        with self.assertRaises(outlook.NeedsSignInError):
            source.token()

    def test_saved_sign_in_is_readable_only_by_its_owner(self) -> None:
        path = self.folder / "state" / "token.json"
        outlook.write_private_file(path, "secret")
        self.assertEqual(path.read_text(), "secret")
        self.assertEqual(stat.S_IMODE(path.stat().st_mode), 0o600)
        self.assertEqual(stat.S_IMODE(path.parent.stat().st_mode), 0o700)

    def test_rewriting_keeps_the_file_private(self) -> None:
        path = self.folder / "token.json"
        path.write_text("old")
        path.chmod(0o644)
        outlook.write_private_file(path, "new")
        self.assertEqual(stat.S_IMODE(path.stat().st_mode), 0o600)

    def test_a_reader_never_sees_a_half_written_file(self) -> None:
        path = self.folder / "token.json"
        short, long = "a" * 10, "b" * 200_000
        outlook.write_private_file(path, short)
        stop = threading.Event()

        def rewrite() -> None:
            while not stop.is_set():
                outlook.write_private_file(path, long)
                outlook.write_private_file(path, short)

        writer = threading.Thread(target=rewrite)
        writer.start()
        try:
            seen = {path.read_text() for _ in range(2000)}
        finally:
            stop.set()
            writer.join()
        self.assertTrue(seen <= {short, long}, "saw a partly written file")

    def test_writing_leaves_no_stray_files(self) -> None:
        path = self.folder / "token.json"
        outlook.write_private_file(path, "one")
        outlook.write_private_file(path, "two")
        self.assertEqual(
            [p.name for p in self.folder.iterdir()], ["token.json"]
        )

    def test_token_reads_wait_for_the_sign_in_lock(self) -> None:
        path = self.folder / "token.json"
        outlook.write_private_file(path, "{}")
        source = outlook.MsalTokenSource("client", path)
        finished = threading.Event()

        def use() -> None:
            with self.assertRaises(outlook.NeedsSignInError):
                source.token()
            finished.set()

        with outlook.sign_in_lock(path):
            worker = threading.Thread(target=use)
            worker.start()
            self.assertFalse(finished.wait(0.3))
        self.assertTrue(finished.wait(5))
        worker.join()


if __name__ == "__main__":
    unittest.main()
