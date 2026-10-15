"""Opt-in, local request evidence for the presenter. Never capture headers.

The presenter supplies a private temporary JSONL file. Ordinary exercise runs
do not record input. Capture happens at the request boundary so replays use the
original inputs, even if .env is changed later.
"""
from __future__ import annotations

import json
import os
from pathlib import Path
from urllib.parse import quote

MAX_INPUT_BYTES = 256_000
MAX_EVENT_BYTES = 65_536


def capture_input(kind, operation, payload, *, token="", endpoint=None):
    destination = os.environ.get("GLEAN_PRESENTER_INPUT_FILE")
    if not destination:
        return
    if __package__:
        from scripts.present import scrub
    else:
        from present import scrub

    def redact(value):
        if isinstance(value, dict):
            return {redact(str(key)): redact(item) for key, item in value.items()}
        if isinstance(value, list):
            return [redact(item) for item in value]
        if isinstance(value, str) and token:
            for secret in {token, quote(token, safe=""), quote(token, safe="").lower()}:
                value = value.replace(secret, "[REDACTED]")
        return value

    event = {"kind": kind, "operation": operation, "payload": payload}
    if endpoint is not None:
        event["endpoint"] = endpoint
    event = scrub(redact(event))
    encoded = (json.dumps(event, ensure_ascii=True) + "\n").encode()
    if len(encoded) > MAX_EVENT_BYTES:
        event["payload"] = {"omitted": "Request exceeds the presenter input size limit."}
        encoded = (json.dumps(event) + "\n").encode()
    # Only append to the existing file created by the parent. Never follow links
    # or create an arbitrary output file from an inherited environment value.
    descriptor = None
    try:
        descriptor = os.open(Path(destination), os.O_WRONLY | os.O_APPEND | os.O_NOFOLLOW)
        stat = os.fstat(descriptor)
        if stat.st_uid != os.getuid() or stat.st_mode & 0o077 or stat.st_size + len(encoded) > MAX_INPUT_BYTES:
            return
        os.write(descriptor, encoded)
    except OSError:
        pass  # Missing capture must not change the underlying exercise result.
    finally:
        if descriptor is not None:
            os.close(descriptor)
