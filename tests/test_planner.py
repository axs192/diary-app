"""Tests for the diary_app.planner public interface."""

import datetime
import itertools
import random
import unittest

from diary_app import planner, recipes

_MON = datetime.date(2026, 11, 23)
_WEEK = [_MON + datetime.timedelta(days=i) for i in range(7)]
_FRI = _WEEK[4]
_SAT = _WEEK[5]
_SUN = _WEEK[6]
_ids = itertools.count(1)


def _recipe(
    name: str,
    *tags: str,
    style: str = "Other",
    favourite: bool = False,
) -> recipes.Recipe:
    return recipes.Recipe(
        id=next(_ids),
        name=name,
        style=style,
        mins=30,
        servings=4,
        ingredients=(),
        steps=(),
        tags=tags,
        source_url="",
        source_name="",
        is_favourite=favourite,
    )


def _plain(count: int) -> list[recipes.Recipe]:
    return [_recipe(f"Plain {i}") for i in range(count)]


def _suggest(
    library: list[recipes.Recipe], seed: int = 1, **fields: object
) -> planner.Suggestion:
    request = planner.SuggestionRequest(
        days=fields.pop("days", _WEEK),  # type: ignore[arg-type]
        library=library,
        **fields,  # type: ignore[arg-type]
    )
    suggester = planner.RuleBasedSuggester(random.Random(seed))  # noqa: S311
    return suggester.suggest_week(request)


def _chosen(
    suggestion: planner.Suggestion, library: list[recipes.Recipe]
) -> dict[datetime.date, recipes.Recipe]:
    by_id = {r.id: r for r in library}
    return {d: by_id[i] for d, i in suggestion.assignments.items()}


