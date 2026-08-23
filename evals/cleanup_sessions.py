"""Remove the throwaway sessions an eval sweep leaves in the real session history.

    python cleanup_sessions.py                 # dry run - lists, deletes nothing
    python cleanup_sessions.py --delete        # actually remove them

New runs no longer need this. Both run_cases.py and grade.py now pass
--no-session-persistence, so nothing is written in the first place. This exists to
clear what earlier sweeps already left behind.

Deleting session history is not reversible, so the identification is deliberately
conservative and has to clear three hurdles:

  1. Only transcripts whose FIRST user message carries an eval marker count. A real
     session that merely discusses this suite - like the one that built it - mentions
     the same paths further down, and would be destroyed by a naive content grep.
  2. Session ids recorded in an iteration's runs.json are matched exactly.
  3. Anything currently live in ~/.claude/sessions is excluded no matter what else
     says, so a running session can never be pulled out from under itself.

Dry run is the default. Nothing is removed without --delete.
"""

import argparse
import json
import os
from pathlib import Path

# Honour CLAUDE_CONFIG_DIR, as the hook does, so a relocated config directory still works.
CLAUDE_DIR = Path(os.environ.get("CLAUDE_CONFIG_DIR", "").strip()
                 or os.path.expanduser("~/.claude")).expanduser()
PROJECTS = CLAUDE_DIR / "projects"
SESSIONS = CLAUDE_DIR / "sessions"
WORKSPACE = CLAUDE_DIR / "state" / "decision-layer-evals"

# Strings that only ever appear in an eval prompt or a grader brief.
MARKERS = (
    "decision-layer-evals",
    "decision-layer/evals/fixtures",
    "--- THE REPLY ---",
)


def live_session_ids():
    """Sessions with a running CLI behind them. Never touch these."""
    ids = set()
    for path in SESSIONS.glob("*.json"):
        try:
            entry = json.loads(path.read_text(encoding="utf-8"))
        except Exception:
            continue
        if entry.get("sessionId"):
            ids.add(str(entry["sessionId"]))
    return ids


def recorded_session_ids():
    """Ids the harness wrote down itself - the exact, unambiguous ones."""
    ids = set()
    for runs in WORKSPACE.glob("iteration-*/runs.json"):
        try:
            for record in json.loads(runs.read_text(encoding="utf-8")):
                if record.get("session_id"):
                    ids.add(str(record["session_id"]))
        except Exception:
            continue
    for run_json in WORKSPACE.glob("iteration-*/*/*/run-*.json"):
        try:
            record = json.loads(run_json.read_text(encoding="utf-8"))
            if record.get("session_id"):
                ids.add(str(record["session_id"]))
        except Exception:
            continue
    return ids


def first_user_text(transcript):
    """The opening user message, which is what identifies a session's purpose."""
    try:
        with transcript.open(encoding="utf-8", errors="replace") as handle:
            for _ in range(40):
                line = handle.readline()
                if not line:
                    return ""
                try:
                    entry = json.loads(line)
                except Exception:
                    continue
                if entry.get("type") != "user":
                    continue
                content = (entry.get("message") or {}).get("content")
                if isinstance(content, str):
                    return content
                if isinstance(content, list):
                    return " ".join(
                        part.get("text", "") for part in content
                        if isinstance(part, dict))
    except Exception:
        return ""
    return ""


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--delete", action="store_true",
                        help="actually remove the transcripts; without it this only reports")
    parser.add_argument("--keep", default="",
                        help="comma-separated session ids to spare on top of the live ones")
    args = parser.parse_args()

    protected = live_session_ids() | {
        s.strip() for s in args.keep.split(",") if s.strip()}
    recorded = recorded_session_ids()

    targets = []
    for transcript in PROJECTS.glob("*/*.jsonl"):
        session_id = transcript.stem
        if session_id in protected:
            continue
        opening = first_user_text(transcript)
        by_marker = any(marker in opening for marker in MARKERS)
        by_record = session_id in recorded
        if by_marker or by_record:
            targets.append((transcript, "recorded by the harness" if by_record
                            else "eval prompt in its first message"))

    if not targets:
        print("No eval sessions found in the history.")
        print(f"({len(protected)} live or spared session(s) were excluded from the scan.)")
        return 0

    total = sum(t.stat().st_size for t, _ in targets)
    print(f"{len(targets)} eval session(s), {total / 1024:.0f} KB:\n")
    for transcript, why in sorted(targets, key=lambda pair: pair[0].name):
        print(f"  {transcript.stem}  ({why})")
    print(f"\n{len(protected)} live or spared session(s) excluded.")

    if not args.delete:
        print("\nDry run. Nothing was removed. Re-run with --delete to remove them.")
        return 0

    removed = 0
    for transcript, _ in targets:
        try:
            transcript.unlink()
            removed += 1
        except Exception as error:
            print(f"  could not remove {transcript.name}: {error}")
    print(f"\nRemoved {removed} of {len(targets)}.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
