"""Permission checks shared by application operations."""

from collections.abc import Iterable

from moseby.permissions import Permission, PermissionResolver


def require_permission(permissions: Iterable[Permission], required: Permission) -> None:
    """Reject the operation unless one of the caller's grants covers its scope."""
    if not PermissionResolver.allows(permissions, required):
        raise PermissionError(f"Required permission: {required.root}")
