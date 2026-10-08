"""Stored Interval Readings: merging, hourly aggregation and gap detection.

Pure module: no Home Assistant imports. Interval keys are Perth-local naive
datetimes; the timezone is injected only where an absolute instant is needed.
"""

from __future__ import annotations

from collections import defaultdict
from collections.abc import Iterable
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta, tzinfo
from itertools import pairwise
from typing import Any

from .parser import Readings

INTERVAL = timedelta(minutes=30)
_SUM_DECIMALS = 6


@dataclass(frozen=True)
class MergeResult:
    """Outcome of merging an Upload into the stored readings."""

    new: int
    replaced: int
    earliest_change: dict[str, datetime]
    """Register slug -> earliest Interval whose value is new or different."""


@dataclass(frozen=True)
class HourlyPoint:
    """One hour of a Register Statistic: UTC hour start and cumulative kWh."""

    start: datetime
    sum: float


@dataclass(frozen=True)
class Gap:
    """A run of ``count`` consecutive missing Intervals beginning at ``start``."""

    start: datetime
    count: int


def merge(stored: Readings, incoming: Readings) -> MergeResult:
    """Merge ``incoming`` into ``stored`` in place; the newest value wins."""
    new = replaced = 0
    earliest: dict[str, datetime] = {}
    for slug, by_interval in incoming.items():
        target = stored.setdefault(slug, {})
        for start, value in by_interval.items():
            previous = target.get(start)
            if previous is None:
                new += 1
            else:
                replaced += 1
            if previous != value:
                target[start] = value
                if slug not in earliest or start < earliest[slug]:
                    earliest[slug] = start
    return MergeResult(new=new, replaced=replaced, earliest_change=earliest)


def hourly_points(
    readings: dict[datetime, float],
    tz: tzinfo,
    from_interval: datetime | None = None,
) -> list[HourlyPoint]:
    """Aggregate Intervals into hourly cumulative points, UTC-stamped.

    Sums always run from the first stored reading so they stay consistent with
    earlier hours; ``from_interval`` only limits which points are returned.
    """
    per_hour: dict[datetime, float] = defaultdict(float)
    for start, value in readings.items():
        per_hour[start.replace(minute=0)] += value

    first_hour = from_interval.replace(minute=0) if from_interval else None
    total = 0.0
    points: list[HourlyPoint] = []
    for hour in sorted(per_hour):
        total += per_hour[hour]
        if first_hour is None or hour >= first_hour:
            points.append(
                HourlyPoint(
                    start=hour.replace(tzinfo=tz).astimezone(UTC),
                    sum=round(total, _SUM_DECIMALS),
                )
            )
    return points


def find_gaps(intervals: Iterable[datetime]) -> list[Gap]:
    """Runs of missing Intervals strictly between the earliest and latest given."""
    ordered = sorted(set(intervals))
    gaps: list[Gap] = []
    for before, after in pairwise(ordered):
        missing = (after - before) // INTERVAL - 1
        if missing > 0:
            gaps.append(Gap(start=before + INTERVAL, count=missing))
    return gaps


@dataclass
class Ledger:
    """Everything stored for one Meter: Register names and their readings."""

    names: dict[str, str] = field(default_factory=dict)
    readings: Readings = field(default_factory=dict)

    def to_json(self) -> dict[str, Any]:
        return {
            "registers": {
                slug: {
                    "name": self.names[slug],
                    "readings": {
                        start.strftime("%Y-%m-%dT%H:%M"): value
                        for start, value in sorted(by_interval.items())
                    },
                }
                for slug, by_interval in self.readings.items()
            }
        }

    @classmethod
    def from_json(cls, data: dict[str, Any] | None) -> Ledger:
        ledger = cls()
        for slug, register in ((data or {}).get("registers") or {}).items():
            ledger.names[slug] = register["name"]
            ledger.readings[slug] = {
                datetime.strptime(key, "%Y-%m-%dT%H:%M"): value
                for key, value in register["readings"].items()
            }
        return ledger
