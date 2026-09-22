"""The concierge definition used by the first runnable demonstration."""

from moseby.permissions import Permission

from .models import AgentDefinition
from .prompts import concierge_prompt


def definition() -> AgentDefinition:
    return AgentDefinition(
        id="concierge",
        version=1,
        display_name="Moseby",
        description="Help staff look after resort guests.",
        system_prompt=concierge_prompt(),
        tools=(
            "search_party_details",
            "issue_room_key",
            "deactivate_room_key",
            "get_stay",
            "create_stay",
            "amend_stay",
            "add_room_to_stay",
            "cancel_stay",
            "complete_stay",
            "update_guest",
            "update_guest_dietary_requirements",
            "search_rooms",
            "search_guests",
            "record_party_detail",
            "search_activities",
            "search_activity_reservations",
            "reserve_activity_places",
            "cancel_activity_reservation",
        ),
        permissions=(
            Permission("moseby.bookings:read"),
            Permission("moseby.bookings:write"),
            Permission("moseby.rooms:read"),
            Permission("moseby.guests:read"),
            Permission("moseby.guests:write"),
            Permission("moseby.activities:read"),
            Permission("moseby.activities:write"),
        ),
        max_turns=8,
        token_budget=20000,
    )
