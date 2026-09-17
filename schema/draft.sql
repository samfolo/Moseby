-- Domain structure for review, not a production migration or booking engine.
-- Read schema/README.md for provisional choices and deliberately deferred models.
-- No CREATE INDEX statements or performance tuning in this pass.
-- Primary/unique keys may create SQLite's own constraint indexes.
-- IDs are caller-supplied text; timestamp storage remains Unix seconds in UTC.
PRAGMA foreign_keys = ON;
BEGIN;

CREATE TABLE hotels (
    id TEXT PRIMARY KEY,
    name TEXT NOT NULL,
    address_line_1 TEXT,
    address_line_2 TEXT,
    city TEXT,
    postcode TEXT,
    country_code TEXT
) STRICT;

CREATE TABLE hotel_staff_members (
    id TEXT PRIMARY KEY,
    hotel_id TEXT NOT NULL REFERENCES hotels(id),
    staff_code TEXT NOT NULL,
    first_name TEXT NOT NULL CHECK (length(first_name) <= 2048),
    last_name TEXT NOT NULL CHECK (length(last_name) <= 2048),
    title TEXT,
    role TEXT NOT NULL DEFAULT 'concierge'
) STRICT;

-- A shared rate has a stable identity. Amounts live on immutable versions.
CREATE TABLE prices (
    id TEXT PRIMARY KEY,
    created_at INTEGER NOT NULL DEFAULT (unixepoch())
) STRICT;

-- Minor-unit integers are a provisional representation, not a universal
-- two-decimal assumption. Currency-specific validation belongs in a later pass.
CREATE TABLE price_versions (
    price_id TEXT NOT NULL REFERENCES prices(id),
    revision INTEGER NOT NULL CHECK (revision >= 1),
    amount_minor INTEGER NOT NULL CHECK (amount_minor >= 0),
    currency TEXT NOT NULL,
    created_at INTEGER NOT NULL DEFAULT (unixepoch()),
    PRIMARY KEY (price_id, revision)
) STRICT;

CREATE TABLE rooms (
    id TEXT PRIMARY KEY,
    hotel_id TEXT NOT NULL REFERENCES hotels(id),
    room_number TEXT NOT NULL,
    description TEXT NOT NULL,
    number_of_beds INTEGER NOT NULL CHECK (number_of_beds >= 0),
    number_of_bathrooms INTEGER NOT NULL CHECK (number_of_bathrooms >= 0),
    max_occupants INTEGER NOT NULL CHECK (max_occupants > 0),
    category TEXT NOT NULL,
    tier TEXT,
    -- Exact operational labels, including cleaning, remain to be settled.
    operational_status TEXT NOT NULL CHECK (length(trim(operational_status)) > 0),
    price_id TEXT NOT NULL REFERENCES prices(id)
) STRICT;

-- Only confirmed stays get a booking record. Draft/hold structure is deferred.
CREATE TABLE bookings (
    id TEXT PRIMARY KEY,
    hotel_id TEXT NOT NULL REFERENCES hotels(id),
    name TEXT NOT NULL,
    created_at INTEGER NOT NULL DEFAULT (unixepoch())
) STRICT;

CREATE TABLE booking_revisions (
    booking_id TEXT NOT NULL REFERENCES bookings(id),
    revision INTEGER NOT NULL CHECK (revision >= 1),
    status TEXT NOT NULL CHECK (status IN (
        'confirmed', 'under_revision', 'completed', 'cancelled', 'error'
    )),
    cancellation_reason TEXT,
    recorded_at INTEGER NOT NULL DEFAULT (unixepoch()),
    PRIMARY KEY (booking_id, revision),
    CHECK (status != 'cancelled' OR
           (cancellation_reason IS NOT NULL AND length(trim(cancellation_reason)) > 0))
) STRICT;

CREATE TRIGGER bookings_keep_identity
BEFORE UPDATE ON bookings
WHEN NEW.id != OLD.id OR NEW.hotel_id != OLD.hotel_id OR NEW.created_at != OLD.created_at
BEGIN
    SELECT RAISE(ABORT, 'Booking identity, hotel and creation time cannot change');
END;

CREATE TRIGGER booking_revisions_first_confirmed
BEFORE INSERT ON booking_revisions
WHEN NEW.revision = 1 AND NEW.status != 'confirmed'
BEGIN
    SELECT RAISE(ABORT, 'A booking begins confirmed');
END;

-- Cancellation of the parent booking is terminal. A new stay needs a new ID.
CREATE TRIGGER booking_revisions_cancelled_is_terminal
BEFORE INSERT ON booking_revisions
WHEN EXISTS (
    SELECT 1 FROM booking_revisions
    WHERE booking_id = NEW.booking_id AND status = 'cancelled'
)
BEGIN
    SELECT RAISE(ABORT, 'A cancelled booking cannot be reinstated');
