"""Hotel records, booking history and room keys.

Dates are UTC microseconds since the Unix epoch. An end time is not included.
Keep this migration self-contained; application models may change later.
"""

import sqlalchemy as sa
from alembic import op

revision = "0001_domain"
down_revision = None
branch_labels = None
depends_on = None


def _id_check(prefix: str) -> str:
    """Check the resource prefix and the 26-character ULID that follows it."""
    start = len(prefix) + 2
    return (
        f"length(id) = {len(prefix) + 27} AND substr(id, 1, {start - 1}) = '{prefix}_' "
        f"AND substr(id, {start}, 1) GLOB '[0-7]' "
        f"AND substr(id, {start}) NOT GLOB '*[^0-9A-HJKMNP-TV-Z]*'"
    )


def _identity(prefix: str) -> tuple:
    """Give each record an ID and a creation time."""
    return (
        sa.Column("id", sa.Text(), nullable=False),
        sa.Column("created_at", sa.Integer(), nullable=False),
        sa.PrimaryKeyConstraint("id", name=f"pk_{prefix}"),
        sa.CheckConstraint(_id_check(prefix), name=f"ck_{prefix}_id"),
    )


def _address() -> tuple:
    """Optional postal fields shared by hotels and venues."""
    return (
        sa.Column("address_line_1", sa.Text()),
        sa.Column("address_line_2", sa.Text()),
        sa.Column("city", sa.Text()),
        sa.Column("postcode", sa.Text()),
        sa.Column("country_code", sa.Text()),
        sa.CheckConstraint(
            "country_code IS NULL OR country_code GLOB '[A-Z][A-Z]'",
            name="ck_country_code",
        ),
    )


def _trigger(name: str, event: str, table: str, body: str, when: str = "") -> None:
    """Run these SQL checks before a write, optionally only when a condition matches."""
    condition = f"WHEN {when}" if when else ""
    op.execute(
        f"CREATE TRIGGER {name} BEFORE {event} ON {table} {condition} BEGIN {body} END"
    )


def _immutable(table: str, columns: tuple[str, ...]) -> None:
    """Prevent changes to the listed fields, such as IDs and party membership."""
    _trigger(
        f"{table}_keep_identity",
        "UPDATE",
        table,
        "SELECT RAISE(ABORT, 'Identity and membership cannot change');",
        " OR ".join(f"NEW.{column} IS NOT OLD.{column}" for column in columns),
    )


def _history(table: str, parent: str) -> None:
    """Add revisions in order, starting at 1; never edit or delete earlier versions."""
    _trigger(
        f"{table}_next_revision",
        "INSERT",
        table,
        "SELECT RAISE(ABORT, 'Expected the next revision');",
        f"NEW.revision != (SELECT COALESCE(MAX(revision), 0) + 1 FROM {table} WHERE {parent} = NEW.{parent})",
    )
    for event in ("UPDATE", "DELETE"):
        _trigger(
            f"{table}_no_{event.lower()}",
            event,
            table,
            "SELECT RAISE(ABORT, 'Accepted history cannot be rewritten');",
        )


def upgrade() -> None:
    """Create the tables, add checks for changes, then define the read queries."""
    _create_property_tables()
    _create_booking_and_guest_tables()
    _create_room_access_tables()
    _create_activity_tables()
    _create_history_rules()
    _create_membership_rules()
    _create_views()


