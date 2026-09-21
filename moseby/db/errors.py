"""Expected write conflicts and unexpected failures to read saved state."""


class WriteConflict(Exception):
    """The saved state no longer permits this change."""


class IdempotencyConflict(WriteConflict):
    """A command key already has different input or a different saved response."""


class ClaimLost(WriteConflict):
    """This worker no longer holds a live claim for the running task."""


class RepositoryInvariantError(RuntimeError):
    """A successful write was followed by missing state in the same transaction."""
