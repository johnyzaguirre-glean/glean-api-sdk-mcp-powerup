#!/usr/bin/env python3
"""Run one real lab exercise with audience-friendly, credential-free output.

The original entrypoints keep their machine-readable JSON interface. This wrapper
uses their existing configuration and safeguards, then adds context and a compact
view of the returned evidence. It never reads a credential file itself.
"""

from __future__ import annotations

import argparse
from dataclasses import dataclass
from datetime import datetime, timezone
import json
import math
import os
from pathlib import Path
import re
import shlex
import subprocess
import sys
import tempfile
import textwrap
import time
import unicodedata
from urllib.parse import urlsplit, urlunsplit

if __package__:
    from scripts.presenter_capture import MAX_INPUT_BYTES, redact_payload
else:
    from presenter_capture import MAX_INPUT_BYTES, redact_payload

ROOT = Path(__file__).resolve().parents[1]
MAX_CAPTURE_BYTES = 6_000_000
MAX_DISPLAY_LINES = 75

# Teaching order for a live session or a replay of recorded, real executions.
MAIN_EXERCISES = (
    "search-rest", "search-python", "search-compare", "chat-rest", "chat-python",
    "mcp-discover", "mcp-search", "indexing-preview", "indexing-apply",
    "indexing-status", "indexing-permissions",
)


@dataclass(frozen=True)
class Exercise:
    title: str
    purpose: str
    command: tuple[str, ...]
    watch: str
    boundary: str
    indexing: bool = False
    timeout: int = 180
    optional: bool = False


