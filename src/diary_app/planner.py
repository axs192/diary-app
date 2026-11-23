"""Suggest a week: choosing dinners for the empty days of a plan.

``MealSuggester`` is the interface the web page uses. ``RuleBasedSuggester``
is the first implementation (household rules, no AI); an AI-backed one can
replace it later without the page changing.
"""

import dataclasses
import datetime
import random
from collections.abc import Sequence
from typing import Protocol

from diary_app import recipes

MIXED = "Mixed"
PRIORITIES = ("healthy", "quick", "kid-friendly", "batch-cook")

_HEALTHY_TAGS = frozenset(
    {"Veg-led", "Lean protein", "Wholegrain", "Oily fish"}
)
_VEG_GOAL = 3
_FISH_GOAL = 1
_FRIDAY = 4
_WEEKEND = frozenset({5, 6})
_RECENT_PENALTY = 40.0
_STYLE_BONUS = 30.0
_FAVOURITE_BONUS = 10.0
_PRIORITY_BONUS = 8.0
_GOAL_BONUS = 25.0
_QUICK_DAY_BONUS = 20.0
_QUICK_DAY_PENALTY = 10.0
_TREAT_FRIDAY_BONUS = 15.0
_TREAT_OTHER_PENALTY = 15.0
_BATCH_WEEKEND_BONUS = 10.0
_BATCH_WEEKDAY_PENALTY = 20.0
_RANDOM_SPREAD = 3.0


@dataclasses.dataclass(frozen=True)
class SuggestionRequest:
    """What to plan.

    Attributes:
        days: The empty days to fill, in the order to fill them.
        library: Recipes to choose from.
        style: A style from ``recipes.STYLES``, or ``MIXED`` for any.
        priorities: Entries from ``PRIORITIES`` to favour.
        planned: Recipes already planned elsewhere this week; they are not
            repeated and count towards the week's balance.
        recent_ids: Recipes cooked in recent weeks, to avoid repeating.
        quick_days: Days that need a quick meal.
    """

    days: Sequence[datetime.date]
    library: Sequence[recipes.Recipe]
    style: str = MIXED
    priorities: frozenset[str] = frozenset()
    planned: Sequence[recipes.Recipe] = ()
    recent_ids: frozenset[int] = frozenset()
    quick_days: frozenset[datetime.date] = frozenset()


@dataclasses.dataclass(frozen=True)
class Suggestion:
    """A suggested plan.

    Attributes:
        assignments: Recipe id chosen for each day that could be filled.
        unfilled: Days left empty because the library ran out of meals.
    """

    assignments: dict[datetime.date, int] = dataclasses.field(
        default_factory=dict
    )
    unfilled: list[datetime.date] = dataclasses.field(default_factory=list)


class MealSuggester(Protocol):
    """Anything that can propose dinners for a week."""

    def suggest_week(self, request: SuggestionRequest) -> Suggestion:
        """Chooses a dinner for each requested day where it can."""
        ...


class RuleBasedSuggester:
    """Household rules: variety, favourites, balance and busy days.

    Every rule is a score, so a small library still gets filled: rules
    steer the choice rather than leave a day empty. The only hard rules
    are no repeats within the week and at most one treat night.
    """

    def __init__(self, rng: random.Random | None = None) -> None:
        """Creates a suggester.

        Args:
            rng: Source of randomness; pass a seeded one for repeatable
                results.
        """
        self._rng = rng or random.Random()  # nosec B311  # noqa: S311

    def suggest_week(self, request: SuggestionRequest) -> Suggestion:
        """Fills the requested days, never repeating a meal.

        Args:
            request: The days, library and preferences.

        Returns:
            The chosen recipe ids and any days that could not be filled.
        """
        chosen: list[recipes.Recipe] = list(request.planned)
        used = {r.id for r in chosen}
        assignments: dict[datetime.date, int] = {}
        unfilled: list[datetime.date] = []
        for day in request.days:
            pool = [
                r
                for r in request.library
                if r.id not in used and not self._treat_blocked(r, chosen)
            ]
            if not pool:
                unfilled.append(day)
                continue
            best = max(pool, key=lambda r: self._score(r, day, chosen, request))
            assignments[day] = best.id
            used.add(best.id)
            chosen.append(best)
        return Suggestion(assignments=assignments, unfilled=unfilled)

    @staticmethod
    def _treat_blocked(
        recipe: recipes.Recipe, chosen: list[recipes.Recipe]
    ) -> bool:
        return "Treat night" in recipe.tags and any(
            "Treat night" in r.tags for r in chosen
        )

    def _score(
        self,
        recipe: recipes.Recipe,
        day: datetime.date,
        chosen: list[recipes.Recipe],
        request: SuggestionRequest,
    ) -> float:
        tags = set(recipe.tags)
        score = self._rng.random() * _RANDOM_SPREAD
        if recipe.is_favourite:
            score += _FAVOURITE_BONUS
        if recipe.id in request.recent_ids:
            score -= _RECENT_PENALTY
        if request.style != MIXED and recipe.style == request.style:
            score += _STYLE_BONUS
        score += self._priority_score(tags, request.priorities)
        score += self._balance_score(tags, chosen)
        score += self._day_score(tags, day, request.quick_days)
        return score

    @staticmethod
    def _priority_score(tags: set[str], priorities: frozenset[str]) -> float:
        wanted = {
            "healthy": bool(tags & _HEALTHY_TAGS),
            "quick": "Quick" in tags,
            "kid-friendly": "Kid-friendly" in tags,
            "batch-cook": "Batch cook" in tags,
        }
        return sum(_PRIORITY_BONUS for p in priorities if wanted.get(p))

    @staticmethod
    def _balance_score(tags: set[str], chosen: list[recipes.Recipe]) -> float:
        veg = sum(1 for r in chosen if "Veg-led" in r.tags)
        fish = sum(1 for r in chosen if "Oily fish" in r.tags)
        score = 0.0
        if "Veg-led" in tags and veg < _VEG_GOAL:
            score += _GOAL_BONUS
        if "Oily fish" in tags and fish < _FISH_GOAL:
            score += _GOAL_BONUS
        return score

    @staticmethod
    def _day_score(
        tags: set[str],
        day: datetime.date,
        quick_days: frozenset[datetime.date],
    ) -> float:
        score = 0.0
        if day in quick_days:
            score += (
                _QUICK_DAY_BONUS if "Quick" in tags else -_QUICK_DAY_PENALTY
            )
        if "Treat night" in tags:
            score += (
                _TREAT_FRIDAY_BONUS
                if day.weekday() == _FRIDAY
                else -_TREAT_OTHER_PENALTY
            )
        if "Batch cook" in tags:
            score += (
                _BATCH_WEEKEND_BONUS
                if day.weekday() in _WEEKEND
                else -_BATCH_WEEKDAY_PENALTY
            )
        return score
