"""Opt-in recording of real request/response bodies. Never capture headers."""
from __future__ import annotations

import json
import os
from pathlib import Path
import re
import stat
from urllib.parse import quote

MAX_INPUT_BYTES = 4_000_000
MAX_EVENT_BYTES = 2_500_000


def redact_payload(value, token=""):
    """Preserve JSON except marked credentials. Do not truncate or rename fields."""
    if isinstance(value, dict):
        return {key: "[REDACTED]" if re.search(
                    r"(?i)(^|_)(token|secret|password|authorization|headers|cookie)(_|$)", str(key))
                else redact_payload(item, token) for key, item in value.items()}
    if isinstance(value, list):
        return [redact_payload(item, token) for item in value]
    if isinstance(value, str):
        if token:
            for secret in {token, quote(token, safe=""), quote(token, safe="").lower()}:
                value = value.replace(secret, "[REDACTED]")
        value = re.sub(r"(?i)\bBearer\s+[^\s\"']+", "Bearer [REDACTED]", value)
        value = re.sub(r"(?<![A-Za-z0-9])[A-Za-z0-9+/]{40,}={1,2}(?![A-Za-z0-9])", "[REDACTED]", value)
        value = re.sub(r"\beyJ[A-Za-z0-9_-]+\.[A-Za-z0-9_-]+\.[A-Za-z0-9_-]+\b", "[REDACTED]", value)
    return value


def _capture(event, token):
    destination = os.environ.get("GLEAN_PRESENTER_INPUT_FILE")
    if not destination:
        return
    event = redact_payload(event, token)
    encoded = (json.dumps(event, ensure_ascii=True) + "\n").encode()
    if len(encoded) > MAX_EVENT_BYTES:
        event["payload"] = None
        event["body_omitted_reason"] = "Body exceeds the capture size limit. No substitute body is shown."
        encoded = (json.dumps(event) + "\n").encode()
    descriptor = None
    try:
        descriptor = os.open(Path(destination), os.O_WRONLY | os.O_APPEND | os.O_NOFOLLOW)
        info = os.fstat(descriptor)
        if (not stat.S_ISREG(info.st_mode) or info.st_uid != os.getuid()
                or info.st_mode & 0o077 or info.st_size + len(encoded) > MAX_INPUT_BYTES):
            return
        os.write(descriptor, encoded)
    except OSError:
        pass
    finally:
        if descriptor is not None:
            os.close(descriptor)


def capture_input(kind, operation, payload, *, token="", endpoint=None):
    event = {"kind": kind, "operation": operation, "payload": payload}
    if endpoint is not None:
        event["endpoint"] = endpoint
    _capture(event, token)


def capture_response(operation, payload, *, token="", endpoint=None, http_status=None,
                     content_type=None, body_format="json"):
    # Local recording metadata is rendered as text, never as response JSON.
    _capture({"kind": "http_response", "operation": operation, "payload": payload,
              "endpoint": endpoint, "http_status": http_status,
              "content_type": content_type, "body_format": body_format}, token)