EXERCISES = {
    "search-rest": Exercise(
        "Search with a direct HTTP request",
        "A customer app needs document links. Send the known-document query directly to Glean Search.",
        ("examples/rest_search.py",),
        "HTTP 200 means the request worked. The expected title and link tell us it found the right document.",
        "This is a search as the configured user. It does not prove another user's access."),
    "search-python": Exercise(
        "The same Search, through the Python client",
        "Use the official API client to express the same Search request in Python.",
        ("examples/python_search.py",),
        "Find the same expected document. The client changes how we write the request, not whose access applies.",
        "Use the pinned Platform API client environment, separate from the Indexing SDK environment."),
    "search-compare": Exercise(
        "Compare REST and Python results",
        "Run both Search paths and compare the exact returned titles and source links.",
        ("scripts/run_diagnostics.py",),
        "Compare the titles and source links in the two real Search responses. The plain-text conclusion reports whether they matched.",
        "Ranking can change between calls. A mismatch is evidence to investigate, not permission to hide a result."),
    "chat-rest": Exercise(
        "Turn a question into an answer with Chat",
        "A customer portal needs an answer, not just links. Send GLEAN_CHAT_QUERY to the Chat API.",
        ("examples/rest_chat.py",),
        "Read the answer and inspect its citations. A completed response is not a fact-checking certificate.",
        "Uses CHAT access and model usage. store:false avoids saving the conversation, not service telemetry.",
        timeout=150),
    "chat-python": Exercise(
        "Ask Chat through the Python client",
        "Ask the same configured question using the official Python API client.",
        ("examples/python_chat.py",),
        "Check COMPLETED, the answer and its citations. Generated wording need not match the REST response.",
        "Uses the same user's access and model usage. This exercise does not run an agent action.", timeout=150),
    "mcp-discover": Exercise(
        "Ask the MCP server what tools it offers",
        "Before a client calls a tool, discover the server's tool list and Search input schema.",
        ("scripts/run_mcp_test.py", "--discover-only"),
        "Read the Search schema's required fields. Tool availability comes from this session's discovery response.",
        "Discovery does not invoke Search or prove that a commercial AI host has been configured.", timeout=240),
    "mcp-search": Exercise(
        "Call Search through MCP",
        "Connect, discover Search, validate its arguments and call it once using the configured query.",
        ("scripts/run_mcp_test.py",),
        "Inspect the JSON-RPC result and its returned document title and source link. Any protocol or tool error stays visible.",
        "The saved schema decides the required arguments. Do not guess extra fields.", timeout=240),
    "indexing-preview": Exercise(
        "Preview one custom document and its access rule",
        "A source has no native connector. Preview the fictional runbook we will submit with a one-user ACL.",
        ("indexing/push_demo.py",),
        "Inspect the document body and permissions.allowedUsers. This SDK preview makes no HTTP request.",
        "No token is read and nothing is sent. Preview is not indexing proof.", indexing=True),
    "indexing-apply": Exercise(
        "Submit the fictional runbook with the Indexing SDK",
        "Upload or update exactly one demo document, including its source link, content and one-user ACL.",
        ("indexing/push_demo.py", "--apply"),
        "HTTP 200 means the upload was accepted. An empty response body is normal here. Check processing and access separately.",
        "This writes the configured demo document. An accepted upload is not yet proof of search visibility.", indexing=True),
    "indexing-status": Exercise(
        "Check processing and the intended reader's access",
        "Read the demo document's status and ask whether the configured user can access it.",
        ("indexing/check_demo.py",),
        "Inspect uploadStatus, indexingStatus, lastUploadedAt and lastIndexedAt in the real status response, then hasAccess in the separate access response.",
        "Processing is asynchronous. A pending check should lead to another read-only check, not a blind reupload.", indexing=True),
    "indexing-permissions": Exercise(
        "Check the permission evidence we actually have",
        "Check datasource identities and the allowed reader, plus a denied reader if one is configured.",
        ("indexing/check_permissions.py",),
        "Inspect the responses to the checks actually sent. The plain-text explanation identifies skipped reader checks and incomplete coverage.",
        "This does not test sign-in, actual search or later revocation. Each reader still needs an end-to-end check.", indexing=True),
    "diagnostics-negative": Exercise(
        "Show controlled invalid-request errors",
        "Compare valid searches and send two deliberately invalid Search requests.",
        ("scripts/run_diagnostics.py", "--include-negative"),
        "The invalid inputs should return the expected 400 errors. Expected failure is a successful diagnostic.",
        "This adds two invalid requests. No broader access or automatic retries are attempted.", optional=True, timeout=240),
    "diagnostics-filters": Exercise(
        "Inspect the Search filter metadata",
        "Compare valid searches and retrieve the available Search filters.",
        ("scripts/run_diagnostics.py", "--include-filters"),
        "Check the filter request's HTTP status and metadata, then compare the Search results.",
        "This is an optional diagnostic, not a promise that every tenant has the same filters.", optional=True, timeout=240),
    "diagnostics-chat": Exercise(
        "Check the Chat connection with a fixed prompt",
        "Run the Search comparison and a small, fixed Chat connection diagnostic.",
        ("scripts/run_diagnostics.py", "--include-chat"),
        "The fixed prompt checks connection behavior. Use chat-rest or chat-python to show a useful answer.",
        "This does not use GLEAN_CHAT_QUERY. It can consume model usage and has the diagnostic's 30-second deadline.",
        optional=True, timeout=240),
}


def clean_text(value: str) -> str:
    """Defense in depth for display. Never render terminal control sequences."""
    value = re.sub(r"\x1b\[[0-?]*[ -/]*[@-~]", "", str(value))
    value = "".join(c if c in "\n\t" or not unicodedata.category(c).startswith("C") else " " for c in value)
    value = re.sub(r"(?i)\bBearer\s+[^\s\"']+", "Bearer [REDACTED]", value)
    # Glean-issued opaque tokens and JWTs must not appear even in unexpected text.
    value = re.sub(r"(?<![A-Za-z0-9])[A-Za-z0-9+/]{40,}={1,2}(?![A-Za-z0-9])", "[REDACTED]", value)
    value = re.sub(r"\beyJ[A-Za-z0-9_-]+\.[A-Za-z0-9_-]+\.[A-Za-z0-9_-]+\b", "[REDACTED]", value)

    def safe_link(match):
        try:
            url = urlsplit(match.group())
            if url.username or url.password:
                return "[credential-bearing link omitted]"
            return urlunsplit((url.scheme, url.netloc, url.path, "", ""))
        except ValueError:
            return "[invalid link omitted]"

    return re.sub(r"https?://[^\s<>\"`]+", safe_link, value)


