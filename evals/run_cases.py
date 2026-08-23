"""Run the decision-layer eval cases as real, armed Claude Code sessions.

    python run_cases.py --runs 3
    python run_cases.py --runs 1 --only decide-python,decide-csharp
    python run_cases.py --runs 3 --iteration 2

Each run is a genuine `claude -p --session-id <uuid>` subprocess. Before it starts
we write the arming flag for that exact session id - the same file the hook's
--arm writes - so the LIVE hook fires and the LIVE output style engages. Nothing
here simulates the boundary, and no test-only switch was added to the hook to
make this possible.

That matters: the thing most likely to break is the wiring between the settings,
the style and the hook, and a harness that injected the rules by hand would be
blind to exactly that.

EVERY main-arm run is armed, including the cases whose expect.boundary is "off".
That is deliberate. Those cases test that the boundary steps ASIDE correctly - when
the reader asks for code, or types --impl - and a session that was never armed in the
first place would prove nothing about stepping aside. expect.boundary governs how the
reply is scored, not whether the flag is written.

Cases marked control_arm additionally run unarmed, giving a falsification arm: an
assertion that passes armed AND unarmed is not measuring the boundary.

Results land in ~/.claude/state/decision-layer-evals/iteration-<n>/, which is
outside the .gitignore allowlist and so never syncs.
"""

import argparse
import json
import os
import shutil
import subprocess
import sys
import uuid
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from score_mechanical import score  # type: ignore[import-not-found]  # noqa: E402  sibling module, path fixed above

EVALS_DIR = Path(__file__).resolve().parent
# Honour CLAUDE_CONFIG_DIR, as the hook does, so a relocated config directory still works.
CLAUDE_DIR = Path(os.environ.get("CLAUDE_CONFIG_DIR", "").strip()
                 or os.path.expanduser("~/.claude")).expanduser()
STATE_DIR = CLAUDE_DIR / "state"
WORKSPACE = STATE_DIR / "decision-layer-evals"
FIXTURES = EVALS_DIR / "fixtures"

TIMEOUT_SECONDS = 900


def load_evals():
    return json.loads((EVALS_DIR / "evals.json").read_text(encoding="utf-8"))


