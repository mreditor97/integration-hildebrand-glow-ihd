"""Tests for the diagnostics download."""

from __future__ import annotations

import json
from typing import TYPE_CHECKING, Any

from pytest_homeassistant_custom_component.common import async_fire_mqtt_message
from pytest_homeassistant_custom_component.components.diagnostics import (
    get_diagnostics_for_config_entry,
)

from .const import DEVICE_ID, ELECTRICITY_PAYLOAD, STATE_PAYLOAD

if TYPE_CHECKING:
    from homeassistant.core import HomeAssistant
    from pytest_homeassistant_custom_component.common import MockConfigEntry
    from pytest_homeassistant_custom_component.typing import (
        ClientSessionGenerator,
        MqttMockHAClient,
    )

REDACTED = "**REDACTED**"


async def test_diagnostics(
    hass: HomeAssistant,
    hass_client: ClientSessionGenerator,
    mqtt_mock: MqttMockHAClient,  # noqa: ARG001
    config_entry: MockConfigEntry,
) -> None:
    """Diagnostics show the settings and latest payloads, without identifiers."""
    config_entry.add_to_hass(hass)
    assert await hass.config_entries.async_setup(config_entry.entry_id)
    await hass.async_block_till_done()
    async_fire_mqtt_message(hass, f"glow/{DEVICE_ID}/STATE", json.dumps(STATE_PAYLOAD))
    async_fire_mqtt_message(
        hass,
        f"glow/{DEVICE_ID}/SENSOR/electricitymeter",
        json.dumps(ELECTRICITY_PAYLOAD),
    )
    await hass.async_block_till_done()

    diagnostics: dict[str, Any] = await get_diagnostics_for_config_entry(
        hass,
        hass_client,
        config_entry,
    )

    assert diagnostics["entry"]["data"]["device_id"] == REDACTED
    assert diagnostics["entry"]["title"] == REDACTED
    assert diagnostics["entry"]["unique_id"] == REDACTED
    assert diagnostics["settings"] == {
        "detects_every_device": True,
        "topic_prefix": "glow",
        "time_zone_electricity": "Europe/London",
        "time_zone_gas": "UTC",
    }
    assert len(diagnostics["devices"]) == 1
    device = diagnostics["devices"][0]
    assert device["available"] is True
    state = device["payloads"]["STATE"]
    assert state["software"] == "v1.8.12"
    assert state["eui"] == REDACTED
    assert state["ethmac"] == REDACTED
    electricity = device["payloads"]["electricitymeter"]["electricitymeter"]
    assert electricity["energy"]["import"]["mpan"] == REDACTED
    assert electricity["energy"]["import"]["cumulative"] == 6613.405
    assert DEVICE_ID not in json.dumps(diagnostics)
