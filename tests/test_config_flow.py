"""Tests for the config and options flows."""

from __future__ import annotations

import json
from typing import TYPE_CHECKING, Any

import pytest
from homeassistant.config_entries import SOURCE_MQTT, SOURCE_USER, ConfigEntryState
from homeassistant.data_entry_flow import FlowResultType
from homeassistant.helpers.service_info.mqtt import MqttServiceInfo
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.hildebrand_glow_ihd.const import DOMAIN

from .const import DEVICE_ID, ENTRY_DATA, OTHER_DEVICE_ID, STATE_PAYLOAD

if TYPE_CHECKING:
    from homeassistant.core import HomeAssistant
    from pytest_homeassistant_custom_component.typing import MqttMockHAClient

TIME_ZONES = {
    "time_zone_electricity": ENTRY_DATA["time_zone_electricity"],
    "time_zone_gas": ENTRY_DATA["time_zone_gas"],
}


def _entry(device_id: str, topic_prefix: str = "glow") -> MockConfigEntry:
    """Return a config entry for a device ID."""
    return MockConfigEntry(
        domain=DOMAIN,
        title=f"Hildebrand Glow IHD ({device_id})",
        unique_id=f"{DOMAIN}_{device_id}",
        data={**ENTRY_DATA, "device_id": device_id, "topic_prefix": topic_prefix},
        minor_version=3,
    )


def _discovery_info(topic: str) -> MqttServiceInfo:
    """Return the discovery info for a message on a topic."""
    return MqttServiceInfo(
        topic=topic,
        payload=json.dumps(STATE_PAYLOAD),
        qos=0,
        retain=False,
        subscribed_topic="glow/+/STATE",
        timestamp=0,
    )


async def _user_flow(hass: HomeAssistant, user_input: dict[str, Any]) -> Any:
    """Run the user step with some input and return the result."""
    result = await hass.config_entries.flow.async_init(
        DOMAIN,
        context={"source": SOURCE_USER},
    )
    return await hass.config_entries.flow.async_configure(
        result["flow_id"],
        user_input,
    )


async def test_user_flow(
    hass: HomeAssistant,
    mqtt_mock: MqttMockHAClient,  # noqa: ARG001
) -> None:
    """The user step creates an entry for the given settings."""
    result = await hass.config_entries.flow.async_init(
        DOMAIN,
        context={"source": SOURCE_USER},
    )
    assert result["type"] is FlowResultType.FORM
    assert result["step_id"] == "user"

    result = await hass.config_entries.flow.async_configure(
        result["flow_id"],
        {**ENTRY_DATA, "device_id": DEVICE_ID},
    )
    assert result["type"] is FlowResultType.CREATE_ENTRY
    assert result["title"] == f"Hildebrand Glow IHD ({DEVICE_ID})"
    assert result["data"] == {**ENTRY_DATA, "device_id": DEVICE_ID}
    # Existing entries use this unique ID
    assert result["result"].unique_id == f"{DOMAIN}_{DEVICE_ID}"


async def test_user_flow_already_configured(
    hass: HomeAssistant,
    mqtt_mock: MqttMockHAClient,  # noqa: ARG001
    config_entry: MockConfigEntry,
) -> None:
    """A second entry for the same device ID is refused."""
    config_entry.add_to_hass(hass)
    result = await hass.config_entries.flow.async_init(
        DOMAIN,
        context={"source": SOURCE_USER},
    )
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"],
        ENTRY_DATA,
    )
    assert result["type"] is FlowResultType.ABORT
    assert result["reason"] == "already_configured"


async def test_user_flow_normalises_device_id(
    hass: HomeAssistant,
    mqtt_mock: MqttMockHAClient,  # noqa: ARG001
) -> None:
    """The device ID and topic prefix are saved the way the IHD uses them."""
    result = await _user_flow(
        hass,
        {
            **ENTRY_DATA,
            "device_id": " aa:bb:cc:dd:ee:ff ",
            "topic_prefix": "/glow/#",
        },
    )
    assert result["type"] is FlowResultType.CREATE_ENTRY
    assert result["data"]["device_id"] == DEVICE_ID
    assert result["data"]["topic_prefix"] == "glow"
    assert result["result"].unique_id == f"{DOMAIN}_{DEVICE_ID}"


async def test_user_flow_same_device_differently_typed(
    hass: HomeAssistant,
    mqtt_mock: MqttMockHAClient,  # noqa: ARG001
) -> None:
    """A device typed in lower case is the same device."""
    _entry(DEVICE_ID).add_to_hass(hass)
    result = await _user_flow(hass, {**ENTRY_DATA, "device_id": DEVICE_ID.lower()})
    assert result["type"] is FlowResultType.ABORT
    assert result["reason"] == "already_configured"


@pytest.mark.parametrize(
    ("existing", "new"),
    [("+", DEVICE_ID), (DEVICE_ID, "+")],
)
async def test_user_flow_overlapping_entry(
    hass: HomeAssistant,
    mqtt_mock: MqttMockHAClient,  # noqa: ARG001
    existing: str,
    new: str,
) -> None:
    """An entry for every device can't sit next to one for a single device."""
    _entry(existing).add_to_hass(hass)
    result = await _user_flow(hass, {**ENTRY_DATA, "device_id": new})
    assert result["type"] is FlowResultType.FORM
    assert result["errors"] == {"base": "overlaps_existing_entry"}


