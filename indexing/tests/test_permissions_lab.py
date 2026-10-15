"""Offline permission evidence checks with the real pinned SDK and mock transport."""
import json
from pathlib import Path
import sys
import unittest

import httpx

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from lab import Config, DOCUMENT_ID, OBJECT_TYPE, SafeFailure, configure
from check_permissions import run_checks

ALLOWED = "reader@example.com"
DENIED = "different-reader@example.com"
TOKEN = "synthetic-test-token-for-offline-tests"
CONFIG = Config("https://example.com", ".secrets/test-only", "powerupdemoTEST",
                ALLOWED, '"Example runbook"', DENIED)


class PermissionLabTests(unittest.TestCase):
    def run_mock(self, *, config=CONFIG, denied_identity=True, denied_access=False,
                 allowed_http=200, indexed=True, denied_response=None, denied_status=None,
                 debug_content_type="application/json; charset=UTF-8", debug_raw_body=None):
        requests = []

        def respond(body, status=200, content_type="application/json; charset=UTF-8"):
            return httpx.Response(status, json=body,
                                  headers={"Content-Type": content_type})

        def handler(request):
            requests.append(request)
            body = json.loads(request.content)
            if request.url.path == "/api/index/v1/debug/powerupdemoTEST/documents":
                return respond({"documentStatuses": [{"docId": DOCUMENT_ID, "objectType": OBJECT_TYPE,
                    "debugInfo": {"status": {"uploadStatus": "UPLOADED",
                        "indexingStatus": "INDEXED" if indexed else "NOT_INDEXED",
                        "lastUploadedAt": "2026-01-01T12:00:00Z",
                        "lastIndexedAt": "2026-01-01T12:00:01Z"}}}]})
            if request.url.path == "/api/index/v1/debug/powerupdemoTEST/user":
                if debug_raw_body is not None:
                    return httpx.Response(allowed_http, content=debug_raw_body,
                                          headers={"Content-Type": debug_content_type})
                if body["email"] == ALLOWED and allowed_http != 200:
                    return respond({"message": "not displayed: " + ALLOWED}, allowed_http,
                                   debug_content_type)
                if body["email"] == DENIED and denied_status is not None:
                    return respond({"status": denied_status}, content_type=debug_content_type)
                ready = body["email"] == ALLOWED or denied_identity
                return respond({"status": {"isActiveUser": ready,
                    "uploadStatus": "UPLOADED" if ready else "NOT_UPLOADED"},
                    "uploadedGroups": []}, content_type=debug_content_type)
            if request.url.path == "/api/index/v1/checkdocumentaccess":
                if body["userEmail"] == DENIED and denied_response is not None:
                    return respond(denied_response)
                return respond({"hasAccess": True if body["userEmail"] == ALLOWED else denied_access})
            self.fail("Unexpected endpoint: " + request.url.path)

        report = run_checks(config, TOKEN, transport=httpx.MockTransport(handler))
        serialized = json.dumps(report)
        for private in (ALLOWED, DENIED, TOKEN):
            self.assertNotIn(private, serialized)
        self.assertLessEqual(len(requests), 5)
        self.assertTrue(all(r.method == "POST" for r in requests))
        return report, requests

    def test_valid_readers_and_false_denied_result_complete_api_matrix(self):
        report, requests = self.run_mock()
        self.assertEqual(report["allowed_reader"]["result"], "PASS")
        self.assertEqual(report["denied_reader"]["result"], "PASS")
        self.assertIs(report["denied_reader"]["has_access"], False)
        self.assertTrue(report["all_expected_results_observed"])
        self.assertEqual(report["end_to_end_search"], "NOT_RUN")
        self.assertEqual(len(requests), 5)

    def test_missing_second_reader_is_not_run_not_denied_pass(self):
        config = Config(CONFIG.base_url, CONFIG.token_file, CONFIG.datasource, ALLOWED, CONFIG.query)
        report, requests = self.run_mock(config=config)
        self.assertEqual(report["denied_reader"]["result"], "NOT_RUN")
        self.assertEqual(report["denied_reader"]["reason"], "second_reader_not_configured")
        self.assertNotIn("has_access", report["denied_reader"])
        self.assertFalse(report["api_matrix_complete"])
        self.assertEqual(len(requests), 3)

    def test_plain_json_debug_response_recovers_without_another_request(self):
        config = Config(CONFIG.base_url, CONFIG.token_file, CONFIG.datasource, ALLOWED, CONFIG.query)
        report, requests = self.run_mock(config=config, debug_content_type="application/json")
        self.assertEqual(report["allowed_reader"]["result"], "PASS")
        self.assertEqual(len(requests), 3)
        self.assertEqual(sum(r.url.path.endswith("/user") for r in requests), 1)

    def test_plain_json_recovery_rejects_bad_json_schema_or_non200(self):
        config = Config(CONFIG.base_url, CONFIG.token_file, CONFIG.datasource, ALLOWED, CONFIG.query)
        cases = [
            (200, "application/json", b'{"status":'),
            (200, "application/json", b'{"status":{"isActiveUser":"true","uploadStatus":"UPLOADED"}}'),
            (200, "text/plain", b'{"status":{"isActiveUser":true,"uploadStatus":"UPLOADED"}}'),
            (401, "application/json", b'{"status":{"isActiveUser":true,"uploadStatus":"UPLOADED"}}'),
            (201, "application/json", b'{"status":{"isActiveUser":true,"uploadStatus":"UPLOADED"}}'),
        ]
        for status, content_type, body in cases:
            with self.subTest(status=status, content_type=content_type, body=body):
                report, requests = self.run_mock(config=config, allowed_http=status,
                    debug_content_type=content_type, debug_raw_body=body)
                self.assertEqual(report["allowed_reader"]["result"], "NOT_RUN")
                self.assertEqual(len(requests), 2)
                self.assertFalse(any(r.url.path.endswith("checkdocumentaccess") for r in requests))

    def test_plain_json_recovery_keeps_response_size_bound(self):
        config = Config(CONFIG.base_url, CONFIG.token_file, CONFIG.datasource, ALLOWED, CONFIG.query)
        report, requests = self.run_mock(config=config, debug_content_type="application/json",
            debug_raw_body=b'{"padding":"' + b'x' * 2_000_000 + b'"}')
        self.assertEqual(report["allowed_reader"]["result"], "NOT_RUN")
        self.assertEqual(len(requests), 2)

    def test_unresolved_identity_never_sends_access_check_or_counts_denial(self):
        report, requests = self.run_mock(denied_identity=False)
        self.assertEqual(report["denied_reader"]["result"], "NOT_RUN")
        self.assertNotIn("has_access", report["denied_reader"])
        self.assertFalse(report["all_expected_results_observed"])
        access = [r for r in requests if r.url.path.endswith("checkdocumentaccess")]
        self.assertEqual(len(access), 1)
        self.assertEqual(json.loads(access[0].content)["userEmail"], ALLOWED)

    def test_missing_access_boolean_is_unknown_and_true_denied_is_failure(self):
        unknown, _ = self.run_mock(denied_response={})
        self.assertEqual(unknown["denied_reader"]["result"], "NOT_RUN")
        mismatch, _ = self.run_mock(denied_access=True)
        self.assertEqual(mismatch["denied_reader"]["result"], "FAIL")
        self.assertFalse(mismatch["all_expected_results_observed"])

    def test_unknown_or_missing_identity_fields_are_inconclusive(self):
        for status in ({}, {"uploadStatus": "STATUS_UNKNOWN", "isActiveUser": True},
                       {"uploadStatus": "UPLOADED"}):
            with self.subTest(status=status):
                report, requests = self.run_mock(denied_status=status)
                self.assertEqual(report["denied_reader"]["result"], "NOT_RUN")
                self.assertNotIn("has_access", report["denied_reader"])
                self.assertEqual(len(requests), 4)

    def test_auth_rejection_stops_all_later_reads(self):
        for status in (401, 403, 429):
            with self.subTest(status=status):
                report, requests = self.run_mock(allowed_http=status)
                self.assertEqual(len(requests), 2)
                self.assertEqual(report["denied_reader"]["result"], "NOT_RUN")
                self.assertEqual(report["denied_reader"]["reason"],
                                 "resolve_authentication_authorization_or_rate_limit_first")

    def test_pending_indexing_stops_before_identity_and_access_requests(self):
        report, requests = self.run_mock(indexed=False)
        self.assertEqual(len(requests), 1)
        self.assertEqual(report["allowed_reader"]["result"], "NOT_RUN")
        self.assertFalse(report["all_expected_results_observed"])

    def test_second_reader_must_be_valid_and_not_same_email(self):
        values = {"GLEAN_INDEXING_BASE_URL": CONFIG.base_url,
                  "GLEAN_INDEXING_DATASOURCE": CONFIG.datasource,
                  "GLEAN_INDEXING_TEST_EMAIL": ALLOWED}
        for value in (ALLOWED.upper(), "not-an-email", "YOUR-TEST-USER@example.com"):
            with self.subTest(value=value), self.assertRaises(SafeFailure):
                configure({**values, "GLEAN_INDEXING_DENIED_TEST_EMAIL": value})
        self.assertIsNone(configure({**values, "GLEAN_INDEXING_DENIED_TEST_EMAIL": ""}).denied_test_email)


if __name__ == "__main__":
    unittest.main()
