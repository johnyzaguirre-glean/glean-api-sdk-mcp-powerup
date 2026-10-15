"""Verify request capture against real serialization, entirely offline."""
import contextlib
import io
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from scripts import common, present, presenter_capture
from scripts.chat_lab import bounded_client


class InputTests(unittest.TestCase):
    def test_capture_redacts_exact_and_encoded_secret_without_headers(self):
        secret = "short/private+secret"
        with tempfile.NamedTemporaryFile() as sink, patch.dict(os.environ, {"GLEAN_PRESENTER_INPUT_FILE": sink.name}):
            presenter_capture.capture_input("http_request", "POST /api/search",
                {"query": "test " + secret, "nested": {"access_token": secret},
                 "encoded": "short%2Fprivate%2Bsecret", "page_size": 3}, token=secret,
                 endpoint="https://sandbox.example/api/search")
            raw = Path(sink.name).read_text()
        self.assertNotIn(secret, raw)
        self.assertNotIn("short%2Fprivate", raw)
        event = json.loads(raw)
        self.assertEqual(event["payload"]["page_size"], 3)
        self.assertIn("[REDACTED]", event["payload"]["query"])

    def test_capture_is_opt_in_and_refuses_symlink_or_public_file(self):
        with patch.dict(os.environ, {}, clear=True), patch.object(os, "open") as opened:
            presenter_capture.capture_input("http_request", "POST", {"query": "safe"})
            opened.assert_not_called()
        with tempfile.TemporaryDirectory() as directory:
            target = Path(directory) / "target"
            target.write_text("original")
            target.chmod(0o600)
            link = Path(directory) / "link"
            link.symlink_to(target)
            with patch.dict(os.environ, {"GLEAN_PRESENTER_INPUT_FILE": str(link)}):
                presenter_capture.capture_input("http_request", "POST", {})
            self.assertEqual(target.read_text(), "original")
            target.chmod(0o644)
            with patch.dict(os.environ, {"GLEAN_PRESENTER_INPUT_FILE": str(target)}):
                presenter_capture.capture_input("http_request", "POST", {})
            self.assertEqual(target.read_text(), "original")

    def test_prepared_request_captures_actual_wire_body_not_authorization(self):
        import httpx
        request = httpx.Request("POST", "https://sandbox.example/api/chat",
            headers={"Authorization": "Bearer forbidden", "Mcp-Session-Id": "private-session"},
            json={"input": "How do I search?", "store": False})
        with tempfile.NamedTemporaryFile() as sink, patch.dict(os.environ, {"GLEAN_PRESENTER_INPUT_FILE": sink.name}):
            common.capture_http_request(request, "forbidden")
            event = json.loads(Path(sink.name).read_text())
        self.assertEqual(event["payload"], json.loads(request.content))
        self.assertNotIn("forbidden", json.dumps(event))
        self.assertNotIn("private-session", json.dumps(event))
        self.assertNotIn("stream", event["payload"])

    def test_sdk_search_capture_matches_request_passed_to_transport(self):
        import httpx
        actual = []
        def receive(request):
            actual.append(json.loads(request.content))
            return httpx.Response(200, json={"results": []})
        original_client = httpx.Client
        def client(**kwargs):
            return original_client(transport=httpx.MockTransport(receive), **kwargs)
        with tempfile.NamedTemporaryFile() as sink, \
             patch.dict(os.environ, {"GLEAN_PRESENTER_INPUT_FILE": sink.name}), \
             patch.object(httpx, "Client", side_effect=client):
            common.sdk_probe("https://sandbox.example", "demo-only-secret", "known document")
            events = [json.loads(line) for line in Path(sink.name).read_text().splitlines()]
        self.assertEqual(len(actual), 1)
        self.assertEqual(events[0]["payload"], actual[0])
        self.assertEqual(actual[0]["query"], "known document")
        self.assertEqual(actual[0]["page_size"], 3)

    def test_child_capture_survives_as_evidence_and_standalone_import_works(self):
        code = ("from presenter_capture import capture_input; "
                "capture_input('http_request','POST /api/search',{'query':'saved input','page_size':3}); "
                "print('{\"http_status\":200}')")
        result = present.run_child([sys.executable, "-c", code], 10, root=ROOT / "scripts")
        self.assertEqual(result["exit_code"], 0)
        self.assertEqual(result["inputs"][0]["payload"]["query"], "saved input")

    def test_replay_uses_recorded_payload_and_does_not_read_current_config(self):
        saved = {"exercise": "search-rest", "completed_at": "2026-10-15T14:00:00+00:00",
                 "command": [".venv/bin/python", "examples/rest_search.py"], "exit_code": 0,
                 "elapsed_seconds": 1, "report": {"http_status": 200},
                 "inputs": [{"kind": "http_request", "operation": "POST /api/search",
                             "payload": {"query": "ORIGINAL QUERY", "page_size": 3}}]}
        with patch.object(present, "load_recording", return_value=saved), \
             patch.object(common, "load_config", side_effect=AssertionError("Do not read .env")), \
             patch.object(present, "run_child") as child, \
             contextlib.redirect_stdout(io.StringIO()) as output:
            present.main(["search-rest", "--replay", "--color", "never"])
        child.assert_not_called()
        text = output.getvalue()
        self.assertIn("ORIGINAL QUERY", text)
        self.assertLess(text.index("RECORDED INPUT"), text.index("RECORDED EVIDENCE"))

    def test_old_upload_keeps_current_preview_separate_from_original_evidence(self):
        stream = io.StringIO()
        preview = {"completed_at": "2026-10-15T14:00:00+00:00", "inputs": [
            {"kind": "sdk_preview", "operation": "PushUploader.index_documents", "payload": {"documents": []}}]}
        present.show_inputs(present.Screen("never", stream), "indexing-apply", {}, recorded=True, fallback=preview)
        self.assertIn("not captured with the recorded upload", stream.getvalue())
        self.assertIn("nothing sent", stream.getvalue())

    def test_step_pauses_only_in_interactive_terminal(self):
        args = present.parser().parse_args(["search-rest", "--step"])
        with patch.object(sys.stdin, "isatty", return_value=True), patch("builtins.input") as wait:
            present.pause_for_response(present.Screen("never", io.StringIO()), args)
            wait.assert_called_once()
        with patch.object(sys.stdin, "isatty", return_value=False), patch("builtins.input") as wait:
            present.pause_for_response(present.Screen("never", io.StringIO()), args)
            wait.assert_not_called()


if __name__ == "__main__":
    unittest.main()
