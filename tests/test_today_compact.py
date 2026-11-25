"""Tests for the one-screen tablet layout of Today.

On the kitchen iPad the page must show Tonight, the kids and a compact
Coming up without scrolling, with a button to expand the full detail. It is
all markup and CSS (a checkbox and a label), so it needs no script on iOS 9.
"""

import re
import unittest

from tests import calendar_support as cal
from tests import support


class _CompactTestCase(cal.AppTestCase):
    def setUp(self) -> None:
        super().setUp()
        self.add_person("Alex", "Adult", "#B04A17")
        self.add_person("Sam", "Child", "#5B2E86")

    def home(self) -> str:
        return self.page("/home")

    def block(self, html: str, name: str) -> str:
        found = re.search(
            rf'<div class="{name}".*?(?=<div class="coming-full"|</section>)',
            html,
            re.DOTALL,
        )
        self.assertIsNotNone(found, f"no {name}")
        return found.group(0) if found else ""


class ToggleTest(_CompactTestCase):
    def test_there_is_a_compact_list_a_full_list_and_a_checkbox_toggle(
        self,
    ) -> None:
        html = self.home()
        self.assertIn('class="coming-compact"', html)
        self.assertIn('class="coming-full"', html)
        self.assertRegex(html, r'<input[^>]*type="checkbox"[^>]*id="show-more"')
        self.assertRegex(html, r'<label[^>]*for="show-more"')
        self.assertIn("Show full detail", html)

    def test_the_checkbox_comes_before_the_whole_row_it_controls(self) -> None:
        html = self.home()
        box = html.index('id="show-more"')
        self.assertLess(box, html.index('class="today '))
        self.assertLess(box, html.index('class="kid-days"'))
        self.assertLess(box, html.index('class="coming-full"'))

    def test_the_page_still_loads_only_the_app_script(self) -> None:
        support.assert_only_app_script(self, self.home(), "/home")


class CompactListTest(_CompactTestCase):
    def test_each_day_is_one_block_with_its_where_line(self) -> None:
        self.sync([cal.all_day("m", "Alex : [London]", 9)])
        compact = self.block(self.home(), "coming-compact")
        self.assertEqual(compact.count('class="cday"'), 5)
        self.assertRegex(compact, r"Alex\s+London")

    def test_events_show_their_title_time_and_who(self) -> None:
        self.sync([cal.timed("p", "Sam : Piano", 9, "15:00", "15:45")])
        compact = self.block(self.home(), "coming-compact")
        self.assertRegex(compact, r"3pm(?s:.*?)Piano(?s:.*?)Sam")
        self.assertIn('href="/event?id=p&amp;from=home"', compact)

    def test_all_day_events_do_not_say_all_day(self) -> None:
        self.sync([cal.all_day("h", "Sam : Haircut", 9)])
        compact = self.block(self.home(), "coming-compact")
        self.assertIn("Haircut", compact)
        self.assertNotIn("All day", compact)

    def test_a_quiet_day_says_nothing_on(self) -> None:
        self.assertIn("Nothing on.", self.block(self.home(), "coming-compact"))

    def test_a_busy_day_shows_four_and_counts_the_rest(self) -> None:
        self.sync(
            [cal.all_day(f"e{n}", f"Sam : Thing {n}", 9) for n in range(7)]
        )
        compact = self.block(self.home(), "coming-compact")
        self.assertEqual(compact.count('class="cev"'), 4)
        self.assertIn("+3", compact)

    def test_the_full_list_still_has_every_event(self) -> None:
        self.sync(
            [cal.all_day(f"e{n}", f"Sam : Thing {n}", 9) for n in range(7)]
        )
        full = self.home().split('class="coming-full"', maxsplit=1)[1]
        for n in range(7):
            self.assertIn(f"Thing {n}", full)

    def test_a_long_range_shows_five_days_and_says_how_many_more(self) -> None:
        self.client.post("/settings/today-range", data={"range": "14"})
        html = self.home()
        compact = self.block(html, "coming-compact")
        self.assertEqual(compact.count('class="cday"'), 5)
        self.assertIn("9 more days", compact)
        self.assertEqual(len(re.findall(r'class="up-day', html)), 14)

    def test_titles_are_escaped_in_the_compact_list_too(self) -> None:
        self.sync([cal.all_day("x", "Sam : <b>Hi</b>", 9)])
        compact = self.block(self.home(), "coming-compact")
        self.assertIn("&lt;b&gt;Hi&lt;/b&gt;", compact)
        self.assertNotIn("<b>Hi</b>", compact)


class KidsColumnsTest(_CompactTestCase):
    def test_today_and_tomorrow_share_a_row_for_each_child(self) -> None:
        html = self.home()
        self.assertEqual(html.count('class="kid-days"'), 1)
        row = html.split('class="kid-days"', maxsplit=1)[1]
        self.assertLess(row.index("Today"), row.index("Tomorrow"))