END;

CREATE TABLE parties (
    id TEXT PRIMARY KEY,
    booking_id TEXT NOT NULL UNIQUE REFERENCES bookings(id)
) STRICT;

CREATE TABLE guests (
    id TEXT PRIMARY KEY,
    party_id TEXT NOT NULL REFERENCES parties(id),
    first_name TEXT NOT NULL,
    last_name TEXT NOT NULL,
    preferred_name TEXT,
    age INTEGER NOT NULL CHECK (age >= 0),
    dietary_requirements TEXT
) STRICT;

CREATE TABLE party_details (
    id TEXT PRIMARY KEY,
    party_id TEXT NOT NULL REFERENCES parties(id),
    detail TEXT NOT NULL,
    -- A JSON array follows the requested list shape. Membership and element
    -- types require application validation; this is not a foreign-key array.
    -- NULL means no accepted classification yet; [] means no referenced guests.
    referenced_guest_ids_json TEXT CHECK (
        referenced_guest_ids_json IS NULL OR CASE
            WHEN json_valid(referenced_guest_ids_json)
            THEN json_type(referenced_guest_ids_json) = 'array'
            ELSE 0 END
    )
) STRICT;

CREATE TABLE room_reservations (
    id TEXT NOT NULL,
    revision INTEGER NOT NULL CHECK (revision >= 1),
    booking_id TEXT NOT NULL REFERENCES bookings(id),
    room_id TEXT NOT NULL REFERENCES rooms(id),
    check_in_at INTEGER NOT NULL,
    check_out_at INTEGER NOT NULL,
    -- Labels remain open; the latest accepted revision represents the allocation.
    status TEXT NOT NULL CHECK (length(trim(status)) > 0),
    price_id TEXT NOT NULL,
    price_revision INTEGER NOT NULL,
    recorded_at INTEGER NOT NULL DEFAULT (unixepoch()),
    PRIMARY KEY (id, revision),
    FOREIGN KEY (price_id, price_revision) REFERENCES price_versions(price_id, revision),
    CHECK (check_out_at > check_in_at)
) STRICT;

CREATE TABLE room_keys (
    id TEXT PRIMARY KEY,
    room_id TEXT NOT NULL REFERENCES rooms(id),
    key_code TEXT,
    effective_from INTEGER NOT NULL,
    effective_to INTEGER NOT NULL,
    -- Proposed revocation representation, independent of the planned end time.
    deactivated_at INTEGER,
    deactivation_reason TEXT,
    CHECK (effective_to > effective_from),
    CHECK (deactivated_at IS NULL OR
           (deactivation_reason IS NOT NULL AND length(trim(deactivation_reason)) > 0))
) STRICT;

CREATE TABLE venues (
    id TEXT PRIMARY KEY,
    name TEXT NOT NULL,
    address_line_1 TEXT,
    address_line_2 TEXT,
    city TEXT,
    postcode TEXT,
    country_code TEXT,
    capacity INTEGER NOT NULL CHECK (capacity > 0)
) STRICT;

CREATE TABLE scheduled_activities (
    id TEXT PRIMARY KEY,
    venue_id TEXT NOT NULL REFERENCES venues(id),
    title TEXT NOT NULL,
    type TEXT NOT NULL,
    description TEXT NOT NULL,
    starts_at INTEGER NOT NULL,
    ends_at INTEGER NOT NULL,
    -- NULL means no activity-level limit. Venue constraints still need design.
    capacity INTEGER CHECK (capacity IS NULL OR capacity > 0),
    minimum_booking_size INTEGER NOT NULL DEFAULT 1 CHECK (minimum_booking_size > 0),
    maximum_booking_size INTEGER CHECK (
        maximum_booking_size IS NULL OR maximum_booking_size >= minimum_booking_size
    ),
    minimum_age INTEGER NOT NULL DEFAULT 0 CHECK (minimum_age >= 0),
    price_id TEXT NOT NULL REFERENCES prices(id),
    CHECK (ends_at > starts_at)
) STRICT;

-- Provisional unit: keep the earlier per-guest reservation and aggregate by
-- party. The quantity-only party alternative remains a modelling question.
CREATE TABLE activity_reservations (
    id TEXT NOT NULL,
    revision INTEGER NOT NULL CHECK (revision >= 1),
    party_id TEXT NOT NULL REFERENCES parties(id),
    guest_id TEXT NOT NULL REFERENCES guests(id),
    scheduled_activity_id TEXT NOT NULL REFERENCES scheduled_activities(id),
    status TEXT NOT NULL CHECK (status IN ('active', 'cancelled')),
    cancellation_reason TEXT,
    price_id TEXT NOT NULL,
    price_revision INTEGER NOT NULL,
    recorded_at INTEGER NOT NULL DEFAULT (unixepoch()),
    PRIMARY KEY (id, revision),
    FOREIGN KEY (price_id, price_revision) REFERENCES price_versions(price_id, revision),
    CHECK (status != 'cancelled' OR
           (cancellation_reason IS NOT NULL AND length(trim(cancellation_reason)) > 0))
) STRICT;

