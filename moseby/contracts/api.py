"""HTTP routes and their generated contract."""

from fastapi import FastAPI
from sqlalchemy import Engine

from moseby.db.pagination import InvalidCursor
from moseby.gateway.dependencies import GatewayBinding
from moseby.gateway.domain_reads import router as reads_router
from moseby.gateway.errors import invalid_cursor, permission_denied
from moseby.identifiers import HotelId, StaffMemberId

from .domain_api import router as domain_router
from .runtime_api import router as runtime_router

UNIMPLEMENTED = {501: {"description": "Operation is not implemented."}}


def create_app(
    *,
    engine: Engine | None = None,
    staff_member_id: StaffMemberId | None = None,
    hotel_id: HotelId | None = None,
) -> FastAPI:
    """Build the API with one host-selected staff identity; the caller owns the engine."""
    supplied = (engine is not None, staff_member_id is not None, hotel_id is not None)
    if any(supplied) and not all(supplied):
        raise ValueError("Supply the engine, staff member ID and hotel ID together")
    application = FastAPI(
        title="Moseby",
        version="0.1.0",
        docs_url=None,
        redoc_url=None,
        description="Resort operations API for guest lookup, room search and activity browsing.",
    )
    application.openapi_version = "3.2.1"
    application.state.gateway_binding = (
        GatewayBinding(engine, staff_member_id, hotel_id) if all(supplied) else None
    )
    application.include_router(domain_router, responses=UNIMPLEMENTED)
    application.include_router(runtime_router, responses=UNIMPLEMENTED)
    application.include_router(reads_router)
    application.add_exception_handler(PermissionError, permission_denied)
    application.add_exception_handler(InvalidCursor, invalid_cursor)
    return application


app = create_app()