def scrub(value, depth=0):
    if depth > 16:
        return "[nested content omitted]"
    if isinstance(value, dict):
        result = {}
        for key, item in list(value.items())[:200]:
            name = clean_text(str(key))[:200]
            # These fields are never needed in a presenter report.
            if re.search(r"(?i)(^|_)(token|secret|password|authorization|headers|cookie)(_|$)", name):
                result[name] = "[REDACTED]"
            else:
                result[name] = scrub(item, depth + 1)
        return result
    if isinstance(value, list):
        return [scrub(item, depth + 1) for item in value[:200]]
    if isinstance(value, str):
        return clean_text(value)[:16384]
    return value if value is None or isinstance(value, (bool, int, float)) else "[unsupported value]"


def selected(data, keys):
    return {key: data[key] for key in keys if key in data}


def compact_report(name, report):
    """Show an honest subset of returned evidence, not a fabricated response."""
    if not isinstance(report, dict):
        return {"result": "No structured JSON report was returned."}
    common = ("http_status", "test_expectation_met", "error", "exception_type", "code", "request_id")
    if name in {"search-rest", "search-python"}:
        result = selected(report, common + ("result_count", "expected_document_matched"))
        result["results"] = [selected(row, ("title", "url")) for row in report.get("results", [])[:3]]
        return result
    if name.startswith("chat-"):
        result = selected(report, common + ("response_status", "store", "conversation_id_present", "answer_present", "citation_count"))
        if "answer" in report:
            result["answer_excerpt"] = report["answer"][:700]
            result["answer_excerpt_shortened"] = len(report["answer"]) > 700 or report.get("answer_truncated", False)
        result["citations_shown"] = [selected(row, ("title", "url")) for row in report.get("citations", [])[:2]]
        return result
    if name == "search-compare" or name.startswith("diagnostics-"):
        result = selected(report, ("sdk_version", "all_test_expectations_met", "same_returned_titles_and_urls"))
        result["checks"] = [selected(row, ("id", "http_status", "test_expectation_met", "expected_document_matched",
                                          "datasource_count", "datasource_ids", "code", "field_errors",
                                          "response_status", "benign_answer_matched", "not_run", "error"))
                            for row in report.get("tests", [])]
        return result
    if name.startswith("mcp-"):
        result = selected(report, ("tool_count", "more_tools_pages_available", "stop_reason", "search_protocol_success", "search_test_expectations_met"))
        schema = report.get("search_input_schema", {})
        result["search_required_fields"] = schema.get("required", [])
        result["search_field_types"] = {key: value.get("type", "see schema") for key, value in schema.get("properties", {}).items() if isinstance(value, dict)}
        result["checks"] = [selected(row, ("id", "http_status", "error", "tool_is_error", "expected_fixture_result_matched")) for row in report.get("tests", [])]
        for row in report.get("tests", []):
            if "fixture_result_metadata" in row:
                result["results"] = [selected(item, ("title", "url")) for item in row["fixture_result_metadata"][:3]]
        return result
    return report


