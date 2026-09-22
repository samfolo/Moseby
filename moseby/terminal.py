"""Small terminal presentation helpers shared by live replies and saved history."""

import os
import sys

from moseby.runtime.enums import RunStatus
from moseby.runtime.loop import TurnResult
from moseby.runtime.models.messages import ToolResultStatus


def speaker_label(name: str) -> str:
    """Colour just the speaker in interactive terminals, respecting NO_COLOR."""
    if (
        not sys.stdout.isatty()
        or "NO_COLOR" in os.environ
        or os.environ.get("TERM") == "dumb"
    ):
        return f"{name}:"
    colour = "36" if name == "You" else "32"
    return f"\033[1;{colour}m{name}:\033[0m"


def read_message() -> str | None:
    """Wait for text; an empty line keeps the prompt open, while EOF or /exit leaves."""
    while True:
        try:
            text = input(f"{speaker_label('You')} ").strip()
        except EOFError:
            return None
        if text == "/exit":
            return None
        if text:
            return text
        print("Enter a message, or /exit to leave.")


def waiting_for_model() -> None:
    """Show request activity while the complete model response is being awaited."""
    print("  … Waiting for model…", flush=True)


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
