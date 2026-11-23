"""The Meals page: the weekly dinner plan, the library, Suggest a week."""

import datetime
import re
import sqlite3

import fastapi
from fastapi import responses

from diary_app import db, mealplan, planner, recipes
from diary_app.web import common

router = common.protected_router()

_STYLE_KEY = "meal_style"
_PRIORITIES_KEY = "meal_priorities"
_FLASH_KEY = "flash"
_TABS = (("ideas", "Ideas"), ("favourites", "Favourites"), ("mine", "My meals"))
_PRIORITY_LABELS = (
    ("healthy", "Healthy"),
    ("quick", "Quick"),
    ("kid-friendly", "Kid-friendly"),
    ("batch-cook", "Batch-cook"),
)
_STYLES = (planner.MIXED, *recipes.STYLES)
_TAB_NAMES = {key: key for key, _label in _TABS}  # constants, not input
_BACK_RECIPE = re.compile(r"^/recipes/([0-9]{1,9})$")
_BACK_MEALS = re.compile(
    r"^/meals(?:\?week=([0-9]{4}-[0-9]{2}-[0-9]{2})"
    r"(?:&tab=(ideas|favourites|mine))?)?$"
)


def parse_day(text: str) -> datetime.date | None:
    """Reads an ISO date (YYYY-MM-DD), or None if it isn't one."""
    try:
        return datetime.date.fromisoformat(text.strip())
    except ValueError:
        return None


def safe_back(back: str, default: str = "/meals") -> str:
    """Turns a "return to" value from a form into one of our own pages.

    The address is rebuilt from validated parts (a recipe number, a real
    date, a known tab name), so the submitted text itself is never used as
    a redirect target.

    Args:
        back: The submitted value, e.g. ``/meals?week=2030-01-07&tab=ideas``
            or ``/recipes/12``.
        default: Used when ``back`` isn't one of those shapes.

    Returns:
        A path on this site.
    """
    recipe = _BACK_RECIPE.match(back)
    if recipe:
        return f"/recipes/{int(recipe.group(1))}"
    meals_page = _BACK_MEALS.match(back)
    if not meals_page:
        return default
    url = "/meals"
    week = parse_day(meals_page.group(1) or "")
    if week is not None:
        url += f"?week={week.isoformat()}"
        tab = _TAB_NAMES.get(meals_page.group(2) or "")
        if tab:
            url += f"&tab={tab}"
    return url


def _week_of(text: str) -> datetime.date:
    day = parse_day(text) or datetime.date.today()
    return mealplan.monday_of(day)


def _chosen_priorities(conn: sqlite3.Connection) -> list[str]:
    saved = db.get_setting(conn, _PRIORITIES_KEY, "")
    return [p for p in saved.split(",") if p in planner.PRIORITIES]


def _meals_url(monday: datetime.date) -> str:
    return f"/meals?week={monday.isoformat()}"


@router.get("/meals")
def show_meals(
    request: fastapi.Request,
    conn: common.Db,
    week: str = "",
    tab: str = "ideas",
    day: str = "",
) -> responses.HTMLResponse:
    """Shows one week's plan with the meal library beside it."""
    monday = _week_of(week)
    tab = tab if tab in dict(_TABS) else "ideas"
    days = mealplan.week(conn, monday)
    planned_ids = [d.recipe.id for d in days if d.recipe]
    style = db.get_setting(conn, _STYLE_KEY, planner.MIXED)
    if tab == "favourites":
        library = recipes.search(conn, favourites_only=True)
    elif tab == "mine":
        library = recipes.search(conn)
    else:
        library = recipes.search(
            conn,
            style=None if style == planner.MIXED else style,
            exclude_ids=planned_ids,
        )
    preselected = parse_day(day)
    first_empty = next((d.day for d in days if d.recipe is None), monday)
    here = f"{_meals_url(monday)}&tab={tab}"
    return common.render(
        request,
        conn,
        "meals.html",
        monday=monday,
        days=days,
        today=datetime.date.today(),
        prev_week=_meals_url(monday - datetime.timedelta(days=7)),
        next_week=_meals_url(monday + datetime.timedelta(days=7)),
        tabs=_TABS,
        tab=tab,
        library=library,
        library_total=len(recipes.search(conn)),
        selected_day=preselected or first_empty,
        here=here,
        here_week=_meals_url(monday),
        styles=_STYLES,
        style=style,
        priority_labels=_PRIORITY_LABELS,
        priorities=_chosen_priorities(conn),
        bars=mealplan.balance(days),
        flash=request.session.pop(_FLASH_KEY, ""),
    )


