"""Convert stored UTC microseconds without rounding through floating-point seconds."""

from datetime import UTC, datetime, timedelta

_EPOCH = datetime(1970, 1, 1, tzinfo=UTC)
_MICROSECOND = timedelta(microseconds=1)


def to_datetime(value: int) -> datetime:
    return _EPOCH + timedelta(microseconds=value)


def to_microseconds(value: datetime) -> int:
    if value.utcoffset() is None:
        raise ValueError("a database timestamp requires a timezone")
    return (value - _EPOCH) // _MICROSECOND
