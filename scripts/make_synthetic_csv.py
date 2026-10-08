#!/usr/bin/env python3
"""Generate synthetic Synergy interval data files (stdlib only, deterministic).

Shape is modelled on real exports (Perth, ~5 kW inverter, no battery) but every
value here is invented; no real data is used or committed.

    make_synthetic_csv.py --start 2026-01-05 --end 2026-01-18 --seed 1 > summer.csv
    make_synthetic_csv.py --fixtures tests/fixtures
"""

from __future__ import annotations

import argparse
import math
import random
import sys
from datetime import date, datetime, time, timedelta
from pathlib import Path

DEFAULT_REGISTERS = ("ANYTIME (KWH)", "Solar export (Units)")
TOU_REGISTERS = ("PEAK (KWH)", "OFF-PEAK (KWH)", "SUPER OFF-PEAK (KWH)", "Solar export (Units)")
INTERVAL = timedelta(minutes=30)


def _solar_kwh(when: datetime, peak: float, cloud: float) -> float:
    """Bell curve between 07:00 and 17:30 local, scaled by season and cloud."""
    hour = when.hour + when.minute / 60 + 0.25  # mid-interval
    if not 7.0 <= hour <= 17.5:
        return 0.0
    return peak * cloud * math.sin(math.pi * (hour - 7.0) / 10.5) ** 2


def _load_kwh(when: datetime, rng: random.Random) -> float:
    """Overnight base load plus a morning and an evening bump."""
    hour = when.hour + when.minute / 60
    load = 0.2 + rng.uniform(-0.03, 0.03)
    if 6.0 <= hour < 8.5:
        load += 0.25
    if 17.0 <= hour < 21.0:
        load += rng.uniform(0.3, 0.6)
    return load


def _tou_register(when: datetime) -> str:
    if 9 <= when.hour < 15:
        return "SUPER OFF-PEAK (KWH)"
    if 15 <= when.hour < 21:
        return "PEAK (KWH)"
    return "OFF-PEAK (KWH)"


def generate(
    start: date,
    end: date,
    *,
    seed: int = 0,
    registers: tuple[str, ...] = DEFAULT_REGISTERS,
    drop: frozenset[tuple[date, time]] = frozenset(),
    last_day_until: time | None = None,
) -> str:
    """Return the CSV text for [start, end], inclusive."""
    rng = random.Random(seed)
    tou = "PEAK (KWH)" in registers
    lines = [",".join(["Date", "Time", *registers, "Billing Status"])]
    day = start
    while day <= end:
        summer = day.month in (12, 1, 2)
        peak = 1.8 if summer else 1.0
        cloud = rng.choice((1.0, 1.0, 0.8, 0.4))
        for slot in range(48):
            when = datetime.combine(day, time(slot // 2, 30 * (slot % 2)))
            if (day, when.time()) in drop:
                continue
            if day == end and last_day_until is not None and when.time() > last_day_until:
                continue
            solar = _solar_kwh(when, peak, cloud)
            load = _load_kwh(when, rng)
            grid_import = max(load - solar, 0.0)
            export = max(solar - load, 0.0)
            values: dict[str, float] = {"Solar export (Units)": export}
            if tou:
                for name in registers:
                    values.setdefault(name, 0.0)
                values[_tou_register(when)] = grid_import
            else:
                values["ANYTIME (KWH)"] = grid_import
            cells = [f"{values[name]:.3f}" for name in registers]
            lines.append(",".join([when.strftime("%d/%m/%Y,%H:%M"), *cells, "Billed"]))
        day += timedelta(days=1)
    return "\n".join(lines) + "\n"


def write_fixtures(directory: Path) -> None:
    """Write the small committed fixtures used by the test-suite."""
    directory.mkdir(parents=True, exist_ok=True)
    summer = (date(2026, 1, 5), date(2026, 1, 18))
    out = {
        "summer_2w.csv": generate(*summer, seed=1),
        "winter_2w.csv": generate(date(2026, 7, 6), date(2026, 7, 19), seed=2),
        # Same dates as summer_2w, different values (seed) to prove replacement.
        "overlap.csv": generate(date(2026, 1, 12), date(2026, 1, 25), seed=3),
        "partial_day.csv": generate(
            date(2026, 1, 5), date(2026, 1, 6), seed=4, last_day_until=time(14, 0)
        ),
        "with_gap.csv": generate(
            date(2026, 1, 5),
            date(2026, 1, 6),
            seed=5,
            drop=frozenset((date(2026, 1, 5), time(h, m)) for h in (10, 11) for m in (0, 30)),
        ),
        "tou_registers.csv": generate(
            date(2026, 1, 5), date(2026, 1, 7), seed=6, registers=TOU_REGISTERS
        ),
    }
    header = "Date,Time,ANYTIME (KWH),Solar export (Units),Billing Status\n"
    out.update(
        {
            "invalid_header.csv": "Foo,Bar\n1,2\n",
            "invalid_no_registers.csv": "Date,Time,Billing Status\n05/01/2026,00:00,Billed\n",
            "invalid_column_count.csv": header + "05/01/2026,00:00,0.200,Billed\n",
            "invalid_datetime.csv": header + "31/02/2026,00:00,0.200,0.000,Billed\n",
            "invalid_boundary.csv": header + "05/01/2026,00:15,0.200,0.000,Billed\n",
            "invalid_value.csv": header + "05/01/2026,00:00,abc,0.000,Billed\n",
            "invalid_negative.csv": header + "05/01/2026,00:00,-0.1,0.000,Billed\n",
            "invalid_duplicate.csv": header + "05/01/2026,00:00,0.2,0,Billed\n"
            "05/01/2026,00:00,0.3,0,Billed\n",
            "invalid_empty.csv": header,
        }
    )
    for name, text in out.items():
        (directory / name).write_text(text, encoding="utf-8", newline="\n")


def _parse_time(text: str) -> time:
    return datetime.strptime(text, "%H:%M").time()


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--start", type=date.fromisoformat)
    parser.add_argument("--end", type=date.fromisoformat)
    parser.add_argument("--seed", type=int, default=0)
    parser.add_argument("--preset", choices=("default", "tou"), default="default")
    parser.add_argument("--partial-last-day", type=_parse_time, metavar="HH:MM")
    parser.add_argument("--drop", action="append", default=[], metavar="YYYY-MM-DDTHH:MM")
    parser.add_argument("--fixtures", type=Path, help="write the committed fixtures here")
    args = parser.parse_args(argv)

    if args.fixtures:
        write_fixtures(args.fixtures)
        return 0
    if not (args.start and args.end):
        parser.error("--start and --end are required unless --fixtures is given")
    drops = frozenset(
        (datetime.fromisoformat(d).date(), datetime.fromisoformat(d).time()) for d in args.drop
    )
    registers = TOU_REGISTERS if args.preset == "tou" else DEFAULT_REGISTERS
    sys.stdout.write(
        generate(
            args.start,
            args.end,
            seed=args.seed,
            registers=registers,
            drop=drops,
            last_day_until=args.partial_last_day,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