@router.post("/meals/day", response_model=None)
def submit_meal_for_day(
    request: fastapi.Request,
    conn: common.Db,
    day: common.FormText = "",
    recipe_id: int = fastapi.Form(0),
) -> responses.Response:
    """Plans a recipe for a day (adding or swapping)."""
    planned_day = parse_day(day)
    if planned_day is None:
        return common.rejected(request, conn, "Pick a day.", back="/meals")
    try:
        mealplan.set_meal(conn, planned_day, recipe_id)
    except LookupError as exc:
        raise fastapi.HTTPException(status_code=404) from exc
    return common.back_to(_meals_url(mealplan.monday_of(planned_day)))


@router.post("/meals/day/remove", response_model=None)
def submit_remove_day(
    request: fastapi.Request, conn: common.Db, day: common.FormText = ""
) -> responses.Response:
    """Empties one day."""
    planned_day = parse_day(day)
    if planned_day is None:
        return common.rejected(request, conn, "Pick a day.", back="/meals")
    mealplan.clear_day(conn, planned_day)
    return common.back_to(_meals_url(mealplan.monday_of(planned_day)))


@router.post("/meals/clear")
def submit_clear_week(
    conn: common.Db, week: common.FormText = ""
) -> responses.RedirectResponse:
    """Empties every day of a week."""
    monday = _week_of(week)
    mealplan.clear_week(conn, monday)
    return common.back_to(_meals_url(monday))


@router.post("/meals/suggest", response_model=None)
def submit_suggest(
    request: fastapi.Request,
    conn: common.Db,
    week: common.FormText = "",
    style: common.FormText = planner.MIXED,
    priorities: common.FormList = None,
) -> responses.Response:
    """Saves the preferences, then fills the week's empty days."""
    chosen = list(priorities or [])
    if style not in _STYLES:
        return common.rejected(
            request, conn, "Pick one of the offered styles.", back="/meals"
        )
    if any(p not in planner.PRIORITIES for p in chosen):
        return common.rejected(
            request, conn, "Pick priorities from the list.", back="/meals"
        )
    db.set_setting(conn, _STYLE_KEY, style)
    db.set_setting(conn, _PRIORITIES_KEY, ",".join(chosen))

    monday = _week_of(week)
    days = mealplan.week(conn, monday)
    empty = [d.day for d in days if d.recipe is None]
    suggestion = request.app.state.suggester.suggest_week(
        planner.SuggestionRequest(
            days=empty,
            library=recipes.search(conn),
            style=style,
            priorities=frozenset(chosen),
            planned=[d.recipe for d in days if d.recipe],
            recent_ids=frozenset(mealplan.recent_recipe_ids(conn, monday)),
        )
    )
    for planned_day, recipe_id in suggestion.assignments.items():
        mealplan.set_meal(conn, planned_day, recipe_id)
    request.session[_FLASH_KEY] = _summary(
        len(suggestion.assignments), len(suggestion.unfilled), len(empty)
    )
    return common.back_to(_meals_url(monday))


def _summary(filled: int, unfilled: int, empty_before: int) -> str:
    if empty_before == 0:
        return "Every day already has a meal."
    more = "Add more meals to fill the week."
    if filled == 0:
        return more
    text = f"Filled {filled} day{'s' if filled != 1 else ''}."
    return f"{text} {more}" if unfilled else text
