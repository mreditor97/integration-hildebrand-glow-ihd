"""Runtime data for the Home Assistant Hildebrand Glow IHD Integration."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any

from homeassistant.const import CONF_DEVICE_ID, CONF_NAME
from homeassistant.util import dt as dt_util

from .const import (
    CONF_ELECTRICITY_TARIFF_TYPE,
    CONF_ELECTRICITY_UNIT_RATE_ENTITY,
    CONF_TIME_ZONE_ELECTRICITY,
    CONF_TIME_ZONE_GAS,
    CONF_TOPIC_PREFIX,
    DEFAULT_ELECTRICITY_TARIFF_TYPE,
    ELECTRICITY_TARIFF_TYPES,
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
    # Whether the name was given at setup, rather than made from the ID
    named: bool = False
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
    electricity_tariff_type: str = DEFAULT_ELECTRICITY_TARIFF_TYPE
    # The sensor a variable tariff's unit rate is read from, if one is set
    electricity_unit_rate_entity: str | None = None
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
    electricity_tariff_type = settings.get(
        CONF_ELECTRICITY_TARIFF_TYPE,
        DEFAULT_ELECTRICITY_TARIFF_TYPE,
    )
    if electricity_tariff_type not in ELECTRICITY_TARIFF_TYPES:
        electricity_tariff_type = DEFAULT_ELECTRICITY_TARIFF_TYPE
    return GlowRuntimeData(
        device_id=normalize_device_id(settings.get(CONF_DEVICE_ID)),
        topic_prefix=normalize_topic_prefix(settings.get(CONF_TOPIC_PREFIX)),
        time_zone_electricity=await _async_time_zone(
            settings.get(CONF_TIME_ZONE_ELECTRICITY),
        ),
        time_zone_gas=await _async_time_zone(settings.get(CONF_TIME_ZONE_GAS)),
        electricity_tariff_type=electricity_tariff_type,
        electricity_unit_rate_entity=(
            settings.get(CONF_ELECTRICITY_UNIT_RATE_ENTITY) or None
        ),
        name=(settings.get(CONF_NAME) or "").strip() or None,
    )
