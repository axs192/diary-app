-- The household's meal library and the dinner plan.
CREATE TABLE recipe (
    id           INTEGER PRIMARY KEY,
    name         TEXT NOT NULL,
    style        TEXT NOT NULL,
    mins         INTEGER NOT NULL,
    servings     INTEGER NOT NULL DEFAULT 4,
    source_url   TEXT NOT NULL DEFAULT '',
    source_name  TEXT NOT NULL DEFAULT '',
    is_favourite INTEGER NOT NULL DEFAULT 0 CHECK (is_favourite IN (0, 1))
);

-- Raw ingredient lines in recipe order; Phase 3 parses them for shopping.
CREATE TABLE recipe_ingredient (
    recipe_id INTEGER NOT NULL REFERENCES recipe (id) ON DELETE CASCADE,
    position  INTEGER NOT NULL,
    text      TEXT NOT NULL,
    PRIMARY KEY (recipe_id, position)
);

CREATE TABLE recipe_step (
    recipe_id INTEGER NOT NULL REFERENCES recipe (id) ON DELETE CASCADE,
    position  INTEGER NOT NULL,
    text      TEXT NOT NULL,
    PRIMARY KEY (recipe_id, position)
);

CREATE TABLE recipe_tag (
    recipe_id INTEGER NOT NULL REFERENCES recipe (id) ON DELETE CASCADE,
    tag       TEXT NOT NULL,
    PRIMARY KEY (recipe_id, tag)
);

-- One dinner per day (ISO date, YYYY-MM-DD).
CREATE TABLE meal_plan (
    day       TEXT PRIMARY KEY,
    recipe_id INTEGER NOT NULL REFERENCES recipe (id) ON DELETE CASCADE
);
