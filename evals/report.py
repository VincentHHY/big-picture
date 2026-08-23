"""Turn one iteration's runs and grades into a readable baseline.

    python report.py --iteration 1

Three things it is built to surface, because the aggregate pass rate hides all of them:

  the gap        Armed against unarmed on the same case. A number that is high in both
                 arms is not measuring the boundary.
  guards         Invariants that must hold every time, reported separately from the
                 discriminators. A guard passing always is the correct outcome, NOT a
                 reason to prune it - which is what a flat "non-discriminating" list
                 would eventually invite someone to do.
  bad wording    A blind assertion that scores the same in both arms, or never passes,
                 is measuring its own wording rather than the skill. Sighted assertions
                 are exempt: correctness is not supposed to change with the boundary.

Cases whose boundary is expected to be off report the reader-facing columns as n/a.
There the blind grader is the wrong instrument - the reader ASKED for the raw wording,
so a non-programmer truthfully saying they cannot read a stack trace is the case
working, not failing.
"""

import argparse
import json
import statistics
from collections import defaultdict
from pathlib import Path
import os

# Honour CLAUDE_CONFIG_DIR, as the hook does, so a relocated config directory still works.
CLAUDE_DIR = Path(os.environ.get("CLAUDE_CONFIG_DIR", "").strip()
                 or os.path.expanduser("~/.claude")).expanduser()
WORKSPACE = CLAUDE_DIR / "state" / "decision-layer-evals"
EVALS_DIR = Path(__file__).resolve().parent


def mean(values):
    return statistics.mean(values) if values else 0.0


def collect(root):
    """Everything for one iteration, keyed by (case, arm)."""
    runs = defaultdict(list)
    for run_json in sorted(root.glob("*/*/run-*.json")):
        # run-1.grading.json also matches that glob, and it is a different shape.
        if run_json.name.endswith(".grading.json"):
            continue
        record = json.loads(run_json.read_text(encoding="utf-8"))
        grading_path = run_json.with_name(run_json.stem + ".grading.json")
        record["grading"] = (
            json.loads(grading_path.read_text(encoding="utf-8"))
            if grading_path.exists() else None
        )
        runs[(record["case"], record["arm"])].append(record)
    return runs


