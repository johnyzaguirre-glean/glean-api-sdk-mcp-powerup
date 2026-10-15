#!/usr/bin/env python3
"""Ask a question with the pinned Glean Python client's Platform Chat API."""
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from scripts.common import guarded_main
from scripts.chat_lab import run_chat


if __name__ == "__main__":
    raise SystemExit(guarded_main(lambda: run_chat(use_sdk=True)))
