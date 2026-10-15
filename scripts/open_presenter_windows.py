#!/usr/bin/env python3
"""User-run macOS launcher for recorded exercise evidence in separate windows.

This launcher opens Terminal only when the user runs it. It never executes a lab
request, uploads a document, reads a token, or closes any existing window. Use
--plan to inspect its exact commands without opening or controlling applications.
"""
from __future__ import annotations

import argparse
from pathlib import Path
import shlex
import subprocess
import sys

from present import EXERCISES, MAIN_EXERCISES, ROOT, load_recording


def applescript_string(value):
    """Quote a literal for AppleScript, independently from shell quoting."""
    if any(ord(character) < 32 for character in value):
        raise ValueError("A launcher path contains unsupported control characters.")
    return '"' + value.replace("\\", "\\\\").replace('"', '\\"') + '"'


def window_commands(root=ROOT):
    python = root / ".venv" / "bin" / "python"
    commands = []
    for number, name in enumerate(MAIN_EXERCISES, 1):
        arguments = [str(python), str(root / "scripts/present.py"), name,
                     "--replay", "--color", "always", "--hold", "--step"]
        commands.append({"name": name, "title": f"{number:02d} | Glean PowerUp | {EXERCISES[name].title}",
                         "command": "cd " + shlex.quote(str(root)) + " && " + shlex.join(arguments)})
    return commands


def script_for(commands):
    lines = ['tell application "Terminal"', '  activate']
    for item in commands:
        lines += ["  set demoTab to do script " + applescript_string(item["command"]),
                  "  set custom title of demoTab to " + applescript_string(item["title"])]
    lines.append("end tell")
    return "\n".join(lines) + "\n"


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--plan", action="store_true", help="Show all proposed windows and missing recordings, without controlling an app")
    args = parser.parse_args(argv)
    commands = window_commands()
    missing = []
    for item in commands:
        try:
            load_recording(item["name"])
        except ValueError:
            missing.append(item["name"])
    print("Glean PowerUp: recorded exercise windows")
    print("Each window shows the input first. Press Enter to reveal the saved response and its meaning.")
    print("Requests and responses carry the original run timestamp. Missing bodies are never reconstructed.")
    print("Opening these windows does not rerun requests, consume model usage, or reupload a document.")
    if args.plan:
        for item in commands:
            print("\n" + item["title"])
            print(item["command"])
        print("\nMissing or invalid recordings: " + (", ".join(missing) if missing else "none"))
        print("PLAN ONLY. No application was opened or controlled.")
        return 0
    if sys.platform != "darwin":
        print("This window launcher requires macOS. Run present.py NAME --replay in separate terminals instead.", file=sys.stderr)
        return 2
    if not (ROOT / ".venv/bin/python").is_file():
        print("Create the repository's .venv first, following the README.", file=sys.stderr)
        return 2
    if missing:
        print("Run and record these exercises before opening the full session: " + ", ".join(missing), file=sys.stderr)
        return 2
    print("Opening 11 separate Terminal windows. macOS may ask you to allow Terminal automation.")
    # The user explicitly runs this launcher. Do not invoke it from an agent when
    # application control is unavailable; --plan is the non-controlling audit path.
    try:
        completed = subprocess.run(["/usr/bin/osascript", "-"], input=script_for(commands),
                                   text=True, capture_output=True, check=False)
    except OSError:
        print("Could not start the macOS window launcher. No request was rerun.", file=sys.stderr)
        return 1
    if completed.returncode:
        print("macOS did not complete opening all windows. Existing windows remain open. No request was rerun.", file=sys.stderr)
        print("You can run the commands from --plan in separate terminals yourself.", file=sys.stderr)
        return 1
    print("All 11 windows are open. Each waits for Enter so the evidence stays visible.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