class BusyKidTest(_CompactTestCase):
    """A child with many events shows three rows and counts the rest."""

    def busy(self, timed: int = 4) -> str:
        events = [cal.all_day("all", "Sam : Own clothes day", 8)]
        events += [
            cal.timed(
                f"t{n}",
                f"Sam : Thing {n}",
                8,
                f"{9 + n:02d}:00",
                f"{10 + n:02d}:00",
            )
            for n in range(timed)
        ]
        self.sync(events)
        html = self.home()
        row = html.split('class="kid-days"', maxsplit=1)[1]
        return row.split("</section>", maxsplit=1)[0]

    def today_column(self, kids: str) -> str:
        return kids.split("Tomorrow", maxsplit=1)[0]

    def test_five_events_show_three_and_hide_two(self) -> None:
        today = self.today_column(self.busy())
        self.assertEqual(today.count('class="ev-row"'), 3)
        self.assertEqual(today.count('class="ev-row kid-extra"'), 2)
        self.assertIn("+2 more", today)

    def test_the_all_day_event_and_earliest_come_first(self) -> None:
        today = self.today_column(self.busy())
        shown, hidden = today.split('class="ev-row kid-extra"', maxsplit=1)
        self.assertIn("Own clothes day", shown)
        self.assertIn("Thing 0", shown)
        self.assertIn("Thing 1", shown)
        self.assertNotIn("Thing 3", shown)
        self.assertIn("Thing 3", hidden)

    def test_the_hidden_events_are_still_in_the_page_for_the_expand(
        self,
    ) -> None:
        today = self.today_column(self.busy())
        for n in range(4):
            self.assertIn(f"Thing {n}", today)

    def test_three_events_need_no_more_button(self) -> None:
        today = self.today_column(self.busy(timed=2))
        self.assertNotIn("more", today.lower().replace("tomorrow", ""))
        self.assertNotIn("kid-extra", today)

    def test_the_more_and_less_buttons_toggle_the_page_checkbox(self) -> None:
        today = self.today_column(self.busy())
        self.assertRegex(today, r'<label[^>]*for="show-more"[^>]*>\+2 more')
        self.assertRegex(today, r'<label[^>]*for="show-more"[^>]*>Show less')

    def test_tomorrow_is_capped_separately(self) -> None:
        events = [
            cal.timed(
                f"m{n}",
                f"Sam : Later {n}",
                9,
                f"{9 + n:02d}:00",
                f"{10 + n:02d}:00",
            )
            for n in range(5)
        ]
        self.sync(events)
        html = self.home()
        tomorrow = html.split("Tomorrow", maxsplit=2)[1]
        self.assertEqual(tomorrow.count("kid-extra"), 2)
        self.assertIn("+2 more", tomorrow)


class StylesheetTest(_CompactTestCase):
    def css(self) -> str:
        return str(self.client.get("/static/app.css").text)

    def test_tonight_moves_to_the_top_on_wide_screens_only(self) -> None:
        css = self.css()
        wide, _, phone = css.partition("@media (max-width: 600px) {\n  .today")
        self.assertRegex(wide, r"\.today > \.tonight \{[^}]*order: -1")
        self.assertRegex(phone, r"\.today > \.tonight \{[^}]*order: 2")

    def test_the_toggle_swaps_the_lists_with_no_script(self) -> None:
        css = self.css()
        self.assertRegex(
            css,
            r"\.more-toggle:checked ~ \.today \.coming-full"
            r" \{[^}]*display: block",
        )
        self.assertRegex(
            css,
            r"\.more-toggle:checked ~ \.today \.coming-compact"
            r" \{[^}]*display: none",
        )

    def test_extra_kid_events_are_hidden_until_expanded(self) -> None:
        css = self.css()
        self.assertRegex(css, r"\.kid-extra \{[^}]*display: none")
        self.assertRegex(
            css,
            r"\.more-toggle:checked ~ \.today \.kid-extra \{[^}]*display: flex",
        )
        self.assertRegex(
            css,
            r"\.more-toggle:checked ~ \.today \.ev-more \{[^}]*display: none",
        )

    def test_phones_show_every_kid_event_and_no_more_button(self) -> None:
        phone = self.css().split("@media (max-width: 600px) {\n  .today", 1)[1]
        self.assertRegex(phone, r"\.kid-extra \{[^}]*display: flex")
        self.assertRegex(phone, r"\.ev-more \{[^}]*display: none")
        self.assertRegex(phone, r"\.ev-less \{[^}]*display: none")

    def test_phones_always_show_the_full_list(self) -> None:
        phone = self.css().split("@media (max-width: 600px) {\n  .today", 1)[1]
        self.assertRegex(phone, r"\.coming-compact \{[^}]*display: none")
        self.assertRegex(phone, r"\.coming-full \{[^}]*display: block")
        self.assertRegex(phone, r"\.more-btn \{[^}]*display: none")


if __name__ == "__main__":
    unittest.main()
