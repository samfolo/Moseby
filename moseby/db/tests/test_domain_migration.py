"""Exercise migrations and constraints against file-backed SQLite."""

import json
import tempfile
import unittest
from pathlib import Path

import sqlalchemy as sa
from alembic import command
from alembic.config import Config
from sqlalchemy.exc import IntegrityError, OperationalError

from moseby.db.connection import create_database_engine
from moseby.db.transaction import transaction

ROOT = Path(__file__).resolve().parents[3]


def identifier(prefix: str, number: int = 1) -> str:
    return f"{prefix}_{number:026d}"


class DomainMigrationTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.engine = create_database_engine(
            sa.URL.create("sqlite", database=f"{self.directory.name}/test.db"),
            timeout=0.05,
        )
        self.config = Config(str(ROOT / "alembic.ini"))
        self.migrate("head")
        self.metadata = sa.MetaData()
        with self.engine.connect() as connection:
            self.metadata.reflect(connection)
        self.addCleanup(self.directory.cleanup)
        self.addCleanup(self.engine.dispose)

    def migrate(self, revision, *, downgrade=False):
        with transaction(self.engine, write=True) as connection:
            self.config.attributes["connection"] = connection
            try:
                action = command.downgrade if downgrade else command.upgrade
                action(self.config, revision)
            finally:
                self.config.attributes.pop("connection", None)

    def insert(self, connection, table, **values):
        connection.execute(self.metadata.tables[table].insert().values(**values))

    def seed(self, connection):
        self.insert(
            connection, "hotels", id=identifier("hotel"), created_at=0, name="Hotel"
        )
        self.insert(
            connection, "hotels", id=identifier("hotel", 2), created_at=0, name="Other"
        )
        self.insert(connection, "prices", id=identifier("price"), created_at=0)
        self.insert(
            connection,
            "price_versions",
            price_id=identifier("price"),
            revision=1,
            amount_minor=100,
            currency="GBP",
            created_at=0,
        )
        self.insert(
            connection,
            "rooms",
            id=identifier("room"),
            hotel_id=identifier("hotel"),
            created_at=0,
            label="Rose",
            description="",
            tier="ROOM_TIER_STANDARD",
            number_of_bathrooms=1,
            in_service=1,
            price_id=identifier("price"),
        )
        for number in (1, 2):
            self.insert(
                connection,
                "bookings",
                id=identifier("booking", number),
                hotel_id=identifier("hotel", number),
                created_at=0,
                name="Stay",
            )
            self.insert(
                connection,
                "booking_revisions",
                booking_id=identifier("booking", number),
                revision=1,
                status="BOOKING_STATUS_CONFIRMED",
                recorded_at=0,
            )
            self.insert(
                connection,
                "parties",
                id=identifier("party", number),
                booking_id=identifier("booking", number),
                created_at=0,
            )
            self.insert(
                connection,
                "guests",
                id=identifier("guest", number),
                party_id=identifier("party", number),
                created_at=0,
                first_name="Dan",
                last_name="Guest",
                age=30,
            )
        self.insert(
            connection,
            "room_reservations",
            id=identifier("room_reservation"),
            booking_id=identifier("booking"),
            room_id=identifier("room"),
            created_at=0,
        )
        self.room_revision(connection, 1)
        self.insert(
            connection,
            "room_keys",
            id=identifier("room_key"),
            room_reservation_id=identifier("room_reservation"),
            created_at=0,
        )
        self.insert(
            connection,
            "venues",
            id=identifier("venue"),
            created_at=0,
            name="Court",
            capacity=0,
        )
        self.insert(
            connection,
            "activities",
            id=identifier("activity"),
            created_at=0,
            venue_id=identifier("venue"),
            title="Tennis",
            type="ACTIVITY_TYPE_TENNIS",
            description="",
            min_date=10,
            max_date=20,
            capacity=4,
            min_booking_size=2,
            max_booking_size=4,
            minimum_age=0,
            price_id=identifier("price"),
            price_unit="ACTIVITY_PRICE_UNIT_PER_GUEST",
        )
        self.insert(
            connection,
            "activity_reservations",
            id=identifier("activity_reservation"),
            created_at=0,
            party_id=identifier("party"),
            guest_id=identifier("guest"),
            activity_id=identifier("activity"),
        )
        self.activity_revision(connection, 1)

    def room_revision(self, connection, revision, **changes):
        values = dict(
            room_reservation_id=identifier("room_reservation"),
            revision=revision,
            min_date=10,
            max_date=20,
            cancelled=0,
            price_id=identifier("price"),
            price_revision=1,
            recorded_at=revision,
        )
        self.insert(connection, "room_reservation_revisions", **(values | changes))

    def activity_revision(self, connection, revision, **changes):
        values = dict(
            activity_reservation_id=identifier("activity_reservation"),
            revision=revision,
            cancelled=0,
            price_id=identifier("price"),
            price_revision=1,
            price_unit="ACTIVITY_PRICE_UNIT_PER_GUEST",
            recorded_at=revision,
        )
        self.insert(connection, "activity_reservation_revisions", **(values | changes))

    def invalid(self, connection, action):
        with self.assertRaises(IntegrityError), connection.begin_nested():
            action()

    def test_upgrade_downgrade_and_reapply(self):
        with transaction(self.engine, write=True) as connection:
            self.seed(connection)
            inspector = sa.inspect(connection)
            self.assertEqual(len(inspector.get_table_names()), 20)
            for name in inspector.get_table_names():
                if name != "alembic_version":
                    self.assertTrue(inspector.get_table_options(name)["sqlite_strict"])
                    self.assertTrue(inspector.get_pk_constraint(name)["name"])
                    for fk in inspector.get_foreign_keys(name):
                        self.assertTrue(fk["name"])
            self.assertEqual(
                connection.exec_driver_sql("PRAGMA foreign_key_check").all(), []
            )
        self.migrate("base", downgrade=True)
        with self.engine.connect() as connection:
            self.assertEqual(
                sa.inspect(connection).get_table_names(), ["alembic_version"]
            )
        self.migrate("head")
        self.migrate("head")

    def test_transaction_rollback_including_ddl(self):
        with self.assertRaisesRegex(RuntimeError, "abort"):
            with transaction(self.engine, write=True) as connection:
                self.seed(connection)
                connection.exec_driver_sql("CREATE TABLE rollback_probe (id INTEGER)")
                raise RuntimeError("abort")
        with self.engine.connect() as connection:
            self.assertFalse(sa.inspect(connection).has_table("rollback_probe"))
            self.assertEqual(
                connection.execute(
                    sa.select(sa.func.count()).select_from(
                        self.metadata.tables["hotels"]
                    )
                ).scalar_one(),
                0,
            )

    def test_failed_migration_rolls_back_all_tables(self):
        self.migrate("base", downgrade=True)
        with self.assertRaisesRegex(RuntimeError, "abort"):
            with transaction(self.engine, write=True) as connection:
                self.config.attributes["connection"] = connection
                try:
                    command.upgrade(self.config, "head")
                    raise RuntimeError("abort")
                finally:
                    self.config.attributes.pop("connection")
        with self.engine.connect() as connection:
            self.assertEqual(
                sa.inspect(connection).get_table_names(), ["alembic_version"]
            )
            self.assertIsNone(
                connection.exec_driver_sql(
                    "SELECT version_num FROM alembic_version"
                ).first()
            )

    def test_history_and_terminal_cancellation(self):
        with transaction(self.engine, write=True) as connection:
            self.seed(connection)
            self.invalid(connection, lambda: self.room_revision(connection, 3))
            self.invalid(
                connection,
                lambda: connection.execute(
                    self.metadata.tables["price_versions"]
                    .update()
                    .values(amount_minor=500)
                ),
            )
            self.invalid(
                connection,
                lambda: connection.execute(
                    self.metadata.tables["booking_revisions"].delete()
                ),
            )
            self.room_revision(
                connection, 2, cancelled=1, cancellation_reason="Change of room"
            )
            self.invalid(connection, lambda: self.room_revision(connection, 3))
            self.activity_revision(
                connection, 2, cancelled=1, cancellation_reason="Changed mind"
            )
            self.invalid(connection, lambda: self.activity_revision(connection, 3))
            self.insert(
                connection,
                "booking_revisions",
                booking_id=identifier("booking"),
                revision=2,
                status="BOOKING_STATUS_CANCELLED",
                cancellation_reason="Cancelled stay",
                recorded_at=2,
            )
            self.invalid(
                connection,
                lambda: self.insert(
                    connection,
                    "booking_revisions",
                    booking_id=identifier("booking"),
                    revision=3,
                    status="BOOKING_STATUS_CONFIRMED",
                    recorded_at=3,
                ),
            )

    def test_cross_hotel_and_guest_party_references(self):
        with transaction(self.engine, write=True) as connection:
            self.seed(connection)
            self.invalid(
                connection,
                lambda: self.insert(
                    connection,
                    "room_reservations",
                    id=identifier("room_reservation", 2),
                    booking_id=identifier("booking", 2),
                    room_id=identifier("room"),
                    created_at=0,
                ),
            )
            self.invalid(
                connection,
                lambda: self.insert(
                    connection,
                    "activity_reservations",
                    id=identifier("activity_reservation", 2),
                    party_id=identifier("party"),
                    guest_id=identifier("guest", 2),
                    activity_id=identifier("activity"),
                    created_at=0,
                ),
            )
            self.invalid(
                connection,
                lambda: self.insert(
                    connection,
                    "parties",
                    id=identifier("party", 3),
                    booking_id=identifier("booking"),
                    created_at=0,
                ),
            )
            self.invalid(
                connection,
                lambda: connection.execute(
                    self.metadata.tables["guests"]
                    .update()
                    .values(party_id=identifier("party", 2))
                ),
            )
            self.invalid(
                connection,
                lambda: self.insert(
                    connection,
                    "room_keys",
                    id=identifier("room_key", 2),
                    room_reservation_id=identifier("room_reservation", 5),
                    created_at=0,
                ),
            )

    def test_key_dates_follow_revision_and_revocation_is_permanent(self):
        with transaction(self.engine, write=True) as connection:
            self.seed(connection)
            query = sa.text(
                "SELECT eligible AND min_date <= :now AND :now < max_date FROM room_key_access WHERE id = :id"
            )

            def effective(now):
                return connection.execute(
                    query, {"now": now, "id": identifier("room_key")}
                ).scalar_one()

            self.assertFalse(effective(9))
            self.assertTrue(effective(10))
            self.assertFalse(effective(20))
            self.room_revision(connection, 2, max_date=30)
            self.assertTrue(effective(20))
            keys = self.metadata.tables["room_keys"]
            connection.execute(
                keys.update().values(deactivated_at=15, deactivation_reason="Lost")
            )
            self.assertFalse(effective(20))
            self.invalid(
                connection,
                lambda: connection.execute(
                    keys.update().values(deactivated_at=None, deactivation_reason=None)
                ),
            )
            self.invalid(
                connection,
                lambda: connection.execute(
                    keys.update().values(
                        room_reservation_id=identifier("room_reservation", 2)
                    )
                ),
            )

    def test_parent_cancellation_does_not_rewrite_key_or_activity_history(self):
        with transaction(self.engine, write=True) as connection:
            self.seed(connection)
            self.insert(
                connection,
                "booking_revisions",
                booking_id=identifier("booking"),
                revision=2,
                status="BOOKING_STATUS_CANCELLED",
                cancellation_reason="Cancelled stay",
                recorded_at=2,
            )
            row = connection.exec_driver_sql(
                "SELECT eligible, deactivated_at FROM room_key_access"
            ).one()
            self.assertEqual(tuple(row), (0, None))
            self.assertEqual(
                connection.exec_driver_sql(
                    "SELECT revision, cancelled FROM current_activity_reservation_revisions"
                ).one(),
                (1, 0),
            )

    def test_party_reference_membership_and_classification(self):
        with transaction(self.engine, write=True) as connection:
            self.seed(connection)

            def detail(refs, status="GUEST_REFERENCE_STATUS_RESOLVED"):
                self.insert(
                    connection,
                    "party_details",
                    id=identifier("party_detail"),
                    party_id=identifier("party"),
                    created_at=0,
                    text="Dan likes pottery",
                    reference_format_version=1,
                    reference_status=status,
                    referenced_guest_ids_json=json.dumps(refs),
                )

            for refs in [
                [identifier("guest", 2)],
                [identifier("guest")] * 2,
                [None],
                {"guest": identifier("guest")},
            ]:
                self.invalid(connection, lambda refs=refs: detail(refs))
            self.invalid(
                connection,
                lambda: detail([identifier("guest")], "GUEST_REFERENCE_STATUS_PENDING"),
            )
            detail([identifier("guest")])

    def test_activity_types_can_be_added_without_a_migration(self):
        from pydantic import TypeAdapter, ValidationError

        from moseby.contracts.activities import (
            ActivityTypeCode,
            SearchActivitiesRequestPayload,
        )

        code = "ACTIVITY_TYPE_KAYAKING"
        with transaction(self.engine, write=True) as connection:
            self.seed(connection)
            activities = self.metadata.tables["activities"]
            types = self.metadata.tables["activity_types"]
            self.invalid(
                connection,
                lambda: connection.execute(activities.update().values(type=code)),
            )
            self.insert(connection, "activity_types", code=code, name="Kayaking")
            connection.execute(activities.update().values(type=code))
            self.assertEqual(
                connection.execute(sa.select(activities.c.type)).scalar_one(), code
            )
            connection.execute(
                types.update().where(types.c.code == code).values(name="Sea kayaking")
            )
            self.invalid(
                connection,
                lambda: connection.execute(types.delete().where(types.c.code == code)),
            )
            self.invalid(
                connection,
                lambda: connection.execute(
                    types.update()
                    .where(types.c.code == code)
                    .values(code="ACTIVITY_TYPE_CANOEING")
                ),
            )
            self.invalid(
                connection,
                lambda: self.insert(
                    connection, "activity_types", code="kayaking", name="Kayaking"
                ),
            )
            self.assertEqual(
                connection.exec_driver_sql(
                    "SELECT version_num FROM alembic_version"
                ).scalar_one(),
                "0001_domain",
            )
        self.assertEqual(TypeAdapter(ActivityTypeCode).validate_python(code), code)
        self.assertEqual(SearchActivitiesRequestPayload(types=[code]).types, [code])
        with self.assertRaises(ValidationError):
            TypeAdapter(ActivityTypeCode).validate_python("kayaking")
        # Rollback must remove caller-added lookup rows as well as seeded rows.
        self.migrate("base", downgrade=True)
        self.migrate("head")

    def test_row_checks_and_known_enum_values(self):
        with transaction(self.engine, write=True) as connection:
            self.seed(connection)
            self.invalid(
                connection,
                lambda: self.room_revision(connection, 2, min_date=20, max_date=20),
            )
            self.invalid(
                connection, lambda: self.room_revision(connection, 2, cancelled=1)
            )
            self.invalid(
                connection,
                lambda: self.room_revision(
                    connection, 2, cancellation_reason="Not cancelled"
                ),
            )
            self.invalid(
                connection, lambda: self.room_revision(connection, 2, price_revision=9)
            )
            self.invalid(
                connection,
                lambda: connection.execute(
                    self.metadata.tables["guests"]
                    .update()
                    .values(contact_preference="CONTACT_PREFERENCE_EMAIL")
                ),
            )
            self.invalid(
                connection,
                lambda: connection.execute(
                    self.metadata.tables["rooms"].update().values(tier="VIP")
                ),
            )
            self.invalid(
                connection,
                lambda: self.insert(
                    connection,
                    "hotels",
                    id=identifier("room"),
                    created_at=0,
                    name="Wrong prefix",
                ),
            )
            self.invalid(
                connection,
                lambda: self.insert(
                    connection,
                    "price_versions",
                    price_id=identifier("price"),
                    revision=2,
                    amount_minor=-1,
                    currency="GBP",
                    created_at=0,
                ),
            )
            self.invalid(
                connection,
                lambda: self.insert(
                    connection,
                    "price_versions",
                    price_id=identifier("price"),
                    revision=2,
                    amount_minor=1,
                    currency="gbp",
                    created_at=0,
                ),
            )

    def test_second_writer_cannot_read_then_reserve_under_the_same_write_lock(self):
        with transaction(self.engine, write=True) as first:
            self.assertEqual(
                first.exec_driver_sql("PRAGMA foreign_keys").scalar_one(), 1
            )
            with self.assertRaises(OperationalError):
                with transaction(self.engine, write=True):
                    self.fail("Second writer entered before first writer finished")
        with transaction(self.engine, write=True) as second:
            self.assertEqual(
                second.exec_driver_sql("PRAGMA foreign_keys").scalar_one(), 1
            )


if __name__ == "__main__":
    unittest.main()
