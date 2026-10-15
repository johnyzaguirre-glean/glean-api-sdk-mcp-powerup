"""Offline Chat request, output, configuration and failure checks."""
import contextlib
import copy
import io
import json
import os
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

import httpx

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from scripts import chat_lab, common
from scripts.common import SafeFailure, load_config, serialized_output
from scripts.check_setup import main as check_setup

TOKEN = "synthetic-chat-token-12345"
ANSWER = {
    "id": "offline-response", "object": "RESPONSE",
    "created_at": "2026-10-14T12:00:00Z", "status": "COMPLETED",
    "request_id": "offline-request", "store": False,
    "output": [{"type": "MESSAGE", "role": "ASSISTANT", "content": [{
        "type": "OUTPUT_TEXT", "text": "Use the documented endpoint.",
        "annotations": [{"type": "CITATION", "sources": [{
            "type": "DOCUMENT", "title": "API guide",
            "url": "https://example.com/guide?signature=private#section",
        }]}],
    }]}],
}


class ChatTests(unittest.TestCase):
    def invoke(self, handler, use_sdk=False):
        original = httpx.Client
        client_options = []
        def factory(**kwargs):
            client_options.append(kwargs)
            return original(transport=httpx.MockTransport(handler), **kwargs)
        with patch("httpx.Client", side_effect=factory):
            result = chat_lab.chat_probe("https://example.com", TOKEN,
                'What is the "API" endpoint?', use_sdk=use_sdk)
        self.assertFalse(client_options[0]["follow_redirects"])
        self.assertEqual(client_options[0]["timeout"], 120)
        return result

    def test_rest_and_actual_pinned_sdk_send_chat_contract(self):
        for use_sdk in (False, True):
            with self.subTest(use_sdk=use_sdk):
                requests = []
                def handler(req):
                    requests.append(req)
                    return httpx.Response(200, json=ANSWER)
                result = self.invoke(handler, use_sdk)
                self.assertEqual(len(requests), 1)
                request = requests[0]
                self.assertEqual(request.method, "POST")
                self.assertEqual(set(request.extensions["timeout"].values()), {120})
                self.assertEqual(request.url.path, "/api/chat")
                self.assertEqual(request.headers["Authorization"], "Bearer " + TOKEN)
                self.assertEqual(json.loads(request.content), {
                    "input": 'What is the "API" endpoint?', "store": False, "stream": False})
                self.assertEqual(result["response_status"], "COMPLETED")
                self.assertTrue(result["answer_present"])
                self.assertEqual(result["citation_count"], 1)
                self.assertEqual(result["citations"][0]["url"], "https://example.com/guide")
                self.assertNotIn("private", json.dumps(result))

    def test_failed_empty_and_missing_citation_outputs(self):
        failed = dict(ANSWER, status="FAILED", error={"code": "backend_unavailable", "message": TOKEN})
        result = chat_lab.chat_summary(failed, TOKEN)
        self.assertFalse(result["answer_present"])
        self.assertNotIn("answer", result)
        self.assertEqual(result["chat_error_code"], "backend_unavailable")
        empty = copy.deepcopy(ANSWER)
        empty["output"][0]["content"][0]["text"] = "\x1b[31m \u202e"
        self.assertFalse(chat_lab.chat_summary(empty, TOKEN)["answer_present"])
        uncited = copy.deepcopy(ANSWER)
        uncited["output"][0]["content"][0].pop("annotations")
        result = chat_lab.chat_summary(uncited, TOKEN)
        self.assertTrue(result["answer_present"])
        self.assertEqual(result["citation_count"], 0)
        self.assertIn("No source citations", result["citation_notice"])
        for malformed in (None, [], {"status": "COMPLETED", "output": "bad"},
                          {"status": "COMPLETED", "output": [{"role": "ASSISTANT", "content": 1}]}):
            self.assertFalse(chat_lab.chat_summary(malformed, TOKEN)["answer_present"])

    def test_redaction_precedes_truncation_and_removes_controls_and_signed_links(self):
        answer = copy.deepcopy(ANSWER)
        part = answer["output"][0]["content"][0]
        part["text"] = ("\x1b[31mRead https://example.com/a?token=OTHER_SECRET#secret "
                         "\u202e" + "x" * 3950 + TOKEN + "y" * 200)
        part["annotations"][0]["sources"][0]["title"] = "x" * 230 + TOKEN
        output = serialized_output(chat_lab.chat_summary(answer, TOKEN), TOKEN)
        for secret in (TOKEN, "OTHER_SECRET", "\\u001b", "\\u202e", "synthetic-chat"):
            self.assertNotIn(secret, output)
        self.assertIn('"answer_truncated": true', output)
        self.assertLessEqual(len(json.loads(output)["answer"]), 4000)

    def test_no_retries_redirects_or_raw_error_details(self):
        for status in (302, 401, 403, 429, 500):
            for use_sdk in (False, True):
                with self.subTest(status=status, use_sdk=use_sdk):
                    calls = []
                    def handler(req):
                        calls.append(req)
                        return httpx.Response(status, headers={
                            "Location": "https://other.example/steal",
                            "Content-Type": "application/problem+json"},
                            json={"status": status, "code": "access_denied", "request_id": "offline",
                                  "detail": "PRIVATE ERROR " + TOKEN})
                    result = self.invoke(handler, use_sdk)
                    self.assertEqual(len(calls), 1)
                    self.assertEqual(result["request_count"], 1)
                    self.assertEqual(result["http_status"], status)
                    self.assertNotIn("PRIVATE ERROR", json.dumps(result))
                    self.assertNotIn(TOKEN, json.dumps(result))
                    self.assertNotIn("answer", result)

    def test_transport_error_body_limit_and_compression_fail_closed(self):
        def fail(_req):
            raise RuntimeError("private exception " + TOKEN)
        for use_sdk in (False, True):
            result = self.invoke(fail, use_sdk)
            self.assertEqual(result["exception_type"], "RuntimeError")
            self.assertNotIn(TOKEN, json.dumps(result))
            with patch.object(chat_lab, "MAX_RESPONSE_BYTES", 20):
                result = self.invoke(lambda req: httpx.Response(200, json=ANSWER), use_sdk)
            self.assertEqual(result["response_omitted"], "body_limit")
            with patch.object(chat_lab, "MAX_RESPONSE_BYTES", 20):
                result = self.invoke(lambda req: httpx.Response(200,
                    stream=httpx.ByteStream(b"x" * 21)), use_sdk)
            self.assertEqual(result["response_omitted"], "body_limit")
            result = self.invoke(lambda req: httpx.Response(200,
                headers={"content-encoding": "gzip"},
                stream=httpx.ByteStream(b"compressed-secret")), use_sdk)
            self.assertEqual(result["exception_type"], "SafeFailure")
            self.assertNotIn("compressed-secret", json.dumps(result))

    def test_chat_config_is_separate_and_setup_ignores_search_placeholder(self):
        with tempfile.TemporaryDirectory() as directory:
            token = Path(directory) / "token"
            token.write_text(TOKEN)
            token.chmod(0o600)
            envfile = Path(directory) / ".env"
            envfile.write_text(
                "GLEAN_BASE_URL=https://example.com\n"
                f"GLEAN_TOKEN_FILE={token}\n"
                "GLEAN_QUERY=YOUR KNOWN DOCUMENT TITLE\n"
                "GLEAN_CHAT_QUERY='What is our API endpoint?'\n")
            config = load_config(envfile, environ={})
            self.assertEqual(config["GLEAN_CHAT_QUERY"], "What is our API endpoint?")
            with patch.object(chat_lab, "load_config", return_value=config), contextlib.redirect_stdout(io.StringIO()):
                self.assertEqual(check_setup(["--chat"]), 0)
                args = chat_lab.chat_parser("test").parse_args([])
                self.assertEqual(chat_lab.prepare_chat(args)[2], config["GLEAN_CHAT_QUERY"])
                args.query = None
                with self.assertRaises(SafeFailure):
                    chat_lab.prepare_chat(args)

    def test_total_deadline_defaults_to_30_and_chat_override_is_120(self):
        def timeout():
            raise TimeoutError("private detail")
        for seconds, kwargs in ((30, {}), (120, {"timeout_seconds": 120})):
            with self.subTest(seconds=seconds), patch.object(common.signal, "setitimer") as timer:
                result = common.execute("test", 200, timeout, **kwargs)
                self.assertEqual(result["error"], f"timeout_{seconds}_seconds")
                self.assertFalse(result["test_expectation_met"])
                self.assertEqual(timer.call_args_list[0].args, (common.signal.ITIMER_REAL, seconds))
                self.assertEqual(timer.call_args_list[-1].args, (common.signal.ITIMER_REAL, 0))

    def test_reports_saved_private_and_exit_status_tracks_outcome(self):
        for status, text, citations, expected_exit in (
                ("COMPLETED", "Answer", [], 0), ("COMPLETED", "", [], 1),
                ("FAILED", "private", [], 1)):
            with self.subTest(status=status, text=text), tempfile.TemporaryDirectory() as directory:
                data = copy.deepcopy(ANSWER)
                data["status"] = status
                data["output"][0]["content"][0].update(text=text, annotations=citations)
                result = {"http_status": 200, "request_count": 1, **chat_lab.chat_summary(data, TOKEN)}
                with patch.object(chat_lab, "ROOT", Path(directory)), \
                     patch.object(chat_lab, "prepare_chat", return_value=("https://example.com", TOKEN, "question")), \
                     patch.object(chat_lab, "chat_parser") as parser, \
                     patch.object(chat_lab, "chat_probe", return_value=result), \
                     patch.object(chat_lab, "execute", wraps=chat_lab.execute) as timed, \
                     contextlib.redirect_stdout(io.StringIO()):
                    parser.return_value.parse_args.return_value = object()
                    self.assertEqual(chat_lab.run_chat(), expected_exit)
                    self.assertEqual(timed.call_args.kwargs["timeout_seconds"], 120)
                report = Path(directory) / "outputs/rest-chat.json"
                self.assertEqual(report.stat().st_mode & 0o777, 0o600)
                self.assertNotIn(TOKEN, report.read_text())


if __name__ == "__main__":
    unittest.main()