def classify(name, returncode, report):
    if name == "indexing-permissions" and returncode == 2 and isinstance(report, dict):
        if report.get("allowed_reader", {}).get("result") == "PASS" and report.get("denied_reader", {}).get("result") == "NOT_RUN":
            return "PARTIAL", "Allowed-reader check passed. Denied-reader coverage is NOT_RUN."
    if returncode != 0:
        return "CHECK REQUIRED", f"The real exercise exited with code {returncode}. Review the evidence before retrying."
    if name == "indexing-preview":
        return "PREVIEW ONLY", "The preview completed. No network requests were made."
    if name == "indexing-apply":
        return "UPLOAD ACCEPTED", "The upload completed. Indexing and search visibility still need separate checks."
    if name == "mcp-discover":
        return "DISCOVERY COMPLETE", "Tools and Search schema were discovered. Search was not called."
    return "PASSED", "The exercise's own checks passed. Read the limits below before extending the conclusion."


def build_command(name, args, root=ROOT):
    exercise = EXERCISES[name]
    interpreter = root / (".venv-indexing" if exercise.indexing else ".venv") / "bin" / "python"
    command = [str(interpreter), *exercise.command]
    if name == "indexing-apply":
        if not args.confirm_sandbox or not re.fullmatch(r"[A-Za-z0-9](?:[A-Za-z0-9.-]*[A-Za-z0-9])?", args.confirm_sandbox):
            raise ValueError("indexing-apply requires --confirm-sandbox with the exact approved backend hostname")
        command += ["--confirm-sandbox", args.confirm_sandbox]
    elif args.confirm_sandbox:
        raise ValueError("--confirm-sandbox is only accepted for indexing-apply")
    if args.search_args_file or args.query_pointer != "/query":
        if name != "mcp-search":
            raise ValueError("MCP argument options are only accepted for mcp-search")
        if args.search_args_file:
            path = Path(args.search_args_file)
            if any(unicodedata.category(c).startswith("C") for c in str(path)):
                raise ValueError("the arguments-file path contains control characters")
            command += ["--search-args-file", str(path)]
        command += ["--query-pointer", args.query_pointer]
    return command


class Screen:
    COLORS = {"blue": "\033[94m", "cyan": "\033[96m", "green": "\033[92m", "yellow": "\033[93m", "red": "\033[91m", "dim": "\033[2m", "bold": "\033[1m"}

    def __init__(self, color="auto", stream=None):
        self.stream = stream or sys.stdout
        self.color = color == "always" or (color == "auto" and self.stream.isatty() and not os.environ.get("NO_COLOR"))

    def style(self, text, color):
        return self.COLORS[color] + text + "\033[0m" if self.color else text

    def line(self, text="", color=None):
        text = clean_text(text)
        print(self.style(text, color) if color else text, file=self.stream, flush=True)

    def paragraph(self, label, text):
        self.line(label, "cyan")
        for line in textwrap.wrap(clean_text(text), width=100):
            self.line("  " + line)

    def json(self, value, complete=False):
        rendered = json.dumps(value, indent=2, ensure_ascii=True)
        lines = rendered.splitlines()
        shortened = not complete and len(lines) > MAX_DISPLAY_LINES
        if shortened:
            lines = lines[:MAX_DISPLAY_LINES]
        # Tokenize JSON without changing any literal text. Only our own ANSI codes
        # are emitted, after the input has passed through scrub().
        pattern = r'"(?:\\.|[^"\\])*"(?=\s*:)|"(?:\\.|[^"\\])*"|\b(?:true|false|null)\b|-?\b\d+(?:\.\d+)?(?:[eE][+-]?\d+)?\b'
        for line in lines:
            if self.color:
                def highlight(match):
                    token = match.group()
                    after = line[match.end():].lstrip()
                    color = "cyan" if token.startswith('"') and after.startswith(":") else "green" if token.startswith('"') else "yellow"
                    return self.style(token, color)
                line = re.sub(pattern, highlight, line)
            print(line, file=self.stream, flush=True)
        if shortened:
            self.line("[Display excerpt ends here. The saved presenter report contains the bounded full report.]", "yellow")


