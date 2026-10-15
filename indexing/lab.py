"""Shared setup and bounded transport for the isolated, pinned Indexing SDK lab."""
from __future__ import annotations

import argparse
import contextlib
from dataclasses import dataclass
from datetime import datetime
import importlib.metadata
import json
import logging
import math
import os
from pathlib import Path
import re
import sys
from urllib.parse import urlsplit

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from scripts.common import (MAX_RESPONSE_BYTES, QuietLogger, ResponseBodyLimitExceeded,
                            SafeFailure, TIMEOUT, deadline, guarded_main, identifier,
                            read_token, serialized_output, token_path, validate_base,
                            validate_query, validate_token)

HERE = Path(__file__).resolve().parent
DOCUMENT_ID = "powerup-indexing-demo-v1"
OBJECT_TYPE = "article"
TITLE = "PowerUp Demo: Orion Service Recovery"
SOURCE_URL = "https://github.com/johnyzaguirre-glean/glean-api-sdk-mcp-powerup/blob/main/indexing/sample_document.md"
BODY = (HERE / "sample_document.md").read_text(encoding="utf-8")
KEYS = {"GLEAN_INDEXING_BASE_URL", "GLEAN_INDEXING_TOKEN_FILE", "GLEAN_INDEXING_DATASOURCE",
        "GLEAN_INDEXING_TEST_EMAIL", "GLEAN_INDEXING_QUERY", "GLEAN_INDEXING_DENIED_TEST_EMAIL"}


@dataclass(frozen=True)
class Config:
    base_url: str
    token_file: str
    datasource: str
    test_email: str
    query: str
    denied_test_email: str | None = None


def load_env(path=None, environ=None):
    path = Path(path) if path is not None else HERE / ".env"
    values = {}
    if path.exists():
        if path.stat().st_size > 65536:
            raise SafeFailure("indexing/.env is too large")
        for number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
            line = line.strip()
            if not line or line.startswith("#"):
                continue
            key, sep, value = line.partition("=")
            key, value = key.strip(), value.strip()
            if not sep or key not in KEYS:
                raise SafeFailure(f"unsupported indexing/.env key on line {number}")
            if value.startswith(("'", '"')):
                if len(value) < 2 or value[-1] != value[0]:
                    raise SafeFailure(f"unclosed quote on indexing/.env line {number}")
                value = value[1:-1]
            if any(ord(c) < 32 or ord(c) == 127 for c in value):
                raise SafeFailure(f"control character on indexing/.env line {number}")
            values[key] = value
    env = os.environ if environ is None else environ
    values.update({key: env[key] for key in KEYS if key in env})
    return values


def validate_test_email(email):
    if (not re.fullmatch(r"[A-Za-z0-9.!#$%&'*+/=?^_`{|}~-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}", email)
            or len(email) > 254 or email.upper().startswith("YOUR-")):
        raise SafeFailure("set the test email to one existing approved sandbox user")
    return email


def configure(values=None):
    values = load_env() if values is None else values
    base = validate_base(values.get("GLEAN_INDEXING_BASE_URL"))
    source = values.get("GLEAN_INDEXING_DATASOURCE", "")
    if not re.fullmatch(r"powerupdemo[a-zA-Z0-9]{1,40}", source) or "YOUR" in source.upper():
        raise SafeFailure("use a dedicated alphanumeric datasource named powerupdemo plus your demo suffix")
    email = validate_test_email(values.get("GLEAN_INDEXING_TEST_EMAIL", ""))
    denied_email = values.get("GLEAN_INDEXING_DENIED_TEST_EMAIL", "").strip() or None
    if denied_email:
        validate_test_email(denied_email)
        if denied_email.casefold() == email.casefold():
            raise SafeFailure("the denied test reader must be a different approved sandbox user")
    query = validate_query(values.get("GLEAN_INDEXING_QUERY", '"' + TITLE + '"'))
    secret_file = values.get("GLEAN_INDEXING_TOKEN_FILE", ".secrets/glean-indexing-token")
    token_path(secret_file)
    return Config(base, secret_file, source, email, query, denied_email)


def confirm_target(config, confirmation):
    if confirmation != urlsplit(config.base_url).hostname:
        raise SafeFailure("--apply requires --confirm-sandbox with the exact configured backend hostname")


def check_versions():
    for name, expected in (("glean-indexing-sdk", "1.2.1"), ("glean-api-client", "0.13.0")):
        if importlib.metadata.version(name) != expected:
            raise SafeFailure("use .venv-indexing with indexing/requirements.txt; keep the search environment separate")


def make_document(config):
    from glean.indexing.models import ContentDefinition, DocumentDefinition, UserReferenceDefinition
    from glean.api_client.models import DocumentPermissionsDefinition
    return DocumentDefinition(
        datasource=config.datasource, id=DOCUMENT_ID, object_type=OBJECT_TYPE,
        title=TITLE, view_url=SOURCE_URL,
        body=ContentDefinition(mime_type="text/plain", text_content=BODY),
        permissions=DocumentPermissionsDefinition(
            allowed_users=[UserReferenceDefinition(email=config.test_email)],
            allow_anonymous_access=False, allow_all_datasource_users_access=False),
    )


