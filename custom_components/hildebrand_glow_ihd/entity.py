"""Base entity for the Home Assistant Hildebrand Glow IHD Integration."""

from __future__ import annotations

from typing import TYPE_CHECKING

from homeassistant.const import ATTR_DEVICE_ID
from homeassistant.helpers.device_registry import CONNECTION_NETWORK_MAC, DeviceInfo
from homeassistant.helpers.entity import Entity
from homeassistant.util import slugify

from .const import MANUFACTURER, MODEL, TopicKind
from .helpers import device_versions

if TYPE_CHECKING:
    from homeassistant.helpers.entity import EntityDescription

    from .models import GlowDeviceState


class GlowEntity(Entity):
    """An entity of a Glow device, updated from its MQTT messages."""

    _attr_has_entity_name = True
    _attr_should_poll = False

    def __init__(
        self,
        device_id: str,
        description: EntityDescription,
        unique_id_name: str,
        device_state: GlowDeviceState,
    ) -> None:
        """Initialise the entity."""
        self.entity_description = description
        self._device_id = device_id
        self._device_state = device_state
        self._added = False
        # Existing installs rely on this unique ID, don't change it. It is
        # made from the sensor's name from before names were translated.
        self._attr_unique_id = slugify(f"{device_id}_{unique_id_name}")
        # Known if the device's first message was its state, otherwise the
        # device registry is updated when the state arrives
        software_version, hardware_version = device_versions(
            device_state.payloads.get(TopicKind.STATE, {}),
        )
        self._attr_device_info = DeviceInfo(
            connections={(CONNECTION_NETWORK_MAC, device_id)},
            manufacturer=MANUFACTURER,
            model=MODEL,
            name=f"Glow Smart Meter {device_id}",
            sw_version=software_version,
            hw_version=hardware_version,
        )
        self._attr_extra_state_attributes = {ATTR_DEVICE_ID: device_id}

    @property
    def available(self) -> bool:
        """Return whether the device has published recently."""
        return self._device_state.available

    async def async_added_to_hass(self) -> None:
        """Start writing state updates once the entity is added."""
        await super().async_added_to_hass()
        self._added = True

    async def async_will_remove_from_hass(self) -> None:
        """Stop writing state updates when the entity is removed."""
        self._added = False
        await super().async_will_remove_from_hass()

    def async_write_state_if_added(self) -> None:
        """Write the state, unless the entity isn't added to Home Assistant.

        A device's entities are created when its first message arrives and
        are updated from that message before Home Assistant has added them.
        Home Assistant writes their state itself when it adds them.
        """
        if self._added:
            self.async_write_ha_state()
