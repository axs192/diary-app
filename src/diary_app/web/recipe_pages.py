"""Recipe pages: view, add, edit, delete, import from a web address."""

import datetime
import sqlite3
from typing import Annotated

import fastapi
import httpx
from fastapi import responses

from diary_app import mealplan, recipe_import, recipes
from diary_app.web import common, meals

router = common.protected_router()

_UPCOMING_DAYS = 14


def _to_int(text: str) -> int:
    """Reads a whole number from form text; 0 (always rejected) if not."""
    try:
        return int(text.strip())
    except ValueError:
        return 0


def _form_draft(  # noqa: PLR0913
    *,
    name: common.FormText = "",
    style: common.FormText = "Other",
    mins: common.FormText = "",
    servings: common.FormText = "4",
    ingredients: common.FormText = "",
    steps: common.FormText = "",
    tags: common.FormList = None,
    source_url: common.FormText = "",
    source_name: common.FormText = "",
) -> recipes.RecipeDraft:
    return recipes.RecipeDraft(
        name=name,
        style=style,
        mins=_to_int(mins),
        servings=_to_int(servings),
        ingredients=ingredients.splitlines(),
        steps=steps.splitlines(),
        tags=tuple(tags or ()),
        source_url=source_url,
        source_name=source_name,
    )


FormDraft = Annotated[recipes.RecipeDraft, fastapi.Depends(_form_draft)]


def _form_page(  # noqa: PLR0913
    request: fastapi.Request,
    conn: sqlite3.Connection,
    *,
    draft: recipes.RecipeDraft,
    action: str,
    heading: str,
    cancel: str,
    error: str = "",
    notice: str = "",
    status_code: int = 200,
) -> responses.HTMLResponse:
    return common.render(
        request,
        conn,
        "recipe_form.html",
        status_code=status_code,
        draft=draft,
        action=action,
        heading=heading,
        cancel=cancel,
        error=error,
        notice=notice,
        styles=recipes.STYLES,
        tags=recipes.TAGS,
    )


def _http_client(request: fastapi.Request) -> httpx.Client:
    if request.app.state.http_client is None:
        request.app.state.http_client = httpx.Client()
    client: httpx.Client = request.app.state.http_client
    return client


@router.get("/recipes/new")
def show_new_recipe(
    request: fastapi.Request, conn: common.Db
) -> responses.HTMLResponse:
    """Shows an empty form for a meal of your own."""
    return _form_page(
        request,
        conn,
        draft=recipes.RecipeDraft(name=""),
        action="/recipes",
        heading="Add your own meal",
        cancel="/meals",
    )


@router.get("/recipes/import")
def show_import(
    request: fastapi.Request, conn: common.Db
) -> responses.HTMLResponse:
    """Shows the form asking for a recipe's web address."""
    return common.render(
        request,
        conn,
        "import.html",
        url="",
        error="",
        sites=sorted(recipe_import.ALLOWED_HOSTS),
    )


@router.post("/recipes/import")
def submit_import(
    request: fastapi.Request, conn: common.Db, url: common.FormText = ""
) -> responses.HTMLResponse:
    """Reads a recipe from a web page into the form, for review (not saved)."""
    if not url.strip():
        return common.render(
            request,
            conn,
            "import.html",
            status_code=400,
            url=url,
            sites=sorted(recipe_import.ALLOWED_HOSTS),
            error="Paste the web address of a recipe page.",
        )
    try:
        draft = recipe_import.fetch_draft(
            url, _http_client(request), request.app.state.resolve
        )
    except recipe_import.RecipeImportError as exc:
        return common.render(
            request,
            conn,
            "import.html",
            status_code=400,
            url=url,
            sites=sorted(recipe_import.ALLOWED_HOSTS),
            error=str(exc),
        )
    return _form_page(
        request,
        conn,
        draft=draft,
        action="/recipes",
        heading="Check the imported meal",
        cancel="/meals",
        notice="Nothing is saved yet. Check the details, then press Save.",
    )


