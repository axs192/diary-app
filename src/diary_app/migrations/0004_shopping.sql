-- The pantry, the generated shopping list, and "cooked it" bookkeeping.

-- What is in the cupboard. `amount` is an exact fraction ("3/2") in the base
-- unit `unit` (g, ml, a count, or a counted unit such as tin); see ingredients.py.
CREATE TABLE pantry_item (
    id         INTEGER PRIMARY KEY,
    name       TEXT NOT NULL,
    shelf      TEXT NOT NULL
               CHECK (shelf IN ('Fridge', 'Cupboard', 'Freezer', 'Spices', 'Baking')),
    unit       TEXT NOT NULL,
    amount     TEXT NOT NULL,
    expires_on TEXT
);

-- One week's list. Rows made from meals are replaced each time the list is
-- generated; rows the household added (source 'extra') are kept. `amount`
-- is what is still to buy (NULL for a line that could not be read), `have`
-- a note of what the pantry holds, and `covered` rows are not to be bought.
CREATE TABLE shopping_item (
    id      INTEGER PRIMARY KEY,
    week    TEXT NOT NULL,
    source  TEXT NOT NULL CHECK (source IN ('meal', 'extra')),
    name    TEXT NOT NULL,
    aisle   TEXT NOT NULL,
    unit    TEXT NOT NULL DEFAULT '',
    amount  TEXT,
    have    TEXT NOT NULL DEFAULT '',
    covered INTEGER NOT NULL DEFAULT 0 CHECK (covered IN (0, 1)),
    ticked  INTEGER NOT NULL DEFAULT 0 CHECK (ticked IN (0, 1))
);
CREATE INDEX shopping_item_week ON shopping_item (week);

-- Which days the week's list was last generated for (comma-separated ISO dates).
CREATE TABLE shopping_generation (
    week TEXT PRIMARY KEY,
    days TEXT NOT NULL
);

-- A dinner marked as cooked, and exactly what that took out of the pantry,
-- so Undo can put it back.
CREATE TABLE cooked_day (
    day TEXT PRIMARY KEY REFERENCES meal_plan (day) ON DELETE CASCADE
);
CREATE TABLE cooked_deduction (
    day       TEXT NOT NULL REFERENCES cooked_day (day) ON DELETE CASCADE,
    pantry_id INTEGER NOT NULL REFERENCES pantry_item (id) ON DELETE CASCADE,
    amount    TEXT NOT NULL,
    PRIMARY KEY (day, pantry_id)
);
