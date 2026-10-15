"""Offline tests exercise the real pinned SDK through a mock HTTP transport."""
import contextlib
import io
import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch
import httpx

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from lab import (Config, DOCUMENT_ID, OBJECT_TYPE, SafeFailure, bounded_client, configure,
                 confirm_target, load_env, make_document, safe_failure, status_summary)
from glean.indexing.push import PushUploader, StatusClient
from glean.api_client.models import DebugDocumentsResponse, DebugDocumentRequest, DatasourceUserDefinition
import push_demo
import index_test_user
from check_demo import next_step

CONFIG = Config("https://example.com", ".secrets/test-only", "powerupdemoTEST",
                "tester@example.com", '"PowerUp Demo: Orion Service Recovery"')
TOKEN = "synthetic-test-token-12345"


class IndexingLabTests(unittest.TestCase):
    def test_next_step_distinguishes_ready_pending_denied_and_unknown_access(self):
        ready = next_step({"latest_upload_indexed": True, "configured_user_has_access": True})
        self.assertIn("Search GLEAN_INDEXING_QUERY", ready)
        pending = next_step({"latest_upload_indexed": False, "configured_user_has_access": True})
        self.assertIn("not confirmed indexed", pending)
        self.assertIn("Do not resend", pending)
        denied = next_step({"latest_upload_indexed": True, "configured_user_has_access": False})
        self.assertIn("does not have access", denied)
        self.assertIn("identity mapping", denied)
        self.assertIn("one-user ACL intact", denied)
        unknown = next_step({"latest_upload_indexed": True, "configured_user_has_access": None})
        self.assertIn("not confirmed", unknown)
        self.assertNotIn("does not have access", unknown)
        skipped = next_step({"access_check_skipped": "resolve_authentication_authorization_or_rate_limit_first"})
        self.assertIn("rate-limit", skipped)
        self.assertIn("read-only", skipped)

    def test_inert_env_preserves_phrase_without_shell_execution(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / ".env"
            marker = Path(directory) / "never-created"
            path.write_text("GLEAN_INDEXING_QUERY='\"Example phrase\"'\n"
                            f"GLEAN_INDEXING_TOKEN_FILE=$(touch {marker})\n")
            values = load_env(path, {})
            self.assertEqual(values["GLEAN_INDEXING_QUERY"], '"Example phrase"')
            self.assertIn("$(touch", values["GLEAN_INDEXING_TOKEN_FILE"])
            self.assertFalse(marker.exists())
            path.write_text("GLEAN_INDEXING_API_TOKEN=do-not-print\n")
            with self.assertRaises(SafeFailure) as caught:
                load_env(path, {})
            self.assertNotIn("do-not-print", str(caught.exception))

    def test_dedicated_source_and_exact_sandbox_confirmation(self):
        values = {"GLEAN_INDEXING_BASE_URL": CONFIG.base_url,
                  "GLEAN_INDEXING_DATASOURCE": CONFIG.datasource,
                  "GLEAN_INDEXING_TEST_EMAIL": CONFIG.test_email}
        self.assertEqual(configure(values).datasource, CONFIG.datasource)
        for source in ["companywiki", "powerupdemo", "powerupdemo_bad", "powerupdemoYOURSUFFIX"]:
            with self.subTest(source=source), self.assertRaises(SafeFailure):
                configure({**values, "GLEAN_INDEXING_DATASOURCE": source})
        confirm_target(CONFIG, "example.com")
        for confirmation in [None, "example.com.evil.example", "https://example.com", "yes"]:
            with self.subTest(confirmation=confirmation), self.assertRaises(SafeFailure):
                confirm_target(CONFIG, confirmation)

    def test_dry_run_never_reads_a_token_or_makes_a_network_call(self):
        for command in (push_demo, index_test_user):
            with patch.object(command, "configure", return_value=CONFIG), \
                 patch.object(command, "read_token") as read_secret, \
                 patch.object(command, "bounded_client") as client, \
                 patch("sys.argv", [command.__name__]), contextlib.redirect_stdout(io.StringIO()) as output:
                self.assertEqual(command.main(), 0)
                self.assertEqual(json.loads(output.getvalue())["network_requests"], 0)
                read_secret.assert_not_called()
                client.assert_not_called()

    def test_apply_without_confirmation_stops_before_token_or_network(self):
        with patch.object(push_demo, "configure", return_value=CONFIG), \
             patch.object(push_demo, "read_token") as read_secret, \
             patch.object(push_demo, "bounded_client") as client, \
             patch("sys.argv", ["push_demo", "--apply"]):
            with self.assertRaises(SafeFailure):
                push_demo.main()
            read_secret.assert_not_called()
            client.assert_not_called()

    def test_sdk_adds_one_document_with_only_one_user_acl(self):
        requests = []
        def handler(request):
            requests.append(request)
            return httpx.Response(200)
        observations = []
        with bounded_client(CONFIG, TOKEN, observations, transport=httpx.MockTransport(handler)):
            PushUploader(datasource=CONFIG.datasource, timeout_ms=30000).index_documents([make_document(CONFIG)])
        self.assertEqual(len(requests), 1)
        self.assertEqual(requests[0].url.path, "/api/index/v1/indexdocuments")
        payload = json.loads(requests[0].content)
        self.assertEqual(payload["datasource"], CONFIG.datasource)
        self.assertEqual(len(payload["documents"]), 1)
        doc = payload["documents"][0]
        self.assertEqual(doc["id"], DOCUMENT_ID)
        self.assertEqual(doc["objectType"], OBJECT_TYPE)
        self.assertEqual(doc["body"]["textContent"], (Path(__file__).resolve().parents[1] / "sample_document.md").read_text())
        self.assertIn("violet comet 641", doc["body"]["textContent"])
        self.assertEqual(doc["permissions"]["allowedUsers"], [{"email": CONFIG.test_email}])
        self.assertFalse(doc["permissions"]["allowAnonymousAccess"])
        self.assertFalse(doc["permissions"]["allowAllDatasourceUsersAccess"])
        self.assertNotIn("isLastPage", payload)
        self.assertNotIn(TOKEN, json.dumps(observations))

    def test_identity_is_separate_single_user_operation(self):
        requests = []
        def handler(request):
            requests.append(request)
            return httpx.Response(200)
        with bounded_client(CONFIG, TOKEN, [], transport=httpx.MockTransport(handler)):
            PushUploader(datasource=CONFIG.datasource).index_user(
                DatasourceUserDefinition(email=CONFIG.test_email, name="PowerUp demo tester", is_active=True))
        self.assertEqual(len(requests), 1)
        self.assertEqual(requests[0].url.path, "/api/index/v1/indexuser")
        self.assertEqual(json.loads(requests[0].content)["user"]["email"], CONFIG.test_email)

    def test_redirect_is_not_followed_and_error_text_is_omitted(self):
        requests = []
        def handler(request):
            requests.append(request)
            return httpx.Response(302, headers={"Location": "https://elsewhere.example"}, text="PRIVATE BODY " + TOKEN)
        with bounded_client(CONFIG, TOKEN, [], transport=httpx.MockTransport(handler)):
            with self.assertRaises(Exception) as caught:
                PushUploader(datasource=CONFIG.datasource).index_documents([make_document(CONFIG)])
        self.assertEqual(len(requests), 1)
        self.assertNotIn("PRIVATE", json.dumps(safe_failure(caught.exception)))
        self.assertNotIn(TOKEN, json.dumps(safe_failure(caught.exception)))

    def test_current_debug_and_access_api_paths_and_status_projection(self):
        requests = []
        body = {"documentStatuses": [{"docId": DOCUMENT_ID, "objectType": OBJECT_TYPE,
            "debugInfo": {"status": {"uploadStatus": "UPLOADED", "indexingStatus": "INDEXED",
                "permissionIdentityStatus": "UPLOADED", "lastUploadedAt": "2026-01-01T12:00:00Z",
                "lastIndexedAt": "2026-01-01T12:00:01Z"},
                "uploadedPermissions": {"allowedUsers": [{"email": "never-print@example.com"}]}}}]}
        def handler(request):
            requests.append(request)
            return httpx.Response(200, json={"hasAccess": True} if request.url.path.endswith("checkdocumentaccess") else body)
        with bounded_client(CONFIG, TOKEN, [], transport=httpx.MockTransport(handler)):
            client = StatusClient(datasource=CONFIG.datasource)
            response = client.get_documents_status([DebugDocumentRequest(doc_id=DOCUMENT_ID, object_type=OBJECT_TYPE)])
            access = client.check_document_access(object_type=OBJECT_TYPE, document_id=DOCUMENT_ID, user_email=CONFIG.test_email)
        self.assertTrue(access.has_access)
        self.assertEqual(len(requests), 2)
        self.assertEqual(requests[0].url.path, "/api/index/v1/debug/powerupdemoTEST/documents")
        self.assertEqual(requests[1].url.path, "/api/index/v1/checkdocumentaccess")
        summary = status_summary(response)
        self.assertTrue(summary["latest_upload_indexed"])
        self.assertEqual(summary["readiness_reason"], "latest_upload_indexed")
        self.assertNotIn("never-print", json.dumps(summary))
        body["documentStatuses"][0]["debugInfo"]["status"]["lastIndexedAt"] = "2025-01-01T00:00:00Z"
        older = status_summary(DebugDocumentsResponse.model_validate(body))
        self.assertFalse(older["latest_upload_indexed"])
        self.assertEqual(older["readiness_reason"], "indexed_version_older_than_upload")
        missing = status_summary(DebugDocumentsResponse(document_statuses=[]))
        self.assertFalse(missing["latest_upload_indexed"])
        self.assertEqual(missing["readiness_reason"], "no_matching_document")

    def test_status_readiness_reasons_distinguish_pending_and_unusable_timestamps(self):
        cases = [
            ("NOT_INDEXED", "100", "101", "not_indexed", True, False),
            ("NOT_INDEXED", None, None, "not_indexed", False, False),
            ("INDEXED", "100", None, "timestamp_missing_or_invalid", False, False),
            ("INDEXED", "invalid-private-value", "101", "timestamp_missing_or_invalid", False, False),
            ("INDEXED", "100", "NaN", "timestamp_missing_or_invalid", False, False),
            ("INDEXED", "100", "Infinity", "timestamp_missing_or_invalid", False, False),
            ("INDEXED", "100", "99", "indexed_version_older_than_upload", True, False),
            ("INDEXED", "100", "100", "latest_upload_indexed", True, True),
            ("INDEXED", "100", "101", "latest_upload_indexed", True, True),
        ]
        for state, uploaded, indexed, reason, valid, ready in cases:
            with self.subTest(state=state, uploaded=uploaded, indexed=indexed):
                body = {"documentStatuses": [{"docId": DOCUMENT_ID, "objectType": OBJECT_TYPE,
                    "debugInfo": {"status": {"uploadStatus": "UPLOADED", "indexingStatus": state,
                        "lastUploadedAt": uploaded, "lastIndexedAt": indexed}}}]}
                summary = status_summary(DebugDocumentsResponse.model_validate(body))
                self.assertEqual(summary["readiness_reason"], reason)
                self.assertIs(summary["timestamps_valid"], valid)
                self.assertIs(summary["latest_upload_indexed"], ready)
                self.assertNotIn("invalid-private-value", json.dumps(summary))
                self.assertNotIn("last_uploaded_at", summary)
                self.assertNotIn("last_indexed_at", summary)

    def test_missing_or_ambiguous_document_status_has_no_readiness_claim(self):
        entry = {"docId": DOCUMENT_ID, "objectType": OBJECT_TYPE,
                 "debugInfo": {"status": {"indexingStatus": "INDEXED",
                     "lastUploadedAt": "100", "lastIndexedAt": "101"}}}
        for entries in ([], [entry, entry], [{"docId": "other", "objectType": OBJECT_TYPE}],
                        [{"docId": DOCUMENT_ID, "objectType": OBJECT_TYPE}]):
            with self.subTest(entries=entries):
                summary = status_summary(DebugDocumentsResponse.model_validate({"documentStatuses": entries}))
                self.assertFalse(summary["matching_document_status_found"])
                self.assertFalse(summary["latest_upload_indexed"])
                self.assertFalse(summary["timestamps_valid"])
                self.assertEqual(summary["readiness_reason"], "no_matching_document")


if __name__ == "__main__":
    unittest.main()
