"""The household's meal library: recipes, tags and favourites.

``RecipeDraft`` is the one shape for recipe details going in (typed by hand,
or read from a web page by ``recipe_import``). ``Recipe`` is what comes out:
the same details plus the database id and favourite flag.
"""

import dataclasses
import sqlite3
from collections.abc import Collection, Sequence

STYLES = (
    "Italian",
    "Mexican",
    "Indian",
    "Asian",
    "Mediterranean",
    "British",
    "Other",
)
TAGS = (
    "Oily fish",
    "Veg-led",
    "Lean protein",
    "Wholegrain",
    "Treat night",
    "Batch cook",
    "Quick",
    "Kid-friendly",
)
_MAX_NAME_LENGTH = 100
_MAX_MINS = 24 * 60
_MAX_URL_LENGTH = 500
_CLEAR_LISTS = (
    "DELETE FROM recipe_ingredient WHERE recipe_id = ?",
    "DELETE FROM recipe_step WHERE recipe_id = ?",
    "DELETE FROM recipe_tag WHERE recipe_id = ?",
)


class InvalidRecipeError(ValueError):
    """Raised when a recipe's details are not acceptable."""


@dataclasses.dataclass(frozen=True)
class RecipeDraft:
    """Recipe details, before they are stored.

    Attributes:
        name: Meal name.
        style: One of ``STYLES``.
        mins: Total minutes, 1 to 1440.
        servings: How many people it feeds.
        ingredients: One entry per ingredient line.
        steps: One entry per method step.
        tags: Entries from ``TAGS``.
        source_url: Web address the recipe came from (http or https), or "".
        source_name: Site name to credit, such as "BBC Good Food", or "".
    """

    name: str
    style: str = "Other"
    mins: int = 30
    servings: int = 4
    ingredients: Sequence[str] = ()
    steps: Sequence[str] = ()
    tags: Sequence[str] = ()
    source_url: str = ""
    source_name: str = ""


@dataclasses.dataclass(frozen=True)
class Recipe:
    """A stored recipe (see ``RecipeDraft`` for the shared fields).

    Attributes:
        id: Database id.
        is_favourite: Whether the household has hearted it.
    """

    id: int
    name: str
    style: str
    mins: int
    servings: int
    ingredients: tuple[str, ...]
    steps: tuple[str, ...]
    tags: tuple[str, ...]
    source_url: str
    source_name: str
    is_favourite: bool


def add(conn: sqlite3.Connection, draft: RecipeDraft) -> Recipe:
    """Stores a new recipe.

    Args:
        conn: Open database connection.
        draft: Details to store. Text is trimmed, blank lines dropped and
            repeated tags merged.

    Returns:
        The stored recipe.

    Raises:
        InvalidRecipeError: If any detail is not acceptable; nothing is
            stored.
    """
    clean = _validate(draft)
    conn.execute("BEGIN")
    try:
        cursor = conn.execute(
            "INSERT INTO recipe"
            " (name, style, mins, servings, source_url, source_name)"
            " VALUES (?, ?, ?, ?, ?, ?)",
            (
                clean.name,
                clean.style,
                clean.mins,
                clean.servings,
                clean.source_url,
                clean.source_name,
            ),
        )
        recipe_id = int(cursor.lastrowid or 0)
        _write_lists(conn, recipe_id, clean)
        conn.execute("COMMIT")
    except sqlite3.Error:
        conn.execute("ROLLBACK")
        raise
    return get(conn, recipe_id)


def update(
    conn: sqlite3.Connection, recipe_id: int, draft: RecipeDraft
) -> Recipe:
    """Replaces a recipe's details, keeping its id and favourite flag.

    Args:
        conn: Open database connection.
        recipe_id: Recipe to change.
        draft: The new details.

    Returns:
        The updated recipe.

    Raises:
        InvalidRecipeError: If any detail is not acceptable; nothing changes.
        LookupError: If no such recipe exists.
    """
    get(conn, recipe_id)
    clean = _validate(draft)
    conn.execute("BEGIN")
    try:
        conn.execute(
            "UPDATE recipe SET name = ?, style = ?, mins = ?, servings = ?,"
            " source_url = ?, source_name = ? WHERE id = ?",
            (
                clean.name,
                clean.style,
                clean.mins,
                clean.servings,
                clean.source_url,
                clean.source_name,
                recipe_id,
            ),
        )
        for statement in _CLEAR_LISTS:
            conn.execute(statement, (recipe_id,))
        _write_lists(conn, recipe_id, clean)
        conn.execute("COMMIT")
    except sqlite3.Error:
        conn.execute("ROLLBACK")
        raise
    return get(conn, recipe_id)