@contextlib.contextmanager
def bounded_client(config, token, observations, transport=None):
    """Adapt the pinned SDK's client factory so its real calls use a bounded transport.

    PushUploader and StatusClient build clients internally in SDK 1.2.1. This scoped
    adapter supplies the official API client with redirects/retries disabled. It is
    restored afterward. No token is exported to the shell or written into .env.
    """
    import httpx
    from glean.api_client import Glean
    from glean.indexing.push import uploader as uploader_module

    class LimitedStream(httpx.SyncByteStream):
        def __init__(self, stream):
            self.stream = stream
        def __iter__(self):
            count = 0
            for chunk in self.stream:
                count += len(chunk)
                if count > MAX_RESPONSE_BYTES:
                    raise ResponseBodyLimitExceeded("body_limit")
                yield chunk
        def close(self):
            self.stream.close()

    def observe(response):
        row = {"http_status": response.status_code}
        if request_id := identifier(response.headers.get("x-request-id")):
            row["request_id"] = request_id
        observations.append(row)
        if response.headers.get("content-encoding", "identity").lower() not in ("", "identity"):
            response.close()
            raise SafeFailure("unexpected compressed response")
        response.stream = LimitedStream(response.stream)

    @contextlib.contextmanager
    def client_factory():
        with httpx.Client(timeout=TIMEOUT, follow_redirects=False, transport=transport,
                          headers={"Accept-Encoding": "identity"},
                          event_hooks={"response": [observe]}) as client:
            with Glean(api_token=token, server_url=config.base_url, client=client,
                       retry_config=None, timeout_ms=TIMEOUT * 1000,
                       debug_logger=QuietLogger()) as glean:
                yield glean
    original = uploader_module.api_client
    uploader_module.api_client = client_factory
    try:
        yield
    finally:
        uploader_module.api_client = original


def mutation_parser(description):
    parser = argparse.ArgumentParser(description=description)
    parser.add_argument("--apply", action="store_true", help="Perform the one described mutation; otherwise preview only")
    parser.add_argument("--confirm-sandbox", metavar="BACKEND_HOSTNAME", help="Attest this exact configured host is an approved sandbox")
    return parser


def preview(config, operation):
    return {"mode": "dry_run", "network_requests": 0, "operation": operation,
            "target_hostname": urlsplit(config.base_url).hostname,
            "datasource": config.datasource, "document_id": DOCUMENT_ID,
            "document_title": TITLE, "acl_user_count": 1,
            "anonymous_access": False, "all_datasource_users_access": False,
            "note": "Review your local indexing/.env email and target. Nothing has been sent."}


def safe_failure(exc):
    result = {"operation_completed": False, "exception_type": type(exc).__name__,
              "note": "Response body omitted. Check status before retrying an uncertain upload."}
    status = getattr(exc, "status_code", None)
    if isinstance(status, int):
        result["http_status"] = status
    return result


def emit(report, token=""):
    print(serialized_output(report, token), end="")


def run_guarded(main):
    logging.disable(logging.CRITICAL)
    return guarded_main(main)


def status_summary(response):
    """Keep only the known document's enumerated status and timestamp comparison."""
    entries = response.document_statuses or []
    matches = [item for item in entries if item.doc_id == DOCUMENT_ID and item.object_type == OBJECT_TYPE]
    if len(matches) != 1 or not matches[0].debug_info or not matches[0].debug_info.status:
        return {"matching_document_status_found": False, "latest_upload_indexed": False,
                "timestamps_valid": False, "readiness_reason": "no_matching_document"}
    status = matches[0].debug_info.status
    allowed = {"NOT_UPLOADED", "UPLOADED", "NOT_INDEXED", "INDEXED", "STATUS_UNKNOWN"}
    report = {"matching_document_status_found": True}
    for field in ("upload_status", "indexing_status", "permission_identity_status"):
        value = getattr(status, field, None)
        report[field] = value if value in allowed else "STATUS_UNKNOWN"
    def timestamp(value):
        if not isinstance(value, str):
            return None
        try:
            parsed = float(value)
        except ValueError:
            try:
                parsed = datetime.fromisoformat(value.replace("Z", "+00:00")).timestamp()
            except (ValueError, OverflowError, OSError):
                return None
        return parsed if math.isfinite(parsed) else None
    uploaded, indexed = timestamp(status.last_uploaded_at), timestamp(status.last_indexed_at)
    report["timestamps_valid"] = uploaded is not None and indexed is not None
    report["latest_upload_indexed"] = (status.indexing_status == "INDEXED"
        and uploaded is not None and indexed is not None and indexed >= uploaded)
    if status.indexing_status != "INDEXED":
        report["readiness_reason"] = "not_indexed"
    elif not report["timestamps_valid"]:
        report["readiness_reason"] = "timestamp_missing_or_invalid"
    elif not report["latest_upload_indexed"]:
        report["readiness_reason"] = "indexed_version_older_than_upload"
    else:
        report["readiness_reason"] = "latest_upload_indexed"
    return report