class RuleBasedSuggesterTest(unittest.TestCase):
    """RuleBasedSuggester fills empty days using the household's rules."""

    def test_it_is_a_meal_suggester(self) -> None:
        suggester: planner.MealSuggester = planner.RuleBasedSuggester()
        self.assertTrue(callable(suggester.suggest_week))

    def test_fills_every_day_when_the_library_is_big_enough(self) -> None:
        suggestion = _suggest(_plain(10))
        self.assertEqual(set(suggestion.assignments), set(_WEEK))
        self.assertEqual(suggestion.unfilled, [])

    def test_never_repeats_a_meal_in_the_week(self) -> None:
        suggestion = _suggest(_plain(10))
        ids = list(suggestion.assignments.values())
        self.assertEqual(len(ids), len(set(ids)))

    def test_small_library_fills_what_it_can_and_reports_the_rest(
        self,
    ) -> None:
        suggestion = _suggest(_plain(3))
        self.assertEqual(len(suggestion.assignments), 3)
        self.assertEqual(len(suggestion.unfilled), 4)
        self.assertEqual(
            set(suggestion.assignments) | set(suggestion.unfilled),
            set(_WEEK),
        )

    def test_empty_library_leaves_every_day_unfilled(self) -> None:
        suggestion = _suggest([])
        self.assertEqual(suggestion.assignments, {})
        self.assertEqual(suggestion.unfilled, _WEEK)

    def test_only_the_requested_days_are_filled(self) -> None:
        suggestion = _suggest(_plain(10), days=[_WEEK[2], _WEEK[3]])
        self.assertEqual(set(suggestion.assignments), {_WEEK[2], _WEEK[3]})

    def test_meals_already_planned_this_week_are_not_repeated(self) -> None:
        library = _plain(8)
        planned = library[:2]
        suggestion = _suggest(library, planned=planned, days=_WEEK[2:])
        used = set(suggestion.assignments.values())
        self.assertFalse(used & {r.id for r in planned})

    def test_same_seed_gives_the_same_week(self) -> None:
        library = _plain(12)
        self.assertEqual(_suggest(library, seed=7), _suggest(library, seed=7))

    def test_different_seeds_can_give_different_weeks(self) -> None:
        library = _plain(12)
        weeks = {
            tuple(_suggest(library, seed=s).assignments.values())
            for s in range(10)
        }
        self.assertGreater(len(weeks), 1)

    def test_favourites_come_first(self) -> None:
        library = _plain(10)
        loved = [_recipe(f"Loved {i}", favourite=True) for i in range(3)]
        suggestion = _suggest(library + loved)
        self.assertTrue(
            {r.id for r in loved} <= set(suggestion.assignments.values())
        )

    def test_recent_meals_are_avoided_when_there_is_a_choice(self) -> None:
        library = _plain(10)
        recent = {r.id for r in library[:3]}
        suggestion = _suggest(library, recent_ids=frozenset(recent))
        self.assertFalse(recent & set(suggestion.assignments.values()))

    def test_recent_meals_are_used_when_nothing_else_remains(self) -> None:
        library = _plain(7)
        suggestion = _suggest(
            library, recent_ids=frozenset(r.id for r in library)
        )
        self.assertEqual(suggestion.unfilled, [])

    def test_chosen_style_is_honoured(self) -> None:
        library = _plain(10) + [
            _recipe(f"Taco {i}", style="Mexican") for i in range(7)
        ]
        chosen = _chosen(_suggest(library, style="Mexican"), library)
        self.assertTrue(all(r.style == "Mexican" for r in chosen.values()))

    def test_style_falls_back_to_other_meals_when_too_few_match(self) -> None:
        library = [*_plain(10), _recipe("Taco", style="Mexican")]
        suggestion = _suggest(library, style="Mexican")
        self.assertEqual(suggestion.unfilled, [])
        chosen = _chosen(suggestion, library)
        self.assertEqual(
            sum(1 for r in chosen.values() if r.style == "Mexican"), 1
        )

    def test_mixed_style_uses_everything(self) -> None:
        library = [
            _recipe(f"Dish {i}", style=style)
            for i, style in enumerate(recipes.STYLES)
        ]
        self.assertEqual(_suggest(library, style="Mixed").unfilled, [])

    def test_aims_for_three_veg_led_dinners(self) -> None:
        veg = [_recipe(f"Veg {i}", "Veg-led") for i in range(4)]
        loved = [_recipe(f"Meaty {i}", favourite=True) for i in range(6)]
        chosen = _chosen(_suggest(veg + loved), veg + loved)
        count = sum(1 for r in chosen.values() if "Veg-led" in r.tags)
        self.assertGreaterEqual(count, 3)

    def test_aims_for_one_oily_fish_dinner(self) -> None:
        fish = _recipe("Salmon", "Oily fish")
        loved = [_recipe(f"Loved {i}", favourite=True) for i in range(8)]
        chosen = _chosen(_suggest([fish, *loved]), [fish, *loved])
        self.assertIn(fish, chosen.values())

    def test_at_most_one_treat_night(self) -> None:
        treats = [
            _recipe(f"Treat {i}", "Treat night", favourite=True)
            for i in range(4)
        ]
        library = treats + _plain(8)
        chosen = _chosen(_suggest(library), library)
        count = sum(1 for r in chosen.values() if "Treat night" in r.tags)
        self.assertLessEqual(count, 1)

    def test_treat_already_planned_blocks_another(self) -> None:
        planned = [_recipe("Burger", "Treat night")]
        treats = [
            _recipe(f"Treat {i}", "Treat night", favourite=True)
            for i in range(4)
        ]
        library = treats + _plain(8)
        suggestion = _suggest(library, planned=planned, days=_WEEK[1:])
        chosen = _chosen(suggestion, library)
        self.assertFalse(any("Treat night" in r.tags for r in chosen.values()))

    def test_treat_night_prefers_friday(self) -> None:
        treat = _recipe("Pizza", "Treat night")
        library = [treat, *_plain(8)]
        for seed in range(5):
            chosen = _chosen(_suggest(library, seed=seed), library)
            self.assertEqual(chosen.get(_FRI), treat, seed)

    def test_batch_cooking_prefers_the_weekend(self) -> None:
        batch = [_recipe(f"Batch {i}", "Batch cook") for i in range(2)]
        library = batch + _plain(8)
        for seed in range(5):
            chosen = _chosen(_suggest(library, seed=seed), library)
            where = {d for d, r in chosen.items() if r in batch}
            self.assertEqual(where, {_SAT, _SUN}, seed)

    def test_quick_days_get_quick_meals(self) -> None:
        quick = [_recipe(f"Quick {i}", "Quick") for i in range(3)]
        library = quick + _plain(8)
        busy = frozenset({_WEEK[0], _WEEK[2], _WEEK[3]})
        chosen = _chosen(_suggest(library, quick_days=busy), library)
        for day in busy:
            self.assertIn("Quick", chosen[day].tags, day)

    def test_no_quick_days_means_no_quick_preference(self) -> None:
        quick = [_recipe(f"Quick {i}", "Quick") for i in range(3)]
        library = quick + _plain(8)
        chosen = _chosen(_suggest(library, seed=3), library)
        self.assertEqual(len(chosen), 7)

    def test_kid_friendly_priority_picks_kid_friendly_meals(self) -> None:
        kids = [_recipe(f"Kids {i}", "Kid-friendly") for i in range(7)]
        library = kids + _plain(7)
        suggestion = _suggest(library, priorities=frozenset({"kid-friendly"}))
        chosen = _chosen(suggestion, library)
        self.assertTrue(all("Kid-friendly" in r.tags for r in chosen.values()))

    def test_quick_priority_picks_quick_meals(self) -> None:
        quick = [_recipe(f"Quick {i}", "Quick") for i in range(7)]
        library = quick + _plain(7)
        suggestion = _suggest(library, priorities=frozenset({"quick"}))
        chosen = _chosen(suggestion, library)
        self.assertTrue(all("Quick" in r.tags for r in chosen.values()))

    def test_healthy_priority_picks_healthy_meals(self) -> None:
        healthy = [_recipe(f"Fresh {i}", "Wholegrain") for i in range(7)]
        library = healthy + _plain(7)
        suggestion = _suggest(library, priorities=frozenset({"healthy"}))
        chosen = _chosen(suggestion, library)
        self.assertTrue(all("Wholegrain" in r.tags for r in chosen.values()))


if __name__ == "__main__":
    unittest.main()
