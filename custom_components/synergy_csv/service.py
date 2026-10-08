"""Upload use-case, written against ports so Home Assistant stays at the edge.

``LedgerRepository`` and ``StatisticsPublisher`` are the two seams; the
Home Assistant adapters live in ``store.py`` and ``statistics.py``.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, tzinfo
from typing import Protocol

from .parser import ParsedFile
from .readings import Gap, HourlyPoint, Ledger, find_gaps, hourly_points, merge


class LedgerRepository(Protocol):
    """Persists the Meter's stored Interval Readings."""

    async def load(self) -> Ledger: ...
    async def save(self, ledger: Ledger) -> None: ...
    async def clear(self) -> None: ...


class StatisticsPublisher(Protocol):
    """Publishes hourly Register Statistics to the host system."""

    def publish(self, slug: str, name: str, points: list[HourlyPoint]) -> None: ...
    def clear(self, slugs: list[str]) -> None: ...


@dataclass(frozen=True)
class UploadSummary:
    """What an Upload did, for showing to the user."""

    first: datetime
    last: datetime
    new: int
    replaced: int
    registers: list[str]
    gaps: list[Gap] = field(default_factory=list)
    ignored_columns: list[str] = field(default_factory=list)


class UploadService:
    """Merges Uploads into the Ledger and keeps Register Statistics in step."""

    def __init__(
        self,
        repository: LedgerRepository,
        publisher: StatisticsPublisher,
        tz: tzinfo,
    ) -> None:
        self._repository = repository
        self._publisher = publisher
        self._tz = tz

    async def upload(self, parsed: ParsedFile) -> UploadSummary:
        ledger = await self._repository.load()
        result = merge(ledger.readings, parsed.readings)
        renamed = {s for s, n in parsed.names.items() if ledger.names.get(s, n) != n}
        ledger.names.update(parsed.names)
        await self._repository.save(ledger)

        # Sums are cumulative, so everything after the earliest change is rebuilt.
        for slug, earliest in result.earliest_change.items():
            points = hourly_points(ledger.readings[slug], self._tz, from_interval=earliest)
            self._publisher.publish(slug, ledger.names[slug], points)

        for slug in renamed - result.earliest_change.keys():
            all_points = hourly_points(ledger.readings[slug], self._tz)
            self._publisher.publish(slug, ledger.names[slug], all_points)

        intervals = {start for by_interval in parsed.readings.values() for start in by_interval}
        return UploadSummary(
            first=min(intervals),
            last=max(intervals),
            new=result.new,
            replaced=result.replaced,
            registers=list(parsed.names.values()),
            gaps=find_gaps(intervals),
            ignored_columns=parsed.ignored_columns,
        )

    async def delete_all(self) -> None:
        ledger = await self._repository.load()
        self._publisher.clear(list(ledger.names))
        await self._repository.clear()
