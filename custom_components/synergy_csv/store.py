"""Home Assistant adapter: persist the Ledger in ``.storage``."""

from __future__ import annotations

from typing import Any

from homeassistant.core import HomeAssistant
from homeassistant.helpers.storage import Store

from .const import DOMAIN, STORAGE_VERSION
from .readings import Ledger


class StoreLedgerRepository:
    """LedgerRepository backed by a per-Meter ``Store``."""

    def __init__(self, hass: HomeAssistant, entry_id: str) -> None:
        self._store: Store[dict[str, Any]] = Store(
            hass, STORAGE_VERSION, f"{DOMAIN}.{entry_id}", serialize_in_event_loop=False
        )

    async def load(self) -> Ledger:
        return Ledger.from_json(await self._store.async_load())

    async def save(self, ledger: Ledger) -> None:
        await self._store.async_save(ledger.to_json())

    async def clear(self) -> None:
        await self._store.async_remove()
