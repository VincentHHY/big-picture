Your tests aren't randomly flaky — they're reading the real system clock, and your machine and CI don't agree on what time it is. Your laptop reports British time, which right now runs an hour ahead of the UTC that CI is pinned to. Any test that does date math against "right now" can land on a different day or side of a boundary depending on which clock and which moment it runs at — that's also why a different pair of tests trips each time you rerun it, not the same two.

So this isn't instability to chase down — it's a real, deterministic bug: the code doesn't get told what time it is, it just asks. The fix is to make time-dependent behavior take a supplied time instead of reading the clock itself, so tests can pin it and get the same answer everywhere.

Two ways to size the fix:
- Just the two tests failing today — small, fast, but the same bug can resurface anywhere else in the code that still reads the live clock.
- Every spot in the code that reads the live clock — closes the whole failure class in one pass, more work now.

I'd default to the narrow fix now and track the rest as follow-up, unless you'd rather close it out in one sweep.

--- where ---
1. `src/checkout/total.test.ts:41` and `src/orders/expiry.test.ts:88` — the two failing tests, both date-boundary assertions
2. Your CI config pins `TZ=UTC`; your shell reports `Europe/London` — the source of the mismatch
3. `grep -rn "new Date()" src/` found 37 call sites — the scope of the wider sweep option

▪ decision-layer