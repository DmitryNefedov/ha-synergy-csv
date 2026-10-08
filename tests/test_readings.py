"""Merge, hourly aggregation, gap detection and ledger (de)serialisation."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta, timezone

import pytest

from custom_components.synergy_csv.readings import (
    Gap,
    Ledger,
    find_gaps,
    hourly_points,
    merge,
)

PERTH = timezone(timedelta(hours=8))


def dt(day: int, hour: int, minute: int = 0, month: int = 1) -> datetime:
    return datetime(2026, month, day, hour, minute)


class TestMerge:
    def test_counts_new_readings(self) -> None:
        stored: dict[str, dict[datetime, float]] = {}

        result = merge(stored, {"a": {dt(1, 0): 1.0, dt(1, 0, 30): 2.0}})

        assert (result.new, result.replaced) == (2, 0)
        assert stored == {"a": {dt(1, 0): 1.0, dt(1, 0, 30): 2.0}}
        assert result.earliest_change == {"a": dt(1, 0)}

    def test_replaces_existing_and_keeps_readings_absent_from_the_upload(self) -> None:
        stored = {"a": {dt(1, 0): 1.0, dt(1, 1): 5.0}}

        result = merge(stored, {"a": {dt(1, 0): 9.0, dt(1, 2): 3.0}})

        assert (result.new, result.replaced) == (1, 1)
        assert stored["a"] == {dt(1, 0): 9.0, dt(1, 1): 5.0, dt(1, 2): 3.0}
        assert result.earliest_change == {"a": dt(1, 0)}

    def test_identical_replacement_counts_but_is_not_a_change(self) -> None:
        stored = {"a": {dt(1, 0): 1.0}}

        result = merge(stored, {"a": {dt(1, 0): 1.0}})

        assert (result.new, result.replaced) == (0, 1)
        assert result.earliest_change == {}

    def test_earliest_change_is_tracked_per_register(self) -> None:
        stored = {"a": {dt(1, 0): 1.0}, "b": {dt(1, 0): 1.0}}

        result = merge(
            stored,
            {"a": {dt(3, 0): 1.0, dt(2, 0): 1.0}, "b": {dt(1, 0): 1.0}},
        )

        assert result.earliest_change == {"a": dt(2, 0)}


class TestHourlyPoints:
    def test_sums_two_half_hours_and_accumulates(self) -> None:
        readings = {dt(1, 0): 0.5, dt(1, 0, 30): 0.25, dt(1, 1): 1.0, dt(1, 1, 30): 0.0}

        points = hourly_points(readings, PERTH)

        assert [p.sum for p in points] == [0.75, 1.75]

    def test_start_is_the_utc_instant_of_the_perth_hour(self) -> None:
        points = hourly_points({dt(1, 8): 1.0}, PERTH)

        assert points[0].start == datetime(2026, 1, 1, 0, 0, tzinfo=UTC)
        assert points[0].start.utcoffset() == timedelta(0)

    def test_a_single_half_hour_is_used_on_its_own(self) -> None:
        points = hourly_points({dt(1, 0, 30): 0.4}, PERTH)

        assert [p.sum for p in points] == [0.4]

    def test_hours_without_readings_are_skipped_and_the_sum_stays_flat(self) -> None:
        points = hourly_points({dt(1, 0): 1.0, dt(1, 3): 2.0}, PERTH)

        assert [p.sum for p in points] == [1.0, 3.0]
        assert points[1].start - points[0].start == timedelta(hours=3)

    def test_from_interval_emits_the_hour_onwards_but_keeps_earlier_cumulative(self) -> None:
        readings = {dt(1, 0): 1.0, dt(1, 1): 1.0, dt(1, 2): 1.0}

        points = hourly_points(readings, PERTH, from_interval=dt(1, 1, 30))

        assert [p.sum for p in points] == [2.0, 3.0]

    def test_float_noise_is_rounded_away(self) -> None:
        readings = {dt(1, h): 0.1 for h in range(10)}

        points = hourly_points(readings, PERTH)

        assert points[-1].sum == 1.0

    def test_empty_readings(self) -> None:
        assert hourly_points({}, PERTH) == []


class TestFindGaps:
    def test_no_gap_for_contiguous_intervals(self) -> None:
        assert find_gaps([dt(1, 0), dt(1, 0, 30), dt(1, 1)]) == []

    def test_reports_each_run_of_missing_intervals(self) -> None:
        gaps = find_gaps([dt(1, 0), dt(1, 2), dt(1, 3), dt(1, 4, 30)])

        assert gaps == [
            Gap(start=dt(1, 0, 30), count=3),
            Gap(start=dt(1, 2, 30), count=1),
            Gap(start=dt(1, 3, 30), count=2),
        ]

    def test_input_order_is_irrelevant(self) -> None:
        assert find_gaps([dt(1, 1), dt(1, 0)]) == [Gap(start=dt(1, 0, 30), count=1)]

    def test_empty_input(self) -> None:
        assert find_gaps([]) == []


class TestLedger:
    def test_round_trips_through_json(self) -> None:
        ledger = Ledger(names={"a": "ANYTIME"}, readings={"a": {dt(1, 0): 0.5, dt(1, 0, 30): 0.25}})

        restored = Ledger.from_json(ledger.to_json())

        assert restored == ledger

    def test_empty_json_gives_an_empty_ledger(self) -> None:
        assert Ledger.from_json(None) == Ledger()

    def test_json_uses_minute_precision_iso_keys(self) -> None:
        ledger = Ledger(names={"a": "A"}, readings={"a": {dt(1, 0, 30): 1.0}})

        assert ledger.to_json()["registers"]["a"]["readings"] == {"2026-01-01T00:30": 1.0}

    @pytest.mark.parametrize("payload", [{}, {"registers": {}}])
    def test_missing_registers_are_tolerated(self, payload: dict) -> None:
        assert Ledger.from_json(payload) == Ledger()
