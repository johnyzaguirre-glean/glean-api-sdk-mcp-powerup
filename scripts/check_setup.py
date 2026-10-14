#!/usr/bin/env python3
"""Check local configuration and dependencies without making network requests."""
import importlib.metadata
from common import guarded_main, prepare_search, search_parser


def main():
    args = search_parser(__doc__).parse_args()
    prepare_search(args)
    from glean.api_client import Glean  # noqa: F401
    from jsonschema import validators  # noqa: F401
    from referencing import Registry  # noqa: F401
    version = importlib.metadata.version("glean-api-client")
    if version != "0.17.16":
        print("Configuration is valid, but reinstall requirements.txt to use the demonstrated client version.")
        return 1
    print("Configuration, token-file permissions and dependencies look good. No network requests were made.")
    return 0


if __name__ == "__main__":
    raise SystemExit(guarded_main(main))
