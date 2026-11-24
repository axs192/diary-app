"""Behaviour tests for static/app.js, run in a fake browser under Node.

Only the browser boundary (DOM, timers, clock, XMLHttpRequest, location) is
faked, see ``tests/js/browser.js``; the script under test is the real file.
Real Safari 9 behaviour can only be checked on the iPad.
"""

import json
import os
import pathlib
import shutil
import subprocess
import unittest
from typing import Any

_SCENARIOS = pathlib.Path(__file__).parent / "js" / "scenarios.js"
_NODE = shutil.which("node")


# On a laptop without node the tests skip; in CI (which sets CI) a missing node
# is a failure, so the checks cannot silently stop running.
@unittest.skipIf(
    not _NODE and not os.environ.get("CI"),
    "node is needed to run app.js outside a browser",
)
class AppJsBehaviourTest(unittest.TestCase):
    results: dict[str, Any]

    @classmethod
    def setUpClass(cls) -> None:
        if _NODE is None:
            raise AssertionError("node is required in CI to test app.js")
        done = subprocess.run(  # noqa: S603
            [_NODE, str(_SCENARIOS)],
            capture_output=True,
            text=True,
            check=True,
            timeout=60,
            env={**os.environ, "TZ": "UTC"},
        )
        cls.results = json.loads(done.stdout)

    # --- links ---------------------------------------------------------

    def test_a_same_origin_link_navigates_in_place(self) -> None:
        r = self.results["sameOriginLink"]
        self.assertTrue(r["prevented"])
        self.assertEqual(r["to"], ["http://diary.test:8000/settings"])

    def test_a_tap_on_something_inside_a_link_still_counts(self) -> None:
        r = self.results["childOfLink"]
        self.assertTrue(r["prevented"])
        self.assertEqual(r["to"], ["http://diary.test:8000/meals"])

    def test_other_links_and_taps_are_left_alone(self) -> None:
        self.assertEqual(
            self.results["leftAlone"],
            {
                "external": False,
                "lookalike": False,
                "newTab": False,
                "download": False,
                "notALink": False,
            },
        )
        self.assertEqual(self.results["leftAloneNavigations"], [])

    # --- error banner --------------------------------------------------

    def test_an_error_shows_message_file_and_line(self) -> None:
        b = self.results["banner"]
        self.assertEqual(b["count"], 1)
        self.assertIn("boom", b["text"])
        self.assertIn("/static/app.js", b["text"])
        self.assertIn("12", b["text"])

    def test_further_errors_update_one_banner(self) -> None:
        b = self.results["banner"]
        self.assertEqual(b["countAfterSecond"], 1)
        self.assertIn("second", b["secondText"])

    def test_the_banner_can_be_dismissed_and_returns_on_a_new_error(
        self,
    ) -> None:
        b = self.results["banner"]
        self.assertEqual(b["afterDismiss"], 0)
        self.assertEqual(b["reappears"], 1)

    def test_the_flag_turns_the_banner_off(self) -> None:
        self.assertEqual(self.results["bannerOff"]["handler"], "undefined")

    def test_an_existing_error_handler_still_runs(self) -> None:
        r = self.results["bannerKeepsPrevious"]
        self.assertEqual(r["calls"], ["kept"])
        self.assertEqual(r["shown"], 1)

    # --- reconnecting overlay ------------------------------------------

    def test_a_healthy_server_shows_nothing_and_never_reloads(self) -> None:
        h = self.results["healthy"]
        self.assertEqual((h["overlay"], h["reloads"]), (0, 0))
        self.assertEqual(h["pings"], 6)  # one every 30 seconds
        self.assertTrue(h["allHealth"])
        self.assertTrue(h["cacheBusted"])  # iOS 9 may cache a plain GET

    def test_an_outage_shows_reconnecting_and_keeps_retrying(self) -> None:
        o = self.results["outage"]
        self.assertEqual(o["shown"], 1)
        self.assertIn("Reconnecting", o["text"])
        self.assertEqual(o["stillDown"], {"overlays": 1, "reloads": 0})

    def test_the_page_reloads_once_the_server_is_back(self) -> None:
        self.assertEqual(self.results["outage"]["reloadsAfterRecovery"], 1)

    def test_a_timeout_or_server_error_counts_as_an_outage(self) -> None:
        self.assertEqual(self.results["outage_timeout"], 1)
        self.assertEqual(self.results["outage_500"], 1)

    # --- scheduled reloads ---------------------------------------------

    def test_it_reloads_six_hours_after_loading(self) -> None:
        r = self.results["reloadFrom10"]
        self.assertEqual(r["utcHour"], 16)
        self.assertLessEqual(r["afterMs"], 6 * 3600 * 1000 + 30 * 1000)

    def test_it_reloads_at_three_in_the_morning_when_that_comes_first(
        self,
    ) -> None:
        for key in ("reloadFrom22", "reloadFrom01"):
            self.assertEqual(self.results[key]["utcHour"], 3, key)

    def test_just_after_three_it_does_not_reload_again_at_once(self) -> None:
        r = self.results["reloadFromJustAfter3"]
        self.assertEqual(r["utcHour"], 9)

    def test_a_reload_waits_while_someone_is_typing(self) -> None:
        r = self.results["typing"]
        self.assertEqual(r["deferred"], 0)
        # The fake browser's reload() does not restart the page, so the
        # script keeps asking; a real reload would reset it.
        self.assertGreaterEqual(r["after"], 1)

    def test_a_reload_waits_for_the_server(self) -> None:
        r = self.results["reloadWaitsForServer"]
        self.assertEqual(r["whileDown"], 0)
        self.assertEqual(r["afterRecovery"], 1)

    # --- Meals library tabs --------------------------------------------

    def test_a_tab_swaps_the_list_without_navigating(self) -> None:
        r = self.results["tabSwap"]
        self.assertTrue(r["prevented"])
        self.assertEqual(r["navigations"], [])
        self.assertEqual(
            r["requested"],
            ["/meals/library?week=2030-01-07&tab=favourites"],
        )
        self.assertEqual(r["html"], "<ul>FAVOURITES</ul>")

    def test_the_list_shows_busy_until_the_new_one_arrives(self) -> None:
        r = self.results["tabSwap"]
        self.assertTrue(r["during"]["busy"])
        self.assertEqual(r["during"]["html"], "<ul>IDEAS</ul>")  # not blank
        self.assertFalse(r["busyAfter"])

    def test_the_tapped_tab_becomes_the_current_one(self) -> None:
        self.assertEqual(self.results["tabSwap"]["current"], ["favourites"])

    def test_a_tap_inside_a_tab_counts(self) -> None:
        r = self.results["tabChild"]
        self.assertEqual(r["html"], "<ul>MINE</ul>")
        self.assertEqual(r["current"], ["mine"])

    def test_a_failed_swap_falls_back_to_a_normal_page_load(self) -> None:
        for key in ("tabFails_down", "tabFails_timeout", "tabFails_500"):
            r = self.results[key]
            self.assertEqual(
                r["navigations"],
                [
                    "http://diary.test:8000/meals?week=2030-01-07&tab=mine#library"
                ],
                key,
            )
            self.assertEqual(r["html"], "<ul>IDEAS</ul>", key)  # untouched
            self.assertEqual(r["current"], ["ideas"], key)
            self.assertFalse(r["busyAfter"], key)

    def test_a_late_answer_for_an_earlier_tap_is_ignored(self) -> None:
        r = self.results["tabStale"]
        self.assertEqual(r["html"], "<ul>FAST</ul>")
        self.assertEqual(r["current"], ["mine"])
        self.assertFalse(r["busyAfter"])

    def test_other_links_on_that_page_still_navigate(self) -> None:
        r = self.results["tabsPageOtherLink"]
        self.assertTrue(r["prevented"])
        self.assertEqual(r["to"], ["http://diary.test:8000/settings"])


if __name__ == "__main__":
    unittest.main()
