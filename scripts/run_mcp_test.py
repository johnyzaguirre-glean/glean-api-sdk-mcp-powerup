#!/usr/bin/env python3
"""Bounded MCP discovery plus at most one read-only Glean search tool call."""

from __future__ import annotations

import argparse
import hashlib
import importlib.metadata
import json
import logging
import os
from pathlib import Path
import re
import sys
import time
from urllib import error, parse, request

from common import (MAX_RESPONSE_BYTES, NoRedirect, SafeFailure, TIMEOUT, ROOT, capture_input, capture_response,
                    deadline, identifier, safe_scalar, safe_url, save_report, utc_now,
                    load_config, read_token, validate_query, serialized_output,
                    url_fingerprint, title_fingerprint)

CLASSIC_VERSIONS = {"2025-03-26", "2025-06-18", "2025-11-25"}


def validate_url(value):
    try:
        if not isinstance(value, str) or re.search(r"[\s\x00-\x1f\x7f]", value):
            raise ValueError
        u = parse.urlsplit(value)
        if (u.scheme != "https" or not u.hostname or u.username or u.password
                or u.query or u.fragment or not u.path.startswith("/mcp/")
                or len(u.path) <= len("/mcp/") or u.port not in (None, 443)):
            raise ValueError
    except ValueError:
        raise SafeFailure("GLEAN_MCP_URL must be the exact HTTPS server URL with /mcp/<path>") from None
    if "YOUR-" in value.upper():
        raise SafeFailure("replace GLEAN_MCP_URL placeholder in .env")
    return value


def read_rpc(response, request_id):
    """Read JSON or SSE only until this request's matching response arrives."""
    content_type = response.headers.get_content_type()
    if content_type == "application/json":
        raw = response.read(MAX_RESPONSE_BYTES + 1)
        if len(raw) > MAX_RESPONSE_BYTES:
            raise SafeFailure("response exceeded the body limit")
        data = json.loads(raw)
        if not isinstance(data, dict) or data.get("id") != request_id:
            raise SafeFailure("JSON response did not match the request ID")
        return data
    if content_type != "text/event-stream":
        raise SafeFailure("unexpected MCP response content type")
    total = 0
    pieces = []
    while True:
        line = response.readline(MAX_RESPONSE_BYTES + 1)
        total += len(line)
        if total > MAX_RESPONSE_BYTES:
            raise SafeFailure("response exceeded the body limit")
        if not line and not pieces:
            raise SafeFailure("SSE ended before a matching response")
        if line in (b"\n", b"\r\n", b""):
            if pieces:
                data = json.loads("\n".join(pieces))
                pieces = []
                if isinstance(data, dict) and data.get("id") == request_id:
                    return data
            if not line:
                raise SafeFailure("SSE ended before a matching response")
        elif line.startswith(b"data:"):
            pieces.append(line[5:].lstrip(b" ").decode("utf-8").rstrip("\r\n"))


def capture_bounded_body(response, operation, *, token, endpoint):
    """Capture the actual response body for non-RPC replies, within the read limit."""
    raw = response.read(MAX_RESPONSE_BYTES + 1)
    if len(raw) > MAX_RESPONSE_BYTES:
        raise SafeFailure("response exceeded the body limit")
    if not raw:
        payload, body_format = None, "empty"
    else:
        try:
            payload = json.loads(raw)
            body_format = "json"
        except (ValueError, UnicodeDecodeError):
            payload = raw.decode(response.headers.get_content_charset() or "utf-8", errors="replace")
            body_format = "text"
    capture_response(operation, payload, token=token, endpoint=endpoint,
                     http_status=response.status,
                     content_type=response.headers.get_content_type(), body_format=body_format)


