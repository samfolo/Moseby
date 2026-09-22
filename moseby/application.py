"""Connect the concierge's dependencies and initialise the local demo."""

from pathlib import Path

from alembic import command
from alembic.config import Config
from sqlalchemy import Engine

from moseby.agents.agent import index_agent_definitions
from moseby.agents.models import AgentDefinition
from moseby.db.repositories import demo
from moseby.db.transaction import transaction
from moseby.inference.provider import InferenceProvider
from moseby.runtime.guest_references import GuestReferenceRecorder
from moseby.runtime.storage import ConversationStore, now_microseconds
from moseby.tools.concierge import create_tools
from moseby.tools.definitions import index_tools


def initialize(engine: Engine) -> None:
    """Apply migrations and add the demo hotel, guests, rooms and activity sessions."""
    config = Config(str(Path(__file__).resolve().parents[1] / "alembic.ini"))
    with transaction(engine, write=True) as connection:
        config.attributes["connection"] = connection
        command.upgrade(config, "head")
        demo.seed(connection, now=now_microseconds())


def create_conversation_store(
    engine: Engine,
    provider: InferenceProvider,
    agent: AgentDefinition,
    *,
    classification_model: str,
) -> ConversationStore:
    """Give the demo staff member the selected agent and its executable tools."""
    recorder = GuestReferenceRecorder(
        engine, provider, "openrouter", classification_model
    )
    return ConversationStore(
        engine,
        demo.STAFF_MEMBER_ID,
        demo.HOTEL_ID,
        index_agent_definitions([agent]),
        index_tools(create_tools(engine, recorder)),
    )
