#!/usr/bin/env python3
"""Store a separate Indexing API token through a hidden local prompt."""
import getpass
import os
import sys
from lab import SafeFailure, load_env, run_guarded, token_path, validate_token


def main():
    if not sys.stdin.isatty():
        raise SafeFailure("run this helper in an interactive terminal for hidden token entry")
    path = token_path(load_env().get("GLEAN_INDEXING_TOKEN_FILE", ".secrets/glean-indexing-token"))
    path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    if path.exists() or path.is_symlink():
        raise SafeFailure("file already exists; choose a new GLEAN_INDEXING_TOKEN_FILE path")
    token = validate_token(getpass.getpass("Paste your approved Indexing API token (hidden), then press Enter: ").strip())
    try:
        fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    except FileExistsError:
        raise SafeFailure("file already exists; it was not overwritten") from None
    with os.fdopen(fd, "w", encoding="utf-8") as handle:
        handle.write(token + "\n")
    print("Indexing token saved in the configured owner-only file. Its value was not printed.")
    return 0


if __name__ == "__main__":
    raise SystemExit(run_guarded(main))
