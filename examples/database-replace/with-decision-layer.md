Not safe to apply as-is — this isn't a resize, it's a delete-and-rebuild. Terraform will destroy your live production orders database and stand up a brand new empty one in its place, and nothing is currently set up to save a backup before the old one goes away.

Two things are driving that: jumping the database engine forward that far isn't something that can happen to a running database — it has to be rebuilt fresh — and switching the disk type has the same effect. The extra storage space you wanted is a safe, in-place change on its own; it's the other two changes riding along with it that turn this into a destroy.

Also worth knowing: whatever protection would normally stop an accidental delete is switched off, and no backup snapshot is set to happen on the way out. So if this runs, there's no safety net and a real chance of losing production order data.

My suggestion: split this into two steps. Apply the storage increase alone first — that's safe. Then handle the engine and disk-type change separately, with a backup taken immediately before it runs.

Want me to restructure it that way, or do you want to accept the risk and proceed as one step?

--- where ---
1. Plan line `~ engine_version = "14.7" -> "16.2" # forces replacement`
2. Plan line `~ storage_type = "gp2" -> "io2" # forces replacement`
3. Plan line `skip_final_snapshot = true`
4. Plan line `deletion_protection = false`
5. Plan line `~ allocated_storage = 500 -> 1000` (the one change that doesn't force replacement)

▪ decision-layer