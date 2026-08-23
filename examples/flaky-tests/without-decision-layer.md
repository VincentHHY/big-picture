Both failures are date/time boundary checks, and the flakiness (different tests fail each run) is the signature of tests reading the **real system clock** instead of a fixed time. That's consistent with your evidence:

- Your machine is `Europe/London` (currently UTC+1, British Summer Time); CI is pinned to `TZ: UTC`. The same instant lands on a different calendar day/hour in each — enough to flip a "is this the weekend" or "is this day 30" check.
- Even with TZ fixed, if a test never mocks "now," a "weekend surcharge" test will pass or fail depending on *what day CI happens to run on* — which explains why reruns don't reproduce the same failures.

**Diagnosis, not yet verified against your actual code** (I couldn't find these files locally, so this is inference from the symptoms, not a read of the source):
- `applies weekend surcharge`: likely computes the day-of-week from a real `new Date()` (or `getDay()` on one not pinned to UTC) rather than a fixed test date.
- `marks orders stale after 30 days`: likely computes elapsed days from real "now" minus a fixed timestamp, so the result depends on exactly when the test runs.

**Fix:** mock/freeze the clock in these tests rather than relying on the real system time — e.g. `vi.useFakeTimers()` + `vi.setSystemTime(fixedDate)` (you're likely on Vitest, given the `AssertionError`/`❯` style output) around each test, picking a fixed instant that's unambiguously a weekday/weekend and unambiguously past/before day 30. Separately, decide explicitly which timezone the business logic (weekend, day-boundary) should run in, and pin it in code — don't let it fall through to the host's TZ.

I'd also grep the other 37 `new Date()` call sites in `src/` for the same pattern — any of them without a passed-in/mocked clock carries the same nondeterminism risk, just not yet exercised by a test that happens to straddle a boundary.

Want me to find the actual repo path and grep those two test files + the surcharge/expiry source for unmocked `new Date()` calls, so this moves from inference to confirmed?