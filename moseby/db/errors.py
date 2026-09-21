"""Expected write conflicts and unexpected failures to read saved state."""

from moseby.identifiers import ActivityId, ActivityReservationId, GuestId


class WriteConflict(Exception):
    """The saved state no longer permits this change."""


class ActivityAlreadyReserved(WriteConflict):
    """Requested guests already hold places; retain their IDs for the caller."""

    code = "ACTIVITY_ALREADY_RESERVED"

    def __init__(
        self,
        activity_id: ActivityId,
        reservations_by_guest: dict[GuestId, ActivityReservationId],
    ) -> None:
        super().__init__("Some guests already have reservations for this activity")
        self.activity_id = activity_id
        self.reservations_by_guest = dict(reservations_by_guest)


class IdempotencyConflict(WriteConflict):
    """A command key already has different input or a different saved response."""


class ClaimLost(WriteConflict):
    """This worker no longer holds a live claim for the running task."""


class RepositoryInvariantError(RuntimeError):
    """A successful write was followed by missing state in the same transaction."""
