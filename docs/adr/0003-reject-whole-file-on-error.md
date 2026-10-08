# Reject the whole Interval Data File on any error

An Upload is all-or-nothing: if any line fails validation, nothing is stored and the user sees the first offending line number and reason. Skipping bad rows would silently create holes that look like real zero-usage dips in the graphs, and with "newest Upload wins" a partially accepted file could overwrite good readings with an incomplete picture.

## Consequences

- If Synergy ever ships a file with blank values for recent Intervals, the user must trim those lines (or a later version must define blanks as "not yet available"); revisit then.
