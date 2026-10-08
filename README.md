# Synergy (WA) CSV Import for Home Assistant

Upload the interval data CSV files you download from [Synergy](https://www.synergy.net.au/) into Home Assistant and see your grid import and solar export history next to your solar inverter, in the Energy dashboard or any statistics graph.

Synergy publishes data 2–3 days late and has no live API, so this integration works from files you upload, as often as you like. Re-uploading overlapping or older files is safe: each 30-minute reading is stored once, and the newest upload wins.

Requires Home Assistant **2026.9** or later.

## Installation

### HACS

1. HACS → ⋮ → **Custom repositories** → add this repository's URL, category **Integration**.
2. Install **Synergy (WA) CSV Import** and restart Home Assistant.

### Manual

Copy `custom_components/synergy_csv` into your `/config/custom_components/` and restart.

## Setup

1. Settings → Devices & services → **Add integration** → *Synergy (WA) CSV Import*.
2. Name the meter (e.g. `Home`). One entry per Synergy meter.

## Uploading data

1. Download your interval data CSV from Synergy My Account. It looks like:

   ```
   Date,Time,ANYTIME (KWH),Solar export (Units),Billing Status
   01/06/2026,00:00,0.207,0.000,Billed
   ```

2. Settings → Devices & services → *Synergy (WA) CSV Import* → **Configure** → **Upload Interval Data File** → choose the file.
3. A summary shows the date range, new vs replaced readings, registers found and any gaps.

If any line is invalid, the whole file is rejected and the line number is shown; nothing is changed.

**Configure → Delete all data** removes every stored reading and statistic for that meter. Removing the integration does the same.

## What gets created

No entities. One hourly long-term statistic per energy column in the file, in kWh:

| CSV column | Statistic id (meter named `Home`) |
|---|---|
| `ANYTIME (KWH)` | `synergy_csv:home_anytime` |
| `Solar export (Units)` | `synergy_csv:home_solar_export` |

Time-of-use plans (`PEAK`, `OFF-PEAK`, …) get one statistic per column automatically.

## Viewing

### Energy dashboard

Settings → Dashboards → Energy:

- **Grid consumption**: `Home ANYTIME` (add each tariff column if on a time-of-use plan)
- **Return to grid**: `Home Solar export`
- **Solar production**: your inverter, e.g. `sensor.primo_5_0_1_1_total_energy` (Fronius)

Home Assistant then calculates home consumption and self-consumption. The most recent 2–3 days will show no grid data until the next upload.

### Comparison graph

First set the Fronius energy sensor to kWh so both share an axis: Settings → Entities → *Total energy* → ⚙ → Unit of measurement → `kWh`.

```yaml
type: statistics-graph
title: Synergy vs Fronius
period: hour            # or day / week / month
chart_type: bar
stat_types:
  - change
days_to_show: 7
entities:
  - entity: synergy_csv:home_anytime
    name: Grid import
  - entity: synergy_csv:home_solar_export
    name: Solar export
  - entity: sensor.primo_5_0_1_1_total_energy
    name: Solar production
```

Add any other statistic or energy sensor to `entities` to compare more values.

## Limitations

- Hourly resolution in Home Assistant (Synergy's 30-minute readings are summed per hour).
- No automatic download from Synergy.
- Times are always interpreted as Perth time.

## Development

- Glossary: [CONTEXT.md](CONTEXT.md)
- Decisions: [docs/adr](docs/adr/)
- Specification and test plan: [docs/spec.md](docs/spec.md)

Tests run inside a Home Assistant 2026.9.4 / Python 3.14 container (needs Docker):

```bash
docker build -t synergy-csv-test -f docker/Dockerfile.test .
scripts/test.sh                              # pytest with coverage (fails under 95 %)
scripts/test.sh sh -c "ruff check . && ruff format --check . && mypy"
e2e/run.sh                                   # boots a real HA container and drives it over REST/WebSocket
```

Never commit real Synergy or inverter exports; tests use synthetic data from `scripts/make_synthetic_csv.py`.