def run_child(command, timeout, root=ROOT):
    """Spool to private files, never echo raw stderr or an unstructured response."""
    started = time.monotonic()
    # Existing entrypoints bound network output. Temporary files also keep their
    # incidental messages out of the audience-facing terminal.
    with tempfile.TemporaryFile() as output, tempfile.TemporaryFile() as errors, \
            tempfile.NamedTemporaryFile(prefix="glean-present-input-", mode="w+b") as inputs:
        child_env = dict(os.environ, GLEAN_PRESENTER_INPUT_FILE=inputs.name)
        try:
            completed = subprocess.run(command, cwd=root, stdout=output, stderr=errors,
                                       timeout=timeout, check=False, env=child_env)
            returncode = completed.returncode
        except subprocess.TimeoutExpired:
            returncode = 124
        except OSError:
            return {"exit_code": 127, "elapsed_seconds": round(time.monotonic() - started, 2),
                    "report": None, "runner_issue": "Could not launch the configured interpreter. Complete the environment setup first.", "stderr_present": False}
        output.seek(0)
        raw = output.read(MAX_CAPTURE_BYTES + 1)
        errors.seek(0, 2)
        stderr_present = errors.tell() > 0
        inputs.seek(0)
        exchanges = []
        for line in inputs.read(MAX_INPUT_BYTES + 1).splitlines()[:64]:
            try:
                event = json.loads(line)
                if isinstance(event, dict) and event.get("kind") in {"http_request", "http_response", "sdk_preview", "sdk_call"}:
                    exchanges.append(redact_payload(event))
            except (ValueError, UnicodeError):
                continue
    issue = None
    if len(raw) > MAX_CAPTURE_BYTES:
        report = None
        issue = "The child output exceeded the presenter limit and was omitted."
    else:
        try:
            report = json.loads(raw)
            if not isinstance(report, dict):
                raise ValueError
        except (ValueError, UnicodeError):
            report = None
            issue = "No structured JSON report was returned. Check local configuration with scripts/check_setup.py. Raw output was omitted."
    if returncode == 124:
        issue = "The presenter deadline expired. No automatic retry was made."
    if returncode == 0 and report is None:
        returncode = 1  # Never announce a pass without returned structured evidence.
    return {"exit_code": returncode, "elapsed_seconds": round(time.monotonic() - started, 2),
            "report": scrub(report), "exchanges": exchanges,
            "inputs": [event for event in exchanges if event["kind"] != "http_response"],
            "runner_issue": issue, "stderr_present": stderr_present}


def safe_recording(value):
    result = scrub(value)
    # Preserve complete captured bodies, including original nesting, URL query
    # parameters and long arrays. The lab summary remains separately scrubbed.
    for key in ("inputs", "exchanges"):
        if key in value:
            result[key] = redact_payload(value[key])
    return result


