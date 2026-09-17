-- Draft for review. This is not a production migration or booking engine.
-- SQLite 3.37+ is required for STRICT tables.
-- IDs are supplied by the caller as text; an ID format has not been selected.
-- Timestamps use whole Unix seconds (UTC) for this draft.
-- Every connection must enable foreign keys, before starting a transaction.
PRAGMA foreign_keys = ON;

BEGIN;

CREATE TABLE staff (
    id TEXT PRIMARY KEY,
    staff_code TEXT NOT NULL UNIQUE,
    first_name TEXT NOT NULL,
    last_name TEXT NOT NULL,
    title TEXT
) STRICT;

-- Returning guests can be referenced by more than one booking.
-- This minimal guest record supports the primary guest reference below.
CREATE TABLE guests (
    id TEXT PRIMARY KEY,
    first_name TEXT NOT NULL,
    last_name TEXT NOT NULL,
    age INTEGER NOT NULL CHECK (age >= 0)
) STRICT;

CREATE TABLE bookings (
    id TEXT PRIMARY KEY,
    party_name TEXT NOT NULL,
    created_at INTEGER NOT NULL DEFAULT (CAST(strftime('%s', 'now') AS INTEGER)),
    -- Proposed labels only; allowed transitions have not been defined.
    -- The suggested numeric codes (settled = 3, cancelled = 4) remain in the notes.
    status TEXT NOT NULL DEFAULT 'in_progress' CHECK (status IN (
        'in_progress',
        'awaiting_confirmation',
        'awaiting_payment',
        'settled',
        'cancelled',
        'completed',
        'error',
        'under_review'
    )),
    primary_guest_id TEXT NOT NULL REFERENCES guests(id)
) STRICT;

CREATE TRIGGER bookings_keep_creation_time
BEFORE UPDATE OF created_at ON bookings
WHEN NEW.created_at != OLD.created_at
BEGIN
    SELECT RAISE(ABORT, 'Booking creation time cannot change');
END;

CREATE TABLE rooms (
    id TEXT PRIMARY KEY,
    -- Text permits room labels such as 012 or 12A.
    room_number TEXT NOT NULL UNIQUE,
    description TEXT NOT NULL,
    number_of_beds INTEGER NOT NULL CHECK (number_of_beds >= 0),
    number_of_bathrooms INTEGER NOT NULL CHECK (number_of_bathrooms >= 0),
    category TEXT NOT NULL CHECK (category IN ('twin', 'master', 'presidential'))
) STRICT;

-- One logical reservation has a stable id and one or more numbered revisions.
-- Each row is a complete snapshot, not a patch to apply to the previous row.
-- Add a revision to extend the stay or change its status.
CREATE TABLE room_reservations (
    id TEXT NOT NULL,
    revision INTEGER NOT NULL CHECK (revision >= 1),
    booking_id TEXT NOT NULL REFERENCES bookings(id),
    room_id TEXT NOT NULL REFERENCES rooms(id),
    check_in_at INTEGER NOT NULL,
    check_out_at INTEGER NOT NULL,
    -- The status list is still open. Only a non-empty label is enforced here.
    status TEXT NOT NULL CHECK (length(trim(status)) > 0),
    recorded_at INTEGER NOT NULL DEFAULT (CAST(strftime('%s', 'now') AS INTEGER)),
    PRIMARY KEY (id, revision),
    CHECK (check_out_at > check_in_at)
) STRICT;

-- Revisions start at 1 and advance by 1. This also rejects INSERT OR REPLACE
-- attempts against an existing revision, preserving that historical row.
CREATE TRIGGER room_reservations_next_revision
BEFORE INSERT ON room_reservations
WHEN NEW.revision != (
    SELECT COALESCE(MAX(revision), 0) + 1
    FROM room_reservations
    WHERE id = NEW.id
)
BEGIN
    SELECT RAISE(ABORT, 'Expected the next room reservation revision');
END;

-- A revision belongs to the same booking and room as its original reservation.
-- Reserving a different room creates a new reservation id.
CREATE TRIGGER room_reservations_keep_identity
BEFORE INSERT ON room_reservations
WHEN EXISTS (
    SELECT 1
    FROM room_reservations
    WHERE id = NEW.id
      AND (booking_id != NEW.booking_id OR room_id != NEW.room_id)
)
BEGIN
    SELECT RAISE(ABORT, 'A room reservation must keep its booking and room');
END;

CREATE TRIGGER room_reservations_no_update
BEFORE UPDATE ON room_reservations
BEGIN
    SELECT RAISE(ABORT, 'Room reservation revisions cannot be changed');
END;

CREATE TRIGGER room_reservations_no_delete
BEFORE DELETE ON room_reservations
BEGIN
    SELECT RAISE(ABORT, 'Room reservation revisions cannot be deleted');
END;

CREATE VIEW current_room_reservations AS
SELECT reservation.*
FROM room_reservations AS reservation
WHERE NOT EXISTS (
    SELECT 1
    FROM room_reservations AS newer
    WHERE newer.id = reservation.id
      AND newer.revision > reservation.revision
);

-- Still to design: room overlap checks, booking transitions, party membership,
-- price records and their reservation references, keys, and the arrival logbook.
-- No guest-to-room assignments or internal payment lifecycle are defined.

COMMIT;
