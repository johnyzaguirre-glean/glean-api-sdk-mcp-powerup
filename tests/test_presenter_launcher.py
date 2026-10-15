"""Inspect launcher plans offline. Never run macOS automation in tests."""
import contextlib
import io
from pathlib import Path
import shlex
import sys
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
import open_presenter_windows as launcher


class LauncherTests(unittest.TestCase):
    def test_exactly_eleven_commands_replay_and_hold_without_write_flags(self):
        root = Path('/example/repo with spaces/quote"and$symbol')
        commands = launcher.window_commands(root)
        self.assertEqual(len(commands), 11)
        self.assertEqual(len({item["title"] for item in commands}), 11)
        for item in commands:
            self.assertIn("--replay --color always --hold", item["command"])
            self.assertNotIn("--apply", item["command"])
            self.assertNotIn("--confirm-sandbox", item["command"])
            self.assertIn(shlex.quote(str(root)), item["command"])

    def test_generated_applescript_opens_new_windows_and_never_closes(self):
        script = launcher.script_for(launcher.window_commands(Path("/repo with spaces")))
        self.assertEqual(script.count("set demoTab to do script "), 11)
        self.assertEqual(script.count("set custom title of demoTab"), 11)
        self.assertNotIn("close", script)
        self.assertNotIn("delete", script)
        self.assertIn('tell application "Terminal"', script)
        self.assertEqual(launcher.applescript_string('a"b\\c'), '"a\\"b\\\\c"')
        with self.assertRaises(ValueError):
            launcher.applescript_string("bad\npath")

    def test_plan_never_calls_automation_even_with_missing_recordings(self):
        with patch.object(launcher, "load_recording", side_effect=ValueError("missing")), \
             patch.object(launcher.subprocess, "run") as run, contextlib.redirect_stdout(io.StringIO()) as output:
            self.assertEqual(launcher.main(["--plan"]), 0)
            run.assert_not_called()
        self.assertIn("No application was opened or controlled", output.getvalue())

    def test_missing_recordings_stop_before_automation(self):
        with patch.object(launcher.sys, "platform", "darwin"), \
             patch.object(launcher.Path, "is_file", return_value=True), \
             patch.object(launcher, "load_recording", side_effect=ValueError("missing")), \
             patch.object(launcher.subprocess, "run") as run, \
             contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(io.StringIO()):
            self.assertEqual(launcher.main([]), 2)
            run.assert_not_called()


if __name__ == "__main__":
    unittest.main()
