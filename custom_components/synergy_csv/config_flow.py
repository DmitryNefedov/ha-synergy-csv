"""Config flow (add a Meter) and options flow (Upload / Delete all data)."""

from __future__ import annotations

from typing import Any, cast

import voluptuous as vol
from homeassistant.components.file_upload import process_uploaded_file
from homeassistant.config_entries import ConfigEntry, ConfigFlow, ConfigFlowResult, OptionsFlow
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.selector import FileSelector, FileSelectorConfig

from . import SynergyConfigEntry
from .const import CONF_METER_NAME, DEFAULT_METER_NAME, DOMAIN
from .parser import IntervalFileError, ParsedFile, parse_interval_file
from .service import UploadService
from .slug import slugify
from .summary import format_summary

CONF_FILE = "file"


def _read_and_parse(hass: HomeAssistant, file_id: str) -> ParsedFile:
    """Blocking: read the uploaded file (deleting it afterwards) and parse it."""
    with process_uploaded_file(hass, file_id) as path:
        try:
            text = path.read_text(encoding="utf-8-sig")
        except UnicodeDecodeError:
            raise IntervalFileError("File is not UTF-8 text") from None
    return parse_interval_file(text)


class SynergyConfigFlow(ConfigFlow, domain=DOMAIN):
    VERSION = 1

    async def async_step_user(self, user_input: dict[str, Any] | None = None) -> ConfigFlowResult:
        errors: dict[str, str] = {}
        if user_input is not None:
            name = user_input[CONF_METER_NAME].strip()
            slug = slugify(name)
            if slug:
                await self.async_set_unique_id(slug)
                self._abort_if_unique_id_configured()
                return self.async_create_entry(title=name, data={CONF_METER_NAME: name})
            errors[CONF_METER_NAME] = "invalid_name"
        return self.async_show_form(
            step_id="user",
            data_schema=vol.Schema(
                {vol.Required(CONF_METER_NAME, default=DEFAULT_METER_NAME): str}
            ),
            errors=errors,
        )

    @staticmethod
    @callback
    def async_get_options_flow(config_entry: ConfigEntry) -> SynergyOptionsFlow:
        return SynergyOptionsFlow()


class SynergyOptionsFlow(OptionsFlow):
    """Configure button: upload a file any number of times, or delete all data."""

    _summary: str = ""

    @property
    def _service(self) -> UploadService:
        entry = cast(SynergyConfigEntry, self.config_entry)
        return entry.runtime_data

    async def async_step_init(self, user_input: dict[str, Any] | None = None) -> ConfigFlowResult:
        return self.async_show_menu(step_id="init", menu_options=["upload", "delete"])

    async def async_step_upload(self, user_input: dict[str, Any] | None = None) -> ConfigFlowResult:
        errors: dict[str, str] = {}
        placeholders = {"error": ""}
        if user_input is not None:
            try:
                parsed = await self.hass.async_add_executor_job(
                    _read_and_parse, self.hass, user_input[CONF_FILE]
                )
            except IntervalFileError as err:
                errors["base"] = "invalid_file"
                placeholders["error"] = str(err)
            else:
                self._summary = format_summary(await self._service.upload(parsed))
                return await self.async_step_summary()
        return self.async_show_form(
            step_id="upload",
            data_schema=vol.Schema(
                {vol.Required(CONF_FILE): FileSelector(FileSelectorConfig(accept=".csv,text/csv"))}
            ),
            errors=errors,
            description_placeholders=placeholders,
        )

    async def async_step_summary(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        if user_input is not None:
            return self.async_create_entry(data=dict(self.config_entry.options))
        return self.async_show_form(
            step_id="summary", description_placeholders={"summary": self._summary}
        )

    async def async_step_delete(self, user_input: dict[str, Any] | None = None) -> ConfigFlowResult:
        """Submitting the empty confirmation form deletes everything."""
        if user_input is not None:
            await self._service.delete_all()
            return self.async_create_entry(data=dict(self.config_entry.options))
        return self.async_show_form(step_id="delete")
