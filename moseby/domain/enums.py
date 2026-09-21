"""Domain choices shared by API validation, database reads and queries."""

from enum import StrEnum


class BedType(StrEnum):
    """Supported bed categories; dimensions and sleeping capacity are defined separately."""

    UNKNOWN = "BED_TYPE_UNKNOWN"
    SINGLE = "BED_TYPE_SINGLE"
    TWIN = "BED_TYPE_TWIN"
    DOUBLE = "BED_TYPE_DOUBLE"
    QUEEN = "BED_TYPE_QUEEN"
    KING = "BED_TYPE_KING"


class RoomTier(StrEnum):
    """Service tier, separate from bed configuration; unknown means not classified."""

    UNKNOWN = "ROOM_TIER_UNKNOWN"
    STANDARD = "ROOM_TIER_STANDARD"
    VIP = "ROOM_TIER_VIP"


class RoomServiceStatus(StrEnum):
    """Room condition, independent of reservations and temporary holds."""

    IN_SERVICE = "ROOM_SERVICE_STATUS_IN_SERVICE"
    OUT_OF_SERVICE = "ROOM_SERVICE_STATUS_OUT_OF_SERVICE"


class BookingStatus(StrEnum):
    """A proposed amendment leaves the accepted booking confirmed until committed."""

    CONFIRMED = "BOOKING_STATUS_CONFIRMED"
    CANCELLED = "BOOKING_STATUS_CANCELLED"
    COMPLETED = "BOOKING_STATUS_COMPLETED"


class ContactPreference(StrEnum):
    """Preferred contact channel; null on the guest selects all supplied channels."""

    PHONE = "CONTACT_PREFERENCE_PHONE"
    EMAIL = "CONTACT_PREFERENCE_EMAIL"


class ActivityPriceUnit(StrEnum):
    """Pricing unit for an activity rate; the demo currently charges per guest."""

    PER_GUEST = "ACTIVITY_PRICE_UNIT_PER_GUEST"


class GuestReferenceStatus(StrEnum):
    """Proposed outcomes distinguish an empty resolved result from unresolved references."""

    PENDING = "GUEST_REFERENCE_STATUS_PENDING"
    RESOLVED = "GUEST_REFERENCE_STATUS_RESOLVED"
    AMBIGUOUS = "GUEST_REFERENCE_STATUS_AMBIGUOUS"
    FAILED = "GUEST_REFERENCE_STATUS_FAILED"


class StaffRole(StrEnum):
    """Initial demo role; unknown grants no permissions."""

    UNKNOWN = "STAFF_ROLE_UNKNOWN"
    CONCIERGE = "STAFF_ROLE_CONCIERGE"
