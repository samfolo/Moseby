"""Assemble the concierge's executable tool catalogue."""

from sqlalchemy import Engine

from moseby.runtime.guest_references import GuestReferenceRecorder

from . import activities, guests, rooms, stays
from .definitions import Tool


def create_tools(engine: Engine, recorder: GuestReferenceRecorder) -> tuple[Tool, ...]:
    return (
        *rooms.create_tools(engine),
        *stays.create_tools(engine),
        *activities.create_tools(engine),
        *guests.create_tools(engine, recorder),
    )
