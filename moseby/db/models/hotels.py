from moseby.identifiers import HotelId

from .addresses import AddressRow


class HotelRow(AddressRow):
    id: HotelId
    name: str
    created_at: int
    updated_at: int
