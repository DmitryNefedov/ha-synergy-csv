# Synergy CSV Import

Brings a household's Synergy (Western Australia) electricity meter history into Home Assistant from the CSV files Synergy publishes, so it can be graphed and compared against on-site solar production.

## Language

### Source data

**Meter**:
The Synergy electricity meter at one premises; the unit a user sets the integration up for.
_Avoid_: Account, NMI, site

**Interval Data File**:
A CSV export of a Meter's interval history downloaded from Synergy, always 2–3 days behind real time.
_Avoid_: Report, statement, export (ambiguous with Solar Export)

**Interval**:
A 30-minute period identified by its local start time in Perth time (e.g. `00:00` covers 00:00–00:30).
_Avoid_: Slot, timestamp

**Register**:
One energy column of an Interval Data File (e.g. `ANYTIME`, `Solar export`, or tariff columns such as `PEAK`).
_Avoid_: Column, channel, tariff

**Interval Reading**:
The energy (kWh) recorded for one Register in one Interval.
_Avoid_: Row, sample, value

**Billing Status**:
Synergy's label on a row of an Interval Data File (e.g. `Billed`); informational only.

### Energy flows

**Grid Import**:
Energy drawn from the grid into the premises, recorded by consumption Registers such as `ANYTIME`.
_Avoid_: Consumption, usage (those mean Home Consumption)

**Solar Export**:
Energy fed from the premises back into the grid, recorded by the `Solar export` Register.
_Avoid_: Feed-in, return, generation

**Solar Production**:
Energy produced by the on-site inverter (Fronius), measured by the inverter, not by the Meter.
_Avoid_: Generation, yield

**Home Consumption**:
Energy used by the premises: Grid Import + Solar Production − Solar Export.
_Avoid_: Load, usage

### In Home Assistant

**Upload**:
The user action of submitting an Interval Data File for a Meter; the newest Upload wins for every Interval Reading it contains.
_Avoid_: Import (reserved for Grid Import), ingest, sync

**Register Statistic**:
The hourly long-term statistic in Home Assistant holding one Register's history for one Meter.
_Avoid_: Sensor, entity, series

**Data Lag**:
The 2–3 day gap between now and the newest Interval available from Synergy.
