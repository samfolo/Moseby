"""Validated permission names and directional, segment-based grant matching."""

from collections.abc import Iterable
from enum import StrEnum
from typing import Annotated

from pydantic import ConfigDict, Field, RootModel

PERMISSION_PATTERN = (
    r"^moseby(?:\.[a-z][a-z0-9]*(?:-[a-z0-9]+)*)*:(?:read|write|execute)$"
)


class PermissionAction(StrEnum):
    READ = "read"
    WRITE = "write"
    EXECUTE = "execute"


class Permission(RootModel[Annotated[str, Field(pattern=PERMISSION_PATTERN)]]):
    """An immutable permission that serializes as its original string."""

    model_config = ConfigDict(frozen=True, strict=True)

    @property
    def path(self) -> tuple[str, ...]:
        return tuple(self.root.partition(":")[0].split("."))

    @property
    def action(self) -> PermissionAction:
        return PermissionAction(self.root.partition(":")[2])


class PermissionResolver:
    """A grant covers itself and descendants with the same action."""

    @staticmethod
    def matches(granted: Permission, required: Permission) -> bool:
        return (
            granted.action == required.action
            and required.path[: len(granted.path)] == granted.path
        )

    @staticmethod
    def allows(grants: Iterable[Permission], required: Permission) -> bool:
        return any(PermissionResolver.matches(grant, required) for grant in grants)

    @staticmethod
    def covering_grants(required: Permission) -> tuple[Permission, ...]:
        """Return the exact permission followed by each ancestor, nearest first."""
        path = required.path
        return tuple(
            Permission(f"{'.'.join(path[:length])}:{required.action.value}")
            for length in range(len(path), 0, -1)
        )
