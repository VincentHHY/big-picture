"""Run the paired comparisons that guard this skill's invariants.

    python compare.py --iteration 2
    python compare.py --iteration 2 --only language-invariance

An invariant here is a GUARD, not a discriminator. It is supposed to pass every
time, and its whole value is the day it stops. Do not delete one for always
passing - see the `invariants` block in evals.json for what each guards and why.

Why a paired comparison rather than two pass rates
--------------------------------------------------
The first baseline scored decide-python and decide-csharp at 100% each over five
runs. Two independent pass rates at that sample size can only catch a large
difference, and the difference worth catching here is small: a word left
unexplained, a background sentence trimmed, a value handed over raw. So instead
of scoring the two sides separately, one grader sees BOTH replies at once and
answers a single question - does either assume more of its reader?

Position bias is handled by alternating which reply goes first, keyed on the run
index, so it is balanced and still reproducible. The grader is never told which
side is which, nor that the two differ in any way.

Only the prose above the divider is compared. The anchor block is meant to be
unreadable to this reader; including it would compare the wrong thing.
"""

import argparse
import json
import os
import re
import subprocess
import sys
from collections import Counter
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from score_mechanical import split_reply  # type: ignore[import-not-found]  # noqa: E402

EVALS_DIR = Path(__file__).resolve().parent
# Honour CLAUDE_CONFIG_DIR, as the hook does, so a relocated config directory still works.
CLAUDE_DIR = Path(os.environ.get("CLAUDE_CONFIG_DIR", "").strip()
                 or os.path.expanduser("~/.claude")).expanduser()
WORKSPACE = CLAUDE_DIR / "state" / "decision-layer-evals"

TIMEOUT_SECONDS = 600
JSON_BLOCK = re.compile(r"\{.*\}", re.S)


def comparator_brief():
    text = (EVALS_DIR / "grader.md").read_text(encoding="utf-8")
    for part in re.split(r"^## Role: ", text, flags=re.M)[1:]:
        if part.startswith("comparator"):
            return part.split("\n---")[0]
    raise ValueError("no 'comparator' role in grader.md")


def ask(prompt):
    env = {k: v for k, v in os.environ.items() if k != "CLAUDECODE"}
    env["PYTHONIOENCODING"] = "utf-8"
    completed = subprocess.run(
        ["claude", "-p", "--no-session-persistence", "--output-format", "json",
         "--disallowedTools", "Read", "Grep", "Glob", "Bash", "Task", "WebFetch"],
        input=prompt.encode("utf-8"), capture_output=True,
        cwd=str(CLAUDE_DIR), env=env, timeout=TIMEOUT_SECONDS)
    raw = completed.stdout.decode("utf-8", errors="replace")
    if not raw.strip():
        raise ValueError("claude printed nothing: "
                         + completed.stderr.decode("utf-8", errors="replace")[:300])
    payload = json.loads(raw)
    body = payload.get("result") or ""
    match = JSON_BLOCK.search(body)
    if not match:
        raise ValueError(f"comparator returned no JSON: {body[:300]}")
    return json.loads(match.group(0)), payload.get("total_cost_usd") or 0.0


