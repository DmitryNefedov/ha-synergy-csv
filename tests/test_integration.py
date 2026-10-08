"""Config/options flows and recorder statistics, on the real HA test harness."""

from __future__ import annotations

from datetime import UTC, datetime
from unittest.mock import patch

from homeassistant.components.recorder import get_instance
from homeassistant.components.recorder.statistics import (
    async_list_statistic_ids,
    statistics_during_period,
)
from homeassistant.config_entries import ConfigEntryState
from homeassistant.core import HomeAssistant
from homeassistant.data_entry_flow import FlowResultType
from pytest_homeassistant_custom_component.common import MockConfigEntry
from pytest_homeassistant_custom_component.components.recorder.common import (
    async_wait_recording_done,
)

from custom_components.synergy_csv.const import CONF_METER_NAME, DOMAIN

from .conftest import fixture_text

FILE_ID = "5c1e0a3e-2b43-4f4e-9a52-0c3a1a1f8e11"
ANYTIME = "synergy_csv:home_anytime"
EXPORT = "synergy_csv:home_solar_export"


async def setup_entry(hass: HomeAssistant, entry: MockConfigEntry) -> None:
    entry.add_to_hass(hass)
    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()


async def open_upload(hass: HomeAssistant, entry: MockConfigEntry) -> str:
    result = await hass.config_entries.options.async_init(entry.entry_id)
    assert result["type"] is FlowResultType.MENU
    assert result["menu_options"] == ["upload", "delete"]
    result = await hass.config_entries.options.async_configure(
        result["flow_id"], {"next_step_id": "upload"}
    )
    assert result["type"] is FlowResultType.FORM
    assert result["step_id"] == "upload"
    return result["flow_id"]


async def upload(hass, entry, fake_upload, content) -> dict:
    """Run one full Upload through the options flow and return the summary form."""
    flow_id = await open_upload(hass, entry)
    with fake_upload(content):
        result = await hass.config_entries.options.async_configure(flow_id, {"file": FILE_ID})
    if result["type"] is FlowResultType.FORM and result["step_id"] == "summary":
        done = await hass.config_entries.options.async_configure(flow_id, {})
        assert done["type"] is FlowResultType.CREATE_ENTRY
    return result


async def sums(hass: HomeAssistant, statistic_id: str) -> list[float]:
    await async_wait_recording_done(hass)
    rows = await get_instance(hass).async_add_executor_job(
        statistics_during_period,
        hass,
        datetime(2000, 1, 1, tzinfo=UTC),
        None,
        {statistic_id},
        "hour",
        None,
        {"sum"},
    )
    return [row["sum"] for row in rows.get(statistic_id, [])]


async def test_user_flow_creates_a_named_meter(hass: HomeAssistant) -> None:
    result = await hass.config_entries.flow.async_init(DOMAIN, context={"source": "user"})
    assert result["type"] is FlowResultType.FORM

    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], {CONF_METER_NAME: " Beach House "}
    )

    assert result["type"] is FlowResultType.CREATE_ENTRY
    assert result["title"] == "Beach House"
    assert result["data"] == {CONF_METER_NAME: "Beach House"}
    assert result["result"].unique_id == "beach_house"


async def test_user_flow_aborts_on_duplicate_meter(
    hass: HomeAssistant, entry: MockConfigEntry
) -> None:
    entry.add_to_hass(hass)

    result = await hass.config_entries.flow.async_init(DOMAIN, context={"source": "user"})
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], {CONF_METER_NAME: "HOME"}
    )

    assert result["type"] is FlowResultType.ABORT
    assert result["reason"] == "already_configured"


async def test_user_flow_rejects_a_name_without_letters_or_digits(hass: HomeAssistant) -> None:
    result = await hass.config_entries.flow.async_init(DOMAIN, context={"source": "user"})

    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], {CONF_METER_NAME: "!!!"}
    )

    assert result["type"] is FlowResultType.FORM
    assert result["errors"] == {CONF_METER_NAME: "invalid_name"}


async def test_upload_creates_hourly_kwh_statistics_with_metadata(
    hass: HomeAssistant, entry: MockConfigEntry, fake_upload
) -> None:
    await setup_entry(hass, entry)

    result = await upload(hass, entry, fake_upload, fixture_text("summer_2w.csv"))

    assert result["step_id"] == "summary"
    summary = result["description_placeholders"]["summary"]
    assert "05/01/2026 – 18/01/2026" in summary
    assert "1,344 new, 0 replaced" in summary
    await async_wait_recording_done(hass)
    ids = {item["statistic_id"]: item for item in await async_list_statistic_ids(hass)}
    assert ids[ANYTIME]["name"] == "Home ANYTIME"
    assert ids[ANYTIME]["statistics_unit_of_measurement"] == "kWh"
    assert ids[ANYTIME]["unit_class"] == "energy"
    assert ids[ANYTIME]["has_sum"] is True
    assert ids[ANYTIME]["source"] == DOMAIN
    assert ids[EXPORT]["name"] == "Home Solar export"
    values = await sums(hass, ANYTIME)
    assert len(values) == 14 * 24
    assert values == sorted(values)  # cumulative sums never decrease


