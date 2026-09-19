"""Contract metadata only; the service must enforce permissions when implemented."""

from pydantic import BaseModel

PERMISSIONS = {
    "moseby:read": "Read across all Moseby resources within the caller's data scope.",
    "moseby:write": "Write across all Moseby resources within the caller's data scope.",
    "moseby.hotels:read": "Read hotel information.",
    "moseby.staff-members:read": "Read staff information.",
    "moseby.rooms:read": "Read rooms, beds, prices and availability.",
    "moseby.venues:read": "Read shared venues.",
    "moseby.bookings:read": "Read bookings, room reservations and keys.",
    "moseby.bookings:write": "Issue and deactivate room keys.",
    "moseby.guests:read": "Read guests, parties and party details.",
    "moseby.guests:write": "Update guests and add party details.",
    "moseby.activities:read": "Read activities and guest reservations.",
    "moseby.activities:write": "Cancel activity reservations.",
}


def access(permission: str, *, hotel_scoped: bool = True) -> dict:
    if permission not in PERMISSIONS:
        raise ValueError(f"Unknown permission: {permission}")
    action = permission.rsplit(":", 1)[1]
    return {
        "x-permissions": {"anyOf": [permission, f"moseby:{action}"]},
        "x-hotel-scoped": hotel_scoped,
    }


def query_body(
    model: type[BaseModel], permission: str, *, hotel_scoped: bool = True
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
