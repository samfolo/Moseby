"""Core query metadata. Handwritten migrations own schema creation and constraints."""

from sqlalchemy import Boolean, Column, Integer, MetaData, Table, Text

metadata = MetaData()

bookings = Table(
    "bookings",
    metadata,
    Column("id", Text),
    Column("hotel_id", Text),
    Column("name", Text),
    Column("created_at", Integer),
    Column("updated_at", Integer),
)
booking_revisions = Table(
    "booking_revisions",
    metadata,
    Column("booking_id", Text),
    Column("revision", Integer),
    Column("status", Text),
    Column("cancellation_reason", Text),
    Column("created_at", Integer),
)
parties = Table(
    "parties",
    metadata,
    Column("id", Text),
    Column("booking_id", Text),
    Column("created_at", Integer),
)
guests = Table(
    "guests",
    metadata,
    Column("id", Text),
    Column("party_id", Text),
    Column("first_name", Text),
    Column("last_name", Text),
    Column("preferred_name", Text),
    Column("age", Integer),
    Column("dietary_requirements", Text),
    Column("phone", Text),
    Column("email", Text),
    Column("contact_preference", Text),
    Column("created_at", Integer),
    Column("updated_at", Integer),
)
room_reservations = Table(
    "room_reservations",
    metadata,
    Column("id", Text),
    Column("booking_id", Text),
    Column("room_id", Text),
    Column("created_at", Integer),
)
room_reservation_revisions = Table(
    "room_reservation_revisions",
    metadata,
    Column("room_reservation_id", Text),
    Column("revision", Integer),
    Column("min_date", Integer),
    Column("max_date", Integer),
    Column("cancelled", Boolean),
    Column("cancellation_reason", Text),
    Column("price_id", Text),
    Column("price_revision", Integer),
    Column("created_at", Integer),
)
price_versions = Table(
    "price_versions",
    metadata,
    Column("price_id", Text),
    Column("revision", Integer),
    Column("amount_minor", Integer),
    Column("currency", Text),
    Column("created_at", Integer),
)
room_keys = Table(
    "room_keys",
    metadata,
    Column("id", Text),
    Column("room_reservation_id", Text),
    Column("code", Text),
    Column("deactivated_at", Integer),
    Column("deactivation_reason", Text),
    Column("created_at", Integer),
    Column("updated_at", Integer),
)
