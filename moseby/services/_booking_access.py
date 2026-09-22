"""Booking permissions also cover room allocations and their keys."""

from moseby.permissions import Permission

READ_PERMISSION = Permission("moseby.bookings:read")
WRITE_PERMISSION = Permission("moseby.bookings:write")
