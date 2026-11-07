"""Diagnostics for the Home Assistant Hildebrand Glow IHD Integration."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from homeassistant.components.diagnostics import async_redact_data
from homeassistant.const import CONF_DEVICE_ID

from .const import DEFAULT_DEVICE_ID

if TYPE_CHECKING:
    from homeassistant.core import HomeAssistant

    from .models import GlowConfigEntry

# Device IDs are MAC addresses, and the meter point numbers identify the home
TO_REDACT = {
    CONF_DEVICE_ID,
    "eui",
    "ethmac",
    "mpan",
    "mprn",
    "title",
    "unique_id",
}


async def async_get_config_entry_diagnostics(
    hass: HomeAssistant,  # noqa: ARG001
    entry: GlowConfigEntry,
) -> dict[str, Any]:
    """Return diagnostics for a config entry."""
    settings = entry.runtime_data
    return {
        "entry": async_redact_data(entry.as_dict(), TO_REDACT),
        "settings": {
            "detects_every_device": settings.device_id == DEFAULT_DEVICE_ID,
            "topic_prefix": settings.topic_prefix,
            "time_zone_electricity": str(settings.time_zone_electricity),
            "time_zone_gas": str(settings.time_zone_gas),
        },
        # Listed in the order they were found, without their IDs
        "devices": [
            {
                "available": device.available,
                "last_seen": device.last_seen.isoformat(),
                "payloads": async_redact_data(
                    {str(kind): payload for kind, payload in device.payloads.items()},
                    TO_REDACT,
                ),
            }
            for device in settings.devices.values()
        ],
    }