def assertion_table(runs):
    """pass rate per assertion per arm, so non-discriminating ones stand out."""
    table = defaultdict(lambda: defaultdict(list))
    for (case, arm), records in runs.items():
        for record in records:
            grading = record.get("grading") or {}
            for item in grading.get("expectations", []):
                table[(case, item["text"], item.get("grader", "?"))][arm].append(
                    bool(item.get("passed")))
    return table


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--iteration", type=int, default=1)
    args = parser.parse_args()

    root = WORKSPACE / f"iteration-{args.iteration}"
    runs = collect(root)
    if not runs:
        print(f"nothing at {root}")
        return 1

    spec = json.loads((EVALS_DIR / "evals.json").read_text(encoding="utf-8"))
    order = [c["name"] for c in spec["evals"]]
    expects = {c["name"]: c.get("expect", {}).get("boundary", "on") for c in spec["evals"]}

    lines = [f"# decision-layer baseline - iteration {args.iteration}", ""]

    lines += ["## Per case", "",
              "| case | boundary | arm | runs | mechanical | blind assertions | blocking | follow | act |",
              "|---|---|---|---|---|---|---|---|---|"]
    for case in order:
        for arm in ("armed", "unarmed"):
            records = runs.get((case, arm))
            if not records:
                continue
            mech = [r["mechanical"]["pass_rate"] for r in records if r.get("mechanical")]
            blind_rates, blocking, follow, act = [], [], [], []
            for record in records:
                grading = record.get("grading") or {}
                items = [e for e in grading.get("expectations", [])
                         if e.get("grader") == "blind"]
                if items:
                    blind_rates.append(sum(1 for e in items if e.get("passed")) / len(items))
                info = grading.get("blind") or {}
                if info:
                    blocking.append(info.get("blocking") or 0)
                    follow.append(bool(info.get("can_follow")))
                    act.append(bool(info.get("can_act")))
            # Where the boundary is meant to step aside, the blind grader is the
            # wrong instrument: the reader ASKED for the raw wording, so a
            # non-programmer truthfully reporting they cannot read a stack trace is
            # correct behaviour, not a failure. Scoring it would punish the very thing
            # the case exists to check.
            boundary = expects.get(case, "on")
            def cell(values, fmt="{:.0%}"):
                return fmt.format(mean(values)) if values else "-"
            reader_cells = (
                (cell(blocking, "{:.1f}"),
                 cell([1 if f else 0 for f in follow]),
                 cell([1 if a else 0 for a in act]))
                if boundary == "on" else ("n/a", "n/a", "n/a"))
            lines.append(
                f"| {case} | {boundary} | {arm} | {len(records)} "
                f"| {cell(mech)} | {cell(blind_rates)} | "
                + " | ".join(reader_cells) + " |")

    lines += ["", "## Invariant guards", "",
              "These are GUARDS, not discriminators. Passing every time is the correct "
              "outcome and is never a reason to remove one - the value is the day a guard "
              "stops passing.", ""]
    invariants = spec.get("invariants", [])
    paired = {}
    paired_path = root / "invariants.json"
    if paired_path.exists():
        for entry in json.loads(paired_path.read_text(encoding="utf-8")):
            paired.setdefault(entry["invariant"], []).append(entry)
    for invariant in invariants:
        # A control pair is calibration, not a guard. Giving it a holds/fails verdict
        # of its own would be nonsense: it is the measuring stick, and it is SUPPOSED
        # to find differences.
        is_control = invariant["a"] == invariant["b"]
        lines.append(f"### {invariant['name']}"
                     + ("  _(calibration, not a guard)_" if is_control else ""))
        lines.append("")
        lines.append(f"{invariant['holds']}")
        lines.append("")
        if is_control:
            entries = paired.get(invariant["name"], [])
            if entries:
                differed = [e for e in entries
                            if e.get("verdict") not in ("no_difference", None)]
                lines.append(f"Noise floor: {len(differed)}/{len(entries)} runs found a "
                             "difference between two replies to the *same* request. Any "
                             "guard that does not beat this rate is inside the noise.")
                lines.append("")
            continue
        for case in (invariant["a"], invariant["b"]):
            records = runs.get((case, invariant.get("arm", "armed")), [])
            mech = [r["mechanical"]["pass_rate"] for r in records if r.get("mechanical")]
            blocking = [(r.get("grading") or {}).get("blind", {}).get("blocking") or 0
                        for r in records if r.get("grading")]
            lines.append(f"- **{case}**: mechanical {mean(mech):.0%}, blocking items "
                         f"{mean(blocking):.1f} over {len(records)} runs")
        entries = paired.get(invariant["name"], [])
        if not entries:
            lines.append("")
            lines.append("_No paired comparison recorded. Run `python compare.py "
                         f"--iteration {args.iteration}` - two separate pass rates at this "
                         "sample size only catch a large difference._")
            lines.append("")
            continue

        differed = [e for e in entries if e.get("verdict") not in ("no_difference", None)]
        lines.append("")
        lines.append(f"**Paired comparison: {len(differed)}/{len(entries)} runs found a "
                     "difference in what is assumed of the reader.**")

        # A paired comparison read against zero is worthless. The comparator finds
        # SOMETHING between almost any two independently generated replies, so the only
        # meaningful question is whether this pair differs more than one case differs
        # from itself. Without the control, a noise floor reads as a regression.
        control_name = invariant.get("control")
        control = paired.get(control_name, []) if control_name else []
        if control:
            control_differed = [e for e in control
                                if e.get("verdict") not in ("no_difference", None)]
            rate, control_rate = len(differed) / len(entries), len(control_differed) / len(control)
            holds = rate <= control_rate
            lines.append(f"Control (`{control_name}`, the same case against itself): "
                         f"{len(control_differed)}/{len(control)} runs found a difference.")
            lines.append("")
            lines.append(f"{'✅ **HOLDS**' if holds else '⚠️ **DOES NOT HOLD**'} — "
                         + (f"the pair differs no more than one case differs from itself "
                            f"({rate:.0%} against {control_rate:.0%}), so any language "
                            f"effect is inside the noise."
                            if holds else
                            f"the pair differs MORE than one case differs from itself "
                            f"({rate:.0%} against {control_rate:.0%}). Investigate."))
        elif control_name:
            lines.append("")
            lines.append(f"⚠️ **Unreadable without its control.** Run `--only "
                         f"{control_name}`. Read against zero this looks like a failure, "
                         "but the comparator finds a difference between almost any two "
                         "replies; only the pair-versus-control ratio means anything.")

        for entry in differed:
            lines.append(f"  - run {entry['run']}: {entry['verdict']} assumes more "
                         f"({entry.get('confidence','')}) - "
                         f"{str(entry.get('evidence',''))[:180]}")
        lines.append("")

    # Only BLIND assertions are expected to discriminate. Sighted ones measure
    # correctness, which the boundary is not supposed to change, so flagging them for
    # scoring the same in both arms is noise that buries the real signal. And an
    # assertion that always passes with no control arm is unproven, not broken - it
    # goes on a watch list, not a defect list.
    lines += ["", "## Assertions worth rewording", "",
              "Blind assertions only. A sighted assertion scoring the same in both arms "
              "is correct: correctness does not depend on the boundary.", ""]
    flagged, watch = [], []
    for (case, text, grader), arms in sorted(assertion_table(runs).items()):
        if grader != "blind":
            continue
        armed = arms.get("armed", [])
        unarmed = arms.get("unarmed", [])
        if armed and unarmed and mean(armed) == mean(unarmed):
            flagged.append(f"- `{case}`: **scores the same in both arms** "
                           f"({mean(armed):.0%}) - measures something other than the "
                           f"boundary - {text}")
        elif armed and mean(armed) == 0.0:
            flagged.append(f"- `{case}`: **never passes** - usually the wording, not the "
                           f"skill - {text}")
        elif armed and not unarmed and mean(armed) == 1.0:
            watch.append(f"- `{case}`: always passes, but has no control arm to prove it "
                         f"discriminates - {text}")
    lines += flagged or ["- none"]
    if watch:
        lines += ["", "### Unproven, not broken", "",
                  "No control arm, so we cannot tell a real check from one that would "
                  "pass anyway. Add a control arm before trusting or deleting these.", ""]
        lines += watch

    lines += ["", "## Mechanical checks that failed, with evidence", ""]
    seen = set()
    for (case, arm), records in sorted(runs.items()):
        if arm != "armed":
            continue
        for record in records:
            for check in (record.get("mechanical") or {}).get("checks", []):
                if check["passed"] or not check["evidence"]:
                    continue
                key = (case, check["text"])
                if key in seen:
                    continue
                seen.add(key)
                lines.append(f"- `{case}` - {check['text']}: {check['evidence'][:200]}")
    if not seen:
        lines.append("- none")

    failures = [r for records in runs.values() for r in records if not r.get("ok")]
    if failures:
        lines += ["", "## Sessions that did not complete", ""]
        for record in failures:
            lines.append(f"- {record['case']} / {record['arm']} #{record['run']}: "
                         f"{record.get('error', 'unknown')}")

    cost = sum(r.get("cost_usd") or 0 for records in runs.values() for r in records)
    grading_cost = sum((r.get("grading") or {}).get("cost_usd") or 0
                       for records in runs.values() for r in records)
    lines += ["", f"Run cost ${cost:.2f}, grading cost ${grading_cost:.2f}."]

    out = root / "report.md"
    out.write_text("\n".join(lines) + "\n", encoding="utf-8")
    print("\n".join(lines))
    print(f"\nwrote {out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
