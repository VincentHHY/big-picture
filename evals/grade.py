"""Grade the replies produced by run_cases.py.

    python grade.py --iteration 1
    python grade.py --iteration 1 --only decide-python

Two graders, each its own `claude -p` session, deliberately kept apart:

  blind    Sees ONLY the reply. No code, no fixture, no original prompt. This is
           the reader's real situation and it is the headline number. It cannot be
           gamed from either end: leak detail and the grader hits tokens it cannot
           resolve, go vague to avoid leaking and the grader cannot decide.
  sighted  Sees the reply and the fixture, and judges correctness alone. It exists
           so a plain, fluent, confidently wrong reply cannot score well.

Style is graded once, by the blind grader and the mechanical scorer. The sighted
grader is told to ignore it, because double-counting style would let a pretty
wrong answer average out to a pass.

Writes grading.json next to each reply, in the shape the skill-creator eval viewer
expects (expectations[] of text / passed / evidence).
"""

import argparse
import json
import os
import re
import subprocess
import sys
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from score_mechanical import split_reply  # type: ignore[import-not-found]  # noqa: E402

EVALS_DIR = Path(__file__).resolve().parent
# Honour CLAUDE_CONFIG_DIR, as the hook does, so a relocated config directory still works.
CLAUDE_DIR = Path(os.environ.get("CLAUDE_CONFIG_DIR", "").strip()
                 or os.path.expanduser("~/.claude")).expanduser()
WORKSPACE = CLAUDE_DIR / "state" / "decision-layer-evals"
FIXTURES = EVALS_DIR / "fixtures"

TIMEOUT_SECONDS = 600
JSON_BLOCK = re.compile(r"\{.*\}", re.S)


def grader_section(role):
    """One role's half of grader.md, so a grader never reads the other's brief."""
    text = (EVALS_DIR / "grader.md").read_text(encoding="utf-8")
    parts = re.split(r"^## Role: ", text, flags=re.M)
    for part in parts[1:]:
        if part.startswith(role):
            return part.split("\n---")[0]
    raise ValueError(f"no '{role}' role in grader.md")


def ask(prompt, allow_read, model=""):
    env = {k: v for k, v in os.environ.items() if k != "CLAUDECODE"}
    env["PYTHONIOENCODING"] = "utf-8"
    # Prompt on stdin, never argv: a grader brief is long and may begin with anything.
    # --no-session-persistence keeps graders out of the real session history too; a
    # full grading pass is another 90 sessions.
    command = ["claude", "-p", "--no-session-persistence", "--output-format", "json"]
    if model:
        command += ["--model", model]
    if allow_read:
        command += ["--allowedTools", "Read"]
    else:
        # A blind grader that can reach the filesystem is not blind. Block the lot
        # rather than merely leaving them unmentioned.
        command += ["--disallowedTools", "Read", "Grep", "Glob", "Bash", "Task", "WebFetch"]
    completed = subprocess.run(command, input=prompt.encode("utf-8"),
                               capture_output=True, cwd=str(CLAUDE_DIR),
                               env=env, timeout=TIMEOUT_SECONDS)
    raw = completed.stdout.decode("utf-8", errors="replace")
    if not raw.strip():
        raise ValueError("claude printed nothing: "
                         + completed.stderr.decode("utf-8", errors="replace")[:300])
    payload = json.loads(raw)
    body = payload.get("result") or ""
    match = JSON_BLOCK.search(body)
    if not match:
        raise ValueError(f"grader returned no JSON: {body[:300]}")
    return json.loads(match.group(0)), payload.get("total_cost_usd") or 0.0


def fixture_for(case, reply_path):
    """The exact copy this run saw, not the pristine original.

    Each run works on its own copy, and one case asks for the bug to be fixed. Judging
    "would this actually fix it" against the untouched original would be judging a
    different file from the one the reply is about.
    """
    found = re.findall(r"\{FIXTURES\}/([\w.\-]+)", case["prompt"])
    if not found:
        return None
    sandbox = reply_path.parent / f"{reply_path.stem}-fixtures" / found[0]
    return sandbox if sandbox.exists() else FIXTURES / found[0]


