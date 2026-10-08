# Register Statistics are external statistics, not sensor entities

Synergy data arrives 2–3 days late (Data Lag), so any sensor entity would show a stale value as if it were current, and backfilling entity history fights the recorder's own statistics compilation. We store each Register as an external statistic (`synergy_csv:<meter>_<register>`, via `async_add_external_statistics`) and create no entities. External statistics are accepted by the Energy dashboard (grid consumption / return) and the `statistics-graph` card, which is everything the use case needs.

## Consequences

- Nothing appears under Settings → Entities; the statistics are found by their `synergy_csv:` id.
- No live state, so no automations can trigger on Synergy values.