async def test_user_flow_other_prefix_allowed(
    hass: HomeAssistant,
    mqtt_mock: MqttMockHAClient,  # noqa: ARG001
) -> None:
    """A single device under another topic prefix doesn't overlap."""
    _entry("+").add_to_hass(hass)
    result = await _user_flow(
        hass,
        {**ENTRY_DATA, "device_id": DEVICE_ID, "topic_prefix": "other"},
    )
    assert result["type"] is FlowResultType.CREATE_ENTRY


async def test_mqtt_discovery(
    hass: HomeAssistant,
    mqtt_mock: MqttMockHAClient,  # noqa: ARG001
) -> None:
    """A discovered device is added once its time zones are confirmed."""
    result = await hass.config_entries.flow.async_init(
        DOMAIN,
        context={"source": SOURCE_MQTT},
        data=_discovery_info(f"glow/{DEVICE_ID}/STATE"),
    )
    assert result["type"] is FlowResultType.FORM
    assert result["step_id"] == "discovery_confirm"
    assert result["description_placeholders"] == {"device_id": DEVICE_ID}

    result = await hass.config_entries.flow.async_configure(
        result["flow_id"],
        TIME_ZONES,
    )
    assert result["type"] is FlowResultType.CREATE_ENTRY
    assert result["title"] == f"Hildebrand Glow IHD ({DEVICE_ID})"
    assert result["data"] == {**ENTRY_DATA, "device_id": DEVICE_ID}
    assert result["result"].unique_id == f"{DOMAIN}_{DEVICE_ID}"


@pytest.mark.parametrize(
    ("topic", "existing", "reason"),
    [
        (f"glow/{DEVICE_ID}/STATE", DEVICE_ID, "already_configured"),
        # An entry for every device already reads it
        (f"glow/{DEVICE_ID}/STATE", "+", "already_configured"),
        ("glow/STATE", None, "invalid_discovery_info"),
    ],
)
async def test_mqtt_discovery_aborts(
    hass: HomeAssistant,
    mqtt_mock: MqttMockHAClient,  # noqa: ARG001
    topic: str,
    existing: str | None,
    reason: str,
) -> None:
    """Discovery stops for a configured device or a message that isn't Glow's."""
    if existing is not None:
        _entry(existing).add_to_hass(hass)
    result = await hass.config_entries.flow.async_init(
        DOMAIN,
        context={"source": SOURCE_MQTT},
        data=_discovery_info(topic),
    )
    assert result["type"] is FlowResultType.ABORT
    assert result["reason"] == reason


async def test_reconfigure_flow(
    hass: HomeAssistant,
    mqtt_mock: MqttMockHAClient,
    config_entry: MockConfigEntry,
) -> None:
    """Reconfigure changes the device, unique ID and title, then reloads."""
    config_entry.add_to_hass(hass)
    assert await hass.config_entries.async_setup(config_entry.entry_id)
    await hass.async_block_till_done()

    result = await config_entry.start_reconfigure_flow(hass)
    assert result["type"] is FlowResultType.FORM
    assert result["step_id"] == "reconfigure"

    result = await hass.config_entries.flow.async_configure(
        result["flow_id"],
        {"device_id": DEVICE_ID.lower(), "topic_prefix": "glow"},
    )
    await hass.async_block_till_done()
    assert result["type"] is FlowResultType.ABORT
    assert result["reason"] == "reconfigure_successful"
    assert config_entry.data["device_id"] == DEVICE_ID
    assert config_entry.unique_id == f"{DOMAIN}_{DEVICE_ID}"
    assert config_entry.title == f"Hildebrand Glow IHD ({DEVICE_ID})"
    assert config_entry.state is ConfigEntryState.LOADED
    subscribed = [call.args[0] for call in mqtt_mock.async_subscribe.call_args_list]
    assert f"glow/{DEVICE_ID}/#" in subscribed


async def test_reconfigure_flow_overlapping_entry(
    hass: HomeAssistant,
    mqtt_mock: MqttMockHAClient,  # noqa: ARG001
) -> None:
    """Reconfigure refuses a device another entry already reads."""
    entry = _entry(DEVICE_ID)
    entry.add_to_hass(hass)
    _entry(OTHER_DEVICE_ID).add_to_hass(hass)

    result = await entry.start_reconfigure_flow(hass)
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"],
        {"device_id": OTHER_DEVICE_ID, "topic_prefix": "glow"},
    )
    assert result["type"] is FlowResultType.FORM
    assert result["errors"] == {"base": "overlaps_existing_entry"}

    # Keeping its own device ID isn't an overlap
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"],
        {"device_id": DEVICE_ID, "topic_prefix": "glow"},
    )
    assert result["type"] is FlowResultType.ABORT
    assert result["reason"] == "reconfigure_successful"


async def test_options_flow(
    hass: HomeAssistant,
    mqtt_mock: MqttMockHAClient,  # noqa: ARG001
    config_entry: MockConfigEntry,
) -> None:
    """Saved time zones are applied by reloading the entry."""
    config_entry.add_to_hass(hass)
    assert await hass.config_entries.async_setup(config_entry.entry_id)
    await hass.async_block_till_done()

    result = await hass.config_entries.options.async_init(config_entry.entry_id)
    assert result["type"] is FlowResultType.FORM
    assert result["step_id"] == "init"

    result = await hass.config_entries.options.async_configure(
        result["flow_id"],
        {**TIME_ZONES, "time_zone_gas": "Europe/London"},
    )
    await hass.async_block_till_done()
    assert result["type"] is FlowResultType.CREATE_ENTRY
    assert config_entry.state is ConfigEntryState.LOADED
    assert str(config_entry.runtime_data.time_zone_gas) == "Europe/London"
