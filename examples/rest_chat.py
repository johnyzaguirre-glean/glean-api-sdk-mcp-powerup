#!/usr/bin/env python3
"""Ask a question with a bounded POST /api/chat request."""
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from scripts.common import guarded_main
from scripts.chat_lab import run_chat


if __name__ == "__main__":
    raise SystemExit(guarded_main(run_chat))
