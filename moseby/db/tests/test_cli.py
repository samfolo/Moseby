"""Exercise the command-line entry point with a local database and scripted replies."""

import io
import tempfile
import unittest
from contextlib import redirect_stderr, redirect_stdout
from pathlib import Path
from unittest.mock import patch

from moseby.cli import main
from moseby.config import InferenceSettings
from moseby.db.tests.inference_fixtures import ScriptedProvider, tool_call, tool_result
from moseby.inference.models.generation import AssistantMessage


class CliTests(unittest.TestCase):
    def test_chat_without_a_database_explains_how_to_initialise_it(self):
        """Starting chat before init gives setup instructions without creating a database."""
        with tempfile.TemporaryDirectory() as directory:
            database = Path(directory) / "missing.db"
            errors = io.StringIO()
            with (
                patch("sys.argv", ["moseby", "--database", str(database), "chat"]),
                redirect_stderr(errors),
                patch("moseby.cli.InferenceSettings.from_environment") as settings,
                self.assertRaises(SystemExit) as raised,
            ):
                main()
            self.assertEqual(raised.exception.code, 2)
            self.assertIn("Run init first", errors.getvalue())
            self.assertFalse(database.exists())
            settings.assert_not_called()

    def test_init_chat_and_resume_keep_the_conversation_and_execute_tools(self):
        """A fresh demo can search rooms, save the reply and reopen the same conversation."""
        settings = InferenceSettings(
            openrouter_api_key="test-key",
            generation_model="test/generation",
            classification_model="test/classification",
        )
        provider = ScriptedProvider(
            tool_call("search_rooms"),
            AssistantMessage(text="The hotel has six rooms."),
            AssistantMessage(text="Welcome back."),
        )
        with (
            tempfile.TemporaryDirectory() as directory,
            patch(
                "moseby.cli.InferenceSettings.from_environment", return_value=settings
            ),
            patch("moseby.cli.OpenRouterProvider", return_value=provider),
        ):
            database = Path(directory) / "demo.db"
            arguments = ["moseby", "--database", str(database)]
            with (
                patch("sys.argv", [*arguments, "init"]),
                redirect_stdout(io.StringIO()),
            ):
                main()
            output = io.StringIO()
            with (
                patch(
                    "sys.argv", [*arguments, "chat", "--message", "Show me the rooms"]
                ),
                redirect_stdout(output),
            ):
                main()
            self.assertEqual(len(tool_result(provider.requests[1])["items"]), 6)
            self.assertIn("• search_rooms", output.getvalue())
            self.assertIn("Moseby: The hotel has six rooms.", output.getvalue())
            thread_id = output.getvalue().splitlines()[0].removeprefix("Thread: ")
            output = io.StringIO()
            with (
                patch(
                    "sys.argv",
                    [
                        *arguments,
                        "chat",
                        "--thread",
                        thread_id,
                        "--message",
                        "Hello again",
                    ],
                ),
                redirect_stdout(output),
            ):
                main()
            self.assertIn("You: Show me the rooms", output.getvalue())
            self.assertIn("Moseby: Welcome back.", output.getvalue())
            messages = provider.requests[2].messages
            self.assertEqual(
                [message.content for message in messages if message.role == "user"],
                ["Show me the rooms", "Hello again"],
            )