class Probe:
    def __init__(self, url, token, out, report):
        self.url, self.token, self.out, self.report = url, token, out, report
        self.version = None
        self.session_id = None
        self.opener = request.build_opener(NoRedirect)

    def send(self, label, payload=None, method="POST"):
        start = time.monotonic()
        item = {"id": label, "started_at": utc_now(), "http_method": method}
        headers = {"Authorization": "Bearer " + self.token,
                   "Accept": "application/json, text/event-stream",
                   "Content-Type": "application/json"}
        if self.version:
            headers["MCP-Protocol-Version"] = self.version
        if self.session_id:
            headers["Mcp-Session-Id"] = self.session_id
        body = json.dumps(payload).encode() if payload is not None else None
        operation = method + " " + parse.urlsplit(self.url).path
        result = None
        try:
            with deadline():
                req = request.Request(self.url, data=body, method=method, headers=headers)
                capture_input("http_request", operation, payload,
                              token=self.token, endpoint=self.url)
                try:
                    response = self.opener.open(req, timeout=TIMEOUT)
                except error.HTTPError as exc:
                    response = exc
                with response:
                    item["http_status"] = response.status
                    item["content_type"] = response.headers.get_content_type()
                    # Only boolean session evidence is persisted, never the identifier.
                    supplied = response.headers.get("Mcp-Session-Id")
                    if label == "M1_initialize" and supplied:
                        if not re.fullmatch(r"[\x21-\x7e]{1,2048}", supplied):
                            raise SafeFailure("invalid session header")
                        self.session_id = supplied
                        item["session_assigned"] = True
                    rid = response.headers.get("x-request-id")
                    if identifier(rid):
                        item["request_id"] = rid
                    is_notification = payload is not None and "id" not in payload
                    if method == "DELETE":
                        capture_bounded_body(response, operation, token=self.token, endpoint=self.url)
                        item["cleanup_accepted_or_unsupported"] = response.status in (200, 202, 204, 405)
                    elif is_notification:
                        capture_bounded_body(response, operation, token=self.token, endpoint=self.url)
                        item["accepted"] = response.status in (200, 202, 204)
                    elif response.status == 200:
                        data = read_rpc(response, payload["id"])
                        capture_response(operation, data, token=self.token, endpoint=self.url,
                                         http_status=response.status, content_type=item["content_type"],
                                         body_format="jsonrpc_message" if item["content_type"] == "text/event-stream" else "json")
                        item["jsonrpc_response"] = data.get("jsonrpc") == "2.0"
                        if not item["jsonrpc_response"]:
                            raise SafeFailure("invalid JSON-RPC version")
                        if isinstance(data.get("error"), dict):
                            code = data["error"].get("code")
                            item["rpc_error_code"] = code if isinstance(code, int) else None
                        elif isinstance(data.get("result"), dict):
                            result = data["result"]
                            item["rpc_result"] = True
                        else:
                            item["error"] = "missing_result_or_error"
                    else:
                        capture_bounded_body(response, operation, token=self.token, endpoint=self.url)
                        item["error"] = "http_request_failed_body_omitted"
        except TimeoutError:
            item["error"] = "timeout_30_seconds"
        except Exception as exc:
            item["error"] = "protocol_transport_or_local_error"
            item["exception_type"] = type(exc).__name__
        item["elapsed_seconds"] = round(time.monotonic() - start, 3)
        self.report["tests"].append(item)
        save_report(self.out, self.report, self.token)
        return item, result


def matching_arguments(schema, query, argument_path, query_pointer="/query"):
    """No guessed alternate fields. Validate before invoking the discovered tool."""
    from jsonschema import validators
    from referencing import Registry
    from referencing.exceptions import NoSuchResource

    def deny_external(uri):
        raise NoSuchResource(ref=uri)

    if argument_path:
        with open(argument_path, "r") as handle:
            raw = handle.read(65537)
        if len(raw) > 65536:
            raise SafeFailure("arguments file exceeds limit")
        args = json.loads(raw)
    else:
        query_property = schema.get("properties", {}).get("query", {})
        property_type = query_property.get("type")
        if property_type != "string" and not (isinstance(property_type, list) and "string" in property_type):
            raise SafeFailure("discovered schema has no string query property")
        args = {"query": query}
    if not isinstance(args, dict):
        raise SafeFailure("search arguments must be an object")
    # The .env query is authoritative, including when extra arguments come from JSON.
    # Only the reviewed final object key may be created. Never invent parent paths.
    if not isinstance(query_pointer, str) or not query_pointer.startswith("/"):
        raise SafeFailure("query pointer must be a nonempty JSON Pointer")
    encoded_fields = query_pointer[1:].split("/")
    if any(re.search(r"~(?![01])", field) for field in encoded_fields):
        raise SafeFailure("query pointer contains an invalid escape")
    fields = [field.replace("~1", "/").replace("~0", "~") for field in encoded_fields]

    def existing_child(parent, field):
        if isinstance(parent, dict) and field in parent:
            return parent[field]
        if isinstance(parent, list) and re.fullmatch(r"0|[1-9][0-9]*", field):
            index = int(field)
            if index < len(parent):
                return parent[index]
        raise SafeFailure("query pointer parent or list position does not exist")

    parent = args
    for field in fields[:-1]:
        parent = existing_child(parent, field)
    final = fields[-1]
    if isinstance(parent, dict):
        parent[final] = query
    elif isinstance(parent, list):
        existing_child(parent, final)
        parent[int(final)] = query
    else:
        raise SafeFailure("query pointer parent must be an object or list")
    cls = validators.validator_for(schema)
    cls.check_schema(schema)
    validator = cls(schema, registry=Registry(retrieve=deny_external))
    if not validator.is_valid(args):
        raise SafeFailure("arguments do not match discovered schema")
    return args


