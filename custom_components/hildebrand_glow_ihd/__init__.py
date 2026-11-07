"""The Home Assistant Hildebrand Glow IHD Integration."""

from __future__ import annotations

import logging
from functools import partial
from typing import TYPE_CHECKING, Any

from awesomeversion import AwesomeVersion
from homeassistant.components import mqtt
from homeassistant.const import CONF_DEVICE_ID
from homeassistant.const import __version__ as HA_VERSION  # noqa: N812
from homeassistant.core import callback
from homeassistant.exceptions import ConfigEntryNotReady
from homeassistant.helpers import config_validation as cv
from homeassistant.helpers import entity_registry as er
from homeassistant.helpers import issue_registry as ir

from .const import CONF_TOPIC_PREFIX, DOMAIN, MIN_HA_VERSION, PLATFORMS
from .helpers import (
    entry_title,
    no_messages_issue_id,
    normalize_device_id,
    normalize_topic_prefix,
)
from .models import async_build_runtime_data, entry_settings

if TYPE_CHECKING:
    from homeassistant.config_entries import ConfigEntry
    from homeassistant.core import HomeAssistant
    from homeassistant.helpers import device_registry as dr
    from homeassistant.helpers.typing import ConfigType

    from .models import GlowConfigEntry

_LOGGER = logging.getLogger(__name__)

# Sensor unique IDs made before entry version 1.3 had this after the device ID
OLD_UNIQUE_ID_PART = "_smart_meter_"

# Set up from the UI only, there is no YAML configuration
CONFIG_SCHEMA = cv.config_entry_only_config_schema(DOMAIN)


async def async_setup(
    hass: HomeAssistant,  # noqa: ARG001
    config: ConfigType,  # noqa: ARG001
) -> bool:
    """Set up the Home Assistant Hildebrand Glow IHD Integration."""
    if AwesomeVersion(HA_VERSION) < AwesomeVersion(MIN_HA_VERSION):  # pragma: no cover
        _LOGGER.critical(
            "This integration requires at least Home Assistant version %s, you"
            " are running version %s. Please upgrade Home Assistant to continue"
            " using this integration.",
            MIN_HA_VERSION,
            HA_VERSION,
        )
        return False
    return True


async def async_migrate_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Migrate a config entry from an earlier version."""
    if entry.version > 1:
        # Made by a newer version of the integration
        return False

    if entry.minor_version < 2:  # noqa: PLR2004
        # Normalise the device ID and topic prefix, and move them out of the
        # options, where Configure used to save them. They are changed with
        # Reconfigure now, which keeps the unique ID and title in step.
        settings = entry_settings(entry)
        old_device_id = settings.get(CONF_DEVICE_ID)
        device_id = normalize_device_id(old_device_id)
        updates: dict[str, Any] = {
            "data": {
                **entry.data,
                CONF_DEVICE_ID: device_id,
                CONF_TOPIC_PREFIX: normalize_topic_prefix(
                    settings.get(CONF_TOPIC_PREFIX),
                ),
            },
            "options": {
                key: value
                for key, value in entry.options.items()
                if key not in (CONF_DEVICE_ID, CONF_TOPIC_PREFIX)
            },
            "minor_version": 2,
        }
        unique_id = f"{DOMAIN}_{device_id}"
        # Unless another entry has it already, then the user step refuses
        # a duplicate the same way
        if not hass.config_entries.async_entry_for_domain_unique_id(
            DOMAIN,
            unique_id,
        ):
            updates["unique_id"] = unique_id
        # Entries created by early versions have a blank title, shown as an
        # unnamed integration entry. Keep a title the user has given it.
        if entry.title in ("", entry_title(entry.data.get(CONF_DEVICE_ID))):
            updates["title"] = entry_title(device_id)
        hass.config_entries.async_update_entry(entry, **updates)
        _LOGGER.debug("Migrated %s to version 1.2", entry.title)

    if entry.minor_version < 3:  # noqa: PLR2004
        # Remove the "smart_meter_" part of the sensors' unique IDs. The
        # entities keep their entity IDs, names and history.
        await er.async_migrate_entries(
            hass,
            entry.entry_id,
            partial(_migrate_unique_id, er.async_get(hass)),
        )
        hass.config_entries.async_update_entry(entry, minor_version=3)
        _LOGGER.debug("Migrated %s to version 1.3", entry.title)

    return True


@callback
def _migrate_unique_id(
    entity_registry: er.EntityRegistry,
    entity_entry: er.RegistryEntry,
) -> dict[str, Any] | None:
    """Return a sensor's unique ID without its "smart_meter_" part."""
    device_id, separator, rest = entity_entry.unique_id.partition(
        OLD_UNIQUE_ID_PART,
    )
    if not separator or not device_id or not rest:
        return None
    unique_id = f"{device_id}_{rest}"
    if entity_registry.async_get_entity_id(
        entity_entry.domain,
        DOMAIN,
        unique_id,
    ):
        # Already taken, leave this entity as it is
        _LOGGER.warning(
            "Can't change the unique ID of %s to %s, another entity has it",
            entity_entry.entity_id,
            unique_id,
        )
        return None
    return {"new_unique_id": unique_id}


async def async_setup_entry(hass: HomeAssistant, entry: GlowConfigEntry) -> bool:
    """Set up a Glow IHD from a config entry."""
    # The sensors are fed by MQTT messages, so wait for the MQTT client
    if not await mqtt.async_wait_for_mqtt_client(hass):
        raise ConfigEntryNotReady(
            translation_domain=DOMAIN,
            translation_key="mqtt_not_available",
        )

    entry.runtime_data = await async_build_runtime_data(entry)
    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
    return True


async def async_unload_entry(hass: HomeAssistant, entry: GlowConfigEntry) -> bool:
    """Unload a config entry.

    The MQTT subscription is removed by the callback the sensor platform
    registered with ``entry.async_on_unload``.
    """
    ir.async_delete_issue(hass, DOMAIN, no_messages_issue_id(entry.entry_id))
    return await hass.config_entries.async_unload_platforms(entry, PLATFORMS)


async def async_remove_config_entry_device(
    hass: HomeAssistant,  # noqa: ARG001
    config_entry: GlowConfigEntry,  # noqa: ARG001
    device_entry: dr.DeviceEntry,  # noqa: ARG001
) -> bool:
    """Allow a Glow device to be deleted from the UI.

    Devices are discovered from MQTT topics, so one that has been replaced or
    is no longer publishing would otherwise be stuck in the device list. If the
    device publishes again it is re-added after Home Assistant restarts or the
    integration is reloaded.
    """
    return True
