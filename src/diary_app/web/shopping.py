"""The Shopping page: the generated list, and the pantry beside it.

Every action is a plain form post that answers with a 303 redirect, so the
page works without the script. With the script (``app.js``), a form marked
``data-swap="shopping-main"`` is posted in the background with
``_fragment=1`` and answered with just the part of the page that changed
(``/shopping/fragment``), so the iPad does not repaint the whole page.

Mistakes someone can fix (nothing ticked, a blank name, a bad amount) are
shown as a one-off note at the top of the page instead of an error page, so
they look the same whether or not the script ran.
"""

import dataclasses
import datetime
import re
import sqlite3
import urllib.parse
from fractions import Fraction
from typing import Annotated, Any

import fastapi
from fastapi import responses

from diary_app import ingredients, mealplan, pantry, shopping
from diary_app.web import common, meals

router = common.protected_router()

_FLASH_KEY = "shopping_flash"
_OPEN_ID = re.compile(r"^[a-z0-9-]{1,40}$")
_ITEM_ID = re.compile(r"^[0-9]{1,9}$")
_ROW_ACTION = re.compile(r"^([0-9]{1,9}):(minus|plus|list)$")
_FRAGMENT_FIELD = Annotated[str | None, fastapi.Form(alias="_fragment")]
_OPEN_FIELD = Annotated[str, fastapi.Form()]


def _monday(request: fastapi.Request, text: str) -> datetime.date:
    day = meals.parse_day(text) or request.app.state.today()
    return mealplan.monday_of(day)


def _page_url(monday: datetime.date) -> str:
    return f"/shopping?week={monday.isoformat()}"


def _flash(request: fastapi.Request, message: str) -> None:
    request.session[_FLASH_KEY] = message


def _after(
    fragment: str | None,
    monday: datetime.date,
    *,
    open_id: str = "",
    anchor: str = "",
) -> responses.RedirectResponse:
    """Redirects after a post: to the fragment for the script, else the page.

    Only a validated week, section id and anchor ever reach the address.
    """
    if fragment:
        return common.back_to(f"/shopping/fragment?week={monday.isoformat()}")
    url = _page_url(monday)
    if _OPEN_ID.match(open_id):
        url += f"&open={urllib.parse.quote(open_id)}"
    if anchor:
        url += f"#{anchor}"
    return common.back_to(url)


def _section_id(prefix: str, name: str) -> str:
    return f"{prefix}-{ingredients.item_key(name)}"


@dataclasses.dataclass(frozen=True)
class _DayChoice:
    day: datetime.date
    label: str
    note: str
    checked: bool


def _day_choices(
    plan: list[mealplan.PlannedDay],
    generated: tuple[datetime.date, ...],
    today: datetime.date,
) -> list[_DayChoice]:
    choices = []
    for planned in plan:
        note = (
            "no meal"
            if planned.recipe is None
            else "cooked"
            if planned.cooked
            else ""
        )
        # After generating, show what was chosen; before, from today onwards.
        wanted = planned.day in generated if generated else planned.day >= today
        choices.append(
            _DayChoice(
                planned.day,
                f"{planned.day:%a} {planned.day.day}",
                note,
                wanted and not note,
            )
        )
    return choices


def _context(
    request: fastapi.Request,
    conn: sqlite3.Connection,
    monday: datetime.date,
    open_id: str,
) -> dict[str, Any]:
    """Gathers what the page and its fragment show, so they never differ."""
    today = request.app.state.today()
    listing = shopping.get_list(conn, monday)
    stock = pantry.items(conn)
    soon = pantry.use_soon(stock, today)
    return {
        "monday": monday,
        "week": monday.isoformat(),
        "flash": request.session.pop(_FLASH_KEY, ""),
        "open_id": open_id if _OPEN_ID.match(open_id) else "",
        "listing": listing,
        "generated_label": ", ".join(
            f"{d:%a} {d.day}" for d in listing.generated_for
        ),
        "day_choices": _day_choices(
            mealplan.week(conn, monday), listing.generated_for, today
        ),
        "aisle_views": [
            {
                "name": a.name,
                "id": _section_id("aisle", a.name),
                "rows": a.items,
                "left": sum(1 for i in a.items if not i.ticked),
            }
            for a in listing.aisles
        ],
        "shelf_views": [
            {
                "name": shelf,
                "id": _section_id("shelf", shelf),
                "rows": [(i, pantry.use_by(i, today)) for i in items],
            }
            for shelf, items in pantry.by_shelf(stock)
        ],
        "soon": [(i, pantry.use_by(i, today)) for i in soon],
        "soon_meals": pantry.meals_using(conn, soon),
        "units": ingredients.UNIT_CHOICES,
        "shelves": pantry.SHELVES,
    }


