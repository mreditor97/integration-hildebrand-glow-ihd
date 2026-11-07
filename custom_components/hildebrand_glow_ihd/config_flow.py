"""Config flow for the Home Assistant Hildebrand Glow IHD Integration."""

from __future__ import annotations

import zoneinfo
from typing import TYPE_CHECKING, Any

import voluptuous as vol
from homeassistant.config_entries import (
    ConfigFlow,
    OptionsFlowWithReload,
)
from homeassistant.const import CONF_DEVICE_ID
from homeassistant.core import callback
from homeassistant.helpers.selector import (
    SelectSelector,
    SelectSelectorConfig,
    SelectSelectorMode,
)

from .const import (
    CONF_TIME_ZONE_ELECTRICITY,
    CONF_TIME_ZONE_GAS,
    CONF_TOPIC_PREFIX,
    DEFAULT_DEVICE_ID,
    DEFAULT_TOPIC_PREFIX,
    DOMAIN,
)
from .helpers import (
    entry_title,
    normalize_device_id,
    normalize_topic_prefix,
    parse_topic,
    settings_overlap,
)
from .models import entry_settings

if TYPE_CHECKING:
    from collections.abc import Mapping

    from homeassistant.config_entries import ConfigEntry, ConfigFlowResult
    from homeassistant.core import HomeAssistant
    from homeassistant.helpers.service_info.mqtt import MqttServiceInfo

# Home Assistant 2026.9 replaced voluptuous with probatio and installs probatio
# under the voluptuous name, while 2026.4 to 2026.8 use voluptuous itself.
# Importing voluptuous works on both, but mypy sees the real voluptuous types,
# hence the type ignores where the schemas are used.


def unique_id_for(device_id: str) -> str:
    """Return the config entry unique ID for a normalised device ID."""
    # Existing entries use this unique ID, don't change its format
    return f"{DOMAIN}_{device_id}"


def _device_schema(defaults: Mapping[str, Any]) -> dict[vol.Marker, Any]:
    """Return the form fields that choose which device's messages are read."""
    return {
        vol.Required(
            CONF_DEVICE_ID,
            default=defaults.get(CONF_DEVICE_ID, DEFAULT_DEVICE_ID),
        ): str,
        vol.Required(
            CONF_TOPIC_PREFIX,
            default=defaults.get(CONF_TOPIC_PREFIX, DEFAULT_TOPIC_PREFIX),
        ): str,
    }


async def _async_time_zone_schema(
    hass: HomeAssistant,
    defaults: Mapping[str, Any],
) -> dict[vol.Marker, Any]:
    """Return the form fields for the meters' time zones."""
    # Listing the time zones reads the disk, so don't do it in the event loop
    time_zones = await hass.async_add_executor_job(zoneinfo.available_timezones)
    time_zone_selector = SelectSelector(
        SelectSelectorConfig(
            options=list(time_zones),
            mode=SelectSelectorMode.DROPDOWN,
            sort=True,
        ),
    )
    return {
        vol.Required(
            CONF_TIME_ZONE_ELECTRICITY,
            default=defaults.get(CONF_TIME_ZONE_ELECTRICITY, hass.config.time_zone),
        ): time_zone_selector,
        vol.Required(
            CONF_TIME_ZONE_GAS,
            default=defaults.get(CONF_TIME_ZONE_GAS, hass.config.time_zone),
        ): time_zone_selector,
    }


def _normalize_device_input(user_input: Mapping[str, Any]) -> dict[str, Any]:
    """Return the form input with the device ID and topic prefix normalised."""
    return {
        **user_input,
        CONF_DEVICE_ID: normalize_device_id(user_input.get(CONF_DEVICE_ID)),
        CONF_TOPIC_PREFIX: normalize_topic_prefix(user_input.get(CONF_TOPIC_PREFIX)),
    }


