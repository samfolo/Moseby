"""Contract metadata only; the service must enforce permissions when implemented."""

from pydantic import BaseModel

from moseby.permissions import Permission, PermissionResolver

PERMISSIONS: dict[Permission, str] = {
    Permission(code): description
    for code, description in {
        "moseby:read": "Read across all Moseby resources within the caller's data scope.",
        "moseby:write": "Write across all Moseby resources within the caller's data scope.",
        "moseby:execute": "Execute registered actions within the caller's data scope.",
        "moseby.hotels:read": "Read hotel information.",
        "moseby.staff-members:read": "Read staff information.",
        "moseby.rooms:read": "Read rooms, beds, prices and availability.",
        "moseby.rooms.configuration:write": "Configure rooms; excluded from the concierge agent profile.",
        "moseby.venues:read": "Read shared venues.",
        "moseby.bookings:read": "Read bookings, room reservations and keys.",
        "moseby.bookings:write": "Create and manage stays; issue and deactivate room keys.",
        "moseby.guests:read": "Read guests, parties and party details.",
        "moseby.guests:write": "Update guests and add party details.",
        "moseby.activities:read": "Read activities and guest reservations.",
        "moseby.activities:write": "Reserve and cancel places in existing activities.",
        "moseby.threads:read": "Read owned threads, input, conversation records and runs.",
        "moseby.threads:write": "Create threads, submit or steer input, and request cancellation.",
        "moseby.jobs:read": "Read permitted jobs and their outcomes.",
        "moseby.jobs:write": "Submit publicly registered operations with their required permissions.",
        "moseby.schedules:read": "Read owned schedules and their accepted occurrences.",
        "moseby.schedules:write": "Create and edit permitted scheduled actions.",
        "moseby.notifications:read": "Read permitted notifications and published events.",
        "moseby.notifications:write": "Request notifications for permitted recipients.",
    }.items()
}


def access(permission: Permission | str, *, hotel_scoped: bool = True) -> dict:
    permission = Permission.model_validate(permission)
    if permission not in PERMISSIONS:
        raise ValueError(f"Unknown permission: {permission.root}")
    return {
        "x-permissions": {
            "anyOf": [
                grant.root for grant in PermissionResolver.covering_grants(permission)
            ]
        },
        "x-hotel-scoped": hotel_scoped,
    }


def access_all(*permissions: Permission | str) -> dict:
    """Require each capability, allowing a covering ancestor for each one."""
    if not permissions:
        raise ValueError("Supply at least one permission")
    return {
        "x-permissions": {
            "allOf": [access(permission)["x-permissions"] for permission in permissions]
        },
        "x-hotel-scoped": True,
    }


def query_body(
    model: type[BaseModel], permission: Permission | str, *, hotel_scoped: bool = True
) -> dict:
    """Supply the QUERY body omitted by FastAPI 0.141.1's schema generator."""
    return {
        **access(permission, hotel_scoped=hotel_scoped),
        "requestBody": {
            "required": True,
            "content": {
                "application/json": {
                    "schema": {
                        "$ref": f"#/components/schemas/{model.__name__}",
                    }
                }
            },
        },
    }
