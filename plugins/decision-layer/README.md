# decision-layer

Answers you can judge and decide on without reading code. The prose carries no code, paths or
line numbers; anything you would need a pointer for waits under a `--- where ---` line at the
bottom; and every reply written under the boundary ends with `▪ decision-layer`.

It starts **off in every new session**. You arm it when you want it, and it does not follow
you into tomorrow.

**This page is the reference** — how to drive it, what to do when it misbehaves, and how it is
built. Installing it, what it is for, a real before-and-after, and the measured results are
all on the **[landing page](../../README.md)**.

## Use

| Command | Effect |
|---|---|
| `/decision-layer setup` | Selects the output style for every project. Run once, at install |
| `/decision-layer` | On, for this session |
| `/decision-layer off` | Off, for this session |
| `--impl` on a message's first or last line | Off for that **one** reply, then back on |
| `--impl-off` on a message's first or last line | Off for the session |

The command menu lists this as `decision-layer:decision-layer`, the same word twice, because
Claude Code files every skill a plugin ships under the plugin's own name and both are called
the same thing. Type the short `/decision-layer`; it is registered too, and it is the one to
use.

Asking for code in plain words — "show me that function", "what does the error actually say" —
also drops the boundary for that one reply. Asking for code is itself a decision you made.

The two `--` switches are handled by the hook, not by the model, so they still work mid-run
when Claude is busy and not reading carefully. Each counts only as a word standing on its
own at the top or the bottom of a message, which is where you would reach for one. Quoting
a switch anywhere else does nothing, so pasting a transcript — or this page, which names
both of them — leaves the boundary exactly as it was.

## If it is not working

- **You ran `/decision-layer setup`, armed, and nothing happened.** Claude Code reads the
  output style once, when a session opens, so the session you ran setup in cannot see it.
  Start a new session, or run `/clear`. Until then arming accepts the command and changes
  nothing — no error, and no footer.
- **The VS Code extension still shows the old style.** It reads the setting when the
  extension starts, so reload the window after changing it.
- **Nothing happens at all, on any surface.** The plugin needs **`bash`** and **Python 3** on
  `PATH` (`python3`, `python` or `py`). macOS and Linux have both; on Windows, Git Bash
  provides `bash`, and the launcher steps over the Microsoft Store's `python3` and `python`
  placeholders to reach a real one. Without either the hook never runs, so the boundary never
  turns on.

The [landing page](../../README.md#if-it-is-not-working) covers the rest: replies with no
footer at all, a selection that reached only one project, and an output style of your own that
stopped applying.

## What it does not touch

Only the message you read. Subagent prompts, tool calls, commit messages, code comments and
pull-request descriptions keep their full technical detail. That traffic is expert to expert,
where dense is correct.

## How it works

Two pieces, and both are needed:

1. **An output style** that holds the rules. It sits in the system prompt permanently, but it
   is written conditionally — it applies only to a turn carrying a `DECISION-LAYER:ARMED`
   marker.
2. **A hook** that decides, per turn, whether to send that marker. Armed state is one file per
   session under your Claude config directory, so a new session always starts off. The same
   hook checks at the start of each session that the style is selected at all, and says so
   on screen when it is not — and it is what `/decision-layer setup` runs, so selecting the
   style needs no separate script.

Why not just an output style? Because a style has no session scope: switch it on and it stays
on until something switches it off, and one forgotten evening later it is quietly still there.
Why not just a hook injecting the rules? Because that costs the whole rulebook in tokens on
every armed turn, instead of a few dozen for the marker.

## Editing the rules

The rules are in `output-styles/decision-layer.md` — the file name, not the style name. The
style is named by the `name:` field in its frontmatter, and Claude Code registers it with the
plugin's name in front, as `decision-layer:Plain`, so two plugins can ship a style called the
same thing without clashing.

The armed marker text is in `skills/decision-layer/SKILL.md`, between the `INJECT` markers —
the hook reads it fresh on every prompt, so an edit takes effect on the next one, with no
restart.

Measure before you change either. The suite in `evals/` at the root of this repository drives
real armed sessions and grades the prose blind, so it answers whether an edit helped rather
than whether it reads well. It is not shipped inside the plugin, and it costs real money to
run.

## Licence

MIT.