@router.get("/shopping")
def show_shopping(
    request: fastapi.Request,
    conn: common.Db,
    week: str = "",
    open_id: Annotated[str, fastapi.Query(alias="open")] = "",
) -> responses.HTMLResponse:
    """Shows one week's shopping list with the pantry beside it."""
    monday = _monday(request, week)
    return common.render(
        request,
        conn,
        "shopping.html",
        prev_week=_page_url(monday - datetime.timedelta(days=7)),
        next_week=_page_url(monday + datetime.timedelta(days=7)),
        **_context(request, conn, monday, open_id),
    )


@router.get("/shopping/fragment")
def show_fragment(
    request: fastapi.Request,
    conn: common.Db,
    week: str = "",
    open_id: Annotated[str, fastapi.Query(alias="open")] = "",
) -> responses.HTMLResponse:
    """Returns just the list and pantry, so a form can swap them in place."""
    monday = _monday(request, week)
    return common.render_fragment(
        request,
        "_shopping_main.html",
        **_context(request, conn, monday, open_id),
    )


@router.get("/shopping/text")
def show_text(
    request: fastapi.Request, conn: common.Db, week: str = ""
) -> responses.HTMLResponse:
    """Shows the list as plain text in a box, for copying into an order."""
    monday = _monday(request, week)
    return common.render(
        request,
        conn,
        "shopping_text.html",
        week=monday.isoformat(),
        back=_page_url(monday),
        text=shopping.as_text(shopping.get_list(conn, monday)),
    )


# --- the list ---------------------------------------------------------------


@router.post("/shopping/generate")
def submit_generate(
    request: fastapi.Request,
    conn: common.Db,
    week: common.FormText = "",
    days: common.FormList = None,
    fragment: _FRAGMENT_FIELD = None,
) -> responses.RedirectResponse:
    """Works out the list for the ticked days."""
    monday = _monday(request, week)
    chosen = [d for text in days or [] if (d := meals.parse_day(text))]
    try:
        shopping.generate(conn, monday, chosen)
    except ValueError as exc:
        _flash(request, str(exc))
    return _after(fragment, monday)


@router.post("/shopping/tick")
def submit_tick(  # noqa: PLR0913, PLR0917
    request: fastapi.Request,
    conn: common.Db,
    week: common.FormText = "",
    item: common.FormText = "",
    open_id: Annotated[str, fastapi.Form(alias="open")] = "",
    fragment: _FRAGMENT_FIELD = None,
) -> responses.RedirectResponse:
    """Ticks an item, or unticks it."""
    monday = _monday(request, week)
    if not _ITEM_ID.match(item):
        _flash(request, "That item is no longer on the list.")
        return _after(fragment, monday)
    try:
        shopping.toggle(conn, int(item))
    except LookupError:
        _flash(request, "That item is no longer on the list.")
        return _after(fragment, monday)
    return _after(fragment, monday, open_id=open_id, anchor=f"item-{item}")


@router.post("/shopping/extras")
def submit_add_extra(  # noqa: PLR0913, PLR0917
    request: fastapi.Request,
    conn: common.Db,
    week: common.FormText = "",
    text: common.FormText = "",
    amount: common.FormText = "",
    unit: common.FormText = "items",
    fragment: _FRAGMENT_FIELD = None,
) -> responses.RedirectResponse:
    """Adds an item of your own to the list."""
    monday = _monday(request, week)
    try:
        wanted = (
            ingredients.parse_amount(amount, unit) if amount.strip() else None
        )
        added = shopping.add_extra(conn, monday, text, wanted)
    except ValueError as exc:
        _flash(request, str(exc))
    else:
        _flash(request, f"Added {added.name} to the list.")
    return _after(fragment, monday, anchor="your-items")