def _create_property_tables() -> None:
    """Hotels, staff, shared prices, rooms and beds."""
    op.create_table(
        "hotels",
        *_identity("hotel"),
        *_address(),
        sa.Column("name", sa.Text(), nullable=False),
        sa.CheckConstraint("length(name) > 0", name="ck_hotels_name"),
        sqlite_strict=True,
    )
    op.create_table(
        "staff_members",
        *_identity("staff_member"),
        sa.Column(
            "hotel_id",
            sa.Text(),
            sa.ForeignKey("hotels.id", name="fk_staff_members_hotels"),
            nullable=False,
        ),
        sa.Column("staff_code", sa.Text(), nullable=False),
        sa.Column("first_name", sa.Text(), nullable=False),
        sa.Column("last_name", sa.Text(), nullable=False),
        sa.Column("title", sa.Text()),
        sa.Column("role", sa.Text(), nullable=False),
        sa.CheckConstraint(
            "length(staff_code) > 0 AND length(first_name) > 0 AND length(last_name) > 0",
            name="ck_staff_names",
        ),
        sa.CheckConstraint(
            "role IN ('STAFF_ROLE_UNKNOWN', 'STAFF_ROLE_CONCIERGE')",
            name="ck_staff_role",
        ),
        sqlite_strict=True,
    )
    op.create_table("prices", *_identity("price"), sqlite_strict=True)
    op.create_table(
        "price_versions",
        sa.Column(
            "price_id",
            sa.Text(),
            sa.ForeignKey("prices.id", name="fk_price_versions_prices"),
            nullable=False,
        ),
        sa.Column("revision", sa.Integer(), nullable=False),
        sa.Column("amount_minor", sa.Integer(), nullable=False),
        sa.Column("currency", sa.Text(), nullable=False),
        sa.Column("created_at", sa.Integer(), nullable=False),
        sa.PrimaryKeyConstraint("price_id", "revision", name="pk_price_versions"),
        sa.CheckConstraint("revision >= 1", name="ck_price_revision"),
        sa.CheckConstraint("amount_minor >= 0", name="ck_price_amount"),
        sa.CheckConstraint("currency GLOB '[A-Z][A-Z][A-Z]'", name="ck_price_currency"),
        sqlite_strict=True,
    )
    op.create_table(
        "rooms",
        *_identity("room"),
        sa.Column(
            "hotel_id",
            sa.Text(),
            sa.ForeignKey("hotels.id", name="fk_rooms_hotels"),
            nullable=False,
        ),
        sa.Column("label", sa.Text(), nullable=False),
        sa.Column("description", sa.Text(), nullable=False),
        sa.Column("tier", sa.Text(), nullable=False),
        sa.Column("number_of_bathrooms", sa.Integer(), nullable=False),
        sa.Column("in_service", sa.Integer(), nullable=False),
        sa.Column(
            "price_id",
            sa.Text(),
            sa.ForeignKey("prices.id", name="fk_rooms_prices"),
            nullable=False,
        ),
        sa.CheckConstraint("length(label) > 0", name="ck_room_label"),
        sa.CheckConstraint(
            "tier IN ('ROOM_TIER_UNKNOWN', 'ROOM_TIER_STANDARD', 'ROOM_TIER_VIP')",
            name="ck_room_tier",
        ),
        sa.CheckConstraint("number_of_bathrooms >= 0", name="ck_room_bathrooms"),
        sa.CheckConstraint("in_service IN (0, 1)", name="ck_room_in_service"),
        sqlite_strict=True,
    )
    op.create_table(
        "beds",
        *_identity("bed"),
        sa.Column(
            "room_id",
            sa.Text(),
            sa.ForeignKey("rooms.id", name="fk_beds_rooms"),
            nullable=False,
        ),
        sa.Column("type", sa.Text(), nullable=False),
        sa.CheckConstraint(
            "type IN ('BED_TYPE_UNKNOWN', 'BED_TYPE_SINGLE', 'BED_TYPE_TWIN', 'BED_TYPE_DOUBLE', 'BED_TYPE_QUEEN', 'BED_TYPE_KING')",
            name="ck_bed_type",
        ),
        sqlite_strict=True,
    )


