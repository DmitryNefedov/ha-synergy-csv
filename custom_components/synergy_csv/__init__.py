"""Synergy (WA) CSV Import: upload interval data files as long-term statistics."""

from __future__ import annotations

from datetime import UTC, tzinfo

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import ConfigEntryError
from homeassistant.util import dt as dt_util

from .const import CONF_METER_NAME, SYNERGY_TIME_ZONE
from .service import UploadService
from .slug import slugify
from .statistics import RecorderStatisticsPublisher
from .store import StoreLedgerRepository

type SynergyConfigEntry = ConfigEntry[UploadService]


def _build_service(hass: HomeAssistant, entry: ConfigEntry, tz: tzinfo) -> UploadService:
    name = entry.data[CONF_METER_NAME]
    return UploadService(
        StoreLedgerRepository(hass, entry.entry_id),
        RecorderStatisticsPublisher(hass, slugify(name), name),
        tz,
    )


async def async_setup_entry(hass: HomeAssistant, entry: SynergyConfigEntry) -> bool:
    tz = await dt_util.async_get_time_zone(SYNERGY_TIME_ZONE)
    if tz is None:
        raise ConfigEntryError(f"Time zone data for {SYNERGY_TIME_ZONE} is unavailable")
    entry.runtime_data = _build_service(hass, entry, tz)
    return True


async def async_unload_entry(hass: HomeAssistant, entry: SynergyConfigEntry) -> bool:
    return True


async def async_remove_entry(hass: HomeAssistant, entry: ConfigEntry) -> None:
    """Removing a Meter deletes its stored readings and statistics."""
    await _build_service(hass, entry, UTC).delete_all()
