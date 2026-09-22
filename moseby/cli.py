"""Run a durable concierge conversation from the terminal."""

import argparse
import asyncio
from pathlib import Path

import httpx
from sqlalchemy import URL, Engine

from moseby.agents.concierge import definition
from moseby.application import create_conversation_store, initialize
from moseby.config import InferenceSettings
from moseby.db.connection import create_database_engine
from moseby.db.errors import WriteConflict
from moseby.identifiers import ThreadId, new_id
from moseby.inference.errors import InferenceError
from moseby.inference.providers.openrouter import OpenRouterProvider
from moseby.runtime.loop import run_turn
from moseby.runtime.models.thread_records import ThreadRecordKind
from moseby.terminal import (
    print_turn_result,
    read_message,
    speaker_label,
    waiting_for_model,
)


async def chat(
    engine: Engine, *, thread_id: ThreadId | None = None, message: str | None = None
) -> None:
    """Run one message or an interactive conversation with the configured model."""
    if message is not None:
        message = message.strip()
        if not message:
            raise ValueError("Enter a nonempty message.")
    settings = InferenceSettings.from_environment()
    async with httpx.AsyncClient() as client:
        provider = OpenRouterProvider(settings, client)
        selected = definition()
        store = create_conversation_store(
            engine,
            provider,
            selected,
            classification_model=settings.classification_model,
        )
        reopening = thread_id is not None
        thread_id = thread_id or store.create(selected)
        store.load_agent(thread_id)
        print(f"Thread: {thread_id}")
        print(
            f"Model: {settings.generation_model} (reasoning: {settings.reasoning_effort})"
        )
        if reopening:
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
            if message is not None:
                text = message
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
            if message is not None:
                return


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
            asyncio.run(chat(engine, thread_id=args.thread, message=args.message))
    except (InferenceError, PermissionError, ValueError, WriteConflict) as error:
        parser.exit(1, f"{error}\n")
    except KeyboardInterrupt:
        print("\nConversation stopped.")
    finally:
        engine.dispose()
