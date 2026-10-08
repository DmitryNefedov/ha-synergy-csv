# Synergy CSV Import — Specification

Status: implemented. Vocabulary follows [CONTEXT.md](../CONTEXT.md); decisions are recorded in [docs/adr](adr/).

## 1. Goal

Let a Synergy (Western Australia) customer Upload Interval Data Files into Home Assistant and view the resulting history next to Fronius Solar Production, in the Energy dashboard and in `statistics-graph` cards. Synergy offers no live data; the newest Interval is always 2–3 days old (Data Lag).

## 2. Scope

### In scope (v1)

- One config entry per Meter, user-named.
- Repeated Uploads through the integration's **Configure** dialog.
- Every energy Register in the file becomes a Register Statistic.
- Per-Interval-Reading deduplication; newest Upload wins.
- Out-of-order Uploads (older history after newer) produce correct statistics.
- "Delete all data" option and full cleanup on removal of the Meter.

### Out of scope (v1)

- Automatic download from the Synergy portal (no API; login required).
- Sensor entities or live state ([ADR 0001](adr/0001-external-statistics-no-entities.md)).
- Costs / tariffs (use the Energy dashboard's static price).
- Derived Statistics (see §11 Roadmap).
- Translations other than English.

## 3. Platform constraints

| Item | Value |
|---|---|
| Home Assistant | 2026.9.x only (HAOS); `hacs.json` minimum `2026.9.0` |
| Python | 3.14 (HA 2026.9 requires ≥ 3.14.2) |
| Runtime dependencies | None beyond the standard library (`csv`, `datetime`, `zoneinfo`) and HA core |
| HA dependencies | `recorder`, `file_upload` (manifest `dependencies`) |
| Statistics resolution | Hourly (HA long-term statistics accept only hour-aligned rows) |
| Upload size limit | 100 MB (HA `file_upload`); a year of data is ≈ 0.5 MB |

## 4. Interval Data File format

Observed format (two real samples, Jan–Mar and Jun–Aug 2026):

```
Date,Time,ANYTIME (KWH),Solar export (Units),Billing Status
01/06/2026,00:00,0.207,0.000,Billed
```

- Comma-separated, ASCII/UTF-8 (a UTF-8 BOM must be tolerated), header on line 1.
- `Date` is `DD/MM/YYYY`; `Time` is `HH:MM`, the **start** of a 30-minute Interval, Perth local time (`Australia/Perth`, UTC+8, no DST). Interpreted in Perth time regardless of HA's configured time zone.
- Every column between `Time` and `Billing Status` whose header ends in `(KWH)` or `(Units)` (case-insensitive) is a **Register**, valued in kWh. Other unit suffixes are ignored and listed in the Upload summary.
- `Billing Status` is optional and ignored.
- Register slug: header with the unit suffix removed, lowercased, non-alphanumerics collapsed to `_`, trimmed (`ANYTIME (KWH)` → `anytime`, `Solar export (Units)` → `solar_export`).
- Other Synergy plans are expected to produce other Registers (e.g. `PEAK`, `OFF-PEAK`, `SUPER OFF-PEAK`); they are handled generically, with no plan-specific code.

### Validation (whole file rejected on the first failure — [ADR 0003](adr/0003-reject-whole-file-on-error.md))

| Rule | Error shown |
|---|---|
| Header missing `Date` / `Time` as first two columns | "Not a Synergy interval data file" |
| No Register columns | "No energy columns found" |
| Row column count ≠ header column count | "Line N: expected X columns" |
| Unparseable date or time | "Line N: invalid date/time" |
| Minute not `00` or `30` | "Line N: time is not on a 30-minute boundary" |
| Register value empty, non-numeric, or negative | "Line N: invalid value for <Register>" |
| Same Interval twice in one file | "Line N: duplicate interval <date time>" |
| No data rows | "File contains no readings" |

## 5. User flows

### 5.1 Add a Meter

Settings → Devices & services → Add integration → **Synergy (WA) CSV Import** → enter a Meter name (default "Home"). The unique id is the Meter slug; adding a second Meter with the same slug aborts with "already configured".

### 5.2 Upload

Integration card → **Configure** → menu:

1. **Upload Interval Data File**: a file field (`FileSelector`, accept `.csv`). On submit:
   1. Parse and validate the file in an executor job (`process_uploaded_file`).
   2. Merge into stored Interval Readings (§6).
   3. Rebuild affected Register Statistics (§7).
   4. Show a summary step, e.g.:
      > Uploaded 01/06/2026 – 30/08/2026 · 8,736 new, 0 replaced Interval Readings · Registers: ANYTIME, Solar export · Gaps: none
   Gaps are runs of missing Intervals *inside* the file's own date range.
2. **Delete all data**: confirmation step, then clear stored readings and all of this Meter's Register Statistics.

Errors are shown on the upload form; nothing is stored.

### 5.3 Remove the Meter

Removing the config entry deletes its stored readings and its Register Statistics (`async_remove_entry` → `async_clear_statistics`).

## 6. Stored Interval Readings

- One HA `Store` per Meter: `.storage/synergy_csv.<entry_id>`, versioned (`version: 1`).
- Shape:

  ```json
  {
    "registers": {
      "anytime": {
        "name": "ANYTIME",
        "readings": { "2026-06-01T00:00": 0.207, "2026-06-01T00:30": 0.199 }
      }
    }
  }
  ```

  Keys are Perth-local Interval starts (naïve ISO, minute precision).
- Merge rule: for each (Register, Interval) in the Upload, insert or overwrite. Readings absent from the Upload are never removed. Count new vs replaced (replaced = existed before, regardless of whether the value changed).
- A replaced value equal to the stored one does not count as a change for §7.

## 7. Register Statistics

Per Register, external statistic ([ADR 0001](adr/0001-external-statistics-no-entities.md)):

| Metadata field | Value |
|---|---|
| `statistic_id` | `synergy_csv:<meter_slug>_<register_slug>` |
| `source` | `synergy_csv` |
| `name` | `<Meter name> <Register name>`, e.g. "Home ANYTIME" |
| `unit_of_measurement` | `kWh` |
| `unit_class` | `energy` |
| `has_sum` | `true` |
| `mean_type` | `StatisticMeanType.NONE` |

(`mean_type` and `unit_class` must be set explicitly; omitting them is deprecated and breaks in 2026.11.)

### Hourly aggregation

- Hour H (Perth) = Interval Readings at `H:00` + `H:30`. If only one half exists, use it (gap reported in the summary). Hours with neither are not emitted.
- `start` = H converted to a UTC-aware datetime.
- `state` = `sum` = cumulative kWh of the Register from its first stored reading up to the end of H.

### Rebuild ([ADR 0002](adr/0002-keep-raw-readings-rebuild-sums.md))

After a merge, for each Register whose readings changed: recompute the hourly series from the earliest changed hour to the newest stored hour, with sums continuing from the unchanged hour before it, and submit via `async_add_external_statistics`. Upserts overwrite stale rows; since readings are never removed, no stale hour rows can remain. "Delete all data" and removal use `async_clear_statistics`.

## 8. Viewing (documented in README, not built)

- **Energy dashboard**: Grid consumption = `synergy_csv:<meter>_anytime` (or each tariff Register), Return to grid = `synergy_csv:<meter>_solar_export`, Solar production = `sensor.primo_5_0_1_1_total_energy`. HA then derives Home Consumption and self-consumption. Caveat: for the Data Lag days the dashboard shows no Grid Import or Solar Export, so Home Consumption is understated (it equals Solar Production) until the next Upload.
- **statistics-graph card**: Synergy Register Statistics plus Fronius `total_energy` (display unit set to kWh so both share one axis), `stat_types: [change]`, `period: hour` or `day`.

Reference sensor (user's install): `sensor.primo_5_0_1_1_total_energy`, Wh, monotonically increasing, ~100 Wh resolution.

## 9. Repository layout (HACS)

```
ha-synergy-csv/
├── CONTEXT.md
├── README.md
├── hacs.json                        # {"name": "Synergy (WA) CSV Import", "homeassistant": "2026.9.0", "country": "AU"}
├── docs/
│   ├── spec.md
│   └── adr/
├── custom_components/synergy_csv/
│   ├── __init__.py                  # setup / unload / remove_entry
│   ├── manifest.json
│   ├── config_flow.py               # Meter setup + options menu (Upload, Delete all data)
│   ├── const.py
│   ├── parser.py                    # pure: file text → validated Interval Readings
│   ├── readings.py                  # pure: merge + hourly aggregation + sums
│   ├── slug.py                      # pure: names → slugs
│   ├── summary.py                   # pure: Upload summary → markdown
│   ├── service.py                   # UploadService + LedgerRepository / StatisticsPublisher ports
│   ├── store.py                     # Store adapter (LedgerRepository)
│   ├── statistics.py                # recorder adapter (StatisticsPublisher)
│   ├── strings.json
│   ├── translations/en.json
│   └── brand/icon.png               # required by HACS; HA ≥ 2026.3 serves it locally
├── scripts/
│   ├── make_synthetic_csv.py        # stdlib-only fixture generator
│   └── test.sh                      # runs commands in the HA test container
├── docker/Dockerfile.test
├── e2e/                             # run.sh boots HA 2026.9.4 in Docker; driver.py drives it
└── tests/
    ├── fixtures/                    # synthetic only
    └── ...
```

`manifest.json`: `domain` `synergy_csv`, `name`, `version`, `config_flow: true`, `dependencies: ["file_upload", "recorder"]`, `requirements: []`, `iot_class: "calculated"`, `integration_type: "service"`, `documentation`, `issue_tracker`, `codeowners`.

`parser.py` and `readings.py` must not import Home Assistant, so they are unit-testable in isolation.

Real Synergy or Fronius exports must never be committed; `.gitignore` excludes `*.csv` outside `tests/fixtures/`.

## 10. Test plan

Tooling: `pytest`, `pytest-homeassistant-custom-component` (pinned to the 2026.9 release), `ruff`. Dev-only; not runtime requirements.

### Unit (pure modules)

- Parser accepts the canonical format, BOM, missing `Billing Status`, extra tariff Registers; slugging rules.
- Each validation rule in §4 rejects with the right line number.
- Merge: new vs replaced counts; readings absent from an Upload survive; identical replacement is not a change.
- Aggregation: two halves summed; single half used; empty hours skipped; Perth → UTC conversion; cumulative sums across a multi-month gap.
- Rebuild window starts at the earliest changed hour and sums continue from the prior hour.

### Integration (HA test harness with recorder)

- Config flow creates a Meter; duplicate slug aborts.
- Options flow Upload with a mocked `process_uploaded_file`: summary text; statistics present with expected metadata.
- **Out-of-order**: Upload Jun–Aug, then Jan–Mar → statistics equal those from uploading in date order.
- **Overlap**: Upload a file, then an overlapping one with changed values → later hours' sums shift accordingly.
- **Partial day**: newest day ends mid-day, later Upload completes it.
- Invalid file → error shown, store and statistics unchanged.
- Delete all data and entry removal clear store and statistics.

## 11. Synthetic test data

Real samples inform the generator but are not committed. `scripts/make_synthetic_csv.py` (stdlib, seeded, deterministic) writes files in the §4 format:

- Options: `--start`, `--end` (inclusive dates), `--seed`, `--registers` (default `ANYTIME (KWH)`, `Solar export (Units)`; alternative preset with `PEAK`, `OFF-PEAK`, `SUPER OFF-PEAK`), `--drop` (Intervals to omit), `--partial-last-day HH:MM`.
- Shape, modelled on the samples (Perth, 5 kW inverter, no battery):
  - Overnight Grid Import 0.18–0.26 kWh per Interval; evening peak 17:00–21:00 up to ~0.8.
  - Daytime Grid Import near zero when solar covers load.
  - Solar Export bell curve ~07:00–17:30, peak up to ~1.8 kWh per Interval in summer, ~55 % in Jun–Aug; random cloudy days.
  - Values to 3 decimal places; `Billing Status` `Billed`.

Committed fixtures (generated once, small):

| Fixture | Purpose |
|---|---|
| `summer_2w.csv` | Baseline happy path |
| `winter_2w.csv` | Out-of-order pairing with summer |
| `overlap.csv` | Overlaps `summer_2w` with altered values |
| `partial_day.csv` | Last day ends 14:00 |
| `with_gap.csv` | Missing Intervals inside the range |
| `tou_registers.csv` | PEAK / OFF-PEAK / SUPER OFF-PEAK Registers |
| `invalid_*.csv` | One per validation rule |

## 12. Roadmap (not v1)

- **Derived Statistics**: Home Consumption and self-consumption as `synergy_csv:` statistics combining Register Statistics with a chosen Solar Production statistic.
- Watched folder (`/share/synergy`) for automatic Upload.
- Upload as an action (`synergy_csv.upload`) for automations.
- Tariff cost statistics.
