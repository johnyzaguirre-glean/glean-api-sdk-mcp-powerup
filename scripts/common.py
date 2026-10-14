#!/usr/bin/env python3
"""Shared bounded requests, inert configuration, and sanitized output helpers."""

from __future__ import annotations

import argparse
import contextlib
import hashlib
import json
import logging
import os
from pathlib import Path
import re
import signal
import stat
import tempfile
import sys
import time
from datetime import datetime, timezone
from enum import Enum
from urllib import error, parse, request

ROOT = Path(__file__).resolve().parents[1]
TIMEOUT = 30
MAX_RESPONSE_BYTES = 2_000_000
CHAT_TEXT = "connection verified"
CHAT_INPUT = "Reply with exactly: " + CHAT_TEXT


def utc_now():
    return datetime.now(timezone.utc).isoformat()


class SafeFailure(Exception):
    pass


class ResponseBodyLimitExceeded(SafeFailure):
    pass


class NoRedirect(request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


class QuietLogger:
    def debug(self, *args, **kwargs):
        pass


@contextlib.contextmanager
def deadline():
    """Enforce a total per-probe deadline, including body download/parsing."""
    def expired(_signum, _frame):
        raise TimeoutError("probe deadline")
    previous = signal.signal(signal.SIGALRM, expired)
    signal.setitimer(signal.ITIMER_REAL, TIMEOUT)
    try:
        yield
    finally:
        signal.setitimer(signal.ITIMER_REAL, 0)
        signal.signal(signal.SIGALRM, previous)


def safe_scalar(value, limit=180):
    if isinstance(value, Enum):
        value = value.value
    if not isinstance(value, (str, int, float, bool)):
        return None
    return re.sub(r"[\x00-\x1f\x7f-\x9f]", " ", str(value))[:limit]


def identifier(value):
    text = safe_scalar(value)
    return text if text and re.fullmatch(r"[A-Za-z0-9_.:/-]{1,180}", text) else None


def problem_metadata(data):
    if not isinstance(data, dict):
        return {}
    result = {key: value for key in ("code", "request_id")
              if (value := identifier(data.get(key))) is not None}
    errors = data.get("errors")
    if isinstance(errors, list):
        result["field_errors"] = [{key: value for key in ("pointer", "code")
                                   if (value := identifier(row.get(key))) is not None}
                                  for row in errors[:10] if isinstance(row, dict)]
    return result


def safe_url(value):
    if not isinstance(value, str) or re.search(r"[\s\x00-\x1f\x7f]", value):
        return None
    try:
        u = parse.urlsplit(value)
        if u.scheme not in ("http", "https") or not u.netloc or u.username or u.password:
            return None
        # Query strings and fragments can contain signed access material.
        return parse.urlunsplit((u.scheme, u.netloc, u.path, "", ""))[:600]
    except ValueError:
        return None


def url_fingerprint(value):
    """Compare complete links without persisting query strings or fragments."""
    if safe_url(value) is None:
        return None
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def title_fingerprint(value):
    """Keep exact title comparisons independent of display truncation."""
    return hashlib.sha256(value.encode("utf-8")).hexdigest() if isinstance(value, str) else None


def same_search_results(left, right):
    """Require nonempty results with identical exact-title and complete-URL hashes."""
    def fingerprints(result):
        return [(row.get("title_sha256"), row.get("url_sha256"))
                for row in result.get("results", []) if isinstance(row, dict)]
    a, b = fingerprints(left), fingerprints(right)
    valid = all(isinstance(value, str) and re.fullmatch(r"[a-f0-9]{64}", value)
                for pair in a for value in pair)
    return bool(a) and valid and a == b


def summarize(kind, data):
    if not isinstance(data, dict):
        return {"json_object": False}
    result = {"json_object": True, **problem_metadata(data)}
    if kind == "search":
        rows = data.get("results")
        if isinstance(rows, list):
            result.update({
                "expected_payload_present": isinstance(data.get("has_more"), bool)
                    and isinstance(data.get("request_id"), str)
                    and isinstance(data.get("warnings"), list) and "next_cursor" in data,
                "result_count": len(rows),
                "results": [{"title": safe_scalar(row.get("title"), 240),
                             "title_sha256": title_fingerprint(row.get("title")),
                             "url": safe_url(row.get("url")),
                             "url_sha256": url_fingerprint(row.get("url")),
                             "datasource": safe_scalar(row.get("datasource"), 100)}
                            for row in rows[:3] if isinstance(row, dict)],
                "has_more": data.get("has_more") if isinstance(data.get("has_more"), bool) else None,
                "next_cursor_present": bool(data.get("next_cursor")),
                "warning_codes": [identifier(w.get("code")) for w in data.get("warnings", [])
                                  if isinstance(w, dict)],
            })
    elif kind == "filters":
        sources = data.get("datasources")
        if isinstance(sources, list):
            result["expected_payload_present"] = isinstance(data.get("request_id"), str)
            result["datasource_count"] = len(sources)
            result["datasource_ids"] = [safe_scalar(v.get("datasource"), 100)
                                        for v in sources[:20] if isinstance(v, dict)]
    elif kind == "chat":
        result.update({"response_status": identifier(data.get("status")),
                       "expected_payload_present": isinstance(data.get("output"), list)
                           and isinstance(data.get("request_id"), str),
                       "store": data.get("store") if isinstance(data.get("store"), bool) else None,
                       "conversation_id_present": bool(data.get("conversation_id"))})
        if isinstance(data.get("error"), dict):
            result["chat_error_code"] = identifier(data["error"].get("code"))
        text = "".join(part.get("text", "") for message in data.get("output", [])
                       if isinstance(message, dict) for part in message.get("content", [])
                       if isinstance(part, dict) and isinstance(part.get("text"), str))
        result["answer_character_count"] = len(text)
        # Whitelist the benign answer. Unexpected model content is never persisted.
        normalized = text.strip().strip('"\'` .\n').lower()
        result["benign_answer_matched"] = normalized == CHAT_TEXT
        result["answer"] = CHAT_TEXT if normalized == CHAT_TEXT else "[unexpected answer omitted]"
    return result


def rest_probe(base_url, token, method, path, payload, kind):
    body = json.dumps(payload).encode() if payload is not None else None
    req = request.Request(base_url + path, data=body, method=method,
                          headers={"Authorization": "Bearer " + token,
                                   "Accept": "application/json",
                                   "Content-Type": "application/json"})
    opener = request.build_opener(NoRedirect)
    try:
        response = opener.open(req, timeout=TIMEOUT)
    except error.HTTPError as exc:
        response = exc
    with response:
        status = response.status
        raw = response.read(MAX_RESPONSE_BYTES + 1)
        if len(raw) > MAX_RESPONSE_BYTES:
            return {"http_status": status, "response_omitted": "body_limit"}
        try:
            data = json.loads(raw)
        except (UnicodeDecodeError, json.JSONDecodeError):
            return {"http_status": status, "response_json": False}
        return {"http_status": status, **summarize(kind, data)}


def sdk_probe(base_url, token, query):
    import httpx
    from glean.api_client import Glean
    status = []
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
    def record_status(response):
        status.append(response.status_code)
        if response.headers.get("content-encoding", "identity").lower() not in ("", "identity"):
            response.close()
            raise SafeFailure("unexpected_compressed_response")
        response.stream = LimitedStream(response.stream)
    with httpx.Client(timeout=TIMEOUT, follow_redirects=False,
                      headers={"Accept-Encoding": "identity"},
                      event_hooks={"response": [record_status]}) as client:
        with Glean(api_token=token, server_url=base_url, client=client,
                   retry_config=None, timeout_ms=TIMEOUT * 1000,
                   debug_logger=QuietLogger()) as glean:
            try:
                value = glean.search.query(query=query, page_size=3,
                                           retries=None, timeout_ms=TIMEOUT * 1000)
                data = value.model_dump(mode="json", by_alias=True)
                return {"http_status": status[-1] if status else None,
                        "request_count": len(status), **summarize("search", data)}
            except TimeoutError:
                raise
            except Exception as exc:
                # Do not serialize exception strings or bodies, which can carry payloads.
                fields = {"http_status": status[-1] if status else None,
                          "request_count": len(status),
                          "exception_type": type(exc).__name__}
                if isinstance(exc, ResponseBodyLimitExceeded):
                    fields["response_omitted"] = "body_limit"
                # This SDK version exposes structured Platform errors on .data.
                structured = getattr(exc, "data", None)
                for key in ("code", "request_id"):
                    if value := identifier(getattr(structured, key, getattr(exc, key, None))):
                        fields[key] = value
                rows = getattr(structured, "errors", None)
                if isinstance(rows, list):
                    fields["field_errors"] = [{key: value for key in ("pointer", "code")
                        if (value := identifier(getattr(row, key, None))) is not None}
                        for row in rows[:10]]
                return fields


def execute(test_id, expected, operation):
    started = time.monotonic()
    entry = {"id": test_id, "started_at": utc_now(), "expected_http_status": expected}
    try:
        with deadline():
            entry.update(operation())
    except TimeoutError:
        entry["error"] = "timeout_30_seconds"
    except Exception as exc:
        entry["error"] = "transport_or_local_error"
        entry["exception_type"] = type(exc).__name__
    entry["elapsed_seconds"] = round(time.monotonic() - started, 3)
    entry["status_expectation_met"] = entry.get("http_status") == expected
    clean = not any(key in entry for key in ("error", "exception_type", "response_omitted"))
    if expected == 200:
        clean = clean and entry.get("expected_payload_present", False)
    else:
        clean = clean and entry.get("json_object", False) and bool(entry.get("code"))
    if test_id == "P3_ephemeral_chat":
        clean = (clean and entry.get("response_status") == "COMPLETED"
                 and entry.get("store") is False and not entry.get("conversation_id_present")
                 and entry.get("benign_answer_matched") is True)
    entry["test_expectation_met"] = entry["status_expectation_met"] and bool(clean)
    return entry


ENV_KEYS = {
    "GLEAN_BASE_URL", "GLEAN_TOKEN_FILE", "GLEAN_QUERY", "GLEAN_EXPECTED_TITLE",
    "GLEAN_EXPECTED_URL", "GLEAN_MCP_URL",
}


def load_config(path=None, environ=None):
    """Parse a small key=value subset, never shell syntax or interpolation."""
    path = Path(path) if path is not None else ROOT / ".env"
    config = {}
    if path.exists():
        if path.stat().st_size > 65536:
            raise SafeFailure(".env is too large")
        for number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
            line = line.strip()
            if not line or line.startswith("#"):
                continue
            key, separator, value = line.partition("=")
            key, value = key.strip(), value.strip()
            if not separator or key not in ENV_KEYS:
                raise SafeFailure(f"unsupported .env entry on line {number}; use example.env keys")
            if value.startswith(("'", '"')):
                if len(value) < 2 or value[-1] != value[0]:
                    raise SafeFailure(f"unclosed .env quote on line {number}")
                value = value[1:-1]
            if any(ord(char) < 32 or ord(char) == 127 for char in value):
                raise SafeFailure(f"control character in .env value on line {number}")
            config[key] = value
    env = os.environ if environ is None else environ
    config.update({key: env[key] for key in ENV_KEYS if key in env})
    return config


def validate_base(value):
    try:
        if not isinstance(value, str) or re.search(r"[\s\x00-\x1f\x7f]", value):
            raise ValueError
        u = parse.urlsplit(value)
        if (u.scheme != "https" or not u.hostname or u.username or u.password
                or u.query or u.fragment or u.path not in ("", "/")
                or u.port not in (None, 443)):
            raise ValueError
    except ValueError:
        raise SafeFailure("GLEAN_BASE_URL must be a complete HTTPS origin without a path") from None
    if "YOUR-" in value.upper():
        raise SafeFailure("replace GLEAN_BASE_URL placeholder in .env")
    return value.rstrip("/")


def validate_query(value):
    if (not isinstance(value, str) or not value.strip() or len(value) > 1000
            or any(ord(c) < 32 or ord(c) == 127 for c in value)):
        raise SafeFailure("GLEAN_QUERY must contain 1 to 1000 characters without control characters")
    if "YOUR KNOWN DOCUMENT TITLE" in value:
        raise SafeFailure("replace GLEAN_QUERY placeholder with a document you can open in Glean")
    return value


def token_path(value):
    if not value:
        raise SafeFailure("set GLEAN_TOKEN_FILE in .env")
    path = Path(value).expanduser()
    return path if path.is_absolute() else ROOT / path


def validate_token(token):
    if not 16 <= len(token) <= 16384 or not re.fullmatch(r"[A-Za-z0-9._~+/=-]+", token):
        raise SafeFailure("credential file format is invalid")
    return token


def read_token(value):
    """Open without following a final symlink and enforce owner-only POSIX access."""
    path = token_path(value)
    if os.name != "posix" or not hasattr(os, "O_NOFOLLOW"):
        raise SafeFailure("this token file check requires macOS or Linux")
    try:
        fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW)
        with os.fdopen(fd, "r", encoding="utf-8") as handle:
            metadata = os.fstat(handle.fileno())
            if not stat.S_ISREG(metadata.st_mode) or metadata.st_uid != os.getuid():
                raise SafeFailure("credential must be a regular file owned by your account")
            if stat.S_IMODE(metadata.st_mode) & 0o077:
                raise SafeFailure("credential file must be owner-only; run chmod 600 on it")
            if metadata.st_size > 16385:
                raise SafeFailure("credential file is too large")
            token = handle.read(16385).strip()
    except (OSError, UnicodeError):
        raise SafeFailure("credential file could not be read; run python scripts/store_token.py") from None
    return validate_token(token)


