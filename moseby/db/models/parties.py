from moseby.identifiers import BookingId, PartyId

from .common import Row


class PartyRow(Row):
    id: PartyId
    booking_id: BookingId
    created_at: int
