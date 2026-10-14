"""Offline checks for configuration, secret boundaries, and response handling."""
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
sys.path.insert(0, str(ROOT / "scripts"))
from common import (NoRedirect, SafeFailure, expected_result, load_config, read_token,
                    rest_probe, sdk_probe, safe_scalar, safe_url, save_report, serialized_output,
                    summarize, validate_base, url_fingerprint, title_fingerprint, same_search_results)
from run_mcp_test import matching_arguments, output_metadata, read_rpc, validate_url


class SafetyTests(unittest.TestCase):
    def test_dotenv_is_data_and_preserves_search_phrase(self):
        with tempfile.TemporaryDirectory() as directory:
            config = Path(directory) / ".env"
            marker = Path(directory) / "must-not-exist"
            config.write_text(
                "GLEAN_QUERY='\"A known document\"'\n"
                f"GLEAN_TOKEN_FILE=$(touch {marker})\n")
            values = load_config(config, environ={})
            self.assertEqual(values["GLEAN_QUERY"], '"A known document"')
            self.assertIn("$(touch", values["GLEAN_TOKEN_FILE"])
            self.assertFalse(marker.exists())
            self.assertEqual(load_config(config, {"GLEAN_QUERY": "override"})["GLEAN_QUERY"], "override")

    def test_dotenv_rejects_unknown_keys_without_printing_value(self):
        with tempfile.TemporaryDirectory() as directory:
            config = Path(directory) / ".env"
            config.write_text("GLEAN_TOKEN=do-not-print-this\n")
            with self.assertRaises(SafeFailure) as captured:
                load_config(config, {})
            self.assertNotIn("do-not-print", str(captured.exception))

    def test_https_origin_and_mcp_url_validation(self):
        self.assertEqual(validate_base("https://example.com/"), "https://example.com")
        for url in ["http://example.com", "https://user:pass@example.com", "https://example.com/api/search",
                    "https://example.com?token=secret", "https://example.com:8443", "https://exa\nmple.com", None]:
            with self.subTest(url=url), self.assertRaises(SafeFailure):
                validate_base(url)
        self.assertEqual(validate_url("https://example.com/mcp/search"), "https://example.com/mcp/search")
        for url in ["https://example.com/mcp/", "https://example.com/mcp/x?q=secret", "http://example.com/mcp/x"]:
            with self.subTest(url=url), self.assertRaises(SafeFailure):
                validate_url(url)

    @unittest.skipUnless(os.name == "posix", "requires POSIX permissions")
    def test_token_permissions_and_symlink_are_enforced(self):
        with tempfile.TemporaryDirectory() as directory:
            token = Path(directory) / "credential"
            token.write_text("synthetic-test-token-12345\n")
            token.chmod(0o600)
            self.assertEqual(read_token(str(token)), "synthetic-test-token-12345")
            token.chmod(0o644)
            with self.assertRaises(SafeFailure):
                read_token(str(token))
            token.chmod(0o600)
            link = Path(directory) / "link"
            link.symlink_to(token)
            with self.assertRaises(SafeFailure):
                read_token(str(link))

    def test_output_strips_snippets_queries_terminal_controls_and_token(self):
        token = "synthetic-test-token-12345"
        data = {"request_id": "request-123", "has_more": False, "warnings": [], "next_cursor": None,
                "results": [{"title": "Document\x1b[31m " + token,
                             "url": "https://example.com/doc?access_token=secret#fragment",
                             "snippet": "PRIVATE DOCUMENT TEXT", "body": "PRIVATE BODY"}]}
        result = summarize("search", data)
        output = serialized_output(result, token)
        for secret in [token, "PRIVATE", "access_token", "fragment", "\\u001b"]:
            self.assertNotIn(secret, output)
        self.assertIn("[REDACTED]", output)
        self.assertEqual(result["results"][0]["url"], "https://example.com/doc")
        self.assertIsNone(safe_url("https://user:secret@example.com/doc"))
        self.assertIsNone(safe_url("https://example.com/\nmalformed"))

    def test_expected_title_and_url_must_be_on_same_row(self):
        data = summarize("search", {"results": [{"title": "Target", "url": "https://example.com/wrong"},
                            {"title": "Other", "url": "https://example.com/right"}]})
        self.assertFalse(expected_result(data, "Target", "https://example.com/right")["expected_document_matched"])
        self.assertTrue(expected_result(data, "Target", "https://example.com/wrong")["expected_document_matched"])

    def test_reports_are_private_and_redacted(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "report.json"
            save_report(path, {"message": "synthetic-test-token-12345"}, "synthetic-test-token-12345")
            self.assertEqual(json.loads(path.read_text())["message"], "[REDACTED]")
            self.assertEqual(path.stat().st_mode & 0o777, 0o600)

    def test_redirect_does_not_forward_bearer_token(self):
        self.assertIsNone(NoRedirect().redirect_request(None, None, 302, "redirect", {}, "https://other.example"))

    def test_mcp_extracts_named_results_not_prose_or_embedded_links(self):
        output = output_metadata({"content": [{"type": "text", "text":
            "## 1. Known document\n**Link:** https://example.com/doc?secret=yes\n"
            "Excerpt mentions PRIVATE TEXT and https://example.com/unrelated\n"}]},
            "Known document", "https://example.com/doc?secret=yes")
        self.assertTrue(output["expected_fixture_result_matched"])
        self.assertEqual(output["fixture_result_metadata"], [{"title": "Known document",
            "title_sha256": title_fingerprint("Known document"), "url": "https://example.com/doc",
            "url_sha256": url_fingerprint("https://example.com/doc?secret=yes")}])
        self.assertNotIn("PRIVATE", json.dumps(output))
        self.assertNotIn("unrelated", json.dumps(output))

    def test_full_url_fingerprints_distinguish_query_and_fragment(self):
        original = "https://example.com/view?doc=expected#section-one"
        response = summarize("search", {"results": [{"title": "Same title", "url": original}]})
        self.assertEqual(response["results"][0]["url"], "https://example.com/view")
        self.assertTrue(expected_result(response, "Same title", original)["expected_document_matched"])
        self.assertTrue(same_search_results(response, response))
        for different in ["https://example.com/view?doc=wrong#section-one",
                          "https://example.com/view?doc=expected#section-two"]:
            with self.subTest(url=different):
                self.assertFalse(expected_result(response, "Same title", different)["expected_document_matched"])
                other = summarize("search", {"results": [{"title": "Same title", "url": different}]})
                self.assertFalse(same_search_results(response, other))
                for block in [
                    {"content": [], "structuredContent": {"results": [{"title": "Same title", "url": original}]}},
                    {"content": [{"type": "text", "text": f"## 1. Same title\n**Link:** {original}\n"}]},
                ]:
                    self.assertFalse(output_metadata(block, "Same title", different)["expected_fixture_result_matched"])
                    self.assertTrue(output_metadata(block, "Same title", original)["expected_fixture_result_matched"])

    def test_long_titles_compare_before_truncation(self):
        title = "A" * 260 + " expected"
        url = "https://example.com/document"
        response = summarize("search", {"results": [{"title": title, "url": url}]})
        self.assertEqual(len(response["results"][0]["title"]), 240)
        self.assertTrue(expected_result(response, title, url)["expected_document_matched"])
        different = "A" * 260 + " different"
        self.assertFalse(expected_result(response, different, url)["expected_document_matched"])
        other = summarize("search", {"results": [{"title": different, "url": url}]})
        self.assertFalse(same_search_results(response, other))
        block = {"content": [], "structuredContent": {"results": [{"title": title, "url": url}]}}
        self.assertTrue(output_metadata(block, title, url)["expected_fixture_result_matched"])
        self.assertFalse(output_metadata(block, different, url)["expected_fixture_result_matched"])

    def test_mcp_schema_validation_and_external_refs(self):
        schema = {"type": "object", "properties": {"query": {"type": "string"}},
                  "required": ["query"], "additionalProperties": False}
        self.assertEqual(matching_arguments(schema, "known", None), {"query": "known"})
        with self.assertRaises(Exception):
            matching_arguments({"$ref": "https://example.invalid/do-not-fetch",
                                "properties": {"query": {"type": "string"}}}, "known", None)

    def test_mcp_env_query_overrides_or_fills_extra_arguments(self):
        schema = {"type": "object", "properties": {
            "query": {"type": "string"}, "goal": {"type": "string"}},
            "required": ["query", "goal"], "additionalProperties": False}
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "args.json"
            for fields in [{"goal": "Find a document"},
                           {"goal": "Find a document", "query": "stale query"}]:
                path.write_text(json.dumps(fields))
                args = matching_arguments(schema, '"Env document"', path)
                self.assertEqual(args, {"goal": "Find a document", "query": '"Env document"'})
            # Injecting the query must not bypass validation of other required fields.
            path.write_text('{}')
            with self.assertRaises(SafeFailure):
                matching_arguments(schema, "known", path)

    def test_mcp_nested_pointer_uses_existing_parent_and_rfc_escapes(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "args.json"
            path.write_text(json.dumps({"input": {"terms": [None], "a/b": {}}}))
            args = matching_arguments({"type": "object"}, "from env", path, "/input/terms/0")
            self.assertEqual(args["input"]["terms"], ["from env"])
            args = matching_arguments({"type": "object"}, "from env", path, "/input/a~1b/query~0text")
            self.assertEqual(args["input"]["a/b"]["query~text"], "from env")
            for pointer in ["input/query", "", "/missing/query", "/input/terms/1",
                            "/input/terms/-", "/input/terms/00", "/input/terms/-1",
                            "/input/terms/0/query", "/input/a~2b", "/input/a~"]:
                with self.subTest(pointer=pointer), self.assertRaises(SafeFailure):
                    matching_arguments({"type": "object"}, "from env", path, pointer)

    def test_rest_error_body_is_not_printed(self):
        class Response(io.BytesIO):
            status = 403
        response = Response(json.dumps({"code": "FORBIDDEN", "message": "SECRET", "request_id": "abc"}).encode())
        with patch("common.request.build_opener") as opener:
            opener.return_value.open.return_value = response
            result = rest_probe("https://example.com", "synthetic-test-token-12345", "POST", "/api/search", {}, "search")
        self.assertEqual(result["http_status"], 403)
        self.assertNotIn("SECRET", json.dumps(result))

    def test_pinned_sdk_sends_platform_search_and_sanitizes_response(self):
        import httpx
        response = {"request_id": "synthetic-request", "has_more": False,
                    "warnings": [], "next_cursor": None,
                    "results": [{"title": "Known document", "url": "https://example.com/doc?secret=yes",
                                 "datasource": "example", "snippets": ["PRIVATE CONTENT"]}]}
        requests = []
        def handler(request):
            requests.append(request)
            return httpx.Response(200, json=response)
        original_client = httpx.Client
        def test_client(**kwargs):
            return original_client(transport=httpx.MockTransport(handler), **kwargs)
        with patch("httpx.Client", side_effect=test_client):
            result = sdk_probe("https://example.com", "synthetic-test-token-12345", '"Known document"')
        self.assertEqual(len(requests), 1)
        self.assertEqual(requests[0].url.path, "/api/search")
        self.assertEqual(json.loads(requests[0].content), {"query": '"Known document"', "page_size": 3})
        self.assertEqual(result["http_status"], 200)
        self.assertTrue(result["expected_payload_present"])
        self.assertEqual(result["results"][0]["url"], "https://example.com/doc")
        self.assertNotIn("PRIVATE", json.dumps(result))


if __name__ == "__main__":
    unittest.main()
