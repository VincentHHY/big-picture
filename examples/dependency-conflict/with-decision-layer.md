The crash is a version mismatch, not a code bug: your app is pulling in an old copy of a shared library, and something else it depends on expects a newer copy. Maven picked the old one because of a default tie-breaking rule, not because anything actually declared it as a requirement — which is also why this is invisible on your laptop: nothing pins the version, so which copy "wins" can quietly depend on how each machine happens to build it, and the server's clean build exposed the real answer while your laptop's did not.

For tonight, the fix is to pin the version explicitly instead of trusting the default tie-break. That's a small, low-risk change, and it removes the "depends on which machine builds it" problem going forward.

Before you ship, don't treat "works on my laptop" as proof — do a clean rebuild on the server side and confirm only one copy of the library shows up. If that comes back clean, ship. If it doesn't resolve in the time you have left, slipping the release is the safer call than shipping a build you can't currently reproduce.

--- where ---
1. Root cause: `hadoop-common:3.3.6` needs Guava ≥27 for `Preconditions.checkArgument(boolean, String, Object)`; Maven's "nearest declaration wins" mediation picked `guava:19.0` (declared directly by `acme-storage:3.2.0`) over the transitive 27.0/32.1.3 from `hadoop-common`/`acme-metrics`. 19.0 lacks that overload → `NoSuchMethodError` at `Configuration.set`.
2. Fix: add an explicit `<dependency>` (or `<dependencyManagement>` entry) for `com.google.guava:guava` version `32.1.3-jre` in `ingest`'s pom, then confirm with `mvn dependency:tree -Dincludes=com.google.guava` that only one version resolves.
3. Verify before shipping: run the pin + `mvn -U clean package` (force fresh dependency resolution) on the server itself, or in a fresh container/checkout, not relying on the laptop's `.m2` cache or IDE classpath ordering — those are the likely reason the laptop's run didn't hit this.

▪ decision-layer