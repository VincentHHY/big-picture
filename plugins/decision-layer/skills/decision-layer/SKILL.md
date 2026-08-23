---
name: decision-layer
description: Answer at the decision level - plain language the user can judge and decide on, with code, file paths and line numbers kept below a marked line. Armed for one session at a time and off by default. Use when the user types /decision-layer, or asks to work at the decision level, to stop mixing code into answers, to hide implementation detail, or to be told only what they can actually decide. `/decision-layer off` turns it back off.
---

# Decision layer

Typing `/decision-layer` arms it already — a hook fires before this file loads. Nothing more
to do. Just confirm the boundary is on for this session and carry on with the work.

If the skill was triggered by plain words rather than the typed command, no arming event
fired. Arm it by hand:

```bash
bash "${CLAUDE_PLUGIN_ROOT}/hooks/decision-layer-mode.sh" --arm
```

If the output style is not selected, arming does nothing. Check with `/output-style` and
pick `decision-layer` once; the selection is remembered, and the boundary still starts off
in every new session because the hook owns that part.

## Turning it off

- `/decision-layer off` — off for the session.
- `--impl-off` typed anywhere in an ordinary message — same thing, handled by the hook, so it
  works mid-run when the user is busy and not reading carefully.
- `--impl` typed anywhere in a message — off for that **one reply** only, then back on
  automatically. Also handled by the hook, so there is nothing to detect.

A plain request for code — "show me that function", "what does the error say" — also drops
the boundary for that reply. That one is a judgement call, not a hook.

## Why the arming matters

Arming is what makes the mode survive. Without the flag file, the rules in the output style
are inert: they are written conditionally and apply only to a turn the hook has marked. The
flag is keyed by session id, so a new session always starts with the boundary off.

The block between the `INJECT` markers below is the only copy of the marker text. The hook
reads it fresh on every prompt, so editing it here changes what gets sent on the next one.
No restart, no code change.

<!-- INJECT:BEGIN -->
DECISION-LAYER:ARMED

This turn is armed. Apply the decision-layer output style's "While armed" rules to your
reply: the sufficiency test, recast-then-own, anchors below `--- where ---`, and the closing
footer.
<!-- INJECT:END -->