def output_metadata(result, expected_title, expected_url=None):
    """Count content and match a fixture result row. Persist no text blocks."""
    blocks = result.get("content", [])
    allowed = {"text", "image", "audio", "resource", "resource_link"}
    valid = (isinstance(result.get("content"), list)
             and all(isinstance(b, dict) and b.get("type") in allowed
                     and (b.get("type") != "text" or isinstance(b.get("text"), str)) for b in blocks)
             and ("isError" not in result or isinstance(result["isError"], bool))
             and ("structuredContent" not in result or isinstance(result["structuredContent"], dict)))
    if not valid:
        return {"tool_result_valid": False}
    text_parts = [b["text"] for b in blocks if isinstance(b, dict) and isinstance(b.get("text"), str)]
    structured = result.get("structuredContent")
    data = {"tool_result_valid": True, "tool_is_error": result.get("isError") is True,
            "content_block_count": len(blocks) if isinstance(blocks, list) else None,
            "content_types": [identifier(b.get("type")) for b in blocks if isinstance(b, dict)],
            "text_character_count": sum(len(t) for t in text_parts),
            "structured_content_present": structured is not None}
    # Extract only named title/URL metadata from JSON-shaped content, never prose/snippets.
    candidates = [structured]
    for text_value in text_parts:
        try:
            candidates.append(json.loads(text_value))
        except (ValueError, TypeError):
            pass
    rows = []
    fixture_match = False
    def record_row(title, url):
        nonlocal fixture_match
        display_url = safe_url(url)
        if not isinstance(title, str) or not display_url:
            return
        fingerprint = url_fingerprint(url)
        row = {"title": safe_scalar(title, 240), "title_sha256": title_fingerprint(title),
               "url": display_url, "url_sha256": fingerprint}
        if len(rows) < 3 and row not in rows:
            rows.append(row)
        if expected_title and title_fingerprint(title) == title_fingerprint(expected_title):
            fixture_match = fixture_match or expected_url is None or fingerprint == url_fingerprint(expected_url)
    def walk(value, depth=0):
        if depth > 8:
            return
        if isinstance(value, dict):
            title, url = value.get("title"), value.get("url")
            record_row(title, url)
            for key, child in value.items():
                if key not in ("text", "snippet", "content", "body"):
                    walk(child, depth + 1)
        elif isinstance(value, list):
            for child in value[:100]:
                walk(child, depth + 1)
    for candidate in candidates:
        walk(candidate)
    # Glean Search returns numbered result sections with a separate Link field.
    # Embedded links inside document excerpts are not search-result metadata.
    markdown_result_count = 0
    for text_value in text_parts:
        headings = list(re.finditer(r"^##[ \t]+\d+\.[ \t]+([^\r\n]+)[ \t]*$", text_value, re.MULTILINE))
        for index, heading in enumerate(headings):
            end = headings[index + 1].start() if index + 1 < len(headings) else len(text_value)
            section = text_value[heading.end():end]
            link = re.search(r"^\*\*Link:\*\*[ \t]+(https?://[^\s]+)[ \t]*$", section, re.MULTILINE)
            if link:
                record_row(heading.group(1).strip(), link.group(1))
                markdown_result_count += 1
    data["fixture_result_metadata"] = rows
    data["numbered_markdown_results_parsed"] = markdown_result_count
    if expected_title:
        data["expected_fixture_result_matched"] = fixture_match
    return data


