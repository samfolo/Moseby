"""Run a durable concierge conversation from the terminal."""

import argparse
import asyncio
from pathlib import Path

import httpx
from alembic import command
from alembic.config import Config
from sqlalchemy import URL, Engine

from moseby.agents.agent import index_agent_definitions
from moseby.agents.concierge import definition
from moseby.config import InferenceSettings
from moseby.db.connection import create_database_engine
from moseby.db.errors import WriteConflict
from moseby.db.repositories import demo
from moseby.db.transaction import transaction
from moseby.identifiers import new_id
from moseby.inference.errors import InferenceError
from moseby.inference.providers.openrouter import OpenRouterProvider
from moseby.runtime.enums import RunStatus
from moseby.runtime.guest_references import GuestReferenceRecorder
from moseby.runtime.loop import TurnResult, run_turn
from moseby.runtime.models.messages import ToolResultStatus
from moseby.runtime.models.thread_records import ThreadRecordKind
from moseby.runtime.storage import ConversationStore, now_microseconds
from moseby.terminal import read_message, speaker_label, waiting_for_model
from moseby.tools.concierge import create_tools as concierge_tools
from moseby.tools.definitions import index_tools


def initialize(engine: Engine) -> None:
    """Apply migrations and add the demo hotel, guests, rooms and activity sessions."""
    config = Config(str(Path(__file__).resolve().parents[1] / "alembic.ini"))
    with transaction(engine, write=True) as connection:
        config.attributes["connection"] = connection
        command.upgrade(config, "head")
        demo.seed(connection, now=now_microseconds())


async def chat(engine: Engine, args: argparse.Namespace) -> None:
    if args.message is not None:
        args.message = args.message.strip()
        if not args.message:
            raise ValueError("Enter a nonempty message.")
    settings = InferenceSettings.from_environment()
    async with httpx.AsyncClient() as client:
        provider = OpenRouterProvider(settings, client)
        selected = definition()
        store = ConversationStore(
            engine,
            demo.STAFF_MEMBER_ID,
            demo.HOTEL_ID,
            index_agent_definitions([selected]),
            index_tools(
                concierge_tools(
                    engine,
                    GuestReferenceRecorder(
                        engine, provider, "openrouter", settings.classification_model
                    ),
                )
            ),
        )
        thread_id = args.thread or store.create(selected)
        store.load_agent(thread_id)
        print(f"Thread: {thread_id}")
        print(
            f"Model: {settings.generation_model} (reasoning: {settings.reasoning_effort})"
        )
        if args.thread:
            for record in store.history(thread_id):
                if record.kind in (
                    ThreadRecordKind.USER_MESSAGE,
                    ThreadRecordKind.ASSISTANT_MESSAGE,
                ):
                    text = record.payload.get("text")
                    if text:
                        who = (
                            "You"
                            if record.kind == ThreadRecordKind.USER_MESSAGE
                            else "Moseby"
                        )
                        print(f"{speaker_label(who)} {text}")
        while True:
            if args.message is not None:
                text = args.message
            else:
                text = read_message()
                if text is None:
                    return
            result = await run_turn(
                store,
                provider,
                thread_id=thread_id,
                text=text,
                request_id=new_id("request"),
                provider_name="openrouter",
                model=settings.generation_model,
                on_tool_start=lambda name: print(f"  • {name}", flush=True),
                on_inference_start=waiting_for_model,
            )
            print_turn_result(result)
            if args.message is not None:
                return


def print_turn_result(result: TurnResult) -> None:
    """Separate the assistant's reply from a runtime stop and its saved tool outcomes."""
    if result.status == RunStatus.COMPLETED:
        print(f"{speaker_label('Moseby')} {result.text or 'Run completed.'}")
        return
    print(f"Run stopped: {result.reason or result.status.value}.")
    if result.tool_outcomes:
        print("Saved tool outcomes (successful changes remain in place):")
        for outcome in result.tool_outcomes:
            status = (
                "succeeded"
                if outcome.status == ToolResultStatus.SUCCEEDED
                else "failed"
            )
            print(f"  • {outcome.name}: {status}")
    print("You can send another message; it starts a new run with its own budget.")


def main() -> None:
    parser = argparse.ArgumentParser(description="Moseby concierge demo")
    parser.add_argument("--database", default="moseby.db", help="SQLite database file")
    subparsers = parser.add_subparsers(dest="command", required=True)
    subparsers.add_parser("init", help="Migrate and seed the demo database")
    conversation = subparsers.add_parser("chat", help="Create or reopen a conversation")
    conversation.add_argument("--thread", help="Reopen a saved thread ID")
    conversation.add_argument("--message", help="Send one message and exit")
    args = parser.parse_args()
    engine = create_database_engine(
        URL.create("sqlite", database=str(Path(args.database).resolve()))
    )
    try:
        if args.command == "init":
            initialize(engine)
            print("Demo database ready.")
        else:
            asyncio.run(chat(engine, args))
    except (InferenceError, PermissionError, ValueError, WriteConflict) as error:
        parser.exit(1, f"{error}\n")
    except KeyboardInterrupt:
        print("\nConversation stopped.")
    finally:
        engine.dispose()


if __name__ == "__main__":
    main()
