#!/bin/zsh
# User-run only. Double-click to open saved real evidence in separate windows.
set -eu
presenter_root="$(cd -- "$(dirname -- "$0")/.." && pwd)"
if [[ ! -x "$presenter_root/.venv/bin/python" ]]; then
  print -u2 'Create the repository .venv first, following the README.'
  exit 2
fi
exec "$presenter_root/.venv/bin/python" "$presenter_root/scripts/open_presenter_windows.py" "$@"
