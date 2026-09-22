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
from . import activities, bookings, room_keys
from ._writes import require_write_transaction

# Resort and staff
HOTEL_ID = "hotel_00000000000000000000000001"
STAFF_MEMBER_ID = "staff_member_00000000000000000000000001"
VENUE_ID = "venue_00000000000000000000000001"

# Prices
ROOM_PRICE_ID = "price_00000000000000000000000001"
ACTIVITY_PRICE_ID = "price_00000000000000000000000002"

# Rooms
ROSE_ROOM_ID = "room_00000000000000000000000001"
GARDEN_ROOM_ID = "room_00000000000000000000000002"
CEDAR_ROOM_ID = "room_00000000000000000000000003"
WILLOW_ROOM_ID = "room_00000000000000000000000004"
ORCHARD_ROOM_ID = "room_00000000000000000000000005"
TERRACE_ROOM_ID = "room_00000000000000000000000006"

# Beds
ROSE_BED_ID = "bed_00000000000000000000000001"
GARDEN_BED_ID = "bed_00000000000000000000000002"
CEDAR_BED_ID = "bed_00000000000000000000000003"
WILLOW_BED_ID = "bed_00000000000000000000000004"
ORCHARD_BED_ID = "bed_00000000000000000000000005"
TERRACE_BED_ID = "bed_00000000000000000000000006"

# Morgan and Patel stay
BOOKING_ID = "booking_00000000000000000000000001"
PARTY_ID = "party_00000000000000000000000001"
ROOM_RESERVATION_ID = "room_reservation_00000000000000000000000001"
DAN_MORGAN_ID = "guest_00000000000000000000000001"
DAN_PATEL_ID = "guest_00000000000000000000000002"
STANDARD_KEY_ID = "room_key_00000000000000000000000001"

# Okafor and Chen stay
SECOND_BOOKING_ID = "booking_00000000000000000000000002"
SECOND_PARTY_ID = "party_00000000000000000000000002"
SECOND_RESERVATION_ID = "room_reservation_00000000000000000000000002"
AMINA_GUEST_ID = "guest_00000000000000000000000003"
LEO_GUEST_ID = "guest_00000000000000000000000004"
SECOND_KEY_ID = "room_key_00000000000000000000000002"


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
        (CEDAR_ROOM_ID, CEDAR_BED_ID, "Cedar", RoomTier.STANDARD, BedType.KING),
        (WILLOW_ROOM_ID, WILLOW_BED_ID, "Willow", RoomTier.STANDARD, BedType.QUEEN),
        (ORCHARD_ROOM_ID, ORCHARD_BED_ID, "Orchard", RoomTier.VIP, BedType.KING),
        (TERRACE_ROOM_ID, TERRACE_BED_ID, "Terrace", RoomTier.VIP, BedType.DOUBLE),
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

    # Two occupied rooms leave standard and VIP alternatives for concierge requests.
    for booking_id, party_id, reservation_id, room_id, key_id, name, guests in (
        (
            BOOKING_ID,
            PARTY_ID,
            ROOM_RESERVATION_ID,
            ROSE_ROOM_ID,
            STANDARD_KEY_ID,
            "Morgan and Patel",
            ((DAN_MORGAN_ID, "Dan", "Morgan", 30), (DAN_PATEL_ID, "Dan", "Patel", 30)),
        ),
        (
            SECOND_BOOKING_ID,
            SECOND_PARTY_ID,
            SECOND_RESERVATION_ID,
            ORCHARD_ROOM_ID,
            SECOND_KEY_ID,
            "Okafor and Chen",
            (
                (AMINA_GUEST_ID, "Amina", "Okafor", 42),
                (LEO_GUEST_ID, "Leo", "Chen", 38),
            ),
        ),
    ):
        _seed_stay(
            connection,
            booking_id=booking_id,
            party_id=party_id,
            reservation_id=reservation_id,
            room_id=room_id,
            key_id=key_id,
            name=name,
            guests=guests,
            now=now,
        )
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


def _seed_stay(
    connection: Connection,
    *,
    booking_id: str,
    party_id: str,
    reservation_id: str,
    room_id: str,
    key_id: str,
    name: str,
    guests: tuple[tuple[str, str, str, int], ...],
    now: int,
) -> None:
    """Create a seven-night party with a standard key, preserving existing stays on reruns."""
    if bookings.find_by_id(connection, booking_id, hotel_id=HOTEL_ID) is not None:
        return
    arrival = to_datetime(now).replace(hour=0, minute=0, second=0, microsecond=0)
    stays.create(
        connection,
        NewStay(
            booking=NewBooking(id=booking_id, name=name),
            party_id=party_id,
            guests=[
                NewGuest(
                    id=id, party_id=party_id, first_name=first, last_name=last, age=age
                )
                for id, first, last, age in guests
            ],
            rooms=[
                NewRoomReservation(
                    id=reservation_id,
                    booking_id=booking_id,
                    room_id=room_id,
                    date_range=DateRange(
                        min_date=to_microseconds(arrival),
                        max_date=to_microseconds(arrival + timedelta(days=7)),
                    ),
                    price_id=ROOM_PRICE_ID,
                    price_revision=1,
                )
            ],
        ),
        hotel_id=HOTEL_ID,
        now=now,
    )
    room_keys.issue(
        connection,
        key_id,
        reservation_id,
        code="Standard key",
        hotel_id=HOTEL_ID,
        now=now,
    )
