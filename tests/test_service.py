"""UploadService behaviour against in-memory fakes of its two ports."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta, timezone
from pathlib import Path

import pytest

from custom_components.synergy_csv.parser import parse_interval_file
from custom_components.synergy_csv.readings import HourlyPoint, Ledger, merge
from custom_components.synergy_csv.service import UploadService
from custom_components.synergy_csv.summary import format_summary

PERTH = timezone(timedelta(hours=8))
FIXTURES = Path(__file__).parent / "fixtures"


class FakeRepository:
    def __init__(self) -> None:
        self.ledger = Ledger()
        self.saves = 0

    async def load(self) -> Ledger:
        return Ledger.from_json(self.ledger.to_json())  # a copy, like real storage

    async def save(self, ledger: Ledger) -> None:
        self.saves += 1
        self.ledger = Ledger.from_json(ledger.to_json())

    async def clear(self) -> None:
        self.ledger = Ledger()


@dataclass
class FakePublisher:
    """Mimics the recorder: upserts rows by hour, never recomputes sums."""

    rows: dict[str, dict[datetime, float]] = field(default_factory=dict)
    names: dict[str, str] = field(default_factory=dict)
    published: list[tuple[str, int]] = field(default_factory=list)
    cleared: list[list[str]] = field(default_factory=list)

    def publish(self, slug: str, name: str, points: list[HourlyPoint]) -> None:
        self.names[slug] = name
        self.published.append((slug, len(points)))
        self.rows.setdefault(slug, {}).update({p.start: p.sum for p in points})

    def clear(self, slugs: list[str]) -> None:
        self.cleared.append(slugs)
        for slug in slugs:
            self.rows.pop(slug, None)


def fixture(name: str):
    return parse_interval_file((FIXTURES / name).read_text())


@pytest.fixture
def repo() -> FakeRepository:
    return FakeRepository()


@pytest.fixture
def publisher() -> FakePublisher:
    return FakePublisher()


@pytest.fixture
def service(repo: FakeRepository, publisher: FakePublisher) -> UploadService:
    return UploadService(repo, publisher, PERTH)


async def test_first_upload_stores_readings_and_publishes_every_register(
    service: UploadService, repo: FakeRepository, publisher: FakePublisher
) -> None:
    summary = await service.upload(fixture("summer_2w.csv"))

    assert summary.new == 2 * 14 * 48
    assert summary.replaced == 0
    assert summary.registers == ["ANYTIME", "Solar export"]
    assert summary.first == datetime(2026, 1, 5, 0, 0)
    assert summary.last == datetime(2026, 1, 18, 23, 30)
    assert summary.gaps == []
    assert set(publisher.rows) == {"anytime", "solar_export"}
    assert len(publisher.rows["anytime"]) == 14 * 24
    assert repo.ledger.names == {"anytime": "ANYTIME", "solar_export": "Solar export"}


async def test_reuploading_the_same_file_publishes_nothing_new(
    service: UploadService, publisher: FakePublisher
) -> None:
    await service.upload(fixture("summer_2w.csv"))
    publisher.published.clear()

    summary = await service.upload(fixture("summer_2w.csv"))

    assert (summary.new, summary.replaced) == (0, 2 * 14 * 48)
    assert publisher.published == []


async def test_upload_order_does_not_change_the_statistics(
    repo: FakeRepository, publisher: FakePublisher
) -> None:
    """Out-of-order uploads must equal date-ordered uploads (ADR 0002)."""
    forward_pub = FakePublisher()
    forward = UploadService(FakeRepository(), forward_pub, PERTH)
    await forward.upload(fixture("summer_2w.csv"))
    await forward.upload(fixture("winter_2w.csv"))

    backward = UploadService(repo, publisher, PERTH)
    await backward.upload(fixture("winter_2w.csv"))
    await backward.upload(fixture("summer_2w.csv"))

    assert publisher.rows == forward_pub.rows


async def test_overlapping_upload_replaces_values_and_shifts_later_sums(
    service: UploadService, publisher: FakePublisher
) -> None:
    await service.upload(fixture("summer_2w.csv"))
    before = dict(publisher.rows["anytime"])

    summary = await service.upload(fixture("overlap.csv"))

    overlap = 7 * 48 * 2  # 12..18 Jan, both registers
    assert summary.replaced == overlap
    assert summary.new == 2 * 7 * 48  # 19..25 Jan
    after = publisher.rows["anytime"]
    untouched = datetime(2026, 1, 11, 15, 0, tzinfo=UTC)  # 11 Jan 23:00 Perth
    assert after[untouched] == before[untouched]
    assert after[max(after)] != before[max(before)]


async def test_overlapping_uploads_equal_one_combined_upload(
    repo: FakeRepository, publisher: FakePublisher
) -> None:
    await UploadService(repo, publisher, PERTH).upload(fixture("summer_2w.csv"))
    await UploadService(repo, publisher, PERTH).upload(fixture("overlap.csv"))

    combined = fixture("summer_2w.csv")
    merge(combined.readings, fixture("overlap.csv").readings)  # newest wins
    expected = FakePublisher()
    await UploadService(FakeRepository(), expected, PERTH).upload(combined)

    assert publisher.rows == expected.rows


async def test_renamed_register_is_republished_even_if_no_value_changed(
    service: UploadService, publisher: FakePublisher
) -> None:
    await service.upload(fixture("summer_2w.csv"))
    publisher.published.clear()
    renamed = (FIXTURES / "summer_2w.csv").read_text().replace("Solar export", "Solar Export")

    await service.upload(parse_interval_file(renamed))

    assert publisher.published == [("solar_export", 14 * 24)]
    assert publisher.names["solar_export"] == "Solar Export"


async def test_partial_day_is_completed_by_a_later_upload(
    service: UploadService, publisher: FakePublisher
) -> None:
    await service.upload(fixture("partial_day.csv"))
    partial_last = max(publisher.rows["anytime"])

    await service.upload(fixture("summer_2w.csv"))  # covers the whole of 5..18 Jan

    assert max(publisher.rows["anytime"]) > partial_last
    assert len(publisher.rows["anytime"]) == 14 * 24


async def test_gaps_inside_the_file_are_reported(service: UploadService) -> None:
    summary = await service.upload(fixture("with_gap.csv"))

    assert [g.count for g in summary.gaps] == [4]
    assert summary.gaps[0].start == datetime(2026, 1, 5, 10, 0)
    assert "4 missing intervals in 1 places" in format_summary(summary)


async def test_ignored_columns_are_surfaced(service: UploadService) -> None:
    parsed = parse_interval_file(
        "Date,Time,ANYTIME (KWH),Reactive (KVARH)\n01/06/2026,00:00,0.1,0.2\n"
    )

    summary = await service.upload(parsed)

    assert summary.ignored_columns == ["Reactive (KVARH)"]
    assert "Ignored columns:** Reactive (KVARH)" in format_summary(summary)


async def test_time_of_use_registers_each_get_a_statistic(
    service: UploadService, publisher: FakePublisher
) -> None:
    await service.upload(fixture("tou_registers.csv"))

    assert set(publisher.rows) == {"peak", "off_peak", "super_off_peak", "solar_export"}


async def test_delete_all_clears_statistics_and_readings(
    service: UploadService, repo: FakeRepository, publisher: FakePublisher
) -> None:
    await service.upload(fixture("summer_2w.csv"))

    await service.delete_all()

    assert publisher.cleared == [["anytime", "solar_export"]]
    assert publisher.rows == {}
    assert repo.ledger == Ledger()


def test_format_summary_without_gaps() -> None:
    from custom_components.synergy_csv.service import UploadSummary

    text = format_summary(
        UploadSummary(
            first=datetime(2026, 6, 1),
            last=datetime(2026, 8, 30, 23, 30),
            new=8736,
            replaced=0,
            registers=["ANYTIME", "Solar export"],
        )
    )

    assert "01/06/2026 – 30/08/2026" in text
    assert "8,736 new, 0 replaced" in text
    assert "**Registers:** ANYTIME, Solar export" in text
    assert "**Gaps:** none" in text
    assert "Ignored" not in text
