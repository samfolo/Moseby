"""Create a small, repeatable hotel fixture for the command-line demonstration."""

from datetime import timedelta

from sqlalchemy import Connection, select
from sqlalchemy.dialects.sqlite import insert

from moseby.domain.enums import BedType, RoomTier, StaffRole

from ..models.activities import NewActivity
from ..models.bookings import NewBooking
from ..models.filters import DateRange
from ..models.guests import NewGuest
from ..models.room_reservations import NewRoomReservation
from ..models.stays import NewStay
from ..operations import stays
from ..tables import beds, hotels, price_versions, prices, rooms, staff_members, venues
from ..timestamps import to_datetime, to_microseconds
from . import activities, bookings
from ._writes import require_write_transaction

HOTEL_ID = "hotel_00000000000000000000000001"
STAFF_MEMBER_ID = "staff_member_00000000000000000000000001"
ROOM_PRICE_ID = "price_00000000000000000000000001"
ACTIVITY_PRICE_ID = "price_00000000000000000000000002"
VENUE_ID = "venue_00000000000000000000000001"
BOOKING_ID = "booking_00000000000000000000000001"
PARTY_ID = "party_00000000000000000000000001"
ROOM_RESERVATION_ID = "room_reservation_00000000000000000000000001"
ROSE_ROOM_ID = "room_00000000000000000000000001"
GARDEN_ROOM_ID = "room_00000000000000000000000002"
ROSE_BED_ID = "bed_00000000000000000000000001"
GARDEN_BED_ID = "bed_00000000000000000000000002"
DAN_MORGAN_ID = "guest_00000000000000000000000001"
DAN_PATEL_ID = "guest_00000000000000000000000002"


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
                staff_code="SFLR48217",
                first_name="Sam",
                last_name="Folorunsho",
                role=StaffRole.CONCIERGE,
            ),
        ),
        (prices, dict(id=ROOM_PRICE_ID)),
        (
            price_versions,
            dict(
                price_id=ROOM_PRICE_ID, revision=1, amount_minor=20000, currency="GBP"
            ),
        ),
    ]
    for room_id, bed_id, label, tier, bed_type in (
        (ROSE_ROOM_ID, ROSE_BED_ID, "Rose", RoomTier.STANDARD, BedType.KING),
        (GARDEN_ROOM_ID, GARDEN_BED_ID, "Garden", RoomTier.VIP, BedType.TWIN),
    ):
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
                    price_id=ROOM_PRICE_ID,
                ),
            )
        )
        rows.append((beds, dict(id=bed_id, room_id=room_id, type=bed_type)))
    for table, values in rows:
        # Revision triggers run before conflict handling, so skip an existing rate explicitly.
        if (
            table is price_versions
            and connection.scalar(
                select(price_versions.c.price_id).where(
                    price_versions.c.price_id == ROOM_PRICE_ID,
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

    _seed_stay(connection, now=now)
    _seed_activities(connection, now=now)


def _seed_activities(connection: Connection, *, now: int) -> None:
    """Add seven days of complimentary sessions without changing existing events."""
    connection.execute(
        insert(venues)
        .values(
            id=VENUE_ID,
            name="Moseby Resort Grounds",
            capacity=100,
            created_at=now,
            updated_at=now,
        )
        .on_conflict_do_nothing()
    )
    connection.execute(
        insert(prices)
        .values(id=ACTIVITY_PRICE_ID, created_at=now)
        .on_conflict_do_nothing()
    )
    if (
        connection.scalar(
            select(price_versions.c.price_id).where(
                price_versions.c.price_id == ACTIVITY_PRICE_ID
            )
        )
        is None
    ):
        connection.execute(
            insert(price_versions).values(
                price_id=ACTIVITY_PRICE_ID,
                revision=1,
                amount_minor=0,
                currency="GBP",
                created_at=now,
            )
        )
    today = to_datetime(now).replace(hour=0, minute=0, second=0, microsecond=0)
    for day in range(7):
        for number, title, code, hour, capacity, minimum, maximum in (
            (1, "Pottery workshop", "ACTIVITY_TYPE_POTTERY", 14, 8, 1, 8),
            (2, "Tennis court", "ACTIVITY_TYPE_TENNIS", 16, 2, 2, 2),
            (3, "Guided garden tour", "ACTIVITY_TYPE_GUIDED_TOUR", 18, None, 1, 100),
        ):
            start = today + timedelta(days=day, hours=hour)
            # The date and session number give repeat runs the same event ID.
            activity_id = f"activity_{start:%Y%m%d}{number:018d}"
            if activities.find_by_id(connection, activity_id) is not None:
                continue
            activities.create(
                connection,
                NewActivity(
                    id=activity_id,
                    venue_id=VENUE_ID,
                    title=title,
                    type=code,
                    description="Complimentary activity for resort guests.",
                    date_range=DateRange(
                        min_date=to_microseconds(start),
                        max_date=to_microseconds(start + timedelta(hours=1)),
                    ),
                    capacity=capacity,
                    min_booking_size=minimum,
                    max_booking_size=maximum,
                    minimum_age=0,
                    price_id=ACTIVITY_PRICE_ID,
                ),
                now=now,
            )


def _seed_stay(connection: Connection, *, now: int) -> None:
    """Give the concierge a party to find and two guests with a shared first name."""
    if bookings.find_by_id(connection, BOOKING_ID, hotel_id=HOTEL_ID) is not None:
        return
    stays.create(
        connection,
        NewStay(
            booking=NewBooking(id=BOOKING_ID, name="Morgan and Patel"),
            party_id=PARTY_ID,
            guests=[
                NewGuest(
                    id=guest_id,
                    party_id=PARTY_ID,
                    first_name="Dan",
                    last_name=name,
                    age=30,
                )
                for guest_id, name in (
                    (DAN_MORGAN_ID, "Morgan"),
                    (DAN_PATEL_ID, "Patel"),
                )
            ],
            rooms=[
                NewRoomReservation(
                    id=ROOM_RESERVATION_ID,
                    booking_id=BOOKING_ID,
                    room_id=ROSE_ROOM_ID,
                    date_range=DateRange(
                        min_date=now,
                        max_date=to_microseconds(to_datetime(now) + timedelta(days=7)),
                    ),
                    price_id=ROOM_PRICE_ID,
                    price_revision=1,
                )
            ],
        ),
        hotel_id=HOTEL_ID,
        now=now,
    )
