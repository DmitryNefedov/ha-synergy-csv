"""Home Assistant adapter: publish Register Statistics as external statistics."""

from __future__ import annotations

from homeassistant.components.recorder import get_instance
from homeassistant.components.recorder.models import (
    StatisticData,
    StatisticMeanType,
    StatisticMetaData,
)
from homeassistant.components.recorder.statistics import async_add_external_statistics
from homeassistant.const import UnitOfEnergy
from homeassistant.core import HomeAssistant
from homeassistant.util.unit_conversion import EnergyConverter

from .const import DOMAIN
from .readings import HourlyPoint


def statistic_id(meter_slug: str, register_slug: str) -> str:
    """``synergy_csv:<meter>_<register>``, the id users pick in dashboards."""
    return f"{DOMAIN}:{meter_slug}_{register_slug}"


class RecorderStatisticsPublisher:
    """StatisticsPublisher that writes to the HA recorder."""

    def __init__(self, hass: HomeAssistant, meter_slug: str, meter_name: str) -> None:
        self._hass = hass
        self._meter_slug = meter_slug
        self._meter_name = meter_name

    def publish(self, slug: str, name: str, points: list[HourlyPoint]) -> None:
        metadata = StatisticMetaData(
            mean_type=StatisticMeanType.NONE,
            has_sum=True,
            name=f"{self._meter_name} {name}",
            source=DOMAIN,
            statistic_id=statistic_id(self._meter_slug, slug),
            unit_class=EnergyConverter.UNIT_CLASS,
            unit_of_measurement=UnitOfEnergy.KILO_WATT_HOUR,
        )
        statistics = [StatisticData(start=p.start, state=p.sum, sum=p.sum) for p in points]
        async_add_external_statistics(self._hass, metadata, statistics)

    def clear(self, slugs: list[str]) -> None:
        if slugs:
            get_instance(self._hass).async_clear_statistics(
                [statistic_id(self._meter_slug, slug) for slug in slugs]
            )
