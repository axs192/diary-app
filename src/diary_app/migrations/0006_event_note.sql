-- Outlook's plain-text preview of an event's body (what the family wrote in
-- the notes box), shown on the event page. Empty when there is none.
ALTER TABLE event ADD COLUMN note TEXT NOT NULL DEFAULT '';