def _create_booking_and_guest_tables() -> None:
    """Bookings, their parties and guests, and notes about each party."""
    op.create_table(
        "bookings",
        *_identity("booking"),
        sa.Column(
            "hotel_id",
            sa.Text(),
            sa.ForeignKey("hotels.id", name="fk_bookings_hotels"),
            nullable=False,
        ),
        sa.Column("name", sa.Text(), nullable=False),
        sa.CheckConstraint("length(name) > 0", name="ck_booking_name"),
        sqlite_strict=True,
    )
    op.create_table(
        "booking_revisions",
        sa.Column(
            "booking_id",
            sa.Text(),
            sa.ForeignKey("bookings.id", name="fk_booking_revisions_bookings"),
            nullable=False,
        ),
        sa.Column("revision", sa.Integer(), nullable=False),
        sa.Column("status", sa.Text(), nullable=False),
        sa.Column("cancellation_reason", sa.Text()),
        sa.Column("recorded_at", sa.Integer(), nullable=False),
        sa.PrimaryKeyConstraint("booking_id", "revision", name="pk_booking_revisions"),
        sa.CheckConstraint("revision >= 1", name="ck_booking_revision"),
        sa.CheckConstraint(
            "status IN ('BOOKING_STATUS_CONFIRMED', 'BOOKING_STATUS_CANCELLED', 'BOOKING_STATUS_COMPLETED')",
            name="ck_booking_status",
        ),
        sa.CheckConstraint(
            "(status = 'BOOKING_STATUS_CANCELLED' AND cancellation_reason IS NOT NULL AND length(cancellation_reason) > 0) OR (status != 'BOOKING_STATUS_CANCELLED' AND cancellation_reason IS NULL)",
            name="ck_booking_cancellation",
        ),
        sqlite_strict=True,
    )
    op.create_table(
        "parties",
        *_identity("party"),
        sa.Column(
            "booking_id",
            sa.Text(),
            sa.ForeignKey("bookings.id", name="fk_parties_bookings"),
            nullable=False,
        ),
        sa.UniqueConstraint("booking_id", name="uq_party_booking"),
        sqlite_strict=True,
    )
    op.create_table(
        "guests",
        *_identity("guest"),
        sa.Column(
            "party_id",
            sa.Text(),
            sa.ForeignKey("parties.id", name="fk_guests_parties"),
            nullable=False,
        ),
        sa.Column("first_name", sa.Text(), nullable=False),
        sa.Column("last_name", sa.Text(), nullable=False),
        sa.Column("preferred_name", sa.Text()),
        sa.Column("age", sa.Integer(), nullable=False),
        sa.Column("dietary_requirements", sa.Text()),
        sa.Column("phone", sa.Text()),
        sa.Column("email", sa.Text()),
        sa.Column("contact_preference", sa.Text()),
        # Reservations use both fields to check that the guest belongs to the party.
        sa.UniqueConstraint("id", "party_id", name="uq_guest_party"),
        sa.CheckConstraint(
            "length(first_name) > 0 AND length(last_name) > 0", name="ck_guest_names"
        ),
        sa.CheckConstraint("age >= 0", name="ck_guest_age"),
        sa.CheckConstraint(
            "contact_preference IS NULL OR contact_preference IN ('CONTACT_PREFERENCE_PHONE', 'CONTACT_PREFERENCE_EMAIL')",
            name="ck_guest_contact_preference",
        ),
        sa.CheckConstraint(
            "contact_preference IS NOT 'CONTACT_PREFERENCE_PHONE' OR (phone IS NOT NULL AND length(phone) > 0)",
            name="ck_guest_phone",
        ),
        sa.CheckConstraint(
            "contact_preference IS NOT 'CONTACT_PREFERENCE_EMAIL' OR (email IS NOT NULL AND length(email) > 0)",
            name="ck_guest_email",
        ),
        sqlite_strict=True,
    )
    op.create_table(
        "party_details",
        *_identity("party_detail"),
        sa.Column(
            "party_id",
            sa.Text(),
            sa.ForeignKey("parties.id", name="fk_party_details_parties"),
            nullable=False,
        ),
        sa.Column("text", sa.Text(), nullable=False),
        sa.Column("referenced_guest_ids_json", sa.Text(), nullable=False),
        sa.Column("reference_format_version", sa.Integer(), nullable=False),
        sa.Column("reference_status", sa.Text(), nullable=False),
        sa.CheckConstraint("length(text) > 0", name="ck_party_detail_text"),
        sa.CheckConstraint(
            "reference_format_version = 1", name="ck_party_reference_version"
        ),
        sa.CheckConstraint(
            "CASE WHEN json_valid(referenced_guest_ids_json) THEN json_type(referenced_guest_ids_json) = 'array' ELSE 0 END",
            name="ck_party_reference_array",
        ),
        sa.CheckConstraint(
            "reference_status IN ('GUEST_REFERENCE_STATUS_PENDING', 'GUEST_REFERENCE_STATUS_RESOLVED', 'GUEST_REFERENCE_STATUS_AMBIGUOUS', 'GUEST_REFERENCE_STATUS_FAILED')",
            name="ck_party_reference_status",
        ),
        sqlite_strict=True,
    )