def run_one(case, armed, index, iteration):
    """One real session. Returns a record; never raises, so one bad run cannot end the sweep."""
    session_id = str(uuid.uuid4())
    flag = STATE_DIR / f"decision-layer-{session_id}"
    arm_name = "armed" if armed else "unarmed"
    out_dir = WORKSPACE / f"iteration-{iteration}" / case["name"] / arm_name
    out_dir.mkdir(parents=True, exist_ok=True)

    record = {
        "case": case["name"],
        "case_id": case["id"],
        "arm": arm_name,
        "run": index,
        "session_id": session_id,
        "ok": False,
    }

    # A private copy of the fixtures for this run alone. One case deliberately asks for
    # the bug to be fixed, and the model obliges - against a shared fixture that rewrites
    # the input every later run depends on, and the contamination is invisible in the
    # results. Isolating costs a directory copy and removes the whole failure class.
    sandbox = out_dir / f"run-{index}-fixtures"
    if sandbox.exists():
        shutil.rmtree(sandbox, ignore_errors=True)
    shutil.copytree(FIXTURES, sandbox)
    prompt = case["prompt"].replace("{FIXTURES}", str(sandbox).replace("\\", "/"))
    record["prompt"] = prompt

    try:
        STATE_DIR.mkdir(parents=True, exist_ok=True)
        if armed:
            flag.write_text("", encoding="utf-8")

        env = {k: v for k, v in os.environ.items() if k != "CLAUDECODE"}
        env["PYTHONIOENCODING"] = "utf-8"

        # The prompt goes in on stdin, not argv. One case's prompt begins with
        # "--impl", and an argument parser reads that as an unknown flag and refuses
        # to start - which is exactly the case that tests the escape hatch.
        #
        # --no-session-persistence keeps these throwaway runs out of the real session
        # history. A sweep is 45 sessions and they would otherwise bury the user's own.
        completed = subprocess.run(
            [
                "claude", "-p",
                "--session-id", session_id,
                "--no-session-persistence",
                "--output-format", "json",
            ],
            input=prompt.encode("utf-8"),
            capture_output=True,
            cwd=str(CLAUDE_DIR),
            env=env,
            timeout=TIMEOUT_SECONDS,
        )
        raw = completed.stdout.decode("utf-8", errors="replace")
        if not raw.strip():
            raise ValueError("claude printed nothing: "
                             + completed.stderr.decode("utf-8", errors="replace")[:300])
        payload = json.loads(raw)
        reply = payload.get("result") or ""
        record["ok"] = not payload.get("is_error") and bool(reply.strip())
        record["cost_usd"] = payload.get("total_cost_usd")
        record["duration_ms"] = payload.get("duration_ms")
        record["denials"] = payload.get("permission_denials")
    except subprocess.TimeoutExpired:
        reply = ""
        record["error"] = f"timed out after {TIMEOUT_SECONDS}s"
    except Exception as error:
        reply = ""
        record["error"] = f"{type(error).__name__}: {error}"
    finally:
        if flag.exists():
            flag.unlink()

    (out_dir / f"run-{index}.md").write_text(reply, encoding="utf-8")

    # An unarmed control is scored against the SAME expectation as its armed twin.
    # That is the whole point: if it passes too, the check proves nothing.
    boundary = case.get("expect", {}).get("boundary", "on")
    record["mechanical"] = score(reply, boundary) if reply.strip() else None
    (out_dir / f"run-{index}.json").write_text(
        json.dumps(record, indent=2), encoding="utf-8")
    return record


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--runs", type=int, default=5,
                        help="runs per case per arm. Three samples can only ever read 0, 33, 67 or 100 per cent, which is too coarse to see a real change; five gives usable resolution. Use 1 only as a smoke test.")
    parser.add_argument("--start-index", type=int, default=1,
                        help="first run number to write. Use it to top an existing iteration "
                             "up to more samples without discarding the ones already there.")
    parser.add_argument("--only", default="", help="comma-separated case names")
    parser.add_argument("--iteration", type=int, default=1)
    parser.add_argument("--concurrency", type=int, default=4)
    args = parser.parse_args()

    spec = load_evals()
    cases = spec["evals"]
    if args.only:
        wanted = {name.strip() for name in args.only.split(",")}
        cases = [c for c in cases if c["name"] in wanted]
        missing = wanted - {c["name"] for c in cases}
        if missing:
            print(f"no such case: {', '.join(sorted(missing))}")
            return 1

    jobs = []
    for case in cases:
        for index in range(args.start_index, args.start_index + args.runs):
            jobs.append((case, True, index))
            if case.get("control_arm"):
                jobs.append((case, False, index))

    print(f"iteration {args.iteration}: {len(cases)} cases, {len(jobs)} sessions, "
          f"{args.concurrency} at a time")

    records = []
    with ThreadPoolExecutor(max_workers=args.concurrency) as pool:
        futures = {
            pool.submit(run_one, case, armed, index, args.iteration): (case["name"], armed, index)
            for case, armed, index in jobs
        }
        for future in as_completed(futures):
            name, armed, index = futures[future]
            record = future.result()
            records.append(record)
            mech = record.get("mechanical")
            state = "FAILED" if not record["ok"] else (
                f"{mech['passed']}/{mech['total']}" if mech else "empty")
            print(f"  {'armed  ' if armed else 'unarmed'} {name} #{index}: {state}"
                  + (f"  ({record['error']})" if record.get("error") else ""))

    # Merge, do not overwrite. With --start-index a partial batch is normal, and a
    # summary that silently replaced the earlier runs would claim to be the whole
    # iteration while holding a slice of it. Keyed so a redone run replaces its twin.
    summary_path = WORKSPACE / f"iteration-{args.iteration}" / "runs.json"
    merged = {}
    if summary_path.exists():
        try:
            for old in json.loads(summary_path.read_text(encoding="utf-8")):
                merged[(old["case"], old["arm"], old["run"])] = old
        except Exception:
            pass
    for record in records:
        merged[(record["case"], record["arm"], record["run"])] = record
    summary_path.write_text(
        json.dumps([merged[key] for key in sorted(merged)], indent=2), encoding="utf-8")

    cost = sum(r.get("cost_usd") or 0 for r in records)
    failed = [r for r in records if not r["ok"]]
    print(f"\nwrote {summary_path}")
    print(f"total cost: ${cost:.2f}   failed sessions: {len(failed)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
