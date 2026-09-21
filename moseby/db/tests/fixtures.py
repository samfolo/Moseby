"""A migrated database with two hotels and one confirmed stay in each."""

import tempfile
import unittest
from pathlib import Path

import sqlalchemy as sa
from alembic import command
from alembic.config import Config

from moseby.db.connection import create_database_engine
from moseby.db.transaction import transaction

ROOT = Path(__file__).resolve().parents[3]
NOW = 1_800_000_000_123_456


def identifier(prefix, number=1):
    return f"{prefix}_{number:026d}"


class StayDatabaseTestCase(unittest.TestCase):
    """Give each test its own migrated database with two independent hotel stays."""

    def setUp(self):
        """Create and seed SQLite; close it before removing the temporary directory."""
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        self.engine = create_database_engine(
            sa.URL.create("sqlite", database=f"{directory.name}/test.db")
        )
        self.addCleanup(self.engine.dispose)
        self.metadata = sa.MetaData()
        with transaction(self.engine, write=True) as connection:
            config = Config(str(ROOT / "alembic.ini"))
            config.attributes["connection"] = connection
            command.upgrade(config, "head")
            self.metadata.reflect(connection)
            self.seed(connection)

    def insert(self, connection, table, **values):
        """Insert fixture values, supplying timestamps when the test omits them."""
        target = self.metadata.tables[table]
        if "created_at" in target.c:
            values.setdefault("created_at", NOW)
        if "updated_at" in target.c:
            values.setdefault("updated_at", values["created_at"])
        connection.execute(target.insert().values(**values))

    def seed(self, connection):
        """Give each hotel a booking, party, guest, reserved room and key."""
        self.insert(connection, "prices", id=identifier("price"))
        self.insert(
            connection,
            "price_versions",
            price_id=identifier("price"),
            revision=1,
            amount_minor=20_000,
            currency="GBP",
        )
        for number in (1, 2):
            self.insert(
                connection, "hotels", id=identifier("hotel", number), name="Hotel"
            )
            self.insert(
                connection,
                "bookings",
                id=identifier("booking", number),
                hotel_id=identifier("hotel", number),
                name="Stay",
            )
            self.insert(
                connection,
                "booking_revisions",
                booking_id=identifier("booking", number),
                revision=1,
                status="BOOKING_STATUS_CONFIRMED",
            )
            self.insert(
                connection,
                "parties",
                id=identifier("party", number),
                booking_id=identifier("booking", number),
            )
            self.insert(
                connection,
                "guests",
                id=identifier("guest", number),
                party_id=identifier("party", number),
                first_name="Dan",
                last_name="Guest",
                age=30,
            )
            self.insert(
                connection,
                "rooms",
                id=identifier("room", number),
                hotel_id=identifier("hotel", number),
                label="Rose",
                description="",
                tier="ROOM_TIER_STANDARD",
                number_of_bathrooms=1,
                in_service=1,
                price_id=identifier("price"),
            )
            self.insert(
                connection,
                "room_reservations",
                id=identifier("room_reservation", number),
                room_id=identifier("room", number),
                booking_id=identifier("booking", number),
            )
            self.insert(
                connection,
                "room_reservation_revisions",
                room_reservation_id=identifier("room_reservation", number),
                revision=1,
                min_date=NOW,
                max_date=NOW + 100,
                cancelled=0,
                price_id=identifier("price"),
                price_revision=1,
            )
            self.insert(
                connection,
                "room_keys",
                id=identifier("room_key", number),
                room_reservation_id=identifier("room_reservation", number),
            )

    def add_guest(self, connection, number, **changes):
        """Add a guest to the first party, with any supplied field overrides."""
        values = dict(
            id=identifier("guest", number),
            party_id=identifier("party"),
            first_name="Guest",
            last_name=str(number),
            age=30,
        )
        self.insert(connection, "guests", **(values | changes))

    def revise_room(self, connection, revision, **changes):
        """Append a revision for the first room reservation with supplied changes."""
        values = dict(
            room_reservation_id=identifier("room_reservation"),
            revision=revision,
            min_date=NOW,
            max_date=NOW + 100,
            cancelled=0,
            price_id=identifier("price"),
            price_revision=1,
        )
        self.insert(connection, "room_reservation_revisions", **(values | changes))