def _create_room_access_tables() -> None:
    """Room reservations, their changes, and the keys issued for each reservation."""
    # Keys point to the reservation ID, so they still work when its dates change.
    op.create_table(
        "room_reservations",
        *_identity("room_reservation"),
        sa.Column(
            "booking_id",
            sa.Text(),
            sa.ForeignKey("bookings.id", name="fk_room_reservations_bookings"),
            nullable=False,
        ),
        sa.Column(
            "room_id",
            sa.Text(),
            sa.ForeignKey("rooms.id", name="fk_room_reservations_rooms"),
            nullable=False,
        ),
        sqlite_strict=True,
    )
    op.create_table(
        "room_reservation_revisions",
        sa.Column(
            "room_reservation_id",
            sa.Text(),
            sa.ForeignKey(
                "room_reservations.id",
                name="fk_room_reservation_revisions_room_reservations",
            ),
            nullable=False,
        ),
        sa.Column("revision", sa.Integer(), nullable=False),
        sa.Column("min_date", sa.Integer(), nullable=False),
        sa.Column("max_date", sa.Integer(), nullable=False),
        sa.Column("cancelled", sa.Integer(), nullable=False),
        sa.Column("cancellation_reason", sa.Text()),
        sa.Column("price_id", sa.Text(), nullable=False),
        sa.Column("price_revision", sa.Integer(), nullable=False),
        sa.Column("recorded_at", sa.Integer(), nullable=False),
        sa.PrimaryKeyConstraint(
            "room_reservation_id", "revision", name="pk_room_reservation_revisions"
        ),
        sa.ForeignKeyConstraint(
            ["price_id", "price_revision"],
            ["price_versions.price_id", "price_versions.revision"],
            name="fk_room_agreed_price",
        ),
        sa.CheckConstraint("revision >= 1", name="ck_room_reservation_revision"),
        sa.CheckConstraint("max_date > min_date", name="ck_room_reservation_dates"),
        sa.CheckConstraint("cancelled IN (0, 1)", name="ck_room_reservation_cancelled"),
        sa.CheckConstraint(
            "(cancelled = 1 AND cancellation_reason IS NOT NULL AND length(cancellation_reason) > 0) OR (cancelled = 0 AND cancellation_reason IS NULL)",
            name="ck_room_reservation_cancellation",
        ),
        sqlite_strict=True,
    )
    op.create_table(
        "room_keys",
        *_identity("room_key"),
        sa.Column(
            "room_reservation_id",
            sa.Text(),
            sa.ForeignKey(
                "room_reservations.id", name="fk_room_keys_room_reservations"
            ),
            nullable=False,
        ),
        sa.Column("code", sa.Text()),
        sa.Column("deactivated_at", sa.Integer()),
        sa.Column("deactivation_reason", sa.Text()),
        sa.CheckConstraint(
            "(deactivated_at IS NULL AND deactivation_reason IS NULL) OR (deactivated_at IS NOT NULL AND deactivated_at >= created_at AND deactivation_reason IS NOT NULL AND length(deactivation_reason) > 0)",
            name="ck_room_key_deactivation",
        ),
        sqlite_strict=True,
    )