@router.post("/recipes", response_model=None)
def submit_new_recipe(
    request: fastapi.Request, conn: common.Db, draft: FormDraft
) -> responses.Response:
    """Saves a new meal."""
    try:
        added = recipes.add(conn, draft)
    except recipes.InvalidRecipeError as exc:
        return _form_page(
            request,
            conn,
            draft=draft,
            action="/recipes",
            heading="Add your own meal",
            cancel="/meals",
            error=str(exc),
            status_code=400,
        )
    return common.back_to(f"/recipes/{added.id}")


def _draft_of(recipe: recipes.Recipe) -> recipes.RecipeDraft:
    return recipes.RecipeDraft(
        name=recipe.name,
        style=recipe.style,
        mins=recipe.mins,
        servings=recipe.servings,
        ingredients=recipe.ingredients,
        steps=recipe.steps,
        tags=recipe.tags,
        source_url=recipe.source_url,
        source_name=recipe.source_name,
    )


def _get_or_404(conn: sqlite3.Connection, recipe_id: int) -> recipes.Recipe:
    try:
        return recipes.get(conn, recipe_id)
    except LookupError as exc:
        raise fastapi.HTTPException(status_code=404) from exc


@router.get("/recipes/{recipe_id}")
def show_recipe(
    request: fastapi.Request, conn: common.Db, recipe_id: int
) -> responses.HTMLResponse:
    """Shows a recipe with its method and an "add to a day" form."""
    today = datetime.date.today()
    upcoming = [
        today + datetime.timedelta(days=i) for i in range(_UPCOMING_DAYS)
    ]
    return common.render(
        request,
        conn,
        "recipe.html",
        recipe=_get_or_404(conn, recipe_id),
        upcoming=upcoming,
        here=f"/recipes/{recipe_id}",
        planned_on={
            d.day
            for d in mealplan.week(conn, today)
            + mealplan.week(conn, upcoming[-1])
            if d.recipe and d.recipe.id == recipe_id
        },
    )


@router.get("/recipes/{recipe_id}/edit")
def show_edit_recipe(
    request: fastapi.Request, conn: common.Db, recipe_id: int
) -> responses.HTMLResponse:
    """Shows the form filled with a recipe's details."""
    recipe = _get_or_404(conn, recipe_id)
    return _form_page(
        request,
        conn,
        draft=_draft_of(recipe),
        action=f"/recipes/{recipe_id}",
        heading=f"Edit {recipe.name}",
        cancel=f"/recipes/{recipe_id}",
    )


@router.post("/recipes/{recipe_id}", response_model=None)
def submit_edit_recipe(
    request: fastapi.Request,
    conn: common.Db,
    recipe_id: int,
    draft: FormDraft,
) -> responses.Response:
    """Saves changes to a recipe."""
    try:
        recipes.update(conn, recipe_id, draft)
    except LookupError as exc:
        raise fastapi.HTTPException(status_code=404) from exc
    except recipes.InvalidRecipeError as exc:
        return _form_page(
            request,
            conn,
            draft=draft,
            action=f"/recipes/{recipe_id}",
            heading="Edit meal",
            cancel=f"/recipes/{recipe_id}",
            error=str(exc),
            status_code=400,
        )
    return common.back_to(f"/recipes/{recipe_id}")


@router.post("/recipes/{recipe_id}/delete")
def submit_delete_recipe(
    conn: common.Db, recipe_id: int
) -> responses.RedirectResponse:
    """Deletes a recipe (and removes it from any planned day)."""
    recipes.delete(conn, recipe_id)
    return common.back_to("/meals")


@router.post("/recipes/{recipe_id}/favourite")
def submit_favourite(
    conn: common.Db,
    recipe_id: int,
    favourite: common.FormText = "1",
    back: common.FormText = "",
) -> responses.RedirectResponse:
    """Hearts (``favourite=1``) or un-hearts (``0``) a recipe."""
    try:
        recipes.set_favourite(conn, recipe_id, is_favourite=favourite == "1")
    except LookupError as exc:
        raise fastapi.HTTPException(status_code=404) from exc
    return common.back_to(meals.safe_back(back))
