# Keep raw Interval Readings and rebuild sums on every Upload

The recorder's statistics import upserts rows hour by hour but never recomputes the cumulative `sum` of later hours, so uploading an older file (or a corrected one) after a newer one would leave every later hour wrong. We therefore keep every 30-minute Interval Reading in the integration's own storage, merge each Upload into it (newest Upload wins per Interval Reading), and re-emit each affected Register Statistic from the earliest changed hour to the end of its history with freshly computed sums.

## Considered Options

- **Upsert only the uploaded hours**: breaks sums for any out-of-order or corrected Upload.
- **Read existing statistics back and patch them**: hourly statistics have already lost the 30-minute detail and per-reading provenance, so per-Interval replacement is impossible.
- **`async_adjust_statistics` to shift later sums**: works for pure inserts but becomes error-prone for replacements spanning gaps; the full re-emit is simpler to reason about and test.

## Consequences

- Raw storage grows ~0.5 MB per Register per year; acceptable for a household.
- The stored readings are the source of truth; the statistics can always be regenerated from them.