def serialized_output(report, token):
    serialized = json.dumps(report, indent=2, ensure_ascii=True)
    if token:
        serialized = serialized.replace(token, "[REDACTED]")
        serialized = serialized.replace(json.dumps(token)[1:-1], "[REDACTED]")
    return serialized + "\n"


def save_report(path, report, token):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, temporary_name = tempfile.mkstemp(prefix=".report-", dir=path.parent)
    temporary = Path(temporary_name)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            handle.write(serialized_output(report, token))
        temporary.replace(path)
    finally:
        temporary.unlink(missing_ok=True)


def expected_result(data, title=None, url=None):
    """Title and complete URL fingerprint must match the same result row."""
    if url and (not title or not safe_url(url)):
        raise SafeFailure("GLEAN_EXPECTED_URL requires a title and a valid HTTP or HTTPS URL")
    if not title:
        return {}
    rows = data.get("results", [])
    matched = any(row.get("title_sha256") == title_fingerprint(title) and (
        not url or row.get("url_sha256") == url_fingerprint(url))
        for row in rows if isinstance(row, dict))
    return {"expected_document_matched": matched}


def search_parser(description):
    config = load_config()
    parser = argparse.ArgumentParser(description=description)
    parser.add_argument("--base-url", default=config.get("GLEAN_BASE_URL"))
    parser.add_argument("--token-file", default=config.get("GLEAN_TOKEN_FILE"))
    parser.add_argument("--query", default=config.get("GLEAN_QUERY"))
    parser.add_argument("--expected-title", default=config.get("GLEAN_EXPECTED_TITLE"))
    parser.add_argument("--expected-url", default=config.get("GLEAN_EXPECTED_URL"))
    return parser


def prepare_search(args):
    logging.disable(logging.CRITICAL)
    base_url = validate_base(args.base_url)
    query = validate_query(args.query)
    expected_result({}, args.expected_title, args.expected_url)
    token = read_token(args.token_file)
    return base_url, token, query


def guarded_main(main):
    try:
        return main()
    except SafeFailure as exc:
        print("Setup failed: " + str(exc), file=sys.stderr)
        return 2
    except KeyboardInterrupt:
        print("Interrupted.", file=sys.stderr)
        return 130
    except Exception as exc:
        # Exception messages can contain response bodies or credentials.
        print("Request failed: " + type(exc).__name__, file=sys.stderr)
        return 2