async def test_out_of_order_uploads_match_date_ordered_uploads(
    hass: HomeAssistant, entry: MockConfigEntry, fake_upload
) -> None:
    await setup_entry(hass, entry)
    await upload(hass, entry, fake_upload, fixture_text("summer_2w.csv"))
    await upload(hass, entry, fake_upload, fixture_text("winter_2w.csv"))
    in_order = await sums(hass, ANYTIME)

    other = MockConfigEntry(
        domain=DOMAIN, title="Other", data={CONF_METER_NAME: "Other"}, unique_id="other"
    )
    await setup_entry(hass, other)
    await upload(hass, other, fake_upload, fixture_text("winter_2w.csv"))
    await upload(hass, other, fake_upload, fixture_text("summer_2w.csv"))

    assert await sums(hass, "synergy_csv:other_anytime") == in_order


async def test_overlapping_upload_replaces_values_and_extends_history(
    hass: HomeAssistant, entry: MockConfigEntry, fake_upload
) -> None:
    await setup_entry(hass, entry)
    await upload(hass, entry, fake_upload, fixture_text("summer_2w.csv"))
    first = await sums(hass, ANYTIME)

    result = await upload(hass, entry, fake_upload, fixture_text("overlap.csv"))

    second = await sums(hass, ANYTIME)
    assert len(second) == 21 * 24  # 5..25 Jan
    assert second[: 7 * 24] == first[: 7 * 24]  # 5..11 Jan untouched
    assert second[7 * 24] != first[7 * 24] or second[-1] != first[-1]
    assert "672 new, 672 replaced" in result["description_placeholders"]["summary"]


async def test_invalid_file_is_rejected_and_nothing_is_stored(
    hass: HomeAssistant, entry: MockConfigEntry, fake_upload
) -> None:
    await setup_entry(hass, entry)
    flow_id = await open_upload(hass, entry)

    with fake_upload(fixture_text("invalid_negative.csv")):
        result = await hass.config_entries.options.async_configure(flow_id, {"file": FILE_ID})

    assert result["type"] is FlowResultType.FORM
    assert result["step_id"] == "upload"
    assert result["errors"] == {"base": "invalid_file"}
    assert "Line 2: invalid value for ANYTIME" in result["description_placeholders"]["error"]
    assert await sums(hass, ANYTIME) == []


async def test_non_utf8_file_is_rejected(
    hass: HomeAssistant, entry: MockConfigEntry, fake_upload
) -> None:
    await setup_entry(hass, entry)
    flow_id = await open_upload(hass, entry)

    with fake_upload(b"Date,Time\n\xff\xfe\x00"):
        result = await hass.config_entries.options.async_configure(flow_id, {"file": FILE_ID})

    assert result["errors"] == {"base": "invalid_file"}
    assert "not UTF-8" in result["description_placeholders"]["error"]


async def test_delete_all_data_clears_statistics_and_storage(
    hass: HomeAssistant, entry: MockConfigEntry, fake_upload, hass_storage
) -> None:
    await setup_entry(hass, entry)
    await upload(hass, entry, fake_upload, fixture_text("summer_2w.csv"))
    assert await sums(hass, ANYTIME)
    assert f"{DOMAIN}.{entry.entry_id}" in hass_storage

    result = await hass.config_entries.options.async_init(entry.entry_id)
    result = await hass.config_entries.options.async_configure(
        result["flow_id"], {"next_step_id": "delete"}
    )
    assert result["type"] is FlowResultType.FORM
    assert result["step_id"] == "delete"
    result = await hass.config_entries.options.async_configure(result["flow_id"], {})

    assert result["type"] is FlowResultType.CREATE_ENTRY
    assert await sums(hass, ANYTIME) == []
    assert f"{DOMAIN}.{entry.entry_id}" not in hass_storage


async def test_removing_the_meter_deletes_its_data(
    hass: HomeAssistant, entry: MockConfigEntry, fake_upload, hass_storage
) -> None:
    await setup_entry(hass, entry)
    await upload(hass, entry, fake_upload, fixture_text("summer_2w.csv"))
    assert await sums(hass, EXPORT)

    await hass.config_entries.async_remove(entry.entry_id)
    await hass.async_block_till_done()

    assert await sums(hass, EXPORT) == []
    assert f"{DOMAIN}.{entry.entry_id}" not in hass_storage


async def test_entry_unloads_cleanly(hass: HomeAssistant, entry: MockConfigEntry) -> None:
    await setup_entry(hass, entry)

    assert await hass.config_entries.async_unload(entry.entry_id)

    assert entry.state is ConfigEntryState.NOT_LOADED


async def test_setup_fails_when_perth_time_zone_data_is_missing(
    hass: HomeAssistant, entry: MockConfigEntry
) -> None:
    entry.add_to_hass(hass)

    with patch("custom_components.synergy_csv.dt_util.async_get_time_zone", return_value=None):
        assert not await hass.config_entries.async_setup(entry.entry_id)

    assert entry.state is ConfigEntryState.SETUP_ERROR
