"""Small terminal presentation helpers shared by live replies and saved history."""

import os
import sys


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
