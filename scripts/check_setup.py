#!/usr/bin/env python3
"""Check local configuration and dependencies without making network requests."""
import argparse
import importlib.metadata
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from scripts.common import guarded_main, prepare_search, search_parser
from scripts.chat_lab import chat_parser, prepare_chat


def main(argv=None):
    selector = argparse.ArgumentParser(add_help=False)
    selector.add_argument("--chat", action="store_true")
    mode, _ = selector.parse_known_args(argv)
    parser = (chat_parser if mode.chat else search_parser)(__doc__)
    parser.add_argument("--chat", action="store_true", help="validate Chat configuration instead of Search")
    args = parser.parse_args(argv)
    (prepare_chat if mode.chat else prepare_search)(args)
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
