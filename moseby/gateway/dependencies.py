from dataclasses import dataclass
from typing import Annotated

from fastapi import Depends, HTTPException, Request
from sqlalchemy import Engine

from moseby.agents.models import AgentDomainContext
from moseby.identifiers import HotelId, StaffMemberId
from moseby.services import authority


@dataclass(frozen=True)
class GatewayBinding:
    """The database and single acting staff identity configured by the demo host."""

    engine: Engine
    staff_member_id: StaffMemberId
    hotel_id: HotelId


def get_binding(request: Request) -> GatewayBinding:
    binding = request.app.state.gateway_binding
    if binding is None:
        raise HTTPException(503, "The gateway has not been configured.")
    return binding


def get_engine(binding: Annotated[GatewayBinding, Depends(get_binding)]) -> Engine:
    return binding.engine


def get_domain_context(
    binding: Annotated[GatewayBinding, Depends(get_binding)],
) -> AgentDomainContext:
    """Read the configured staff member's current role and hotel for each request."""
    try:
        return authority.resolve(
            binding.engine,
            staff_member_id=binding.staff_member_id,
            hotel_id=binding.hotel_id,
        )
    except PermissionError as error:
        raise HTTPException(403, "The acting staff member is unavailable.") from error
