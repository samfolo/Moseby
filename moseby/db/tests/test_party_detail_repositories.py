"""Saved evidence stays private, searchable and separate from inferred guest facts."""

import json

from alembic import command
from alembic.config import Config
from sqlalchemy import delete, update

from moseby.db.models.party_details import PartyDetailFilters
from moseby.db.pagination import InvalidCursor, PageRequest
from moseby.db.repositories import party_details
from moseby.db.tests.fixtures import ROOT, StayDatabaseTestCase, identifier
from moseby.db.transaction import transaction


class PartyDetailRepositoryTests(StayDatabaseTestCase):
    def setUp(self):
        super().setUp()
        with transaction(self.engine, write=True) as connection:
            self.add_guest(connection, 3)
            for number, party, status, guest_ids, text in (
                (1, 1, "RESOLVED", [1, 3], "Dan prefers 50% cacao_ café."),
                (2, 2, "RESOLVED", [2], "Other hotel's private evidence"),
                (3, 1, "PENDING", [], "Dan mentioned tennis"),
                (4, 1, "RESOLVED", [], "Weather is lovely"),
                (5, 1, "AMBIGUOUS", [], "Dan called again"),
                (6, 1, "FAILED", [], "The call was unclear"),
            ):
                self.insert(
                    connection,
                    "party_details",
                    id=identifier("party_detail", number),
                    party_id=identifier("party", party),
                    text=text,
                    referenced_guest_ids_json=json.dumps(
                        [identifier("guest", n) for n in guest_ids]
                    ),
                    reference_format_version=1,
                    reference_status=f"GUEST_REFERENCE_STATUS_{status}",
                )

    def test_json_references_are_typed_and_classification_outcomes_stay_distinct(self):
        with transaction(self.engine) as connection:
            rows = party_details.find_all_by_party_id(
                connection, identifier("party"), hotel_id=identifier("hotel")
            ).items
            self.assertEqual(len(rows), 5)
            self.assertEqual(
                rows[0].referenced_guest_ids, [identifier("guest", n) for n in (1, 3)]
            )
            self.assertEqual(
                [row.reference_status for row in rows[1:]],
                [
                    "GUEST_REFERENCE_STATUS_PENDING",
                    "GUEST_REFERENCE_STATUS_RESOLVED",
                    "GUEST_REFERENCE_STATUS_AMBIGUOUS",
                    "GUEST_REFERENCE_STATUS_FAILED",
                ],
            )
            self.assertTrue(all(row.referenced_guest_ids == [] for row in rows[1:]))

    def test_single_and_filtered_reads_do_not_reveal_another_hotels_notes(self):
        with transaction(self.engine) as connection:
            scope = dict(hotel_id=identifier("hotel"))
            for number in (2, 999):
                self.assertIsNone(
                    party_details.find_by_id(
                        connection, identifier("party_detail", number), **scope
                    )
                )
            result = party_details.search(
                connection,
                PartyDetailFilters(
                    party_ids=[identifier("party", 1), identifier("party", 2)]
                ),
                **scope,
            )
            self.assertEqual(len(result.items), 5)
            self.assertTrue(
                all(row.party_id == identifier("party") for row in result.items)
            )
            self.assertEqual(
                party_details.find_all_by_party_id(
                    connection, identifier("party", 2), **scope
                ).items,
                [],
            )

    def test_guest_filters_match_exact_saved_references_without_duplicating_notes(self):
        with transaction(self.engine) as connection:
            result = party_details.search(
                connection,
                PartyDetailFilters(
                    party_ids=[identifier("party")],
                    guest_ids=[identifier("guest", n) for n in (1, 3, 3)],
                ),
                hotel_id=identifier("hotel"),
                page=PageRequest(limit=1),
            )
            self.assertEqual(
                [row.id for row in result.items], [identifier("party_detail")]
            )
            self.assertIsNone(result.next_cursor)
            for guest in (2, 10):
                self.assertEqual(
                    party_details.search(
                        connection,
                        PartyDetailFilters(
                            party_ids=[identifier("party")],
                            guest_ids=[identifier("guest", guest)],
                        ),
                        hotel_id=identifier("hotel"),
                    ).items,
                    [],
                )

    def test_keywords_ignore_case_and_accents_and_intersect_with_references(self):
        with transaction(self.engine) as connection:
            for text, expected in (
                ("50%", [1]),
                ("_", []),
                ("café", [1]),
                ("dan", [1, 3, 5]),
                ("CAFE", [1]),
                ("CAFE DAN", [1]),
                ("café TENNIS", []),
                ("ten", []),
                ("dan OR tennis", []),
                ('"dan"*', [1, 3, 5]),
                ("cafe\u0301", [1]),
                (" -- ", []),
                ("' OR 1=1 --", []),
            ):
                result = party_details.search(
                    connection,
                    PartyDetailFilters(party_ids=[identifier("party")], text=text),
                    hotel_id=identifier("hotel"),
                )
                self.assertEqual(
                    [row.id for row in result.items],
                    [identifier("party_detail", n) for n in expected],
                )
            result = party_details.search(
                connection,
                PartyDetailFilters(
                    party_ids=[identifier("party")],
                    guest_ids=[identifier("guest")],
                    text="tennis",
                ),
                hotel_id=identifier("hotel"),
            )
            self.assertEqual(result.items, [])

    def test_cursor_continues_tied_notes_and_rejects_changed_filters(self):
        with transaction(self.engine) as connection:
            first = party_details.find_all_by_party_id(
                connection,
                identifier("party"),
                hotel_id=identifier("hotel"),
                page=PageRequest(limit=2),
            )
            rest = party_details.find_all_by_party_id(
                connection,
                identifier("party"),
                hotel_id=identifier("hotel"),
                page=PageRequest(cursor=first.next_cursor),
            )
            self.assertEqual(
                [row.id for row in first.items + rest.items],
                [identifier("party_detail", n) for n in (1, 3, 4, 5, 6)],
            )
            for text, hotel in (
                ("Dan", identifier("hotel")),
                (None, identifier("hotel", 2)),
            ):
                with self.assertRaises(InvalidCursor):
                    party_details.search(
                        connection,
                        PartyDetailFilters(party_ids=[identifier("party")], text=text),
                        hotel_id=hotel,
                        page=PageRequest(cursor=first.next_cursor),
                    )

    def test_parent_cancellation_preserves_the_evidence(self):
        with transaction(self.engine, write=True) as connection:
            self.insert(
                connection,
                "booking_revisions",
                booking_id=identifier("booking"),
                revision=2,
                status="BOOKING_STATUS_CANCELLED",
                cancellation_reason="Cancelled trip",
            )
            row = party_details.find_by_id(
                connection, identifier("party_detail"), hotel_id=identifier("hotel")
            )
            self.assertEqual(
                row.referenced_guest_ids, [identifier("guest", n) for n in (1, 3)]
            )

    def test_keyword_filter_precedes_pagination_and_keeps_hotel_scope(self):
        with transaction(self.engine) as connection:
            filters = PartyDetailFilters(
                party_ids=[identifier("party", n) for n in (1, 2)], text="DAN"
            )
            first = party_details.search(
                connection,
                filters,
                hotel_id=identifier("hotel"),
                page=PageRequest(limit=1),
            )
            rest = party_details.search(
                connection,
                filters,
                hotel_id=identifier("hotel"),
                page=PageRequest(cursor=first.next_cursor),
            )
            self.assertEqual(
                [row.id for row in first.items + rest.items],
                [identifier("party_detail", n) for n in (1, 3, 5)],
            )
            hidden = party_details.search(
                connection,
                PartyDetailFilters(
                    party_ids=filters.party_ids, text="private evidence"
                ),
                hotel_id=identifier("hotel"),
            )
            self.assertEqual(hidden.items, [])

    def test_text_index_tracks_edits_deletes_and_transaction_rollback(self):
        table = self.metadata.tables["party_details"]
        with transaction(self.engine, write=True) as connection:
            connection.execute(
                update(table)
                .where(table.c.id == identifier("party_detail", 3))
                .values(text="Dan enjoys pottery")
            )
            connection.execute(
                delete(table).where(table.c.id == identifier("party_detail", 5))
            )
        with self.assertRaisesRegex(RuntimeError, "roll back"):
            with transaction(self.engine, write=True) as connection:
                connection.execute(
                    update(table)
                    .where(table.c.id == identifier("party_detail", 3))
                    .values(text="Dan enjoys archery")
                )
                raise RuntimeError("roll back")
        with transaction(self.engine) as connection:
            for text, expected in (
                ("tennis", []),
                ("pottery", [3]),
                ("archery", []),
                ("again", []),
            ):
                result = party_details.search(
                    connection,
                    PartyDetailFilters(party_ids=[identifier("party")], text=text),
                    hotel_id=identifier("hotel"),
                )
                self.assertEqual(
                    [row.id for row in result.items],
                    [identifier("party_detail", n) for n in expected],
                )

    def test_migration_indexes_existing_notes_and_downgrade_preserves_them(self):
        with transaction(self.engine, write=True) as connection:
            config = Config(str(ROOT / "alembic.ini"))
            config.attributes["connection"] = connection
            command.downgrade(config, "0003_incoming_cancellation")
            count = connection.exec_driver_sql(
                "SELECT count(*) FROM party_details"
            ).scalar_one()
            self.assertEqual(count, 6)
            command.upgrade(config, "head")
            result = party_details.search(
                connection,
                PartyDetailFilters(party_ids=[identifier("party")], text="CAFE"),
                hotel_id=identifier("hotel"),
            )
            self.assertEqual(
                [row.id for row in result.items], [identifier("party_detail")]
            )