def main():
    config = load_config()
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--mcp-url", default=config.get("GLEAN_MCP_URL"))
    parser.add_argument("--token-file", default=config.get("GLEAN_TOKEN_FILE"))
    parser.add_argument("--query", default=config.get("GLEAN_QUERY"))
    parser.add_argument("--expected-title", default=config.get("GLEAN_EXPECTED_TITLE"), help="Optional expected document title")
    parser.add_argument("--expected-url", default=config.get("GLEAN_EXPECTED_URL"), help="Optional expected canonical document URL")
    parser.add_argument("--search-args-file", type=Path, help="Optional JSON after reviewing discovered schema")
    parser.add_argument("--query-pointer", default="/query", help="Reviewed JSON Pointer for the fixture query in an arguments file")
    parser.add_argument("--discover-only", action="store_true")
    parser.add_argument("--out", type=Path, default=ROOT / "outputs" / "mcp.json")
    args = parser.parse_args()
    logging.disable(logging.CRITICAL)
    url = validate_url(args.mcp_url)
    if args.expected_url and (not args.expected_title or not safe_url(args.expected_url)):
        raise SafeFailure("expected URL requires an expected title and valid HTTPS/HTTP URL")
    args.query = validate_query(args.query)
    token = read_token(args.token_file)
    report = {"schema_version": 1, "started_at": utc_now(), "mcp_url": url,
              "client": "bounded custom Python Streamable HTTP probe",
              "auth_method": "user_scoped_api_token", "automatic_retries": False,
              "commercial_host_tested": False, "timeout_seconds_per_request": TIMEOUT,
              "query_sha256": hashlib.sha256(args.query.encode()).hexdigest(),
              "query_character_count": len(args.query),
              "jsonschema_version": importlib.metadata.version("jsonschema"), "tests": []}
    probe = Probe(url, token, args.out, report)
    try:
        _, initialized = probe.send("M1_initialize", {"jsonrpc": "2.0", "id": 1, "method": "initialize",
            "params": {"protocolVersion": "2025-06-18", "capabilities": {},
                       "clientInfo": {"name": "glean-powerup-example", "version": "0.1"}}})
        if not initialized:
            report["stop_reason"] = "initialization_failed"
            return 1
        version = initialized.get("protocolVersion")
        report["negotiated_protocol_version"] = identifier(version)
        if version not in CLASSIC_VERSIONS:
            report["stop_reason"] = "unsupported_protocol_revision"
            return 1
        probe.version = version
        info = initialized.get("serverInfo", {})
        report["server_info"] = {k: safe_scalar(info.get(k), 120) for k in ("name", "version")}
        capabilities = initialized.get("capabilities", {})
        report["server_capabilities"] = [identifier(k) for k in capabilities]
        if "tools" not in capabilities:
            report["stop_reason"] = "server_did_not_advertise_tools"
            return 1
        item, _ = probe.send("M1b_initialized", {"jsonrpc": "2.0", "method": "notifications/initialized"})
        if not item.get("accepted"):
            report["stop_reason"] = "initialized_notification_failed"
            return 1
        _, listed = probe.send("M2_tools_list", {"jsonrpc": "2.0", "id": 2, "method": "tools/list", "params": {}})
        if not listed or not isinstance(listed.get("tools"), list):
            report["stop_reason"] = "tool_discovery_failed"
            return 1
        tool_list = listed["tools"]
        report["tool_names"] = [identifier(t.get("name")) for t in tool_list if isinstance(t, dict)]
        report["tool_count"] = len(tool_list)
        report["more_tools_pages_available"] = bool(listed.get("nextCursor"))
        search_tools = [t for t in tool_list if isinstance(t, dict) and t.get("name") == "search"]
        if len(search_tools) != 1:
            report["stop_reason"] = "exact_search_tool_unavailable_on_first_page"
            return 1
        tool = search_tools[0]
        schema = tool.get("inputSchema")
        if not isinstance(schema, dict) or len(json.dumps(schema)) > 65536:
            report["stop_reason"] = "invalid_or_oversized_search_schema"
            return 1
        report["search_input_schema"] = schema
        annotations = tool.get("annotations", {})
        report["search_annotations"] = {k: annotations.get(k) for k in
            ("readOnlyHint", "destructiveHint", "idempotentHint", "openWorldHint") if k in annotations}
        if annotations.get("readOnlyHint") is False or annotations.get("destructiveHint") is True:
            report["stop_reason"] = "search_annotations_conflict_with_read_only_test"
            return 1
        if args.discover_only:
            report["stop_reason"] = "requested_discovery_only"
            return 0
        try:
            arguments = matching_arguments(schema, args.query, args.search_args_file, args.query_pointer)
        except Exception as exc:
            report["stop_reason"] = "review_saved_schema_and_supply_matching_search_args_file"
            report["argument_validation_exception"] = type(exc).__name__
            return 1
        report["search_argument_keys"] = list(arguments)
        item, result = probe.send("M3_search", {"jsonrpc": "2.0", "id": 3, "method": "tools/call",
            "params": {"name": "search", "arguments": arguments}})
        if result is None:
            report["stop_reason"] = "search_rpc_failed"
            return 1
        item.update(output_metadata(result, args.expected_title, args.expected_url))
        report["search_protocol_success"] = item.get("tool_result_valid", False) and not item.get("tool_is_error", True)
        report["search_test_expectations_met"] = report["search_protocol_success"] and (
            not args.expected_title or item.get("expected_fixture_result_matched", False))
        return 0 if report["search_test_expectations_met"] else 1
    finally:
        if probe.session_id:
            probe.send("M4_close_session", method="DELETE")
        report["completed_at"] = utc_now()
        save_report(args.out, report, token)
        print(serialized_output(report, token), end="")


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except SafeFailure as exc:
        print("MCP setup failed: " + str(exc), file=sys.stderr)
        raise SystemExit(2)
    except KeyboardInterrupt:
        print("MCP probe interrupted; completed metadata is retained.", file=sys.stderr)
        raise SystemExit(130)
    except Exception as exc:
        print("MCP probe failed: " + type(exc).__name__, file=sys.stderr)
        raise SystemExit(2)
