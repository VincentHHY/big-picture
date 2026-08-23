# decision-layer

Answers you can judge and decide on without reading code. Off by default, armed for one
session at a time with `/decision-layer`.

This file is for you, not for the model. `SKILL.md` is loaded into the prompt when the
skill is invoked, so anything that lives there costs tokens on every use - keep it to what
the model needs. Explanations for the human belong here.

- `SKILL.md` - what the model reads. The arming mechanics and a summary of the rules.
- `../../output-styles/decision-layer.md` - the rules themselves, in the system prompt.
- `evals/` at the root of this repository - the measurement suite and its operating
  manual. Not shipped inside the plugin: it is developer material, and it costs real
  money to run because it drives live Claude sessions.
- `tests/` at the root of this repository - the hook's unit tests. Free and fast; run
  them after any change to the hook.

## How to tell whether it is on

**The footer is the indicator.** Every armed reply ends with a line reading
`▪ decision-layer`.

- **Footer present** - the boundary applied to that reply.
- **No footer** - it did not. Either the session was never armed, `--impl` suppressed it
  for that one turn, something disarmed it, or the reply was a plain request for code where
  the boundary steps aside by design.

Since every session starts off, the footer on the first reply after `/decision-layer` is
your confirmation that the arming took.

## Switching it off

- `/decision-layer off` - off for the session.
- `--impl-off` typed anywhere in an ordinary message - the same thing, handled by the hook,
  so it works mid-run when you are busy and not reading carefully.
- `--impl` typed anywhere in a message - off for that **one reply**, then back on by itself.

Asking for code in plain words - "show me that function", "what does the error say" - also
drops the boundary for that one reply.

## Before you change anything

The style has been measured. Across 55 armed replies where the boundary was meant to apply,
the reader was blocked exactly once.

Every line added to `SKILL.md` or to the output style is paid for on every use. Measure
first; the suite in `evals/` at the repository root exists for that.