def grade_reply(case, reply_path, blind_texts, sighted_texts, sighted_model=""):
    reply = reply_path.read_text(encoding="utf-8")
    result = {"case": case["name"], "reply": str(reply_path), "cost_usd": 0.0,
              "expectations": [], "blind": {}}
    if not reply.strip():
        result["error"] = "empty reply"
        return result

    if blind_texts:
        # Show the blind grader the PROSE ONLY. The anchor block below the divider is
        # meant to be unreadable to this reader - that is what the divider is for - so
        # including it would penalise every reply that gets the contract right. The
        # contract's claim is that the prose stands alone, and that is what we test.
        prose, anchors, _ = split_reply(reply)
        prompt = (
            f"{grader_section('blind')}\n\n"
            f"The assertions to judge:\n"
            + "\n".join(f"- {t}" for t in blind_texts)
            + "\n\nNote: if the reply carried a block of technical pointers below a divider,"
              " it has been withheld from you on purpose. Judge only what is here. Do not"
              " mark anything down for being absent.\n"
            + f"\n--- THE REPLY ---\n{prose}\n--- END OF REPLY ---\n"
        )
        result["had_anchor_block"] = bool(anchors.strip())
        try:
            verdict, cost = ask(prompt, allow_read=False)
            result["cost_usd"] += cost
            result["blind"] = {
                "can_follow": verdict.get("can_follow"),
                "can_act": verdict.get("can_act"),
                "can_scan": verdict.get("can_scan"),
                "scan_problem": verdict.get("scan_problem"),
                "unusable": verdict.get("unusable", []),
                "blocking": sum(1 for u in verdict.get("unusable", [])
                                if isinstance(u, dict) and u.get("blocking")),
                "one_line_summary": verdict.get("one_line_summary", ""),
            }
            for item in verdict.get("expectations", []):
                result["expectations"].append({**item, "grader": "blind"})
        except Exception as error:
            result["blind_error"] = f"{type(error).__name__}: {error}"

    if sighted_texts:
        fixture = fixture_for(case, reply_path)
        prompt = (
            f"{grader_section('sighted')}\n\n"
            f"The assertions to judge:\n"
            + "\n".join(f"- {t}" for t in sighted_texts)
            + (f"\n\nRead the file it is about: {fixture}\n" if fixture else "\n")
            + f"\n--- THE REPLY ---\n{reply}\n--- END OF REPLY ---\n"
        )
        try:
            verdict, cost = ask(prompt, allow_read=True, model=sighted_model)
            result["cost_usd"] += cost
            for item in verdict.get("expectations", []):
                result["expectations"].append({**item, "grader": "sighted"})
        except Exception as error:
            result["sighted_error"] = f"{type(error).__name__}: {error}"

    return result


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--iteration", type=int, default=1)
    parser.add_argument("--only", default="")
    parser.add_argument("--concurrency", type=int, default=4)
    parser.add_argument("--arm", default="armed", choices=["armed", "unarmed", "both"])
    parser.add_argument("--regrade", action="store_true",
                        help="re-grade replies that already have a grading file. Off by "
                             "default so an interrupted pass resumes instead of paying "
                             "for the whole thing again.")
    parser.add_argument("--sighted-model", default="",
                        help="override the sighted grader's model. Empty means inherit the "
                             "session default, which is what you want: this suite exists to "
                             "produce a number worth trusting, and a cheaper fact-checker "
                             "trades measurement quality for money. Both graders run on the "
                             "default tier unless you deliberately say otherwise.")
    args = parser.parse_args()

    spec = json.loads((EVALS_DIR / "evals.json").read_text(encoding="utf-8"))
    common = spec.get("common_assertions", [])
    root = WORKSPACE / f"iteration-{args.iteration}"
    if not root.exists():
        print(f"no results at {root} - run run_cases.py first")
        return 1

    wanted = {n.strip() for n in args.only.split(",")} if args.only else None
    arms = ["armed", "unarmed"] if args.arm == "both" else [args.arm]

    jobs = []
    for case in spec["evals"]:
        if wanted and case["name"] not in wanted:
            continue
        assertions = common + case["assertions"] if case.get("expect", {}).get(
            "boundary", "on") == "on" else case["assertions"]
        blind = [a["text"] for a in assertions if a["grader"] == "blind"]
        sighted = [a["text"] for a in assertions if a["grader"] == "sighted"]
        for arm in arms:
            for reply_path in sorted((root / case["name"] / arm).glob("run-*.md")):
                # Each grading file is written the moment its reply is judged, so an
                # interrupted pass has already banked everything it finished.
                #
                # But a file is written even when the grader FAILED - a rate limit
                # returns prose instead of JSON - and skipping on existence alone would
                # bank the failure and never retry it. A run that hit a weekly limit
                # part way through reported exit 0 with 60% of its verdicts missing.
                # So a file only counts as done if it actually holds verdicts.
                done = reply_path.with_name(reply_path.stem + ".grading.json")
                if done.exists() and not args.regrade:
                    try:
                        prior = json.loads(done.read_text(encoding="utf-8"))
                    except Exception:
                        prior = {}
                    failed = prior.get("blind_error") or prior.get("sighted_error")
                    if prior.get("expectations") and not failed:
                        continue
                jobs.append((case, reply_path, blind, sighted))

    if not jobs:
        print("Nothing left to grade - every reply already has a grading file.")
        print("Use --regrade to judge them again from scratch.")
        return 0
    print(f"grading {len(jobs)} replies, {args.concurrency} at a time")

    results = []
    with ThreadPoolExecutor(max_workers=args.concurrency) as pool:
        futures = {pool.submit(grade_reply, *job, args.sighted_model): job[1] for job in jobs}
        for future in as_completed(futures):
            result = future.result()
            results.append(result)
            path = Path(result["reply"])
            path.with_name(path.stem + ".grading.json").write_text(
                json.dumps(result, indent=2), encoding="utf-8")
            blind = result.get("blind", {})
            passed = sum(1 for e in result["expectations"] if e.get("passed"))
            print(f"  {path.parent.parent.name}/{path.parent.name}/{path.stem}: "
                  f"{passed}/{len(result['expectations'])} "
                  f"follow={blind.get('can_follow')} act={blind.get('can_act')} blocking={blind.get('blocking')}")

    # Rebuild the aggregate from every grading file on disk, not just this pass's
    # results, so resuming after an interruption does not silently drop the first half.
    out = root / "grading.json"
    everything = []
    for path in sorted(root.glob("*/*/run-*.grading.json")):
        try:
            everything.append(json.loads(path.read_text(encoding="utf-8")))
        except Exception:
            continue
    out.write_text(json.dumps(everything, indent=2), encoding="utf-8")
    print(f"\nwrote {out}")
    print(f"grading cost: ${sum(r.get('cost_usd', 0) for r in results):.2f}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