class HildebrandGlowIHDMQTTConfigFlow(ConfigFlow, domain=DOMAIN):
    """Handle a config flow for a Glow IHD."""

    VERSION = 1
    # 1.2 normalised the device ID and topic prefix, and moved them out of
    # the options into the entry data. 1.3 removed "smart_meter_" from the
    # sensors' unique IDs.
    MINOR_VERSION = 3

    _discovered_device_id: str

    def _overlaps_other_entry(
        self,
        topic_prefix: str,
        device_id: str,
        exclude_entry_id: str | None = None,
    ) -> bool:
        """Return whether another entry already reads this device's messages."""
        for entry in self._async_current_entries(include_ignore=False):
            if entry.entry_id == exclude_entry_id:
                continue
            settings = entry_settings(entry)
            if settings_overlap(
                topic_prefix,
                device_id,
                normalize_topic_prefix(settings.get(CONF_TOPIC_PREFIX)),
                normalize_device_id(settings.get(CONF_DEVICE_ID)),
            ):
                return True
        return False

    async def async_step_user(
        self,
        user_input: dict[str, Any] | None = None,
    ) -> ConfigFlowResult:
        """Handle the initial step."""
        errors: dict[str, str] = {}
        if user_input is not None:
            user_input = _normalize_device_input(user_input)
            device_id = user_input[CONF_DEVICE_ID]
            await self.async_set_unique_id(unique_id_for(device_id))
            self._abort_if_unique_id_configured()
            if self._overlaps_other_entry(user_input[CONF_TOPIC_PREFIX], device_id):
                errors["base"] = "overlaps_existing_entry"
            else:
                return self.async_create_entry(
                    title=entry_title(device_id),
                    data=user_input,
                )

        defaults = user_input or {}
        return self.async_show_form(
            step_id="user",
            data_schema=vol.Schema(
                {  # type: ignore[arg-type]
                    **_device_schema(defaults),
                    **await _async_time_zone_schema(self.hass, defaults),
                },
            ),
            errors=errors,
        )

    async def async_step_mqtt(
        self,
        discovery_info: MqttServiceInfo,
    ) -> ConfigFlowResult:
        """Handle a Glow device found by MQTT discovery."""
        glow_topic = parse_topic(DEFAULT_TOPIC_PREFIX, discovery_info.topic)
        if glow_topic is None:
            return self.async_abort(reason="invalid_discovery_info")

        device_id = normalize_device_id(glow_topic.device_id)
        await self.async_set_unique_id(unique_id_for(device_id))
        self._abort_if_unique_id_configured()
        # An entry that detects every device already reads this one
        if self._overlaps_other_entry(DEFAULT_TOPIC_PREFIX, device_id):
            return self.async_abort(reason="already_configured")

        self._discovered_device_id = device_id
        self.context["title_placeholders"] = {"device_id": device_id}
        return await self.async_step_discovery_confirm()

    async def async_step_discovery_confirm(
        self,
        user_input: dict[str, Any] | None = None,
    ) -> ConfigFlowResult:
        """Confirm adding a discovered Glow device and choose its time zones."""
        device_id = self._discovered_device_id
        if user_input is not None:
            return self.async_create_entry(
                title=entry_title(device_id),
                data={
                    CONF_DEVICE_ID: device_id,
                    CONF_TOPIC_PREFIX: DEFAULT_TOPIC_PREFIX,
                    **user_input,
                },
            )

        return self.async_show_form(
            step_id="discovery_confirm",
            data_schema=vol.Schema(
                await _async_time_zone_schema(self.hass, {}),  # type: ignore[arg-type]
            ),
            description_placeholders={"device_id": device_id},
        )

    async def async_step_reconfigure(
        self,
        user_input: dict[str, Any] | None = None,
    ) -> ConfigFlowResult:
        """Change which device's messages an entry reads."""
        entry = self._get_reconfigure_entry()
        errors: dict[str, str] = {}
        if user_input is not None:
            user_input = _normalize_device_input(user_input)
            device_id = user_input[CONF_DEVICE_ID]
            if self._overlaps_other_entry(
                user_input[CONF_TOPIC_PREFIX],
                device_id,
                exclude_entry_id=entry.entry_id,
            ):
                errors["base"] = "overlaps_existing_entry"
            else:
                return self.async_update_reload_and_abort(
                    entry,
                    unique_id=unique_id_for(device_id),
                    title=entry_title(device_id),
                    data_updates=user_input,
                )

        return self.async_show_form(
            step_id="reconfigure",
            data_schema=vol.Schema(
                _device_schema(user_input or entry_settings(entry)),  # type: ignore[arg-type]
            ),
            errors=errors,
        )

    @staticmethod
    @callback
    def async_get_options_flow(
        config_entry: ConfigEntry,  # noqa: ARG004
    ) -> HildebrandGlowIHDMQTTOptionsFlowHandler:
        """Get the options flow for this handler."""
        return HildebrandGlowIHDMQTTOptionsFlowHandler()


class HildebrandGlowIHDMQTTOptionsFlowHandler(OptionsFlowWithReload):
    """Change the meters' time zones, then reload the entry to apply them.

    The device ID and topic prefix are changed with Reconfigure instead, so
    the entry's unique ID and title stay in step with them.
    """

    async def async_step_init(
        self,
        user_input: dict[str, Any] | None = None,
    ) -> ConfigFlowResult:
        """Handle options flow."""
        if user_input is not None:
            return self.async_create_entry(data=user_input)

        return self.async_show_form(
            step_id="init",
            data_schema=vol.Schema(
                await _async_time_zone_schema(  # type: ignore[arg-type]
                    self.hass,
                    entry_settings(self.config_entry),
                ),
            ),
        )
