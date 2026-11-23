-- Key/value application settings (app colour, kiosk options, feature toggles).
CREATE TABLE setting (
    key   TEXT PRIMARY KEY,
    value TEXT NOT NULL
);
