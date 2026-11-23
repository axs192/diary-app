-- Family members. Adults and children are added in Settings; "Family" stands
-- for everyone and is created up front.
CREATE TABLE person (
    id               INTEGER PRIMARY KEY,
    name             TEXT NOT NULL,
    role             TEXT NOT NULL CHECK (role IN ('Adult', 'Child', 'Everyone')),
    colour           TEXT NOT NULL,
    outlook_category TEXT NOT NULL DEFAULT ''
);

INSERT INTO person (name, role, colour, outlook_category)
VALUES ('Family', 'Everyone', '#8A5A00', 'Family');