def _create_activity_tables() -> None:
    """Venues, activity types, scheduled activities and guest reservations."""
    op.create_table(
        "venues",
        *_identity("venue"),
        *_address(),
        sa.Column("name", sa.Text(), nullable=False),
        sa.Column("capacity", sa.Integer(), nullable=False),
        sa.CheckConstraint("length(name) > 0", name="ck_venue_name"),
        sa.CheckConstraint("capacity >= 0", name="ck_venue_capacity"),
        sqlite_strict=True,
    )
    # New types are rows in this table, so adding one does not need a migration.
    activity_types = op.create_table(
        "activity_types",
        sa.Column("code", sa.Text(), nullable=False),
        sa.Column("name", sa.Text(), nullable=False),
        sa.PrimaryKeyConstraint("code", name="pk_activity_types"),
        sa.CheckConstraint(
            "code GLOB 'ACTIVITY_TYPE_[A-Z]*' AND code NOT GLOB '*[^A-Z0-9_]*'",
            name="ck_activity_type_code",
        ),
        sa.CheckConstraint("length(name) > 0", name="ck_activity_type_name"),
        sqlite_strict=True,
    )
    op.bulk_insert(
        activity_types,
        [
            {"code": "ACTIVITY_TYPE_UNKNOWN", "name": "Unknown"},
            {"code": "ACTIVITY_TYPE_TENNIS", "name": "Tennis"},
            {"code": "ACTIVITY_TYPE_POTTERY", "name": "Pottery"},
            {"code": "ACTIVITY_TYPE_GUIDED_TOUR", "name": "Guided tour"},
        ],
    )
    op.create_table(
        "activities",
        *_identity("activity"),
        sa.Column(
            "venue_id",
            sa.Text(),
            sa.ForeignKey("venues.id", name="fk_activities_venues"),
            nullable=False,
        ),
        sa.Column("title", sa.Text(), nullable=False),
        sa.Column(
            "type",
            sa.Text(),
            sa.ForeignKey("activity_types.code", name="fk_activities_type"),
            nullable=False,
        ),
        sa.Column("description", sa.Text(), nullable=False),
        sa.Column("min_date", sa.Integer(), nullable=False),
        sa.Column("max_date", sa.Integer(), nullable=False),
        sa.Column("capacity", sa.Integer()),
        sa.Column("min_booking_size", sa.Integer(), nullable=False),
        sa.Column("max_booking_size", sa.Integer(), nullable=False),
        sa.Column("minimum_age", sa.Integer(), nullable=False),
        sa.Column(
            "price_id",
            sa.Text(),
            sa.ForeignKey("prices.id", name="fk_activities_prices"),
            nullable=False,
        ),
        sa.Column("price_unit", sa.Text(), nullable=False),
        sa.CheckConstraint("length(title) > 0", name="ck_activity_title"),
        sa.CheckConstraint("max_date > min_date", name="ck_activity_dates"),
        sa.CheckConstraint(
            "capacity IS NULL OR capacity >= 0", name="ck_activity_capacity"
        ),
        sa.CheckConstraint(
            "min_booking_size >= 1 AND max_booking_size >= min_booking_size",
            name="ck_activity_booking_size",
        ),
        sa.CheckConstraint("minimum_age >= 0", name="ck_activity_age"),
        sa.CheckConstraint(
            "price_unit = 'ACTIVITY_PRICE_UNIT_PER_GUEST'",
            name="ck_activity_price_unit",
        ),
        sqlite_strict=True,
    )
    op.create_table(
        "activity_reservations",
        *_identity("activity_reservation"),
        sa.Column(
            "party_id",
            sa.Text(),
            sa.ForeignKey("parties.id", name="fk_activity_reservations_parties"),
            nullable=False,
        ),
        sa.Column("guest_id", sa.Text(), nullable=False),
        sa.Column(
            "activity_id",
            sa.Text(),
            sa.ForeignKey("activities.id", name="fk_activity_reservations_activities"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(
            ["guest_id", "party_id"],
            ["guests.id", "guests.party_id"],
            name="fk_activity_reservation_guest_party",
        ),
        sqlite_strict=True,
    )
    op.create_table(
        "activity_reservation_revisions",
        sa.Column(
            "activity_reservation_id",
            sa.Text(),
            sa.ForeignKey(
                "activity_reservations.id",
                name="fk_activity_reservation_revisions_activity_reservations",
            ),
            nullable=False,
        ),
        sa.Column("revision", sa.Integer(), nullable=False),
        sa.Column("cancelled", sa.Integer(), nullable=False),
        sa.Column("cancellation_reason", sa.Text()),
        sa.Column("price_id", sa.Text(), nullable=False),
        sa.Column("price_revision", sa.Integer(), nullable=False),
        sa.Column("price_unit", sa.Text(), nullable=False),
        sa.Column("recorded_at", sa.Integer(), nullable=False),
        sa.PrimaryKeyConstraint(
            "activity_reservation_id",
            "revision",
            name="pk_activity_reservation_revisions",
        ),
        sa.ForeignKeyConstraint(
            ["price_id", "price_revision"],
            ["price_versions.price_id", "price_versions.revision"],
            name="fk_activity_agreed_price",
        ),
        sa.CheckConstraint("revision >= 1", name="ck_activity_reservation_revision"),
        sa.CheckConstraint(
            "cancelled IN (0, 1)", name="ck_activity_reservation_cancelled"
        ),
        sa.CheckConstraint(
            "(cancelled = 1 AND cancellation_reason IS NOT NULL AND length(cancellation_reason) > 0) OR (cancelled = 0 AND cancellation_reason IS NULL)",
            name="ck_activity_reservation_cancellation",
        ),
        sa.CheckConstraint(
            "price_unit = 'ACTIVITY_PRICE_UNIT_PER_GUEST'",
            name="ck_reservation_price_unit",
        ),
        sqlite_strict=True,
    )


def _create_history_rules() -> None:
    """Keep earlier versions unchanged; do not reopen cancellations or disabled keys."""
    for table, parent in (
        ("price_versions", "price_id"),
        ("booking_revisions", "booking_id"),
        ("room_reservation_revisions", "room_reservation_id"),
        ("activity_reservation_revisions", "activity_reservation_id"),
    ):
        _history(table, parent)
    _trigger(
        "booking_starts_confirmed",
        "INSERT",
        "booking_revisions",
        "SELECT RAISE(ABORT, 'A booking starts confirmed');",
        "NEW.revision = 1 AND NEW.status != 'BOOKING_STATUS_CONFIRMED'",
    )
    _trigger(
        "booking_cancellation_terminal",
        "INSERT",
        "booking_revisions",
        "SELECT RAISE(ABORT, 'Booking cancellation is terminal');",
        "EXISTS (SELECT 1 FROM booking_revisions WHERE booking_id = NEW.booking_id AND status = 'BOOKING_STATUS_CANCELLED')",
    )
    for table, parent in (
        ("room_reservation_revisions", "room_reservation_id"),
        ("activity_reservation_revisions", "activity_reservation_id"),
    ):
        _trigger(
            f"{table}_cancellation_terminal",
            "INSERT",
            table,
            "SELECT RAISE(ABORT, 'Reservation cancellation is terminal');",
            f"EXISTS (SELECT 1 FROM {table} WHERE {parent} = NEW.{parent} AND cancelled = 1)",
        )
        _trigger(
            f"{table}_starts_uncancelled",
            "INSERT",
            table,
            "SELECT RAISE(ABORT, 'A reservation starts uncancelled');",
            "NEW.revision = 1 AND NEW.cancelled != 0",
        )
    _trigger(
        "key_revocation_terminal",
        "UPDATE",
        "room_keys",
        "SELECT RAISE(ABORT, 'Key revocation cannot be reversed or rewritten');",
        "OLD.deactivated_at IS NOT NULL AND (NEW.deactivated_at IS NOT OLD.deactivated_at OR NEW.deactivation_reason IS NOT OLD.deactivation_reason)",
    )


def _create_membership_rules() -> None:
    """Keep IDs and membership fixed; check that linked records belong together."""
    for table, columns in (
        ("hotels", ("id", "created_at")),
        ("staff_members", ("id", "created_at")),
        ("prices", ("id", "created_at")),
        ("rooms", ("id", "hotel_id", "created_at")),
        ("beds", ("id", "created_at")),
        ("bookings", ("id", "hotel_id", "created_at")),
        ("parties", ("id", "booking_id", "created_at")),
        ("guests", ("id", "party_id", "created_at")),
        ("party_details", ("id", "party_id", "created_at")),
        ("room_reservations", ("id", "booking_id", "room_id", "created_at")),
        ("room_keys", ("id", "room_reservation_id", "created_at")),
        ("venues", ("id", "created_at")),
        ("activity_types", ("code",)),
        ("activities", ("id", "created_at")),
        (
            "activity_reservations",
            ("id", "party_id", "guest_id", "activity_id", "created_at"),
        ),
    ):
        _immutable(table, columns)
    _trigger(
        "room_reservation_same_hotel",
        "INSERT",
        "room_reservations",
        "SELECT RAISE(ABORT, 'Room and booking must belong to the same hotel');",
        "(SELECT hotel_id FROM rooms WHERE id = NEW.room_id) != (SELECT hotel_id FROM bookings WHERE id = NEW.booking_id)",
    )
    # Check the guest IDs stored in each note’s JSON list.
    for event in ("INSERT", "UPDATE"):
        _trigger(
            f"party_references_{event.lower()}",
            event,
            "party_details",
            """
            -- Check that the JSON is valid before reading it.
            SELECT CASE WHEN NOT json_valid(NEW.referenced_guest_ids_json)
                THEN RAISE(ABORT, 'Guest references must be valid JSON') END;

            -- References are a list, not an object or scalar.
            SELECT CASE WHEN json_type(NEW.referenced_guest_ids_json) != 'array'
                THEN RAISE(ABORT, 'Guest references must be an array') END;

            -- Every entry names a guest from this party.
            SELECT CASE WHEN EXISTS (
                SELECT 1 FROM json_each(NEW.referenced_guest_ids_json) AS ref
                WHERE ref.type != 'text' OR NOT EXISTS (
                    SELECT 1 FROM guests WHERE id = ref.value AND party_id = NEW.party_id
                )
            ) THEN RAISE(ABORT, 'Referenced guests must belong to the party') END;

            -- The same guest cannot appear twice.
            SELECT CASE WHEN (SELECT COUNT(*) FROM json_each(NEW.referenced_guest_ids_json)) !=
                (SELECT COUNT(DISTINCT value) FROM json_each(NEW.referenced_guest_ids_json))
                THEN RAISE(ABORT, 'Guest references must be unique') END;

            -- Keep the guest list empty until classification succeeds.
            SELECT CASE WHEN NEW.reference_status != 'GUEST_REFERENCE_STATUS_RESOLVED'
                AND json_array_length(NEW.referenced_guest_ids_json) != 0
                THEN RAISE(ABORT, 'Unresolved references cannot assert guest identities') END;
        """,
        )
    _trigger(
        "referenced_guest_no_delete",
        "DELETE",
        "guests",
        "SELECT RAISE(ABORT, 'Guest is referenced by party evidence');",
        "EXISTS (SELECT 1 FROM party_details, json_each(referenced_guest_ids_json) AS ref WHERE ref.value = OLD.id)",
    )


def _create_views() -> None:
    """Save these queries under names; results are read fresh, not stored."""
    # Keep a version only if there is no newer version of the same record.
    for table, parent, view in (
        ("price_versions", "price_id", "current_price_versions"),
        ("booking_revisions", "booking_id", "current_booking_revisions"),
        (
            "room_reservation_revisions",
            "room_reservation_id",
            "current_room_reservation_revisions",
        ),
        (
            "activity_reservation_revisions",
            "activity_reservation_id",
            "current_activity_reservation_revisions",
        ),
    ):
        op.execute(f"""CREATE VIEW {view} AS SELECT entry.* FROM {table} AS entry
            WHERE NOT EXISTS (SELECT 1 FROM {table} AS newer
                WHERE newer.{parent} = entry.{parent} AND newer.revision > entry.revision)""")
    # Find the key’s reservation, its latest dates, and the booking’s latest status.
    # A cancelled booking or reservation stops access without updating each key.
    # The repository must also check that now is within the reservation’s dates.
    op.execute("""CREATE VIEW room_key_access AS
        SELECT key.*, reservation.room_id, reservation.booking_id,
               current.min_date, current.max_date,
               (key.deactivated_at IS NULL AND current.cancelled = 0
                AND booking.status = 'BOOKING_STATUS_CONFIRMED') AS eligible
        FROM room_keys AS key
        JOIN room_reservations AS reservation ON reservation.id = key.room_reservation_id
        JOIN current_room_reservation_revisions AS current ON current.room_reservation_id = reservation.id
        JOIN current_booking_revisions AS booking ON booking.booking_id = reservation.booking_id
    """)


def downgrade() -> None:
    """Drop the objects added here, removing dependent tables first."""
    # Keep this list local: future application tables must not change old rollbacks.
    for view in (
        "room_key_access",
        "current_activity_reservation_revisions",
        "current_room_reservation_revisions",
        "current_booking_revisions",
        "current_price_versions",
    ):
        op.execute(f"DROP VIEW {view}")
    # Dropping a table drops its triggers. Remove this trigger before its lookup table.
    op.execute("DROP TRIGGER referenced_guest_no_delete")
    for table in (
        "activity_reservation_revisions",
        "activity_reservations",
        "activities",
        "activity_types",
        "venues",
        "room_keys",
        "room_reservation_revisions",
        "room_reservations",
        "party_details",
        "guests",
        "parties",
        "booking_revisions",
        "bookings",
        "beds",
        "rooms",
        "price_versions",
        "prices",
        "staff_members",
        "hotels",
    ):
        op.drop_table(table)
