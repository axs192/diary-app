-- The Outlook calendars the account can see (learnt by each sync) and which
-- of them the diary shows. Nothing is shown until a calendar is chosen.
CREATE TABLE calendar_source (
    graph_id TEXT PRIMARY KEY,
    name     TEXT NOT NULL,
    selected INTEGER NOT NULL DEFAULT 0 CHECK (selected IN (0, 1))
);

-- Events copied from the chosen calendars. The title is stored exactly as
-- written in Outlook ("Mum : Swimming"); who it is for is worked out when it
-- is read, so renaming a person applies at once. Times are local, as
-- ISO-8601 text without a zone; an all-day event runs midnight to midnight
-- (the end is exclusive). Recurring events are stored one row per occurrence.
CREATE TABLE event (
    calendar_id TEXT NOT NULL
                REFERENCES calendar_source (graph_id) ON DELETE CASCADE,
    id          TEXT NOT NULL,
    title       TEXT NOT NULL,
    starts_at   TEXT NOT NULL,
    ends_at     TEXT NOT NULL,
    all_day     INTEGER NOT NULL CHECK (all_day IN (0, 1)),
    PRIMARY KEY (calendar_id, id)
);
CREATE INDEX event_starts_at ON event (starts_at);
