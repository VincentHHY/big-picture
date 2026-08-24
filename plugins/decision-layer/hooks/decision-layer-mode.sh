#!/usr/bin/env bash
# Runs decision-layer-mode.py with whichever Python this machine calls it.
#
# Linux and macOS usually ship "python3" and often have no bare "python" at all; Windows
# Python installs the bare "python". Picking here means the hook command, and the arming
# command in SKILL.md, stay the same on all three.
#
# Each candidate is RUN, not merely looked up. Windows puts App Execution Alias stubs for
# python3 and python on PATH, ahead of any real install: they resolve, advertise the
# Microsoft Store on stderr and exit without running anything. A name that resolves proves
# nothing, and picking a stub leaves the whole plugin inert with no marker and no error.
# The same probe rules out a "python" that is still Python 2.
#
# Exits 0 whatever happens. A hook that fails must not break the session, and no output
# means no marker, which is ordinary output.

script_dir="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
target="$script_dir/decision-layer-mode.py"

for candidate in python3 python py; do
  # stdin carries the hook payload and can only be read once, so keep the probe off it.
  if "$candidate" -c 'import sys; sys.exit(0 if sys.version_info[0] == 3 else 1)' \
      </dev/null >/dev/null 2>&1; then
    "$candidate" "$target" "$@"
    exit 0
  fi
done

# No Python found. Say so only in hand-run mode; as a hook, stay silent.
if [ -n "$1" ]; then
  echo "No working Python 3 found on PATH (tried python3, python, py)."
fi
exit 0