def delete(conn: sqlite3.Connection, recipe_id: int) -> None:
    """Deletes a recipe, and removes it from any planned day.

    Args:
        conn: Open database connection.
        recipe_id: Recipe to delete; an unknown id is ignored.
    """
    conn.execute("DELETE FROM recipe WHERE id = ?", (recipe_id,))


def get(conn: sqlite3.Connection, recipe_id: int) -> Recipe:
    """Reads one recipe.

    Args:
        conn: Open database connection.
        recipe_id: Recipe to read.

    Returns:
        The recipe.

    Raises:
        LookupError: If no such recipe exists.
    """
    found = _load(conn, "WHERE id = ?", (recipe_id,))
    if not found:
        msg = f"No recipe with id {recipe_id}"
        raise LookupError(msg)
    return found[0]


def get_many(
    conn: sqlite3.Connection, recipe_ids: Collection[int]
) -> dict[int, Recipe]:
    """Reads several recipes at once.

    Args:
        conn: Open database connection.
        recipe_ids: Ids to read; unknown ids are skipped.

    Returns:
        The recipes found, keyed by id.
    """
    if not recipe_ids:
        return {}
    marks = ", ".join("?" * len(recipe_ids))
    found = _load(conn, f"WHERE id IN ({marks})", tuple(recipe_ids))
    return {recipe.id: recipe for recipe in found}


def set_favourite(
    conn: sqlite3.Connection, recipe_id: int, *, is_favourite: bool
) -> None:
    """Hearts or un-hearts a recipe.

    Args:
        conn: Open database connection.
        recipe_id: Recipe to change.
        is_favourite: The new state.

    Raises:
        LookupError: If no such recipe exists.
    """
    cursor = conn.execute(
        "UPDATE recipe SET is_favourite = ? WHERE id = ?",
        (int(is_favourite), recipe_id),
    )
    if cursor.rowcount == 0:
        msg = f"No recipe with id {recipe_id}"
        raise LookupError(msg)


def search(
    conn: sqlite3.Connection,
    *,
    style: str | None = None,
    tag: str | None = None,
    favourites_only: bool = False,
    exclude_ids: Sequence[int] = (),
) -> list[Recipe]:
    """Finds recipes. Every filter given must match.

    Args:
        conn: Open database connection.
        style: Only this style.
        tag: Only recipes carrying this tag.
        favourites_only: Only hearted recipes.
        exclude_ids: Recipe ids to leave out.

    Returns:
        Matching recipes, ordered by name.
    """
    clauses: list[str] = []
    params: list[object] = []
    if style is not None:
        clauses.append("style = ?")
        params.append(style)
    if tag is not None:
        clauses.append("id IN (SELECT recipe_id FROM recipe_tag WHERE tag = ?)")
        params.append(tag)
    if favourites_only:
        clauses.append("is_favourite = 1")
    if exclude_ids:
        marks = ", ".join("?" * len(exclude_ids))
        clauses.append(f"id NOT IN ({marks})")
        params.extend(exclude_ids)
    where = f"WHERE {' AND '.join(clauses)}" if clauses else ""
    return _load(conn, where, tuple(params))


