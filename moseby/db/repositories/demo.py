"""Create a small, repeatable hotel fixture for the command-line demonstration."""

from sqlalchemy import Connection, select
from sqlalchemy.dialects.sqlite import insert

from moseby.domain.enums import BedType, RoomTier, StaffRole

from ..tables import beds, hotels, price_versions, prices, rooms, staff_members
from ._writes import require_write_transaction

HOTEL_ID = "hotel_00000000000000000000000001"
STAFF_MEMBER_ID = "staff_member_00000000000000000000000001"
PRICE_ID = "price_00000000000000000000000001"


def seed(connection: Connection, *, now: int) -> None:
    """Insert missing demo resources; retain any changes made to existing rows."""
    require_write_transaction(connection)
    rows = [
        (hotels, dict(id=HOTEL_ID, name="Moseby Resort")),
        (
            staff_members,
            dict(
                id=STAFF_MEMBER_ID,
                hotel_id=HOTEL_ID,
                staff_code="CONCIERGE",
                first_name="Alex",
                last_name="Morgan",
                role=StaffRole.CONCIERGE,
            ),
        ),
        (prices, dict(id=PRICE_ID)),
        (
            price_versions,
            dict(price_id=PRICE_ID, revision=1, amount_minor=20000, currency="GBP"),
        ),
    ]
    for number, label, tier, bed in (
        (1, "Rose", RoomTier.STANDARD, BedType.KING),
        (2, "Garden", RoomTier.VIP, BedType.TWIN),
    ):
        room_id = f"room_{number:026d}"
        rows.append(
            (
                rooms,
                dict(
                    id=room_id,
                    hotel_id=HOTEL_ID,
                    label=label,
                    description="Garden-facing room",
                    tier=tier,
                    number_of_bathrooms=1,
                    in_service=True,
                    price_id=PRICE_ID,
                ),
            )
        )
        rows.append((beds, dict(id=f"bed_{number:026d}", room_id=room_id, type=bed)))
    for table, values in rows:
        # Revision triggers run before conflict handling, so skip an existing rate explicitly.
        if (
            table is price_versions
            and connection.scalar(
                select(price_versions.c.price_id).where(
                    price_versions.c.price_id == PRICE_ID,
                    price_versions.c.revision == 1,
                )
            )
            is not None
        ):
            continue
        if "created_at" in table.c:
            values["created_at"] = now
        if "updated_at" in table.c:
            values["updated_at"] = now
        connection.execute(insert(table).values(**values).on_conflict_do_nothing())
