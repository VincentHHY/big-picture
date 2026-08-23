# Examples

Real pairs. Each folder holds one question sent to two live Claude Code sessions —
one with `decision-layer` armed, one without — and both replies exactly as they
came back.

Every run used a **clean configuration**: a fresh install holding this plugin and
nothing else. No personal instruction files, no project instructions, no other
plugins. That matters, because a well-tuned setup already nudges Claude toward
plainer writing, which would flatter the unarmed side and understate the difference.

| example | the question | the decision underneath |
|---|---|---|
| [flaky-tests](flaky-tests) | tests pass locally but keep failing in CI | patch the two failing tests, or fix every place with the same bug |
| [dependency-conflict](dependency-conflict) | the build fails on the server but works on my laptop | ship tonight, or slip the release |
| [database-replace](database-replace) | is this infrastructure change safe to apply | apply it, or split it in two |
