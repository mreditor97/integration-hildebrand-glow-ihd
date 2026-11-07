"""Runtime data for the Home Assistant Hildebrand Glow IHD Integration."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any

from homeassistant.const import CONF_DEVICE_ID, CONF_NAME
from homeassistant.util import dt as dt_util

from .const import (
    CONF_TIME_ZONE_ELECTRICITY,
    CONF_TIME_ZONE_GAS,
    CONF_TOPIC_PREFIX,
)
from .helpers import normalize_device_id, normalize_topic_prefix

if TYPE_CHECKING:
    from datetime import datetime, tzinfo

    from homeassistant.config_entries import ConfigEntry

    from .const import TopicKind

type GlowConfigEntry = ConfigEntry[GlowRuntimeData]


@dataclass(slots=True)
class GlowDeviceState:
    """What has been heard from one Glow device since the entry was set up."""

    # The device's name, which new entity IDs are made from
    name: str
    last_seen: datetime
    available: bool = True
    # The latest payload of each kind of message, for diagnostics
    payloads: dict[TopicKind, dict[str, Any]] = field(default_factory=dict)


@dataclass(frozen=True, slots=True)
class GlowRuntimeData:
    """Settings for a config entry, resolved once when it is set up."""

    device_id: str
    topic_prefix: str
    time_zone_electricity: tzinfo
    time_zone_gas: tzinfo
    # The name given at setup, None for entries made before there was one
    name: str | None = None
    # The devices heard from so far, by device ID
    devices: dict[str, GlowDeviceState] = field(default_factory=dict)


def entry_settings(entry: ConfigEntry) -> dict[str, Any]:
    """Return an entry's settings, with options saved by Configure on top."""
    return {**entry.data, **entry.options}


async def _async_time_zone(name: str | None) -> tzinfo:
    """Return a time zone by name, or Home Assistant's own if it is unknown."""
    if name and (time_zone := await dt_util.async_get_time_zone(name)):
        return time_zone
    return dt_util.get_default_time_zone()


async def async_build_runtime_data(entry: ConfigEntry) -> GlowRuntimeData:
    """Return the runtime data for a config entry."""
    settings = entry_settings(entry)
    return GlowRuntimeData(
        device_id=normalize_device_id(settings.get(CONF_DEVICE_ID)),
        topic_prefix=normalize_topic_prefix(settings.get(CONF_TOPIC_PREFIX)),
        time_zone_electricity=await _async_time_zone(
            settings.get(CONF_TIME_ZONE_ELECTRICITY),
        ),
        time_zone_gas=await _async_time_zone(settings.get(CONF_TIME_ZONE_GAS)),
        name=(settings.get(CONF_NAME) or "").strip() or None,
    )
