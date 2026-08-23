# Measuring the decision-layer boundary

Two layers, because the skill has two halves that fail in different ways.

| layer | what it guards | cost | where |
|---|---|---|---|
| hook unit tests | the switch: arming, the escape hatches, the wiring between the three files | free, instant | `../tests/` |
| behavioural evals | the writing: does an armed reply obey the contract | real money, ~15 min | here |

Run the cheap one constantly. Run the expensive one when you change the rules.

## The hook tests

From the repository root:

```bash
python -m pytest tests/test_decision_layer_mode.py -v
```

No model, no network, no cost. Three of them read the **real** hook, skill and style
files rather than fixtures, to catch those three drifting apart. Do not swap them for
fixtures.

## The behavioural evals

From this directory:

```bash
python run_cases.py --runs 3 --iteration 2      # generate replies
python grade.py     --iteration 2 --arm both    # grade them
python report.py    --iteration 2               # read the result
```

⚠️ These drive live Claude sessions, so they cost real money. `--runs 1` is a smoke test
only — one run per case moves on noise.

### How a case runs

Each run is a genuine `claude -p --session-id <uuid>` subprocess. Before it starts the
harness writes the arming flag for that exact session id — the same file the hook's
`--arm` writes — so the live hook fires and the live output style engages. Nothing here
simulates the boundary, and the hook carries no test-only switch.

Every main-arm run is armed, **including** cases that expect no boundary. Those cases
test that the boundary steps *aside* — when the reader asks for code, or types `--impl`.

Each run gets a private copy of `fixtures/`. One case asks for the bug to be fixed and
the model obliges; a shared fixture would silently rewrite the input for every later run.

### The three graders

- **mechanical** (`score_mechanical.py`) — a script. Backticks, paths, call syntax, line
  references, the footer. Free and repeatable. `strict` checks score, `advisory` ones
  only report.
- **blind** (`grader.md`) — sees **only the prose above the divider**, never the code,
  the fixture or the question. This is the headline number.
- **sighted** — sees the reply and the file, and judges correctness only. It is told to
  ignore style.

⚠️ Never read the mechanical score on its own. A reply that says nothing at all scores
perfectly on it.

### Control arms

Cases marked `control_arm` also run **unarmed**. An assertion that passes armed *and*
unarmed is not measuring the boundary. `report.py` lists those automatically, along with
any assertion that never passes.

### Guards and discriminators

Cases serve one of two purposes, and they have **opposite** success conditions.

- A **discriminator** must score differently armed and unarmed. If it does not, reword it.
- A **guard** must pass *every* time. Its value is the day it stops. Never prune a guard
  for always passing.

`report.py` keeps them in separate sections. Do not merge them into one list.

### The paired experiment

`decide-python` and `decide-csharp` are word-for-word the same request about the same
bug, in a language the reader does not know and one they know well. `compare.py` shows
one grader both replies at once and asks whether either assumes more of its reader,
alternating which side leads to cancel position bias.

🔑 Never run the pair without `same-language-control`. The comparator finds *something*
between almost any two independently generated replies, so only the **ratio** means
anything:

> The guard holds while its difference rate is no worse than its control's.

`report.py` refuses to give a verdict without the control, and says so. The comparator is
a model judgement and is not perfectly reproducible, so run the guard and its control in
the same pass and treat single-digit rates as coarse.

### Results, models and cleanup

Results go to `~/.claude/state/decision-layer-evals/`, which sits outside the
`.gitignore` allowlist and never syncs.

Both graders run on the session's default model. `--sighted-model` is there if you want
to change that.

Runs leave no trace in the session history: both scripts pass
`--no-session-persistence`. `cleanup_sessions.py` clears what earlier sweeps left
behind, and is a dry run unless you pass `--delete`.

## ⚠️ Known gaps in the instrument

Left here rather than fixed silently, because each one will look like a regression next
time if you do not know about it.

1. **The blind grader is the wrong instrument for boundary-off cases.**
   `verbatim-error` reports `can_follow` 20% and `can_act` 0% — and that is correct
   behaviour being punished. The reader asked for the raw error wording; the blind
   grader is a non-programmer and truthfully cannot read a stack trace. Skip
   `can_follow`, `can_act` and the blocking count for cases whose `expect.boundary`
   is `off`.
2. **A case with no blind assertions reports 0%, not "not applicable".** `impl-escape`
   has only sighted assertions, and an empty set is being averaged as zero.
3. **The non-discriminating list is over-eager.** It flags *sighted* assertions for
   passing equally in both arms, but sighted assertions measure correctness, which the
   boundary is not supposed to change. Apply the both-arms test to blind assertions
   only.

None of these affect the armed-versus-unarmed gap, which is the number the suite exists
to produce.