def _validate(draft: RecipeDraft) -> RecipeDraft:
    name = draft.name.strip()
    if not name:
        msg = "Give the meal a name."
        raise InvalidRecipeError(msg)
    if len(name) > _MAX_NAME_LENGTH:
        msg = f"Names must be {_MAX_NAME_LENGTH} characters or fewer."
        raise InvalidRecipeError(msg)
    if draft.style not in STYLES:
        msg = "Pick one of the offered styles."
        raise InvalidRecipeError(msg)
    unknown = [t for t in draft.tags if t not in TAGS]
    if unknown:
        msg = "Pick tags from the offered list."
        raise InvalidRecipeError(msg)
    if not 1 <= draft.mins <= _MAX_MINS:
        msg = f"Minutes must be between 1 and {_MAX_MINS}."
        raise InvalidRecipeError(msg)
    if draft.servings < 1:
        msg = "Servings must be at least 1."
        raise InvalidRecipeError(msg)
    source_url = draft.source_url.strip()
    if source_url and (
        not source_url.startswith(("http://", "https://"))
        or len(source_url) > _MAX_URL_LENGTH
    ):
        msg = "The source must be a web address starting http:// or https://."
        raise InvalidRecipeError(msg)
    return dataclasses.replace(
        draft,
        name=name,
        ingredients=_clean_lines(draft.ingredients),
        steps=_clean_lines(draft.steps),
        tags=tuple(dict.fromkeys(draft.tags)),
        source_url=source_url,
        source_name=draft.source_name.strip(),
    )


def _clean_lines(lines: Sequence[str]) -> tuple[str, ...]:
    return tuple(line.strip() for line in lines if line.strip())


def _write_lists(
    conn: sqlite3.Connection, recipe_id: int, draft: RecipeDraft
) -> None:
    conn.executemany(
        "INSERT INTO recipe_ingredient (recipe_id, position, text)"
        " VALUES (?, ?, ?)",
        [(recipe_id, i, line) for i, line in enumerate(draft.ingredients)],
    )
    conn.executemany(
        "INSERT INTO recipe_step (recipe_id, position, text) VALUES (?, ?, ?)",
        [(recipe_id, i, line) for i, line in enumerate(draft.steps)],
    )
    conn.executemany(
        "INSERT INTO recipe_tag (recipe_id, tag) VALUES (?, ?)",
        [(recipe_id, tag) for tag in draft.tags],
    )


def _load(
    conn: sqlite3.Connection, where: str, params: tuple[object, ...]
) -> list[Recipe]:
    # `where` is assembled from fixed fragments and `?` marks only.
    query = (
        "SELECT id, name, style, mins, servings,"  # nosec B608  # noqa: S608
        " source_url, source_name, is_favourite"
        f" FROM recipe {where}"
        " ORDER BY name COLLATE NOCASE, id"
    )
    rows = conn.execute(query, params).fetchall()
    ids = [row["id"] for row in rows]
    lists = {
        table: _grouped(conn, table, column, ids)
        for table, column in (
            ("recipe_ingredient", "text"),
            ("recipe_step", "text"),
            ("recipe_tag", "tag"),
        )
    }
    return [
        Recipe(
            id=row["id"],
            name=row["name"],
            style=row["style"],
            mins=row["mins"],
            servings=row["servings"],
            ingredients=lists["recipe_ingredient"].get(row["id"], ()),
            steps=lists["recipe_step"].get(row["id"], ()),
            tags=lists["recipe_tag"].get(row["id"], ()),
            source_url=row["source_url"],
            source_name=row["source_name"],
            is_favourite=bool(row["is_favourite"]),
        )
        for row in rows
    ]


def _grouped(
    conn: sqlite3.Connection, table: str, column: str, ids: list[int]
) -> dict[int, tuple[str, ...]]:
    """Reads one child table for many recipes, in stored order."""
    if not ids:
        return {}
    marks = ", ".join("?" * len(ids))
    order = "position" if table != "recipe_tag" else "rowid"
    # `table`, `column` and `order` are fixed names from `_load`, never input.
    query = (
        f"SELECT recipe_id, {column} AS value"  # nosec B608  # noqa: S608
        f" FROM {table}"
        f" WHERE recipe_id IN ({marks}) ORDER BY {order}"
    )
    rows = conn.execute(query, ids)
    grouped: dict[int, list[str]] = {}
    for row in rows:
        grouped.setdefault(row["recipe_id"], []).append(row["value"])
    return {key: tuple(values) for key, values in grouped.items()}