@router.post("/shopping/extras/remove")
def submit_remove_extra(
    conn: common.Db,
    request: fastapi.Request,
    week: common.FormText = "",
    item: common.FormText = "",
    fragment: _FRAGMENT_FIELD = None,
) -> responses.RedirectResponse:
    """Removes an item of your own from the list."""
    if _ITEM_ID.match(item):
        shopping.remove_extra(conn, int(item))
    return _after(fragment, _monday(request, week), anchor="your-items")


@router.post("/shopping/done")
def submit_done(
    request: fastapi.Request,
    conn: common.Db,
    week: common.FormText = "",
    fragment: _FRAGMENT_FIELD = None,
) -> responses.RedirectResponse:
    """Moves everything ticked into the pantry."""
    monday = _monday(request, week)
    moved = shopping.done_shopping(conn, monday)
    if moved:
        what = "item" if moved == 1 else "items"
        _flash(request, f"Added {moved} {what} to the pantry.")
    else:
        _flash(request, "Nothing is ticked yet.")
    return _after(fragment, monday, anchor="pantry")


def _row_or_404(
    conn: sqlite3.Connection, item_id: int
) -> shopping.ShoppingItem:
    try:
        return shopping.get_item(conn, item_id)
    except LookupError as exc:
        raise fastapi.HTTPException(status_code=404) from exc


@router.get("/shopping/item/{item_id}/edit")
def show_edit_item(
    request: fastapi.Request,
    conn: common.Db,
    item_id: int,
    week: str = "",
) -> responses.HTMLResponse:
    """Shows a list row's name and amount to correct."""
    item = _row_or_404(conn, item_id)
    monday = _monday(request, week)
    return common.render(
        request,
        conn,
        "shopping_item_form.html",
        item=item,
        week=monday.isoformat(),
        back=_page_url(monday) + f"#item-{item_id}",
        amount_text=_number_text(item.amount.value) if item.amount else "",
        unit=(item.amount.unit if item.amount else "") or "items",
        units=ingredients.UNIT_CHOICES,
    )


@router.post("/shopping/item/{item_id}", response_model=None)
def submit_edit_item(  # noqa: PLR0913, PLR0917
    request: fastapi.Request,
    conn: common.Db,
    item_id: int,
    week: common.FormText = "",
    name: common.FormText = "",
    amount: common.FormText = "",
    unit: common.FormText = "items",
) -> responses.Response:
    """Saves a corrected name and amount, then returns to that row."""
    item = _row_or_404(conn, item_id)
    monday = _monday(request, week)
    try:
        wanted = (
            ingredients.parse_amount(amount, unit) if amount.strip() else None
        )
        saved = shopping.update_item(
            conn, dataclasses.replace(item, name=name, amount=wanted)
        )
    except ValueError as exc:
        return common.rejected(
            request,
            conn,
            str(exc),
            back=f"/shopping/item/{item_id}/edit?week={monday.isoformat()}",
        )
    open_id = (
        _section_id("aisle", saved.aisle) if saved.source == "meal" else ""
    )
    return _after(None, monday, open_id=open_id, anchor=f"item-{saved.id}")


@router.post("/shopping/item/{item_id}/delete")
def submit_delete_item(
    request: fastapi.Request,
    conn: common.Db,
    item_id: int,
    week: common.FormText = "",
) -> responses.RedirectResponse:
    """Takes a row off the list (whether made from a meal or your own)."""
    monday = _monday(request, week)
    try:
        item = shopping.get_item(conn, item_id)
    except LookupError:
        _flash(request, "That item is already gone.")
        return _after(None, monday)
    shopping.remove_item(conn, item_id)
    _flash(request, f"Removed {item.name} from the list.")
    open_id = _section_id("aisle", item.aisle) if item.source == "meal" else ""
    return _after(None, monday, open_id=open_id)


# --- the pantry -------------------------------------------------------------


def _expiry(text: str) -> datetime.date | None:
    if not text.strip():
        return None
    found = meals.parse_day(text)
    if found is None:
        msg = "Use a date like 2030-01-31."
        raise ValueError(msg)
    return found


