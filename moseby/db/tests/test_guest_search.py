"""Keep guest-name search consistent with the rows it describes."""

from alembic import command
from alembic.config import Config

from moseby.db.models.guests import GuestFilters
from moseby.db.repositories import guests
from moseby.db.tests.fixtures import ROOT, StayDatabaseTestCase, identifier
from moseby.db.transaction import transaction


class GuestSearchTests(StayDatabaseTestCase):
    def matches(self, connection, name):
        return [
            row.id
            for row in guests.search(
                connection, GuestFilters(name=name), hotel_id=identifier("hotel")
            ).items
        ]

    def test_name_index_follows_edits_deletions_and_rollback(self):
        """Search follows saved name changes, while a rolled-back edit leaves the old name searchable."""
        with transaction(self.engine, write=True) as connection:
            self.add_guest(connection, 3, first_name="Élodie", last_name="Martin")
            guest_table = self.metadata.tables["guests"]
            self.assertEqual(
                self.matches(connection, "elodie martin"), [identifier("guest", 3)]
            )
            with connection.begin_nested() as savepoint:
                connection.execute(
                    guest_table.update()
                    .where(guest_table.c.id == identifier("guest", 3))
                    .values(first_name="Alice", preferred_name="Ally")
                )
                self.assertEqual(self.matches(connection, "elodie"), [])
                self.assertEqual(
                    self.matches(connection, "ally"), [identifier("guest", 3)]
                )
                savepoint.rollback()
            self.assertEqual(
                self.matches(connection, "elodie"), [identifier("guest", 3)]
            )
            self.assertEqual(self.matches(connection, "ally"), [])
            connection.execute(
                guest_table.update()
                .where(guest_table.c.id == identifier("guest", 3))
                .values(first_name="Alice", last_name="Jones", preferred_name="Ally")
            )
            self.assertEqual(self.matches(connection, "Martin"), [])
            self.assertEqual(
                self.matches(connection, "Jones Ally"), [identifier("guest", 3)]
            )
            connection.execute(
                guest_table.delete().where(guest_table.c.id == identifier("guest", 3))
            )
            self.assertEqual(self.matches(connection, "Ally"), [])

    def test_upgrade_indexes_existing_guests_without_changing_their_data(self):
        """Installing the index makes existing names searchable and preserves the guest rows."""
        with transaction(self.engine, write=True) as connection:
            config = Config(str(ROOT / "alembic.ini"))
            config.attributes["connection"] = connection
            command.downgrade(config, "0005_agent_attribution")
            self.add_guest(connection, 3, first_name="Élodie", last_name="Martin")
            before = guests.find_by_id(
                connection, identifier("guest", 3), hotel_id=identifier("hotel")
            )
            command.upgrade(config, "head")
            self.assertEqual(
                self.matches(connection, "elodie"), [identifier("guest", 3)]
            )
            self.assertEqual(
                guests.find_by_id(connection, before.id, hotel_id=identifier("hotel")),
                before,
            )
