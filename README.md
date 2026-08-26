<div align="center">

# Big Picture

### Claude Code plugins that keep the code out of the answer — so you can judge it and decide.

[![License: MIT](https://img.shields.io/badge/License-MIT-green.svg)](LICENSE)
[![Claude Code](https://img.shields.io/badge/Claude%20Code-plugin-8A63D2)](https://claude.com/claude-code)
[![Measured](https://img.shields.io/badge/measured-55%20sessions-brightgreen)](evals/)

First plugin: **decision-layer** — off by default, armed one session at a time.

</div>

## See the difference

<div align="center">

<sub>SOMEONE ASKED</sub>

### “The release goes out tonight. The build now fails on the server<br>but works on my laptop. What should we do?”

</div>

<details>
<summary>&nbsp;&nbsp;what they pasted in</summary>

```
Exception in thread "main" java.lang.NoSuchMethodError: 'void com.google.common.base.Preconditions.checkArgument(boolean, java.lang.String, java.lang.Object)'
	at org.apache.hadoop.conf.Configuration.set(Configuration.java:1357)
	at com.acme.ingest.SinkFactory.build(SinkFactory.java:88)
	at com.acme.ingest.Main.main(Main.java:41)

$ mvn dependency:tree -Dincludes=com.google.guava
[INFO] com.acme:ingest:jar:7.4.0
[INFO] +- com.acme:acme-storage:jar:3.2.0:compile
[INFO] |  \- com.google.guava:guava:jar:19.0:compile
[INFO] +- org.apache.hadoop:hadoop-common:jar:3.3.6:compile
[INFO] |  \- com.google.guava:guava:jar:27.0-jre:compile  (omitted for conflict with 19.0)
[INFO] \- com.acme:acme-metrics:jar:1.9.4:compile
[INFO]    \- com.google.guava:guava:jar:32.1.3-jre:compile (omitted for conflict with 19.0)
[WARNING] Used undeclared dependencies found: com.google.guava:guava:jar:19.0
```

</details>

<div align="center">

**↓ &nbsp; answered twice &nbsp; ↓**

</div>

<table>
<tr>
<th width="45%">Without decision-layer</th>
<th width="10%"></th>
<th width="45%">With decision-layer</th>
</tr>
<tr valign="top">
<td>

🔎 **Root cause: two versions of Guava are fighting, and the wrong one won.**

Three different things in your project want different Guava versions:
- `acme-storage` wants 19.0 (old)
- `hadoop-common` wants 27.0
- `acme-metrics` wants 32.1.3 (new)

Maven can only put **one** copy of Guava on the classpath, so it "mediates" — picks one.
Its rule is "nearest wins, and if it's a tie, whoever is listed first in the pom wins."

✅ **Fix for tonight (low risk, ~10 minutes):**

1. In the parent `pom.xml`, add a `<dependencyManagement>` entry pinning Guava to
   **32.1.3-jre**.
2. Add Guava as an **explicit direct dependency** of the `ingest` module.
3. Re-run `mvn dependency:tree -Dincludes=com.google.guava` — confirm only one version
   shows, no more "omitted for conflict" lines.
4. Rebuild and smoke-test the ingest path before shipping.

</td>
<td align="center" valign="middle">

# ➜

</td>
<td>

The crash is a version mismatch, not a code bug: your app is pulling in an old copy of a
shared library, and something else it depends on expects a newer copy.

For tonight, the fix is to pin the version explicitly instead of trusting the default
tie-break. That's a small, low-risk change.

Before you ship, don't treat "works on my laptop" as proof — do a clean rebuild on the
server side and confirm only one copy of the library shows up. **If that comes back
clean, ship. If it doesn't resolve in the time you have left, slipping the release is the
safer call than shipping a build you can't currently reproduce.**

```
--- where ---
```

1. `hadoop-common:3.3.6` needs Guava ≥27 for
   `Preconditions.checkArgument(boolean, String, Object)`; Maven's "nearest declaration
   wins" mediation picked `guava:19.0`.

`▪ decision-layer`

</td>
</tr>
</table>

<div align="center">

<sup>☝️ that last line, <code>▪ decision-layer</code>, is how you know it was on</sup>

<br>

| measured on the two full replies | ❌ without | ✅ with |
|---|:---:|:---:|
| **Length of the reply** | 459 words | **191 words** |
| **Code shown to you in the prose** | **23 snippets** | **0** |
| **Times the library is named** | **11** | **0** |
| **Config steps handed back to you** | 4 | none |
| **Ends with a decision you can make** | no | **ship, or slip** |

</div>

The left answer is not wrong — if you write Java, it is the one you want. But the person
asking needs to know whether to ship tonight, and only the right answer tells them:
**ship, or slip.** The detail is not gone. It is under the line, waiting.

<sub>Real, unedited output from two clean Claude Code sessions given the same question,
shortened to fit the page. <b><a href="examples/dependency-conflict">Read the full replies →</a></b>
&nbsp;·&nbsp; <a href="examples">more examples</a></sub>

---

## How it works

<div align="center">

<img src="assets/ladder.svg" alt="The abstraction ladder. Machine code, assembly, C and Python each sit behind a hard boundary. Natural language sits on top of all of them behind a broken one." width="820">

</div>

Every step on that ladder has a hard boundary: you write Python without reading the assembly
it becomes. Natural language is the newest step, and it shipped without one — so the detail
leaks upward, into answers full of code you never agreed to read and cannot decide on.
**decision-layer puts the boundary back.**

<div align="center">

<img src="assets/boundary.svg" alt="A dense technical reply on the left passes through the decision-layer boundary and becomes a short plain-language decision on the right, with the implementation detail kept below a marked line." width="860">

</div>

The agent still does all the work and still knows every detail. What changes is the way back:
the prose has to stand on its own, and anything you would need a pointer for goes below a
`--- where ---` line, where it waits if you want it. Ask for the code in plain words — *"show
me that function"* — and the boundary steps aside for that one reply.

## Install

Three commands, about a minute.

**1 — Install the plugin.**

```
/plugin marketplace add VincentHHY/big-picture
/plugin install decision-layer@big-picture
```

**2 — Select the output style, once.** This makes the boundary available in every project —
terminal, VS Code extension and desktop app alike.

```
/decision-layer setup
```

Under the hood it writes one line, `"outputStyle": "decision-layer:Plain"`, into your own
`~/.claude/settings.json`.

> [!IMPORTANT]
> **Step 3 will not work in this session.** Claude Code reads the output style once, when a
> session opens. Start a new session or run `/clear` first.

**3 — Turn it on whenever you want it.**

```
/decision-layer
```

`/decision-layer off` turns it off again, and **every new session starts off**, so it never
follows you into tomorrow.

Switches, troubleshooting and how it is built: **[plugins/decision-layer](plugins/decision-layer)**.

## Does it hold up?

Every case is a real armed session, driven by the live hook and the live output style. The
judge sees only the prose — never the code, the fixture or the question. That is the reader's
own situation.

<div align="center">

| | ❌ without | ✅ with decision-layer |
|---|:---:|:---:|
| **reader could follow it** | 20–40% | **100%** |
| mechanical checks passed | 18–40% | **91–100%** |

</div>

Across **55** armed replies where the boundary was meant to apply, the reader was blocked
**once**. Suite and method: [evals/](evals/).

## Licence

MIT.
