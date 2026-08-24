# decision-layer

Get answers you can judge and decide on without reading any code.

Claude normally answers a design question by mixing the decision and the evidence together:
the recommendation, then the file it lives in, then the three lines that prove it. That is
right when you are in the code. It is noise when you are deciding whether to do the thing at
all.

`decision-layer` draws a line. While it is on:

- The prose carries **no** file paths, symbol names, quoted lines or command output.
- Any pointers you need go under a `--- where ---` line at the very bottom, numbered to match.
- A choice that cannot be stated without implementation detail is first **recast** — stated by
  what you would actually feel: speed, risk, what breaks, what gets harder later. Only a choice
  with no consequence you could feel is decided for you, silently.
- Every reply ends with `▪ decision-layer`, so you always know it was on.

It is **off by default in every new session**. You turn it on when you want it, and it does not
follow you into tomorrow.

## Install

```
/plugin marketplace add VincentHHY/big-picture
/plugin install decision-layer@big-picture
```

Then select the output style once, in `/config` → **Output style** → **`decision-layer:Plain`**.

On a machine where that screen does not offer the option, put it in `~/.claude/settings.json`
by hand and restart:

```json
"outputStyle": "decision-layer:Plain"
```

The name carries the plugin in front of it because Claude Code registers every
plugin-supplied style that way, so two plugins can ship a style called the same thing without
clashing.

You select the style once and it stays selected. The boundary itself stays off until you
arm a session with `/decision-layer`. If you skip this step the plugin says so at the start
of every session — without the style, arming writes its flag and nothing else happens, which
is the one failure that leaves no trace.

Requires **`bash`** and **Python 3** on `PATH` (`python3`, `python` or `py`). macOS and
Linux have both; on Windows, Git Bash provides `bash`. Without `bash` the hook never runs,
so the boundary simply never turns on — no error, and no footer.

## Use

| Command | Effect |
|---|---|
| `/decision-layer` | On, for this session |
| `/decision-layer off` | Off, for this session |
| `--impl` anywhere in a message | Off for that **one** reply, then back on |
| `--impl-off` anywhere in a message | Off for the session |

Asking for code in plain words — "show me that function", "what does the error actually say" —
also drops the boundary for that one reply. Asking for code is itself a decision you made.

The two `--` switches are handled by the hook, not by the model, so they still work mid-run
when Claude is busy and not reading carefully.

## Does it actually work?

It has been measured, not just written. Every case runs as a real armed session driven by the
live hook and the live output style, and the headline judge is a grader that sees only the
prose — never the code, the fixture or the original question. That is the reader's real
situation.

Across 55 armed replies where the boundary was meant to apply, the reader was blocked
**once**. The same cases run unarmed, as a control:

| | armed | unarmed |
|---|---|---|
| reader could follow it | 100% | 20–40% |
| mechanical checks passed | 91–100% | 18–40% |

The suite lives in `evals/` at the root of this repository. It is not shipped inside the
plugin, and running it costs real money, because it drives live Claude sessions.

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
   on screen when it is not.

Why not just an output style? Because a style has no session scope: switch it on and it stays
on until something switches it off, and one forgotten evening later it is quietly still there.
Why not just a hook injecting the rules? Because that costs the whole rulebook in tokens on
every armed turn, instead of a few dozen for the marker.

## Editing the rules

The rules are in `output-styles/decision-layer.md` — the file name, not the style name;
the style is named by the `name:` field in its frontmatter. The armed marker text is in
`skills/decision-layer/SKILL.md`, between the `INJECT` markers — the hook reads it fresh on
every prompt, so an edit takes effect on the next one, with no restart.

## Licence

MIT.
