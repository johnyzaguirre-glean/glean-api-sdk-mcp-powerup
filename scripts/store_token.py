#!/usr/bin/env python3
"""Save a token from a hidden terminal prompt. Never accepts a token as an argument."""
import getpass
import os
import sys
from common import SafeFailure, guarded_main, load_config, token_path, validate_token


def main():
    if not sys.stdin.isatty():
        raise SafeFailure("run this helper in an interactive terminal for hidden token entry")
    config = load_config()
    path = token_path(config.get("GLEAN_TOKEN_FILE", ".secrets/glean-token"))
    path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    if path.exists() or path.is_symlink():
        raise SafeFailure("token file already exists; choose a new GLEAN_TOKEN_FILE path to replace it safely")
    token = validate_token(getpass.getpass("Paste your Glean token (hidden), then press Enter: ").strip())
    try:
        fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    except FileExistsError:
        raise SafeFailure("token file already exists; it was not overwritten") from None
    with os.fdopen(fd, "w", encoding="utf-8") as handle:
        handle.write(token + "\n")
    print("Token saved in the configured owner-only file. Its value was not printed.")
    return 0


if __name__ == "__main__":
    raise SystemExit(guarded_main(main))
