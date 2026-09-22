"""The demo starts with useful choices and preserves staff changes on reinitialisation."""

from sqlalchemy import func, select

from moseby.db.repositories import demo, room_keys
from moseby.db.tests.fixtures import NOW, StayDatabaseTestCase
from moseby.db.transaction import transaction


class DemoSeedTests(StayDatabaseTestCase):
    def seed(self, connection):
        demo.seed(connection, now=NOW)

    def test_seed_provides_room_choices_and_keeps_existing_keys_revoked(self):
        """Two parties have rooms and keys, spare rooms remain, and rerunning does not revive a lost key."""
        with transaction(self.engine, write=True) as connection:
            expected = {
                "rooms": 6,
                "guests": 4,
                "bookings": 2,
                "room_keys": 2,
                "activities": 21,
            }
            for name, count in expected.items():
                self.assertEqual(
                    connection.scalar(
                        select(func.count()).select_from(self.metadata.tables[name])
                    ),
                    count,
                )
            room_keys.deactivate(
                connection,
                demo.STANDARD_KEY_ID,
                reason="Lost",
                hotel_id=demo.HOTEL_ID,
                now=NOW + 1,
            )
            demo.seed(connection, now=NOW + 2)
            for name, count in expected.items():
                self.assertEqual(
                    connection.scalar(
                        select(func.count()).select_from(self.metadata.tables[name])
                    ),
                    count,
                )
            key = room_keys.find_by_id(
                connection, demo.STANDARD_KEY_ID, hotel_id=demo.HOTEL_ID, now=NOW + 2
            )
            self.assertFalse(key.effective)
