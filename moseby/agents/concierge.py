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
        tools=("search_rooms",),
        permissions=(Permission("moseby.rooms:read"),),
        max_turns=8,
        token_budget=20000,
    )
