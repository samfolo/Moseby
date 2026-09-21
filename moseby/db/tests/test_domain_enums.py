"""Keep shared enum choices aligned with the migrated database."""

import re

from pydantic import ValidationError
from sqlalchemy import inspect

from moseby.db.models.rooms import BedRow
from moseby.db.tests.fixtures import NOW, StayDatabaseTestCase, identifier
from moseby.domain.enums import (
    ActivityPriceUnit,
    BedType,
    BookingStatus,
    ContactPreference,
    GuestReferenceStatus,
    RoomTier,
    StaffRole,
)
from moseby.runtime.enums import JobStatus, RunStatus, TaskStatus
from moseby.runtime.models.incoming_thread_records import (
    IncomingThreadRecordDeliveryMode,
    IncomingThreadRecordKind,
)
from moseby.runtime.models.thread_records import ThreadRecordKind


class DomainEnumTests(StayDatabaseTestCase):
    def test_shared_choices_match_database_constraints(self):
        """Shared enum values must agree with the choices allowed by the database."""
        with self.engine.connect() as connection:
            inspector = inspect(connection)
            for table, enum in (
                ("activities", ActivityPriceUnit),
                ("activity_reservation_revisions", ActivityPriceUnit),
                ("beds", BedType),
                ("booking_revisions", BookingStatus),
                ("guests", ContactPreference),
                ("party_details", GuestReferenceStatus),
                ("rooms", RoomTier),
                ("staff_members", StaffRole),
                ("runs", RunStatus),
                ("jobs", JobStatus),
                ("tasks", TaskStatus),
                ("thread_records", ThreadRecordKind),
                ("incoming_thread_records", IncomingThreadRecordKind),
                ("incoming_thread_records", IncomingThreadRecordDeliveryMode),
            ):
                with self.subTest(table=table):
                    constraints = " ".join(
                        check["sqltext"]
                        for check in inspector.get_check_constraints(table)
                    )
                    prefix = (
                        re.sub(r"(?<!^)(?=[A-Z])", "_", enum.__name__).upper() + "_"
                    )
                    stored = set(re.findall("'(" + prefix + "[A-Z_]+)'", constraints))
                    self.assertEqual(stored, {member.value for member in enum})

    def test_row_parses_stored_enum_strings_without_weakening_other_fields(self):
        """Enum strings parse as members while timestamp fields remain strict."""
        values = dict(
            id=identifier("bed"),
            room_id=identifier("room"),
            type="BED_TYPE_KING",
            created_at=NOW,
            updated_at=NOW,
        )
        self.assertIs(BedRow.model_validate(values).type, BedType.KING)
        for changes in ({"type": "BED_TYPE_MISSPELLED"}, {"created_at": str(NOW)}):
            with self.assertRaises(ValidationError):
                BedRow.model_validate(values | changes)