-- No payment processor, integration runner, scheduler or agent-runtime tables
-- are invented here. Their boundaries and outstanding decisions are in README.

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

CREATE TRIGGER booking_revisions_next_revision
BEFORE INSERT ON booking_revisions
WHEN NEW.revision != (
    SELECT COALESCE(MAX(revision), 0) + 1 FROM booking_revisions WHERE booking_id = NEW.booking_id
)
BEGIN
    SELECT RAISE(ABORT, 'Expected the next booking_revisions revision');
END;

CREATE TRIGGER booking_revisions_no_update
BEFORE UPDATE ON booking_revisions
BEGIN
    SELECT RAISE(ABORT, 'booking_revisions history cannot be changed');
END;

CREATE TRIGGER booking_revisions_no_delete
BEFORE DELETE ON booking_revisions
BEGIN
    SELECT RAISE(ABORT, 'booking_revisions history cannot be deleted');
END;

CREATE TRIGGER price_versions_next_revision
BEFORE INSERT ON price_versions
WHEN NEW.revision != (
    SELECT COALESCE(MAX(revision), 0) + 1 FROM price_versions WHERE price_id = NEW.price_id
)
BEGIN
    SELECT RAISE(ABORT, 'Expected the next price_versions revision');
END;

CREATE TRIGGER price_versions_no_update
BEFORE UPDATE ON price_versions
BEGIN
    SELECT RAISE(ABORT, 'price_versions history cannot be changed');
END;

CREATE TRIGGER price_versions_no_delete
BEFORE DELETE ON price_versions
BEGIN
    SELECT RAISE(ABORT, 'price_versions history cannot be deleted');
END;

CREATE TRIGGER activity_reservations_next_revision
BEFORE INSERT ON activity_reservations
WHEN NEW.revision != (
    SELECT COALESCE(MAX(revision), 0) + 1 FROM activity_reservations WHERE id = NEW.id
)
BEGIN
    SELECT RAISE(ABORT, 'Expected the next activity_reservations revision');
END;

CREATE TRIGGER activity_reservations_no_update
BEFORE UPDATE ON activity_reservations
BEGIN
    SELECT RAISE(ABORT, 'activity_reservations history cannot be changed');
END;

CREATE TRIGGER activity_reservations_no_delete
BEFORE DELETE ON activity_reservations
BEGIN
    SELECT RAISE(ABORT, 'activity_reservations history cannot be deleted');
END;

CREATE TRIGGER activity_reservations_keep_identity
BEFORE INSERT ON activity_reservations
WHEN EXISTS (
    SELECT 1 FROM activity_reservations WHERE id = NEW.id AND (
        party_id != NEW.party_id OR guest_id != NEW.guest_id OR
        scheduled_activity_id != NEW.scheduled_activity_id
    )
)
BEGIN
    SELECT RAISE(ABORT, 'An activity reservation must keep its party, guest and activity');
END;

CREATE VIEW current_booking_revisions AS
SELECT entry.* FROM booking_revisions AS entry
WHERE NOT EXISTS (
    SELECT 1 FROM booking_revisions AS newer
    WHERE newer.booking_id = entry.booking_id AND newer.revision > entry.revision
);

CREATE VIEW current_price_versions AS
SELECT entry.* FROM price_versions AS entry
WHERE NOT EXISTS (
    SELECT 1 FROM price_versions AS newer
    WHERE newer.price_id = entry.price_id AND newer.revision > entry.revision
);

CREATE VIEW current_room_reservations AS
SELECT entry.* FROM room_reservations AS entry
WHERE NOT EXISTS (
    SELECT 1 FROM room_reservations AS newer
    WHERE newer.id = entry.id AND newer.revision > entry.revision
);

CREATE VIEW current_activity_reservations AS
SELECT entry.* FROM activity_reservations AS entry
WHERE NOT EXISTS (
    SELECT 1 FROM activity_reservations AS newer
    WHERE newer.id = entry.id AND newer.revision > entry.revision
);

-- This names only the agreed parent-cancellation rule. It is not yet a full
-- capacity query: activity changes and other booking states still need policy.
CREATE VIEW uncancelled_activity_reservations AS
SELECT reservation.*
FROM current_activity_reservations AS reservation
JOIN parties AS party ON party.id = reservation.party_id
JOIN current_booking_revisions AS booking ON booking.booking_id = party.booking_id
WHERE reservation.status = 'active' AND booking.status != 'cancelled';

COMMIT;
