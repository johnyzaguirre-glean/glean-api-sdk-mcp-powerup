"""Verify authentic request/response capture and presentation, entirely offline."""
import contextlib
import io
import json
import os
from pathlib import Path
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
        self.assertEqual(events[1]["kind"], "http_response")
        self.assertEqual(events[1]["payload"], {"results": []})
        self.assertEqual(events[1]["http_status"], 200)

    def test_sdk_response_capture_preserves_complete_original_body(self):
        import httpx
        original = {
            "results": [], "has_more": False, "next_cursor": None,
            "warnings": [], "request_id": "offline-test-request",
            "additionalServerData": {
                "rows": [{"number": number, "nested": {"unchanged": True}}
                         for number in range(225)],
                "url": "https://example.test/document?version=3&view=full#details",
                "longText": "actual response text " * 1000,
            },
        }
        original_client = httpx.Client
        def client(**kwargs):
            return original_client(transport=httpx.MockTransport(
                lambda request: httpx.Response(200, json=original)), **kwargs)
        with tempfile.NamedTemporaryFile() as sink, \
             patch.dict(os.environ, {"GLEAN_PRESENTER_INPUT_FILE": sink.name}), \
             patch.object(httpx, "Client", side_effect=client):
            common.sdk_probe("https://sandbox.example", "demo-only-secret", "known document")
            events = [json.loads(line) for line in Path(sink.name).read_text().splitlines()]
        response = events[1]
        self.assertEqual(response["payload"], original)
        self.assertEqual(response["body_format"], "json")
        self.assertEqual(response["http_status"], 200)
        self.assertNotIn("http_status", response["payload"])
        self.assertNotIn("latest_upload_indexed", response["payload"])
        self.assertNotIn("readiness_reason", response["payload"])
        preserved = present.safe_recording({"exchanges": events})
        self.assertEqual(preserved["exchanges"][1]["payload"], original)
        stream = io.StringIO()
        args = present.parser().parse_args(["search-python", "--color", "never"])
        present.show_exchanges(present.Screen("never", stream), "search-python", preserved, args)
        self.assertIn(json.dumps(original, indent=2, ensure_ascii=True), stream.getvalue())
        self.assertNotIn("[Display excerpt ends here", stream.getvalue())

    def test_response_capture_is_opt_in_and_does_not_read_disabled_stream(self):
        import httpx
        class ObservedStream(httpx.SyncByteStream):
            def __iter__(self):
                raise AssertionError("Capture must not consume a disabled response stream")
                yield b""
        response = httpx.Response(200, stream=ObservedStream(),
                                 request=httpx.Request("POST", "https://sandbox.example/api/chat"))
        with patch.dict(os.environ, {}, clear=True):
            common.capture_http_response(response, "demo-only-secret")

    def test_empty_http_response_is_not_replaced_with_json_object(self):
        import httpx
        original_client = httpx.Client
        def client(**kwargs):
            return original_client(transport=httpx.MockTransport(
                lambda request: httpx.Response(204, content=b"")), **kwargs)
        with tempfile.NamedTemporaryFile() as sink, \
             patch.dict(os.environ, {"GLEAN_PRESENTER_INPUT_FILE": sink.name}), \
             patch.object(httpx, "Client", side_effect=client):
            with bounded_client({"request_count": 0}, token="demo-only-secret") as transport:
                response = transport.post("https://sandbox.example/api/chat", json={"input": "hello"})
                self.assertEqual(response.content, b"")
            events = [json.loads(line) for line in Path(sink.name).read_text().splitlines()]
        self.assertEqual(events[1]["body_format"], "empty")
        self.assertIsNone(events[1]["payload"])
        stream = io.StringIO()
        args = present.parser().parse_args(["chat-rest", "--color", "never"])
        present.show_exchanges(present.Screen("never", stream), "chat-rest", {"exchanges": events}, args)
        response_text = stream.getvalue().split("RESPONSE 1 | HTTP 204", 1)[1]
        self.assertIn("(Empty body)", response_text)
        self.assertNotIn("{}", response_text)
        self.assertNotIn("null", response_text)

    def test_text_response_keeps_text_body_separate_from_metadata(self):
        with tempfile.NamedTemporaryFile() as sink, patch.dict(os.environ, {"GLEAN_PRESENTER_INPUT_FILE": sink.name}):
            common.capture_http_body("POST /api/search", b"Service temporarily unavailable\n",
                                     http_status=503, content_type="text/plain")
            response = json.loads(Path(sink.name).read_text())
        self.assertEqual(response["payload"], "Service temporarily unavailable\n")
        self.assertEqual(response["body_format"], "text")
        self.assertEqual(response["http_status"], 503)

    def test_child_capture_survives_as_evidence_and_standalone_import_works(self):
        code = ("from presenter_capture import capture_input, capture_response; "
                "capture_input('http_request','POST /api/search',{'query':'saved input','page_size':3}); "
                "capture_response('POST /api/search',{'results':[]},http_status=200); "
                "print('{\"http_status\":200}')")
        result = present.run_child([sys.executable, "-c", code], 10, root=ROOT / "scripts")
        self.assertEqual(result["exit_code"], 0)
        self.assertEqual(result["inputs"][0]["payload"]["query"], "saved input")
        self.assertEqual([event["kind"] for event in result["exchanges"]],
                         ["http_request", "http_response"])
        self.assertEqual(result["exchanges"][1]["payload"], {"results": []})

    def test_replay_uses_recorded_payload_and_does_not_read_current_config(self):
        saved = {"exercise": "search-rest", "completed_at": "2026-10-15T14:00:00+00:00",
                 "command": [".venv/bin/python", "examples/rest_search.py"], "exit_code": 0,
                 "elapsed_seconds": 1, "report": {"http_status": 200},
                 "exchanges": [{"kind": "http_request", "operation": "POST /api/search",
                             "payload": {"query": "ORIGINAL QUERY", "page_size": 3}},
                             {"kind": "http_response", "operation": "POST /api/search",
                              "payload": {"results": []}, "http_status": 200,
                              "body_format": "json"}]}
        with patch.object(present, "load_recording", return_value=saved), \
             patch.object(common, "load_config", side_effect=AssertionError("Do not read .env")), \
             patch.object(present, "run_child") as child, \
             contextlib.redirect_stdout(io.StringIO()) as output:
            present.main(["search-rest", "--replay", "--color", "never"])
        child.assert_not_called()
        text = output.getvalue()
        self.assertIn("ORIGINAL QUERY", text)
        self.assertLess(text.index("REQUEST 1 | POST /api/search"), text.index("RESPONSE 1 | HTTP 200"))
        self.assertLess(text.index("RESPONSE 1 | HTTP 200"), text.index("WHAT THIS MEANS"))
        self.assertNotIn('"http_status"', text)

    def test_lab_interpretation_is_plain_text_without_synthetic_json(self):
        report = {"readiness_reason": "indexed_version_older_than_upload", "latest_upload_indexed": False,
                  "allowed_reader": {"result": "NOT_RUN", "reason": "document_not_confirmed_indexed"},
                  "denied_reader": {"result": "NOT_RUN", "reason": "second_reader_not_configured"}}
        result = {"exit_code": 1, "elapsed_seconds": 1, "report": report}
        output = io.StringIO()
        present.show_result(present.Screen("never", output), "indexing-status", result,
                            ROOT / "outputs/presenter/indexing-status.json", recorded=True)
        text = output.getvalue()
        self.assertIn("WHAT THIS MEANS | lab interpretation, not API response fields", text)
        self.assertIn("last indexed time is earlier than the last uploaded time", text)
        self.assertIn("Allowed-reader check was not run", text)
        self.assertIn("Denied-reader check was not run because no second reader is configured", text)
        self.assertNotIn('"readiness_reason"', text)
        self.assertNotIn('"latest_upload_indexed"', text)
        self.assertNotIn("{", text)
        self.assertEqual(report["readiness_reason"], "indexed_version_older_than_upload")

    def test_old_recording_without_capture_does_not_invent_an_input_or_response(self):
        stream = io.StringIO()
        args = present.parser().parse_args(["indexing-apply", "--replay", "--color", "never"])
        present.show_exchanges(present.Screen("never", stream), "indexing-apply", {}, args, recorded=True)
        self.assertIn("No request or response bodies were captured", stream.getvalue())
        self.assertIn("No reconstructed JSON is shown", stream.getvalue())
        self.assertNotIn("{", stream.getvalue())

    def test_request_and_response_render_exact_bodies_in_order(self):
        request = {"query": "known document", "page_size": 3}
        response = {"documentStatuses": [{"docId": "demo", "debugInfo": {
            "status": {"uploadStatus": "UPLOADED", "indexingStatus": "INDEXED"}}}]}
        events = [{"kind": "http_request", "operation": "POST /debug/source/documents", "payload": request},
                  {"kind": "http_response", "operation": "POST /debug/source/documents",
                   "payload": response, "http_status": 200, "content_type": "application/json", "body_format": "json"}]
        stream = io.StringIO()
        args = present.parser().parse_args(["indexing-status", "--color", "never"])
        present.show_exchanges(present.Screen("never", stream), "indexing-status", {"exchanges": events}, args)
        text = stream.getvalue()
        self.assertIn(json.dumps(request, indent=2), text)
        self.assertIn(json.dumps(response, indent=2), text)
        self.assertLess(text.index('"query"'), text.index("RESPONSE 1 | HTTP 200"))
        self.assertLess(text.index("RESPONSE 1 | HTTP 200"), text.index('"documentStatuses"'))
        self.assertNotIn('"http_status"', text)
        self.assertNotIn('"payload"', text)
        self.assertNotIn('"readiness_reason"', text)
        self.assertIn("-" * 100, text)

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
