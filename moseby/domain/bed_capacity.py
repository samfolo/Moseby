"""Sleeping places used by the demo, without a separate room occupancy limit."""

from .enums import BedType

BED_CAPACITY = {
    BedType.UNKNOWN: 0,
    BedType.SINGLE: 1,
    BedType.TWIN: 1,
    BedType.DOUBLE: 2,
    BedType.QUEEN: 2,
    BedType.KING: 2,
}
