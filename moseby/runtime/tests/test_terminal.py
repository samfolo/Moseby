"""Check CLI input and presentation without starting a model request."""

import asyncio
import io
import unittest
from contextlib import redirect_stdout
from unittest.mock import patch

from moseby.cli import chat
from moseby.terminal import read_message, speaker_label


class TerminalTests(unittest.TestCase):
    def test_blank_lines_wait_for_text_and_exit_ends_input(self):
        """Empty input keeps asking for a message; EOF and /exit finish cleanly."""
        with (
            patch("builtins.input", side_effect=["", "  \t", " Hello "]),
            redirect_stdout(io.StringIO()),
        ):
            self.assertEqual(read_message(), "Hello")
        for ending in ("/exit", EOFError()):
            with patch("builtins.input", side_effect=[ending]):
                self.assertIsNone(read_message())

    def test_blank_message_argument_is_rejected_before_settings_or_inference(self):
        """A blank --message fails before creating a thread or contacting the provider."""
        with patch("moseby.cli.InferenceSettings.from_environment") as settings:
            with self.assertRaisesRegex(ValueError, "nonempty"):
                asyncio.run(chat(None, message="  \n"))
            settings.assert_not_called()

    def test_speaker_colour_respects_redirects_and_no_color(self):
        """Only interactive output gets coloured labels; logs and NO_COLOR stay plain."""
        with (
            patch("moseby.terminal.sys.stdout") as output,
            patch.dict("os.environ", {"TERM": "xterm"}, clear=True),
        ):
            output.isatty.return_value = True
            self.assertEqual(speaker_label("You"), "\033[1;36mYou:\033[0m")
            self.assertEqual(speaker_label("Moseby"), "\033[1;32mMoseby:\033[0m")
            with patch.dict("os.environ", {"NO_COLOR": ""}):
                self.assertEqual(speaker_label("Moseby"), "Moseby:")
            output.isatty.return_value = False
            self.assertEqual(speaker_label("You"), "You:")
