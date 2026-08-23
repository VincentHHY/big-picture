🔎 **Root cause: two versions of Guava are fighting, and the wrong one won.**

Guava is a shared utility library (Google's collections/helpers). Three different things in your project want different Guava versions:
- `acme-storage` wants 19.0 (old)
- `hadoop-common` wants 27.0
- `acme-metrics` wants 32.1.3 (new)

Maven can only put **one** copy of Guava on the classpath, so it "mediates" — picks one. Its rule is "nearest wins, and if it's a tie, whoever is listed first in the pom wins." That's not "safest" or "newest," just "first in the file." Here it picked **19.0**, because `acme-storage` is listed first.

`hadoop-common`'s compiled code expects a newer Guava and calls a method that doesn't exist in 19.0. That mismatch is the crash: `NoSuchMethodError`.

There's a second smell in that tree output: `Used undeclared dependencies found: guava:19.0`. That means `ingest`'s own code calls Guava classes directly but never lists Guava as its own dependency — it's silently riding on whichever copy wins the version fight. That's exactly why this broke without anyone touching Guava on purpose.

⚠️ **Why laptop works and server doesn't — don't trust "works on my laptop" here.**

Given the same `pom.xml` and same repo, Maven's version pick should be identical everywhere. If it isn't, the usual culprits are:
- an uncommitted or unpushed change in the laptop's `pom.xml` (an exclusion/override the server never got)
- a stale `.m2` cache on the laptop — an old cached jar that doesn't match what's actually in the shared repo
- laptop running from an IDE, which resolves/orders the classpath differently than `mvn` on the CLI

Before doing anything else: on the laptop, run `git status` / `git diff` on `pom.xml` and do a clean `mvn clean install -U` (that `-U` forces Maven to re-check the repo instead of trusting the local cache). If the laptop only "works" because of local drift, that needs to be found now, not discovered again on the next machine.

✅ **Fix for tonight (low risk, ~10 minutes):**
1. In the parent `pom.xml`, add a `<dependencyManagement>` entry pinning Guava to **32.1.3-jre** (the highest version required — Guava is generally safe to bump upward, and 27.0/19.0 are both older than what `hadoop-common` and `acme-metrics` already expect).
2. Add Guava as an **explicit direct dependency** of the `ingest` module, since its own code uses it (that undeclared-dependency warning is the proof).
3. Re-run `mvn dependency:tree -Dincludes=com.google.guava` — confirm only one version shows, no more "omitted for conflict" lines.
4. Rebuild and smoke-test the ingest path before shipping.

📌 **After the release ships:** worth a short follow-up to enable Maven's enforcer plugin (or similar) to fail the build on dependency convergence issues, so this class of problem is caught at build time instead of at runtime on release night.