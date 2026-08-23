"""Measure how readable a reply is at a glance, rather than whether it can be followed.

    python score_scannability.py --iterations 2,5

Added because the rest of the suite is blind to this. Every other measure asks whether
the reader can follow the reply and act on it; none asks whether they can find their way
around it. A change could turn well-structured answers into unbroken prose and every
other number here would stay flat.

That gap was found by a human reading two replies side by side and noticing within
seconds that one was easier to scan. No instrument in this suite saw it.

These are proxies, and they are honest about being proxies. A wall of text is usually
harder to scan than the same content in three paragraphs, and a reply with headings is
usually easier to navigate than one without - but a badly written table beats nothing
and a well written paragraph beats a bad list. Read these as symptoms, not verdicts, and
use the worst-paragraph figure in particular as a pointer to go and read the reply.

Only the prose above the divider counts. The anchor block is reference material, not
something the reader navigates.
"""

import argparse
import glob
import io
import os
import re
import statistics
from collections import defaultdict
from pathlib import Path

# Honour CLAUDE_CONFIG_DIR, as the hook does, so a relocated config directory still works.
CLAUDE_DIR = Path(os.environ.get("CLAUDE_CONFIG_DIR", "").strip()
                 or os.path.expanduser("~/.claude")).expanduser()
WORKSPACE = CLAUDE_DIR / "state" / "decision-layer-evals"

ICON = re.compile("[\U0001F300-\U0001FAFF←-⇿☀-➿⬀-⯿️]")
HEADING = re.compile(r"^\s{0,3}#{1,6}\s+\S", re.M)
BULLET = re.compile(r"^\s{0,4}(?:[-*+]|\d+\.)\s+\S", re.M)
TABLE_ROW = re.compile(r"^\s*\|.*\|\s*$", re.M)
BOLD = re.compile(r"\*\*[^*\n]+\*\*")


def measure(prose):
    """Structural facts about one reply's prose."""
    paragraphs = [" ".join(p.split()) for p in re.split(r"\n\s*\n", prose) if p.strip()]
    # A paragraph made only of list rows is already broken up for the eye, so it does
    # not count as a wall of text however long it runs.
    plain = [p for p in paragraphs
             if not BULLET.match(p) and not p.lstrip().startswith("|")]
    return {
        "icons": len(ICON.findall(prose)),
        "headings": len(HEADING.findall(prose)),
        "bullets": len(BULLET.findall(prose)),
        "table_rows": len(TABLE_ROW.findall(prose)),
        "bold": len(BOLD.findall(prose)),
        "paragraphs": len(paragraphs),
        "worst_paragraph": max((len(p) for p in plain), default=0),
        "signposts": (len(HEADING.findall(prose)) + len(BULLET.findall(prose))
                      + len(TABLE_ROW.findall(prose)) + len(ICON.findall(prose))),
    }


def collect(iteration):
    root = WORKSPACE / f"iteration-{iteration}"
    per_case = defaultdict(list)
    for path in sorted(glob.glob(str(root / "*" / "armed" / "run-*.md"))):
        text = io.open(path, encoding="utf-8").read().split("--- where ---")[0]
        text = text.replace("▪ decision-layer", "")
        if not text.strip():
            continue
        case = Path(path).parent.parent.name
        per_case[case].append(measure(text))
    return per_case


def mean_of(rows, key):
    return statistics.mean([r[key] for r in rows]) if rows else 0.0


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--iterations", required=True,
                        help="comma-separated, e.g. 2,5")
    args = parser.parse_args()
    iterations = [i.strip() for i in args.iterations.split(",")]
    data = {i: collect(i) for i in iterations}
    missing = [i for i in iterations if not data[i]]
    if missing:
        print(f"no armed replies for iteration(s): {', '.join(missing)}")
        return 1

    keys = ["signposts", "headings", "bullets", "table_rows", "bold", "icons",
            "paragraphs", "worst_paragraph"]
    print("Averages per armed reply (prose above the divider only)\n")
    width = max(len(k) for k in keys) + 2
    print("measure".ljust(width) + "".join(f"it{i}".rjust(12) for i in iterations))
    print("-" * (width + 12 * len(iterations)))
    for key in keys:
        row = key.replace("_", " ").ljust(width)
        for i in iterations:
            allrows = [r for rows in data[i].values() for r in rows]
            row += f"{mean_of(allrows, key):12.1f}"
        print(row)

    print("\nWorst paragraph, the wall-of-text measure, per case:\n")
    cases = sorted(set.intersection(*(set(data[i]) for i in iterations)))
    print("case".ljust(28) + "".join(f"it{i}".rjust(10) for i in iterations))
    for case in cases:
        row = case.ljust(28)
        for i in iterations:
            row += f"{mean_of(data[i][case], 'worst_paragraph'):10.0f}"
        print(row)

    print("\nSignposts per reply, per case (headings + bullets + table rows + icons):\n")
    print("case".ljust(28) + "".join(f"it{i}".rjust(10) for i in iterations))
    for case in cases:
        row = case.ljust(28)
        for i in iterations:
            row += f"{mean_of(data[i][case], 'signposts'):10.1f}"
        print(row)

    print("\nThese are proxies. A long paragraph is not automatically bad and a bullet "
          "list is not automatically good;\nuse the worst-paragraph column to decide "
          "which replies are worth reading yourself.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
