#!/usr/bin/env python3
"""Make one Platform Search request and print only selected response metadata."""
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from scripts.common import (execute, expected_result, guarded_main, prepare_search,
                            rest_probe, search_parser, serialized_output)


def main():
    args = search_parser(__doc__).parse_args()
    base_url, token, query = prepare_search(args)
    # The wire request is POST /api/search with this JSON object.
    payload = {"query": query, "page_size": 3}
    result = execute("rest_search", 200,
                     lambda: rest_probe(base_url, token, "POST", "/api/search", payload, "search"))
    result.update(expected_result(result, args.expected_title, args.expected_url))
    print(serialized_output(result, token), end="")
    return 0 if result["test_expectation_met"] and result.get("expected_document_matched", True) else 1


if __name__ == "__main__":
    raise SystemExit(guarded_main(main))