@router.post("/pantry")
def submit_add_pantry(  # noqa: PLR0913, PLR0917
    request: fastapi.Request,
    conn: common.Db,
    week: common.FormText = "",
    name: common.FormText = "",
    amount: common.FormText = "",
    unit: common.FormText = "items",
    shelf: common.FormText = "Cupboard",
    expires_on: common.FormText = "",
    fragment: _FRAGMENT_FIELD = None,
) -> responses.RedirectResponse:
    """Puts something in the pantry."""
    monday = _monday(request, week)
    open_id = ""
    try:
        item = pantry.add(
            conn,
            name,
            ingredients.parse_amount(amount, unit),
            shelf=shelf,
            expires_on=_expiry(expires_on),
        )
    except ValueError as exc:
        _flash(request, str(exc))
    else:
        _flash(request, f"Added {item.name} to the pantry.")
        open_id = _section_id("shelf", item.shelf)
    return _after(fragment, monday, open_id=open_id, anchor="pantry")


@router.post("/pantry/row")
def submit_pantry_row(  # noqa: PLR0913, PLR0917
    request: fastapi.Request,
    conn: common.Db,
    week: common.FormText = "",
    action: common.FormText = "",
    open_id: Annotated[str, fastapi.Form(alias="open")] = "",
    fragment: _FRAGMENT_FIELD = None,
) -> responses.RedirectResponse:
    """Handles one pantry button (``<id>:minus``, ``plus`` or ``list``)."""
    monday = _monday(request, week)
    found = _ROW_ACTION.match(action)
    if found is None:
        _flash(request, "That did not work. Try again.")
        return _after(fragment, monday, anchor="pantry")
    item_id, what = int(found.group(1)), found.group(2)
    try:
        item = pantry.get(conn, item_id)
        if what == "list":
            shopping.add_extra(conn, monday, item.name)
            _flash(request, f"Added {item.name} to the list.")
        else:
            step = item.amount.step.value
            pantry.adjust(conn, item_id, step if what == "plus" else -step)
    except LookupError:
        _flash(request, "That pantry item is gone.")
    return _after(fragment, monday, open_id=open_id, anchor="pantry")


def _item_or_404(conn: sqlite3.Connection, item_id: int) -> pantry.PantryItem:
    try:
        return pantry.get(conn, item_id)
    except LookupError as exc:
        raise fastapi.HTTPException(status_code=404) from exc


def _number_text(value: Fraction) -> str:
    if value.denominator == 1:
        return str(value.numerator)
    return f"{float(value):.3f}".rstrip("0").rstrip(".")


@router.get("/pantry/{item_id}/edit")
def show_edit_pantry(
    request: fastapi.Request,
    conn: common.Db,
    item_id: int,
    week: str = "",
) -> responses.HTMLResponse:
    """Shows a pantry item's details to change or delete."""
    item = _item_or_404(conn, item_id)
    monday = _monday(request, week)
    unit = item.amount.unit or "items"
    return common.render(
        request,
        conn,
        "pantry_form.html",
        item=item,
        week=monday.isoformat(),
        back=_page_url(monday) + "#pantry",
        amount_text=_number_text(item.amount.value),
        unit=unit,
        units=[*ingredients.UNIT_CHOICES]
        + ([] if unit in ingredients.UNIT_CHOICES else [unit]),
        shelves=pantry.SHELVES,
        expires_on=item.expires_on.isoformat() if item.expires_on else "",
    )


@router.post("/pantry/{item_id}", response_model=None)
def submit_edit_pantry(  # noqa: PLR0913, PLR0917
    request: fastapi.Request,
    conn: common.Db,
    item_id: int,
    week: common.FormText = "",
    name: common.FormText = "",
    amount: common.FormText = "",
    unit: common.FormText = "items",
    shelf: common.FormText = "Cupboard",
    expires_on: common.FormText = "",
) -> responses.Response:
    """Saves changes to a pantry item."""
    item = _item_or_404(conn, item_id)
    monday = _monday(request, week)
    try:
        pantry.update(
            conn,
            dataclasses.replace(
                item,
                name=name,
                amount=ingredients.parse_amount(amount, unit),
                shelf=shelf,
                expires_on=_expiry(expires_on),
            ),
        )
    except ValueError as exc:
        return common.rejected(
            request,
            conn,
            str(exc),
            back=f"/pantry/{item_id}/edit?week={monday.isoformat()}",
        )
    return _after(None, monday, anchor="pantry")


@router.post("/pantry/{item_id}/delete")
def submit_delete_pantry(
    request: fastapi.Request,
    conn: common.Db,
    item_id: int,
    week: common.FormText = "",
) -> responses.RedirectResponse:
    """Removes something from the pantry."""
    pantry.delete(conn, item_id)
    return _after(None, _monday(request, week), anchor="pantry")
