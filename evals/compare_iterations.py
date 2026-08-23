"""Compare two iterations, to answer "did that change help, hurt, or do nothing?".

    python compare_iterations.py --before 2 --after 4

report.py describes one iteration. Reading two of its reports side by side is how a
small regression gets missed, so this does the subtraction and says which differences
are big enough to mean anything.

Three things it is careful about, each learned the expensive way:

  significance   A shift from 7 of 10 to 10 of 10 looks decisive and is p = 0.21. Every
                 difference here is reported with a Fisher exact p, and anything above
                 0.05 is labelled directional rather than real.
  direction      A change that IMPROVES the armed score while also improving the unarmed
                 one has not improved the boundary; something else moved. The unarmed arm
                 is reported alongside as a sanity check.
  the right unit A per-case rate over five runs is far too coarse. The aggregate over all
                 armed replies is the number with enough behind it to read.
"""

import argparse
import json
import os
import statistics
from collections import defaultdict
from math import comb
from pathlib import Path

# Honour CLAUDE_CONFIG_DIR, as the hook does, so a relocated config directory still works.
CLAUDE_DIR = Path(os.environ.get("CLAUDE_CONFIG_DIR", "").strip()
                 or os.path.expanduser("~/.claude")).expanduser()
WORKSPACE = CLAUDE_DIR / "state" / "decision-layer-evals"
EVALS_DIR = Path(__file__).resolve().parent


def fisher_two_tailed(a, b, c, d):
    """Probability of a table this lopsided or worse, if the change did nothing."""
    n1, n2, k, n = a + b, c + d, a + c, a + b + c + d
    if not all((n1, n2, n)) or k == 0 or k == n:
        return 1.0

    def p(x):
        return comb(n1, x) * comb(n2, k - x) / comb(n, k) if 0 <= k - x <= n2 else 0.0

    observed = p(a)
    return min(1.0, sum(p(x) for x in range(0, min(n1, k) + 1)
                        if p(x) <= observed + 1e-12))


def load(iteration):
    """Per-reply facts for one iteration, keyed by arm."""
    root = WORKSPACE / f"iteration-{iteration}"
    rows = defaultdict(list)
    for run_json in sorted(root.glob("*/*/run-*.json")):
        if run_json.name.endswith(".grading.json"):
            continue
        record = json.loads(run_json.read_text(encoding="utf-8"))
        grading_path = run_json.with_name(run_json.stem + ".grading.json")
        grading = (json.loads(grading_path.read_text(encoding="utf-8"))
                   if grading_path.exists() else {})
        mech = record.get("mechanical") or {}
        blind_items = [e for e in grading.get("expectations", [])
                       if e.get("grader") == "blind"]
        sighted = [e for e in grading.get("expectations", [])
                   if e.get("grader") == "sighted"]
        info = grading.get("blind") or {}
        rows[record["arm"]].append({
            "case": record["case"],
            "clean": bool(mech) and mech.get("passed") == mech.get("total"),
            "blind_pass": sum(1 for e in blind_items if e.get("passed")),
            "blind_total": len(blind_items),
            "sighted_pass": sum(1 for e in sighted if e.get("passed")),
            "sighted_total": len(sighted),
            "blocking": info.get("blocking"),
            "follow": info.get("can_follow"),
            "scan": info.get("can_scan"),
            "scan_problem": info.get("scan_problem"),
        })
    return rows


def counted(rows, key):
    """(hits, misses) over replies where the measure applies."""
    usable = [r for r in rows if r.get(key) is not None]
    hits = sum(1 for r in usable if r[key])
    return hits, len(usable) - hits


