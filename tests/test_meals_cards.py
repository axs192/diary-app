"""Tests for the day cards on Meals: a short card with a "..." menu."""

import re

from tests.test_meals_web import _DAYS, _WEEK, _MealsTestCase


class _CardTestCase(_MealsTestCase):
    def setUp(self) -> None:
        super().setUp()
        self.log_in()

    def card(self, day_index: int = 1, **recipe: object) -> str:
        recipe_id = self.add_recipe("Pasta bake", **recipe)
        self.plan(_DAYS[day_index], recipe_id)
        self.recipe_id = recipe_id
        return self.day_card(self.client.get(_WEEK).text, _DAYS[day_index])

    @staticmethod
    def split_at_menu(card: str) -> tuple[str, str]:
        before, found, after = card.partition('<details class="day-menu"')
        assert found, "no menu on the card"
        return before, after


class DayCardTest(_CardTestCase):
    def test_a_planned_day_shows_the_recipe_and_a_menu(self) -> None:
        card = self.card()
        before, _after = self.split_at_menu(card)
        self.assertIn(
            f'<a class="day-meal" href="/recipes/{self.recipe_id}">', before
        )
        self.assertIn(
            f'<a class="btn btn-small" href="/recipes/{self.recipe_id}">'
            "Recipe</a>",
            before,
        )
        self.assertIn("40 min", before)

    def test_the_other_actions_live_in_the_menu(self) -> None:
        card = self.card()
        before, after = self.split_at_menu(card)
        for text in ("Swap", "/meals/day/remove", "/favourite", "Cooked it"):
            with self.subTest(text=text):
                self.assertIn(text, after)
                self.assertNotIn(text, before)

    def test_the_menu_has_a_label_and_starts_closed(self) -> None:
        card = self.card()
        self.assertIn('<details class="day-menu">', card)
        self.assertRegex(card, r'<summary[^>]*aria-label="More[^"]*"')

    def test_a_cooked_day_shows_a_chip_and_keeps_undo_in_the_menu(self) -> None:
        self.card()
        self.client.post(
            "/meals/day/cooked", data={"day": _DAYS[1].isoformat()}
        )
        card = self.day_card(self.client.get(_WEEK).text, _DAYS[1])
        before, after = self.split_at_menu(card)
        self.assertIn("Cooked", before)
        self.assertNotIn("Undo", before)
        self.assertIn("Undo", after)
        self.assertNotIn("Cooked it", card)

    def test_an_empty_day_is_a_card_of_the_same_kind_with_one_button(
        self,
    ) -> None:
        self.card(1)
        card = self.day_card(self.client.get(_WEEK).text, _DAYS[4])
        self.assertIn("Nothing planned", card)
        self.assertIn("Add a meal", card)
        self.assertNotIn("day-menu", card)

    def test_every_day_is_the_same_kind_of_box(self) -> None:
        html = self.client.get(_WEEK).text
        classes = re.findall(r'<article class="(day [^"]*)"', html)
        self.assertEqual(len(classes), 7)
        # only today may differ (its outline); sizing is by the one .day rule
        plain = {c.replace(" day-today", "") for c in classes}
        self.assertEqual(plain, {"day card"})


class DayCardSizeTest(_CardTestCase):
    def rule(self, selector: str) -> str:
        css = self.client.get("/static/app.css").text
        found = re.search(re.escape(selector) + r" \{([^}]*)\}", css)
        assert found, f"no rule for {selector}"
        return found.group(1)

    def test_the_boxes_have_one_fixed_width_and_a_minimum_height(self) -> None:
        body = self.rule(".days > .day")
        self.assertRegex(
            body, r"flex:\s*0 0 calc\("
        )  # no growing: not stretched
        self.assertIn("min-height", body)

    def test_the_boxes_get_fewer_across_on_narrower_screens(self) -> None:
        css = self.client.get("/static/app.css").text
        self.assertRegex(
            css, r"@media \(max-width: 900px\) \{\s*\.days > \.day"
        )
        self.assertRegex(
            css, r"@media \(max-width: 600px\) \{[^@]*\.days > \.day"
        )

    def test_the_menu_is_a_popover_that_does_not_move_the_cards(self) -> None:
        body = self.rule(".day-menu-body")
        self.assertIn("position: absolute", body)
        self.assertIn("z-index", body)

    def test_the_menu_sits_under_the_phone_menu_bar(self) -> None:
        css = self.client.get("/static/app.css").text
        menu = re.search(r"\.day-menu-body \{[^}]*z-index: (\d+)", css)
        nav = re.search(r"\.nav \{[^}]*z-index: (\d+)", css)
        assert menu and nav
        self.assertLess(int(menu.group(1)), int(nav.group(1)))


class HiddenBalanceTest(_CardTestCase):
    """The week-balance panel is parked: kept in the page but not shown."""

    def test_the_panel_is_still_in_the_page_but_hidden(self) -> None:
        html = self.client.get(_WEEK).text
        self.assertRegex(
            html, r'<section[^>]*aria-label="Week balance"[^>]*\bhidden\b'
        )
        self.assertIn("Veg-led dinners", html)  # still computed and rendered

    def test_hidden_really_hides_it(self) -> None:
        css = self.client.get("/static/app.css").text
        self.assertRegex(css, r"\[hidden\] \{[^}]*display: none !important")

    def test_clear_week_stays_available_outside_the_hidden_panel(self) -> None:
        html = self.client.get(_WEEK).text
        panel = re.search(
            r'<section[^>]*aria-label="Week balance".*?</section>',
            html,
            re.DOTALL,
        )
        assert panel
        self.assertNotIn("Clear week", panel.group(0))
        self.assertRegex(
            html,
            r'(?s)<form class="inline-form" method="post"'
            r' action="/meals/clear">.*?Clear week',
        )

    def test_clear_week_still_empties_the_week(self) -> None:
        self.card()
        response = self.client.post(
            "/meals/clear", data={"week": _DAYS[0].isoformat()}
        )
        self.assertEqual(response.status_code, 303)
        card = self.day_card(self.client.get(_WEEK).text, _DAYS[1])
        self.assertIn("Nothing planned", card)
