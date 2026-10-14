#!/usr/bin/env python3
"""Run the same search with the pinned Glean Python client."""
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from scripts.common import (execute, expected_result, guarded_main, prepare_search,
                            sdk_probe, search_parser, serialized_output)


def main():
    args = search_parser(__doc__).parse_args()
    base_url, token, query = prepare_search(args)
    # sdk_probe wraps this client call with a timeout and a response-size limit:
    # with Glean(api_token=token, server_url=base_url, ...) as glean:
    #     result = glean.search.query(query=query, page_size=3, ...)
    result = execute("python_search", 200, lambda: sdk_probe(base_url, token, query))
    result.update(expected_result(result, args.expected_title, args.expected_url))
    print(serialized_output(result, token), end="")
    return 0 if result["test_expectation_met"] and result.get("expected_document_matched", True) else 1


if __name__ == "__main__":
    raise SystemExit(guarded_main(main))
