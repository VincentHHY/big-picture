#!/usr/bin/env bash
# Runs decision-layer-mode.py with whichever Python this machine calls it.
#
# Linux and macOS usually ship "python3" and often have no bare "python" at all; Windows
# Python installs the bare "python". Picking here means the hook command, and the arming
# command in SKILL.md, stay the same on all three.
#
# Exits 0 whatever happens. A hook that fails must not break the session, and no output
# means no marker, which is ordinary output.

script_dir="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
target="$script_dir/decision-layer-mode.py"

for candidate in python3 python py; do
  if command -v "$candidate" >/dev/null 2>&1; then
    "$candidate" "$target" "$@"
    exit 0
  fi
done

# No Python found. Say so only in hand-run mode; as a hook, stay silent.
if [ -n "$1" ]; then
  echo "No Python interpreter found on PATH (looked for python3, python, py)."
fi
exit 0
