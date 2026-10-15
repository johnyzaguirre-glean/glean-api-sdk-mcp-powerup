"""Offline presenter checks. These never read .env or call a Glean service."""
import argparse
import contextlib
import io
import json
import re
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from scripts import present


class PresenterTests(unittest.TestCase):
    def args(self, **values):
        defaults = {"confirm_sandbox": None, "search_args_file": None, "query_pointer": "/query"}
        defaults.update(values)
        return argparse.Namespace(**defaults)

    def test_separate_interpreters_and_exact_write_confirmation(self):
        root = Path("/repo with spaces")
        search = present.build_command("search-rest", self.args(), root)
        self.assertEqual(search, [str(root / ".venv/bin/python"), "examples/rest_search.py"])
        preview = present.build_command("indexing-preview", self.args(), root)
        self.assertEqual(preview, [str(root / ".venv-indexing/bin/python"), "indexing/push_demo.py"])
        for hostname in (None, "https://sandbox.example", "sandbox.example; touch X", "bad\nhost"):
            with self.subTest(hostname=hostname), self.assertRaises(ValueError):
                present.build_command("indexing-apply", self.args(confirm_sandbox=hostname), root)
        write = present.build_command("indexing-apply", self.args(confirm_sandbox="sandbox.example"), root)
        self.assertEqual(write[-3:], ["--apply", "--confirm-sandbox", "sandbox.example"])
        with self.assertRaises(ValueError):
            present.build_command("search-rest", self.args(confirm_sandbox="sandbox.example"), root)

    def test_mcp_options_only_reach_mcp_search_without_shell_interpolation(self):
        value = "outputs/args with spaces $(not-a-command).json"
        command = present.build_command("mcp-search", self.args(search_args_file=value))
        self.assertIn(value, command)
        self.assertEqual(command[-2:], ["--query-pointer", "/query"])
        with self.assertRaises(ValueError):
            present.build_command("mcp-discover", self.args(search_args_file=value))

    def test_partial_is_not_pass_and_mutation_does_not_claim_searchable(self):
        partial = {"allowed_reader": {"result": "PASS"}, "denied_reader": {"result": "NOT_RUN"}}
        self.assertEqual(present.classify("indexing-permissions", 2, partial)[0], "PARTIAL")
        self.assertEqual(present.classify("indexing-permissions", 1, partial)[0], "CHECK REQUIRED")
        self.assertEqual(present.classify("search-rest", 2, {})[0], "CHECK REQUIRED")
        self.assertEqual(present.classify("indexing-preview", 0, {})[0], "PREVIEW ONLY")
        label, meaning = present.classify("indexing-apply", 0, {})
        self.assertEqual(label, "UPLOAD ACCEPTED")
        self.assertIn("still need separate checks", meaning)

    def test_json_sanitization_removes_credentials_signed_links_and_controls(self):
        opaque = "a" * 43 + "="
        value = {
            "Authorization": "Bearer private-value", "api_token": opaque,
            "headers": {"x-private": "secret"},
            "answer": "\x1b[31mhello\u202e " + opaque + " https://example.com/doc?secret=value#private",
            "title": "safe", "request_id": "request-123",
        }
        text = json.dumps(present.scrub(value))
        for secret in (opaque, "private-value", "x-private", "secret=value", "#private", "\\u001b", "\\u202e"):
            self.assertNotIn(secret, text)
        self.assertIn("https://example.com/doc", text)
        self.assertIn("request-123", text)

    def test_run_child_preserves_exit_and_never_echoes_raw_stderr(self):
        def fake_run(command, **kwargs):
            self.assertNotIn("shell", kwargs)
            self.assertEqual(kwargs["timeout"], 30)
            kwargs["stdout"].write(b'{"http_status":403,"code":"access_denied"}')
            kwargs["stderr"].write(b"PRIVATE RAW ERROR")
            return subprocess.CompletedProcess(command, 1)
        with patch.object(present.subprocess, "run", side_effect=fake_run):
            result = present.run_child(["python", "example.py"], 30)
        self.assertEqual(result["exit_code"], 1)
        self.assertEqual(result["report"]["http_status"], 403)
        self.assertTrue(result["stderr_present"])
        self.assertNotIn("PRIVATE", json.dumps(result))

    def test_unstructured_oversize_or_timed_out_output_cannot_be_a_pass(self):
        for raw in (b"SECRET unstructured output", b"[]", b"{}" * 30):
            def fake_run(command, **kwargs):
                kwargs["stdout"].write(raw)
                return subprocess.CompletedProcess(command, 0)
            with self.subTest(raw=raw), patch.object(present, "MAX_CAPTURE_BYTES", 40), \
                 patch.object(present.subprocess, "run", side_effect=fake_run):
                result = present.run_child(["python"], 30)
                self.assertNotEqual(result["exit_code"], 0)
                self.assertIsNone(result["report"])
                self.assertNotIn("SECRET", json.dumps(result))
        with patch.object(present.subprocess, "run", side_effect=subprocess.TimeoutExpired("python", 30)):
            result = present.run_child(["python"], 30)
            self.assertEqual(result["exit_code"], 124)

    def test_summary_uses_returned_values_and_marks_chat_excerpt(self):
        report = {"http_status": 200, "result_count": 2, "expected_document_matched": False,
                  "results": [{"title": "Different doc", "url": "https://example.com/other", "url_sha256": "abc"}]}
        compact = present.compact_report("search-rest", report)
        self.assertFalse(compact["expected_document_matched"])
        self.assertEqual(compact["results"], [{"title": "Different doc", "url": "https://example.com/other"}])
        chat = present.compact_report("chat-rest", {"answer": "a" * 900, "citations": []})
        self.assertTrue(chat["answer_excerpt_shortened"])
        self.assertEqual(len(chat["answer_excerpt"]), 700)

    def test_colors_are_optional_and_reports_are_owner_only(self):
        stream = io.StringIO()
        present.Screen("never", stream).json({"works": True})
        self.assertNotIn("\x1b", stream.getvalue())
        self.assertEqual(json.loads(stream.getvalue()), {"works": True})
        colored = io.StringIO()
        present.Screen("always", colored).json({"works": True})
        self.assertIn("\x1b[", colored.getvalue())
        self.assertEqual(json.loads(present.clean_text(colored.getvalue())), {"works": True})
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "presenter/result.json"
            present.save_result(path, {"outcome": "PARTIAL"})
            self.assertEqual(path.stat().st_mode & 0o777, 0o600)
            self.assertEqual(json.loads(path.read_text())["outcome"], "PARTIAL")

    def test_list_and_plan_never_start_a_child(self):
        with patch.object(present, "run_child") as run, contextlib.redirect_stdout(io.StringIO()):
            self.assertEqual(present.main(["--list"]), 0)
            self.assertEqual(present.main(["search-rest", "--plan", "--color", "never"]), 0)
            self.assertEqual(present.main(["indexing-apply", "--plan", "--confirm-sandbox", "sandbox.example"]), 0)
            run.assert_not_called()

    def test_replay_is_labeled_and_never_runs_or_overwrites_evidence(self):
        recorded = {"exercise": "search-rest", "completed_at": "2026-10-15T14:00:00+00:00",
                    "command": [".venv/bin/python", "examples/rest_search.py"],
                    "exit_code": 0, "elapsed_seconds": 1.5, "report": {"http_status": 200},
                    "runner_issue": None, "stderr_present": False}
        stream = io.StringIO()
        with patch.object(present, "load_recording", return_value=recorded), \
             patch.object(present, "run_child") as run, patch.object(present, "save_result") as save, \
             contextlib.redirect_stdout(stream):
            self.assertEqual(present.main(["search-rest", "--replay", "--color", "never"]), 0)
            run.assert_not_called()
            save.assert_not_called()
        self.assertIn("RECORDED RESULT", stream.getvalue())
        self.assertIn("not a live rerun", stream.getvalue())
        self.assertIn(recorded["completed_at"], stream.getvalue())

    def test_recording_validation_is_bounded_and_matches_exercise(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            path = root / "outputs/presenter/search-rest.json"
            path.parent.mkdir(parents=True)
            valid = {"exercise": "search-rest", "completed_at": "2026-10-15T14:00:00+00:00",
                     "command": [".venv/bin/python", "examples/rest_search.py"],
                     "exit_code": 1, "elapsed_seconds": 1.5, "report": {"http_status": 403}}
            path.write_text(json.dumps(valid))
            self.assertEqual(present.load_recording("search-rest", root)["exit_code"], 1)
            path.write_text(json.dumps(dict(valid, exercise="indexing-apply")))
            with self.assertRaises(ValueError):
                present.load_recording("search-rest", root)
            path.write_text("x" * 50)
            with patch.object(present, "MAX_CAPTURE_BYTES", 30), self.assertRaises(ValueError):
                present.load_recording("search-rest", root)

    def test_replay_refuses_live_write_options(self):
        args = self.args(confirm_sandbox="sandbox.example")
        with self.assertRaises(ValueError), patch.object(present, "run_child") as run:
            present.replay("indexing-apply", args, present.Screen("never", io.StringIO()))
        run.assert_not_called()

    def test_recorded_command_cannot_become_an_arbitrary_rerun_suggestion(self):
        for command in (["sh", "-c", "echo untrusted"],
                        [".venv/bin/python", "examples/rest_search.py", ";", "echo untrusted"],
                        [".venv/bin/python", "examples/rest_search.py\nmisleading command"],
                        [".venv/bin/python", "examples/rest_search.py", "\x1b]52;c;payload\x07"]):
            with self.subTest(command=command), self.assertRaises(ValueError):
                present.validate_recorded_command("search-rest", command)
        present.validate_recorded_command("mcp-search", [".venv/bin/python", "scripts/run_mcp_test.py",
            "--search-args-file", "outputs/path with spaces.json", "--query-pointer", "/query"])
        present.validate_recorded_command("indexing-apply", [".venv-indexing/bin/python", "indexing/push_demo.py",
            "--apply", "--confirm-sandbox", "sandbox.example"])

    def test_terminal_control_payloads_are_inert_before_json_rendering(self):
        report = {"answer": "\x1b]52;c;clipboard payload\x07\x1b[2J\x9b2J\u202ehidden",
                  "title\x1b[0m": "\x1bPdevice payload\x1b\\"}
        output = io.StringIO()
        screen = present.Screen("always", output)
        screen.json(present.scrub(report))
        text = output.getvalue()
        allowed_sgr = re.sub(r"\x1b\[(?:0|1|2|9[1-6])m", "", text)
        for control in ("\x1b", "\x07", "\x9b", "\u202e"):
            self.assertNotIn(control, allowed_sgr)


if __name__ == "__main__":
    unittest.main()