def line(label, before, after):
    a_hit, a_miss = before
    b_hit, b_miss = after
    n1, n2 = a_hit + a_miss, b_hit + b_miss
    if not n1 or not n2:
        return f"| {label} | - | - | - | - |"
    r1, r2 = a_hit / n1, b_hit / n2
    p = fisher_two_tailed(a_hit, a_miss, b_hit, b_miss)
    if p > 0.05:
        verdict = "no detectable change" if abs(r2 - r1) < 1e-9 else f"directional (p={p:.2f})"
    else:
        verdict = f"**{'better' if r2 > r1 else 'WORSE'}** (p={p:.3f})"
    return (f"| {label} | {a_hit}/{n1} ({r1:.0%}) | {b_hit}/{n2} ({r2:.0%}) "
            f"| {r2 - r1:+.0%} | {verdict} |")


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--before", type=int, required=True)
    parser.add_argument("--after", type=int, required=True)
    args = parser.parse_args()

    before, after_rows = load(args.before), load(args.after)
    if not before or not after_rows:
        print("one of the iterations has no runs")
        return 1

    out = [f"# iteration {args.before} -> iteration {args.after}", ""]

    for arm in ("armed", "unarmed"):
        b_rows, a_rows = before.get(arm, []), after_rows.get(arm, [])
        if not b_rows or not a_rows:
            continue
        out += [f"## {arm}", "",
                "| measure | before | after | delta | verdict |",
                "|---|---|---|---|---|",
                line("replies with no mechanical failure", counted(b_rows, "clean"),
                     counted(a_rows, "clean")),
                line("reader could follow it", counted(b_rows, "follow"),
                     counted(a_rows, "follow")),
                line("reader could scan it", counted(b_rows, "scan"),
                     counted(a_rows, "scan")),
                line("replies with zero blocking items",
                     (sum(1 for r in b_rows if r.get("blocking") == 0),
                      sum(1 for r in b_rows if (r.get("blocking") or 0) > 0)),
                     (sum(1 for r in a_rows if r.get("blocking") == 0),
                      sum(1 for r in a_rows if (r.get("blocking") or 0) > 0))),
                line("blind assertions passed",
                     (sum(r["blind_pass"] for r in b_rows),
                      sum(r["blind_total"] - r["blind_pass"] for r in b_rows)),
                     (sum(r["blind_pass"] for r in a_rows),
                      sum(r["blind_total"] - r["blind_pass"] for r in a_rows))),
                line("sighted assertions passed (correctness)",
                     (sum(r["sighted_pass"] for r in b_rows),
                      sum(r["sighted_total"] - r["sighted_pass"] for r in b_rows)),
                     (sum(r["sighted_pass"] for r in a_rows),
                      sum(r["sighted_total"] - r["sighted_pass"] for r in a_rows))),
                ""]

    # A change that lifts BOTH arms did not improve the boundary - something else moved.
    if before.get("unarmed") and after_rows.get("unarmed"):
        out += ["The unarmed rows are the sanity check. A change that moves the armed and "
                "unarmed numbers together has not improved the boundary; something outside "
                "it moved.", ""]

    # A signpost count can only go up, so it reads an over-formatted reply as an
    # improvement. The grader's reason is the half that can say "too much".
    out += ["## Why scanning failed, when it did", ""]
    seen_any = False
    for arm in ("armed", "unarmed"):
        for label, rows in ((f"before ({arm})", before.get(arm, [])),
                            (f"after ({arm})", after_rows.get(arm, []))):
            problems = [r.get("scan_problem") for r in rows
                        if r.get("scan") is False and r.get("scan_problem")]
            if problems:
                seen_any = True
                counts = {p: problems.count(p) for p in set(problems)}
                out.append(f"- {label}: " + ", ".join(f"{v}x {k}" for k, v in counts.items()))
    if not seen_any:
        out.append("- no scanning failures reported in either iteration")
    out.append("")
    out += ["## Cases that got worse", ""]
    worse = []
    for arm in ("armed",):
        b_by = defaultdict(list)
        a_by = defaultdict(list)
        for r in before.get(arm, []):
            b_by[r["case"]].append(r)
        for r in after_rows.get(arm, []):
            a_by[r["case"]].append(r)
        for case in sorted(set(b_by) & set(a_by)):
            b_clean = sum(1 for r in b_by[case] if r["clean"])
            a_clean = sum(1 for r in a_by[case] if r["clean"])
            b_block = statistics.mean([r["blocking"] or 0 for r in b_by[case]
                                       if r.get("blocking") is not None] or [0])
            a_block = statistics.mean([r["blocking"] or 0 for r in a_by[case]
                                       if r.get("blocking") is not None] or [0])
            if a_clean < b_clean or a_block > b_block:
                worse.append(f"- `{case}`: clean runs {b_clean}->{a_clean}, "
                             f"blocking items {b_block:.1f}->{a_block:.1f}")
    out += worse or ["- none"]

    out += ["", "⚠️ Five runs per case is coarse. Read the aggregate rows above, which "
            "pool every armed reply; a per-case rate over five runs moves on noise."]

    root = WORKSPACE / f"iteration-{args.after}"
    (root / f"vs-iteration-{args.before}.md").write_text("\n".join(out) + "\n",
                                                         encoding="utf-8")
    print("\n".join(out))
    print(f"\nwrote {root / f'vs-iteration-{args.before}.md'}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
