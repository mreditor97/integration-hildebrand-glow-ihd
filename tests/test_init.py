"""Tests for setting up and unloading the integration."""

from __future__ import annotations

from typing import TYPE_CHECKING
from unittest.mock import patch

from homeassistant.config_entries import ConfigEntryState
from homeassistant.helpers import device_registry as dr
from homeassistant.setup import async_setup_component
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.hildebrand_glow_ihd.const import DOMAIN

from .const import DEVICE_ID, ENTRY_DATA

if TYPE_CHECKING:
    from homeassistant.core import HomeAssistant
    from pytest_homeassistant_custom_component.typing import (
        MqttMockHAClient,
        WebSocketGenerator,
    )


async def test_setup_and_unload(
    hass: HomeAssistant,
    mqtt_mock: MqttMockHAClient,
    config_entry: MockConfigEntry,
) -> None:
    """The entry subscribes when set up and unsubscribes when unloaded."""
    config_entry.add_to_hass(hass)
    assert await hass.config_entries.async_setup(config_entry.entry_id)
    await hass.async_block_till_done()
    assert config_entry.state is ConfigEntryState.LOADED
    assert config_entry.runtime_data.device_id == "+"
    assert config_entry.runtime_data.topic_prefix == "glow"
    subscribed = {
        call.args[0]: call.args[2] for call in mqtt_mock.async_subscribe.call_args_list
    }
    assert subscribed["glow/+/#"] == 1

    assert await hass.config_entries.async_unload(config_entry.entry_id)
    await hass.async_block_till_done()
    assert config_entry.state is ConfigEntryState.NOT_LOADED


async def test_setup_retries_without_mqtt(
    hass: HomeAssistant,
    config_entry: MockConfigEntry,
) -> None:
    """Setup is retried later when the MQTT client isn't available."""
    config_entry.add_to_hass(hass)
    with patch(
        "homeassistant.components.mqtt.async_wait_for_mqtt_client",
        return_value=False,
    ):
        await hass.config_entries.async_setup(config_entry.entry_id)
        await hass.async_block_till_done()
    assert config_entry.state is ConfigEntryState.SETUP_RETRY


async def test_blank_title_is_replaced(
    hass: HomeAssistant,
    mqtt_mock: MqttMockHAClient,  # noqa: ARG001
) -> None:
    """Entries from earlier versions with a blank title get one."""
    entry = MockConfigEntry(
        domain=DOMAIN,
        title="",
        unique_id=f"{DOMAIN}_+",
        data=ENTRY_DATA,
    )
    entry.add_to_hass(hass)
    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()
    assert entry.title == "Hildebrand Glow IHD"


async def test_migrate_settings_out_of_options(
    hass: HomeAssistant,
    mqtt_mock: MqttMockHAClient,  # noqa: ARG001
) -> None:
    """Version 1.1 entries get normalised settings in their data."""
    entry = MockConfigEntry(
        domain=DOMAIN,
        title="Hildebrand Glow IHD",
        unique_id=f"{DOMAIN}_+",
        data=ENTRY_DATA,
        # Saved by Configure in earlier versions
        options={
            "device_id": DEVICE_ID.lower(),
            "topic_prefix": "glow/",
            "time_zone_gas": "Europe/London",
        },
    )
    entry.add_to_hass(hass)
    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()

    assert entry.state is ConfigEntryState.LOADED
    assert entry.minor_version == 3
    assert entry.data == {**ENTRY_DATA, "device_id": DEVICE_ID}
    assert entry.options == {"time_zone_gas": "Europe/London"}
    assert entry.unique_id == f"{DOMAIN}_{DEVICE_ID}"
    assert entry.title == f"Hildebrand Glow IHD ({DEVICE_ID})"


async def test_migrate_keeps_custom_title_and_taken_unique_id(
    hass: HomeAssistant,
    mqtt_mock: MqttMockHAClient,  # noqa: ARG001
) -> None:
    """Migration keeps a user's title, and a unique ID another entry has."""
    MockConfigEntry(
        domain=DOMAIN,
        unique_id=f"{DOMAIN}_{DEVICE_ID}",
        data={**ENTRY_DATA, "device_id": DEVICE_ID},
        minor_version=3,
    ).add_to_hass(hass)
    entry = MockConfigEntry(
        domain=DOMAIN,
        title="My meter",
        unique_id=f"{DOMAIN}_{DEVICE_ID.lower()}",
        data={**ENTRY_DATA, "device_id": DEVICE_ID.lower()},
    )
    entry.add_to_hass(hass)
    await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()

    assert entry.minor_version == 3
    assert entry.title == "My meter"
    assert entry.unique_id == f"{DOMAIN}_{DEVICE_ID.lower()}"


async def test_migrate_from_future_version_fails(
    hass: HomeAssistant,
    mqtt_mock: MqttMockHAClient,  # noqa: ARG001
) -> None:
    """An entry made by a newer version of the integration isn't set up."""
    entry = MockConfigEntry(domain=DOMAIN, data=ENTRY_DATA, version=2)
    entry.add_to_hass(hass)
    await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()
    assert entry.state is ConfigEntryState.MIGRATION_ERROR


async def test_device_can_be_removed(
    hass: HomeAssistant,
    hass_ws_client: WebSocketGenerator,
    mqtt_mock: MqttMockHAClient,  # noqa: ARG001
    config_entry: MockConfigEntry,
) -> None:
    """A Glow device can be deleted from the UI."""
    config_entry.add_to_hass(hass)
    assert await hass.config_entries.async_setup(config_entry.entry_id)
    await hass.async_block_till_done()
    device_registry = dr.async_get(hass)
    device = device_registry.async_get_or_create(
        config_entry_id=config_entry.entry_id,
        connections={(dr.CONNECTION_NETWORK_MAC, "AABBCCDDEEFF")},
    )
    assert await async_setup_component(hass, "config", {})
    client = await hass_ws_client(hass)
    response = await client.remove_device(device.id)
    assert response["success"]
    assert device_registry.async_get(device.id) is None
