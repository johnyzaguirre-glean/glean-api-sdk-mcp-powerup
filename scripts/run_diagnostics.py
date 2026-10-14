#!/usr/bin/env python3
"""Compare bounded REST and Python searches. Extra probes require explicit flags."""
import hashlib
import importlib.metadata
from pathlib import Path

from common import (CHAT_INPUT, ROOT, TIMEOUT, execute, expected_result, guarded_main,
                    prepare_search, rest_probe, save_report, sdk_probe,
                    search_parser, serialized_output, utc_now, same_search_results)


def main():
    parser = search_parser(__doc__)
    parser.add_argument("--out", type=Path, default=ROOT / "outputs" / "diagnostics.json")
    parser.add_argument("--include-negative", action="store_true", help="Also send two deliberately invalid search requests")
    parser.add_argument("--include-filters", action="store_true", help="Also read search filter metadata")
    parser.add_argument("--include-chat", action="store_true", help="Also send one fixed, ephemeral Chat request")
    args = parser.parse_args()
    base_url, token, query = prepare_search(args)
    # Import before the first request to avoid partial runs when installation is incomplete.
    from glean.api_client import Glean  # noqa: F401
    report = {"schema_version": 1, "started_at": utc_now(),
              "sdk_package": "glean-api-client",
              "sdk_version": importlib.metadata.version("glean-api-client"),
              "timeout_seconds_per_probe": TIMEOUT, "automatic_retries": False,
              "query_sha256": hashlib.sha256(query.encode()).hexdigest(),
              "query_character_count": len(query), "page_size": 3, "tests": []}
    probes = [("P1_search", 200, "POST", "/api/search", {"query": query, "page_size": 3}, "search")]
    if args.include_filters:
        probes.append(("P2_filters", 200, "GET", "/api/search/filters", None, "filters"))
    if args.include_negative:
        probes.extend([
            ("N1_empty_search", 400, "POST", "/api/search", {}, "error"),
            ("N2_page_size_zero", 400, "POST", "/api/search", {"query": query, "page_size": 0}, "error"),
        ])
    if args.include_chat:
        probes.append(("P3_ephemeral_chat", 200, "POST", "/api/chat",
                       {"input": CHAT_INPUT, "stream": False, "store": False}, "chat"))
    stop_reason = None
    for test_id, expected, method, path, payload, kind in probes:
        if stop_reason:
            report["tests"].append({"id": test_id, "not_run": stop_reason})
            continue
        item = execute(test_id, expected, lambda: rest_probe(base_url, token, method, path, payload, kind))
        item.update({"method": method, "path": path})
        if kind == "search":
            item.update(expected_result(item, args.expected_title, args.expected_url))
            item["test_expectation_met"] &= item.get("expected_document_matched", True)
        report["tests"].append(item)
        if item.get("http_status") == 429:
            stop_reason = "stopped_after_rate_limit"
        elif item.get("http_status") in (401, 403):
            stop_reason = "authentication_or_authorization_failed"
        save_report(args.out, report, token)
    if stop_reason:
        report["tests"].append({"id": "P4_sdk_search", "not_run": stop_reason})
    else:
        item = execute("P4_sdk_search", 200, lambda: sdk_probe(base_url, token, query))
        item.update({"method": "SDK search.query", "path": "/api/search"})
        item.update(expected_result(item, args.expected_title, args.expected_url))
        item["test_expectation_met"] &= item.get("expected_document_matched", True)
        report["tests"].append(item)
    rest = report["tests"][0]
    sdk = report["tests"][-1]
    report["same_returned_titles_and_urls"] = same_search_results(rest, sdk)
    report["completed_at"] = utc_now()
    report["all_test_expectations_met"] = all(t.get("test_expectation_met", False) for t in report["tests"])
    save_report(args.out, report, token)
    print(serialized_output(report, token), end="")
    return 0 if report["all_test_expectations_met"] and report["same_returned_titles_and_urls"] else 1


if __name__ == "__main__":
    raise SystemExit(guarded_main(main))