def compare_one(invariant, root, index, run_count):
    """One run of side A against side B.

    When a and b name the SAME case this is a control pair: run N against run N+1 of
    that one case. Two independently generated replies always differ a little, and a
    grader asked "does either assume more?" will find something if it looks hard
    enough. The control measures that floor. A cross-language difference only counts
    as real if it beats it.
    """
    arm = invariant.get("arm", "armed")
    offset = invariant.get("b_run_offset", 0)
    index_b = (index - 1 + offset) % run_count + 1 if offset else index
    path_a = root / invariant["a"] / arm / f"run-{index}.md"
    path_b = root / invariant["b"] / arm / f"run-{index_b}.md"
    result = {"invariant": invariant["name"], "run": index, "run_b": index_b,
              "a": invariant["a"], "b": invariant["b"],
              "is_control": invariant["a"] == invariant["b"], "cost_usd": 0.0}
    if not (path_a.exists() and path_b.exists()):
        result["error"] = "one side has no reply for this run"
        return result

    prose_a = split_reply(path_a.read_text(encoding="utf-8"))[0]
    prose_b = split_reply(path_b.read_text(encoding="utf-8"))[0]

    # Alternate which side leads, so position bias cancels across runs instead of
    # loading onto whichever case happens to be named first.
    a_leads = index % 2 == 1
    first, second = (prose_a, prose_b) if a_leads else (prose_b, prose_a)
    result["a_shown_first"] = a_leads

    prompt = (f"{comparator_brief()}\n\n"
              f"--- FIRST REPLY ---\n{first}\n--- END FIRST REPLY ---\n\n"
              f"--- SECOND REPLY ---\n{second}\n--- END SECOND REPLY ---\n")
    try:
        verdict, cost = ask(prompt)
        result["cost_usd"] = cost
        raw = str(verdict.get("verdict", "")).lower()
        # Translate the grader's positional answer back to the named sides.
        if raw == "no_difference":
            result["verdict"] = "no_difference"
        elif raw == "first_assumes_more":
            result["verdict"] = ("run-%d" % (index if a_leads else index_b)
                                 if result["is_control"]
                                 else (invariant["a"] if a_leads else invariant["b"]))
        elif raw == "second_assumes_more":
            result["verdict"] = ("run-%d" % (index_b if a_leads else index)
                                 if result["is_control"]
                                 else (invariant["b"] if a_leads else invariant["a"]))
        else:
            result["verdict"] = f"unparsed: {raw}"
        result["evidence"] = verdict.get("evidence", "")
        result["confidence"] = verdict.get("confidence", "")
    except Exception as error:
        result["error"] = f"{type(error).__name__}: {error}"
    return result


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--iteration", type=int, default=2)
    parser.add_argument("--only", default="")
    parser.add_argument("--concurrency", type=int, default=3)
    args = parser.parse_args()

    spec = json.loads((EVALS_DIR / "evals.json").read_text(encoding="utf-8"))
    invariants = spec.get("invariants", [])
    if args.only:
        wanted = {n.strip() for n in args.only.split(",")}
        invariants = [i for i in invariants if i["name"] in wanted]
    if not invariants:
        print("no invariants to compare")
        return 1

    root = WORKSPACE / f"iteration-{args.iteration}"
    jobs = []
    for invariant in invariants:
        arm = invariant.get("arm", "armed")
        runs = sorted((root / invariant["a"] / arm).glob("run-*.md"))
        for path in runs:
            if path.name.endswith(".grading.json"):
                continue
            index = int(path.stem.split("-")[1])
            jobs.append((invariant, root, index, len(runs)))

    if not jobs:
        print(f"no replies under {root} to compare")
        return 1
    print(f"comparing {len(jobs)} pair(s), {args.concurrency} at a time")

    results = []
    with ThreadPoolExecutor(max_workers=args.concurrency) as pool:
        futures = [pool.submit(compare_one, *job) for job in jobs]
        for future in as_completed(futures):
            result = future.result()
            results.append(result)
            print(f"  {result['invariant']} #{result['run']}: "
                  f"{result.get('verdict', result.get('error'))} "
                  f"({result.get('confidence', '')})")

    # Merge, do not replace. Running with --only must not wipe the other
    # invariant's results - and a guard is worthless if its control is missing.
    out = root / "invariants.json"
    merged = {}
    if out.exists():
        try:
            for old in json.loads(out.read_text(encoding="utf-8")):
                merged[(old["invariant"], old["run"])] = old
        except Exception:
            pass
    for entry in results:
        merged[(entry["invariant"], entry["run"])] = entry
    out.write_text(json.dumps([merged[k] for k in sorted(merged)], indent=2),
                   encoding="utf-8")

    print()
    for invariant in invariants:
        mine = [r for r in results if r["invariant"] == invariant["name"]]
        tally = Counter(r.get("verdict") for r in mine if r.get("verdict"))
        held = tally.get("no_difference", 0)
        print(f"{invariant['name']}: {held}/{len(mine)} runs found no difference")
        for verdict, count in tally.most_common():
            if verdict != "no_difference":
                print(f"  ⚠ {count} run(s) said {verdict} assumes more of its reader")
        if held != len(mine):
            print(f"  the invariant it guards: {invariant['holds']}")
    print(f"\nwrote {out}")
    print(f"comparison cost: ${sum(r.get('cost_usd', 0) for r in results):.2f}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