def save_result(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, temporary_name = tempfile.mkstemp(prefix=".present-", dir=path.parent)
    temporary = Path(temporary_name)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            json.dump(value, handle, indent=2, ensure_ascii=True)
            handle.write("\n")
        temporary.replace(path)
    finally:
        temporary.unlink(missing_ok=True)


def validate_recorded_command(name, command):
    """Only suggest the known lab command, never arbitrary text from a recording."""
    exercise = EXERCISES[name]
    prefix = [(".venv-indexing" if exercise.indexing else ".venv") + "/bin/python", *exercise.command]
    if (not isinstance(command, list) or not all(isinstance(item, str) for item in command)
            or command[:len(prefix)] != prefix
            or any(unicodedata.category(character).startswith("C") for item in command for character in item)):
        raise ValueError("The recorded command is not a supported lab command.")
    tail = command[len(prefix):]
    if name == "indexing-apply":
        if (len(tail) != 2 or tail[0] != "--confirm-sandbox"
                or not re.fullmatch(r"[A-Za-z0-9](?:[A-Za-z0-9.-]*[A-Za-z0-9])?", tail[1])):
            raise ValueError("The recorded indexing command has no valid sandbox confirmation.")
    elif name == "mcp-search":
        if tail[:1] == ["--search-args-file"]:
            if len(tail) < 2 or not tail[1]:
                raise ValueError("The recorded MCP arguments path is missing.")
            tail = tail[2:]
        if tail and (len(tail) != 2 or tail[0] != "--query-pointer" or not tail[1].startswith("/")):
            raise ValueError("The recorded MCP command has unsupported options.")
    elif tail:
        raise ValueError("The recorded command has unsupported options.")


def load_recording(name, root=ROOT):
    """Load a local, bounded report for display only. Its command is never run."""
    path = root / "outputs" / "presenter" / (name + ".json")
    try:
        with path.open("rb") as handle:
            raw = handle.read(MAX_CAPTURE_BYTES + 1)
        if len(raw) > MAX_CAPTURE_BYTES:
            raise ValueError
        saved = json.loads(raw)
        if not isinstance(saved, dict) or saved.get("exercise") != name:
            raise ValueError
        if not isinstance(saved.get("exit_code"), int) or isinstance(saved["exit_code"], bool):
            raise ValueError
        if (not isinstance(saved.get("elapsed_seconds"), (int, float))
                or isinstance(saved["elapsed_seconds"], bool)
                or not math.isfinite(saved["elapsed_seconds"]) or saved["elapsed_seconds"] < 0):
            raise ValueError
        validate_recorded_command(name, saved.get("command"))
        if not isinstance(saved.get("completed_at"), str):
            raise ValueError
        datetime.fromisoformat(saved["completed_at"])
        if saved.get("report") is not None and not isinstance(saved["report"], dict):
            raise ValueError
        if saved["exit_code"] == 0 and saved.get("report") is None:
            raise ValueError
        for key in ("inputs", "exchanges"):
            if key not in saved:
                continue
            if not isinstance(saved[key], list) or len(saved[key]) > 64:
                raise ValueError
            for event in saved[key]:
                if (not isinstance(event, dict)
                        or event.get("kind") not in {"http_request", "http_response", "sdk_preview", "sdk_call"}
                        or not isinstance(event.get("operation"), str)
                        or (event.get("endpoint") is not None and not isinstance(event["endpoint"], str))):
                    raise ValueError
    except (OSError, ValueError, UnicodeError, TypeError):
        raise ValueError(f"No valid recorded presenter result for {name}. Run that exercise first.") from None
    return safe_recording(saved)


def show_result(screen, name, result, path, recorded=False):
    """Plain-language interpretation only. Never present a lab report as JSON."""
    exercise = EXERCISES[name]
    label, meaning = classify(name, result["exit_code"], result["report"])
    screen.line()
    screen.line("=" * 100, "blue")
    screen.line("WHAT THIS MEANS | lab interpretation, not API response fields", "cyan")
    screen.line(f"{label} | {result['elapsed_seconds']:.2f}s | exit {result['exit_code']}",
                "green" if result["exit_code"] == 0 else "yellow")
    screen.line(meaning)
    if result.get("runner_issue"):
        screen.line(result["runner_issue"], "yellow")
    report = result.get("report") or {}
    document = report.get("document", report)
    if document.get("readiness_reason") == "indexed_version_older_than_upload":
        screen.paragraph("TIMESTAMP CHECK", "The last indexed time is earlier than the last uploaded time. Our lab cannot confirm that the latest upload has been indexed.")
    for key, title in (("allowed_reader", "Allowed-reader check"), ("denied_reader", "Denied-reader check")):
        check = report.get(key, {})
        if check.get("result") == "NOT_RUN":
            reason = {"document_not_confirmed_indexed": "the latest upload is not confirmed indexed",
                      "second_reader_not_configured": "no second reader is configured"}.get(check.get("reason"), "its prerequisite was not confirmed")
            screen.line(title + " was not run because " + reason + ".")
    screen.paragraph("HOW TO READ THIS", exercise.watch)
    screen.paragraph("LIMIT", exercise.boundary)
    screen.line("Saved private recording: " + str(path.relative_to(ROOT)), "dim")
    screen.line("=" * 100, "blue")


def pause(screen, args, message):
    if args.step and sys.stdin.isatty():
        screen.line(message, "cyan")
        try:
            input()
        except EOFError:
            pass


def show_exchanges(screen, name, result, args, recorded=False):
    """Render only authentic bodies as JSON, with metadata outside each body."""
    events = result.get("exchanges") or result.get("inputs") or []
    if not events:
        screen.line("No request or response bodies were captured with this recording. No reconstructed JSON is shown.", "yellow")
        return
    screen.line("The following bodies were captured during the recorded run." if recorded else
                "The following bodies were captured during this run.")
    screen.line("JSON is pretty-printed in full. Credential redactions appear as [REDACTED]. Headers are omitted.", "dim")
    request_count = response_count = 0
    for position, event in enumerate(events):
        kind = event["kind"]
        screen.line()
        screen.line("-" * 100, "blue")
        if kind == "http_response":
            response_count += 1
            screen.line(f"RESPONSE {response_count} | HTTP {event.get('http_status', 'unknown')}", "bold")
            if event.get("content_type"):
                screen.line("Content-Type: " + event["content_type"])
            if event.get("body_format") == "jsonrpc_message":
                screen.line("JSON-RPC message received from the SSE response stream:")
        elif kind == "sdk_preview":
            screen.line("SDK INPUT PREVIEW | no HTTP request was sent", "bold")
            screen.line(event["operation"])
        else:
            request_count += 1
            screen.line(f"REQUEST {request_count} | " + event["operation"], "bold")
            if event.get("endpoint"):
                screen.line(event["endpoint"], "blue")
        screen.line("-" * 100, "blue")
        if event.get("body_omitted_reason"):
            screen.line(event["body_omitted_reason"], "yellow")
        elif event.get("body_format") == "empty" or (kind != "http_response" and event.get("payload") is None):
            screen.line("(Empty body)")
        elif event.get("body_format") == "text":
            screen.line(event.get("payload", ""))
        else:
            screen.json(redact_payload(event.get("payload")), complete=True)
        screen.line("-" * 100, "blue")
        if position + 1 < len(events):
            following = events[position + 1]["kind"]
            pause(screen, args, "Press Enter to show the response." if following == "http_response" else
                  "Press Enter to show the next request.")
    if request_count and not response_count:
        screen.line("The actual response body was not captured in this older recording. No substitute response is shown.", "yellow")


def pause_for_response(screen, args):
    pause(screen, args, "Press Enter to reveal the response and what it means.")


def hold_window(screen):
    screen.line("Presentation window kept open. Press Enter when you are finished with this example.", "cyan")
    try:
        input()
    except EOFError:
        pass


def replay(name, args, screen):
    if args.confirm_sandbox or args.search_args_file or args.query_pointer != "/query":
        raise ValueError("--replay uses the saved command. It does not accept live-run overrides.")
    saved = load_recording(name)
    screen.line("=" * 100, "blue")
    screen.line("GLEAN POWERUP | " + EXERCISES[name].title, "bold")
    screen.line("RECORDED RESULT | actual completed run, not a live rerun", "yellow")
    screen.line("Recorded at: " + saved["completed_at"])
    screen.line("=" * 100, "blue")
    screen.paragraph("WHY THIS EXAMPLE", EXERCISES[name].purpose)
    screen.line()
    screen.line("COMMAND THAT PRODUCED THIS RECORDING", "cyan")
    screen.line("$ " + shlex.join(saved["command"]), "bold")
    screen.line("This view reads local saved evidence. It makes no requests and changes no data.", "dim")
    if args.plan:
        screen.line("PLAN ONLY | recording validated; no process started.", "yellow")
        return 0
    show_exchanges(screen, name, saved, args, recorded=True)
    show_result(screen, name, saved, ROOT / "outputs" / "presenter" / (name + ".json"), recorded=True)
    screen.line("To rerun live, use the command shown above. Recheck credential expiry and write intent first.", "dim")
    if args.hold:
        hold_window(screen)
    return saved["exit_code"]


def parser():
    result = argparse.ArgumentParser(description=__doc__)
    result.add_argument("exercise", nargs="?", choices=EXERCISES)
    result.add_argument("--list", action="store_true", help="List exercises without reading settings or making requests")
    result.add_argument("--plan", action="store_true", help="Print the real command and purpose without running it")
    result.add_argument("--replay", action="store_true", help="Display this exercise's saved real result, clearly labeled recorded; never run a request")
    result.add_argument("--color", choices=("auto", "always", "never"), default="auto")
    result.add_argument("--hold", action="store_true", help="Wait for Enter after completion; use in a dedicated terminal window")
    result.add_argument("--step", action="store_true", help="In an interactive terminal, pause on the request inputs; press Enter to reveal the response")
    result.add_argument("--confirm-sandbox", help="Required only for the one-document indexing write")
    result.add_argument("--search-args-file", help="Reviewed extra Search arguments for mcp-search only")
    result.add_argument("--query-pointer", default="/query", help="Reviewed query location for mcp-search only")
    return result


def main(argv=None):
    cli = parser()
    args = cli.parse_args(argv)
    screen = Screen(args.color)
    if args.list:
        screen.line("GLEAN POWERUP | available presenter exercises", "bold")
        for name, exercise in EXERCISES.items():
            suffix = " (optional diagnostic)" if exercise.optional else ""
            screen.line(f"  {name:23s} {exercise.title}{suffix}")
        screen.line("Each invocation runs one real entrypoint. Directory/user maintenance is not a regular exercise.", "dim")
        return 0
    if not args.exercise:
        cli.error("choose an exercise or use --list")
    if args.replay:
        try:
            return replay(args.exercise, args, screen)
        except ValueError as error:
            cli.error(str(error))
    try:
        command = build_command(args.exercise, args)
    except ValueError as error:
        cli.error(str(error))
    exercise = EXERCISES[args.exercise]
    relative_command = [str(Path(command[0]).relative_to(ROOT)), *command[1:]]
    shown_command = shlex.join(relative_command)
    screen.line("=" * 100, "blue")
    screen.line("GLEAN POWERUP | " + exercise.title, "bold")
    screen.line("=" * 100, "blue")
    screen.paragraph("WHY THIS EXAMPLE", exercise.purpose)
    screen.line()
    screen.line("REAL COMMAND", "cyan")
    screen.line("$ " + shown_command, "bold")
    screen.line("Uses the existing local configuration. Credential values and request headers are never displayed.", "dim")
    screen.line()
    if args.plan:
        screen.paragraph("WHAT TO LOOK FOR", exercise.watch)
        screen.paragraph("LIMIT", exercise.boundary)
        screen.line("PLAN ONLY | no child process started and no network requests made.", "yellow")
        return 0
    if not Path(command[0]).is_file():
        screen.line("SETUP REQUIRED | the selected Python environment is missing. Follow the README first.", "red")
        return 2
    screen.line("Running the exercise now. Waiting for the real response...", "yellow")
    result = run_child(command, exercise.timeout)
    label, meaning = classify(args.exercise, result["exit_code"], result["report"])
    saved = {"exercise": args.exercise, "title": exercise.title,
             "completed_at": datetime.now(timezone.utc).isoformat(), "command": relative_command,
             "outcome": label, **result}
    path = ROOT / "outputs" / "presenter" / (args.exercise + ".json")
    save_result(path, safe_recording(saved))
    show_exchanges(screen, args.exercise, result, args)
    show_result(screen, args.exercise, result, path)
    if args.hold:
        hold_window(screen)
    return result["exit_code"]


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except KeyboardInterrupt:
        print("\nPresenter interrupted. No automatic retry was made.", file=sys.stderr)
        raise SystemExit(130)
