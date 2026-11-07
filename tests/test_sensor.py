"""Tests for the Glow sensors."""

from __future__ import annotations

import json
from datetime import timedelta
from typing import TYPE_CHECKING, Any

import pytest
from homeassistant.const import STATE_UNAVAILABLE, STATE_UNKNOWN
from homeassistant.helpers import device_registry as dr
from homeassistant.helpers import entity_registry as er
from homeassistant.helpers import issue_registry as ir
from pytest_homeassistant_custom_component.common import (
    MockConfigEntry,
    async_fire_mqtt_message,
    async_fire_time_changed,
)

from custom_components.hildebrand_glow_ihd.const import AVAILABILITY_TIMEOUT, DOMAIN

from .const import (
    DEVICE_ID,
    ELECTRICITY_PAYLOAD,
    ENTRY_DATA,
    GAS_PAYLOAD,
    OTHER_DEVICE_ID,
    STATE_PAYLOAD,
)

if TYPE_CHECKING:
    from freezegun.api import FrozenDateTimeFactory
    from homeassistant.core import HomeAssistant
    from pytest_homeassistant_custom_component.typing import MqttMockHAClient

STATE_TOPIC = f"glow/{DEVICE_ID}/STATE"
ELECTRICITY_TOPIC = f"glow/{DEVICE_ID}/SENSOR/electricitymeter"
GAS_TOPIC = f"glow/{DEVICE_ID}/SENSOR/gasmeter"

# Every sensor's unique ID, entity ID suffix and state for the test payloads.
# The unique IDs are made from the names the sensors had before they were
# translated, without "Smart Meter", and existing installs rely on them.
EXPECTED_SENSORS: list[tuple[str, str, str]] = [
    ("ihd_software_version", "ihd_software_version", "v1.8.12"),
    ("ihd_hardware", "ihd_hardware", "GLOW-IHD-01-1v4-SMETS2"),
    ("ihd_han_status", "ihd_han_status", "joined"),
    ("ihd_han_rssi", "ihd_han_rssi", "-75"),
    ("ihd_han_lqi", "ihd_han_lqi", "100"),
    ("electricity_export", "electricity_export", "0.0"),
    ("electricity_import", "electricity_import", "6613.405"),
    ("electricity_import_today", "electricity_import_today", "13.252"),
    (
        "electricity_import_this_week",
        "electricity_import_this_week",
        "141.71",
    ),
    (
        "electricity_import_this_month",
        "electricity_import_this_month",
        "293.598",
    ),
    (
        "electricity_import_unit_rate",
        "electricity_import_unit_rate",
        "0.04998",
    ),
    (
        "electricity_import_standing_charge",
        "electricity_import_standing_charge",
        "0.2403",
    ),
    ("electricity_power", "electricity_power", "0.951"),
    ("electricity_cost_today", "electricity_cost_today", "0.9"),
    ("gas_import", "gas_import", "17940.852"),
    ("gas_import_vol", "gas_import_vol", "1500.2"),
    # The IHD reports these volumes in kWh, so they're unknown
    ("gas_import_vol_today", "gas_import_vol_today", STATE_UNKNOWN),
    (
        "gas_import_vol_this_week",
        "gas_import_vol_this_week",
        STATE_UNKNOWN,
    ),
    (
        "gas_import_vol_this_month",
        "gas_import_vol_this_month",
        STATE_UNKNOWN,
    ),
    ("gas_import_today", "gas_import_today", "11.128"),
    ("gas_import_this_week", "gas_import_this_week", "104.749"),
    ("gas_import_this_month", "gas_import_this_month", "217.122"),
    # No unit rate from the supplier
    ("gas_import_unit_rate", "gas_import_unit_rate", STATE_UNKNOWN),
    (
        "gas_import_standing_charge",
        "gas_import_standing_charge",
        "0.1785",
    ),
    ("gas_cost_today", "gas_cost_today", "0.18"),
]


# The sensors that are disabled by default, with their entity ID suffix and
# state for the test payloads
DISABLED_SENSORS: list[tuple[str, str, str]] = [
    ("ihd_zigbee_version", "ihd_zigbee_version", "1.2.5"),
    ("ihd_smets_version", "ihd_smets_version", "SMETS2"),
    (
        "electricity_last_reading",
        "electricity_last_reading",
        "2022-06-11T23:38:00+00:00",
    ),
    ("gas_last_reading", "gas_last_reading", "2022-06-11T20:53:52+00:00"),
]


async def _setup(hass: HomeAssistant, entry: MockConfigEntry) -> None:
    """Set up a config entry."""
    entry.add_to_hass(hass)
    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()


def _publish(hass: HomeAssistant, topic: str, payload: dict[str, Any] | str) -> None:
    """Publish a payload to a Glow topic."""
    async_fire_mqtt_message(
        hass,
        topic,
        payload if isinstance(payload, str) else json.dumps(payload),
    )


def _entity_id(hass: HomeAssistant, unique_id_suffix: str) -> str:
    """Return the entity ID of a sensor of the test device."""
    entity_id = er.async_get(hass).async_get_entity_id(
        "sensor",
        DOMAIN,
        f"{DEVICE_ID.lower()}_{unique_id_suffix}",
    )
    assert entity_id is not None
    return entity_id


async def _publish_all(hass: HomeAssistant) -> None:
    """Publish one message of each kind for the test device."""
    _publish(hass, STATE_TOPIC, STATE_PAYLOAD)
    _publish(hass, ELECTRICITY_TOPIC, ELECTRICITY_PAYLOAD)
    _publish(hass, GAS_TOPIC, GAS_PAYLOAD)
    await hass.async_block_till_done()


async def test_sensors(
    hass: HomeAssistant,
    mqtt_mock: MqttMockHAClient,  # noqa: ARG001
    config_entry: MockConfigEntry,
) -> None:
    """A device's sensors are added on its first message and updated."""
    await _setup(hass, config_entry)
    assert not hass.states.async_all("sensor")

    await _publish_all(hass)

    entity_registry = er.async_get(hass)
    entries = er.async_entries_for_config_entry(
        entity_registry,
        config_entry.entry_id,
    )
    assert len(entries) == len(EXPECTED_SENSORS) + len(DISABLED_SENSORS)
    for unique_id_suffix, _, _ in DISABLED_SENSORS:
        entry = entity_registry.async_get(_entity_id(hass, unique_id_suffix))
        assert entry is not None
        assert entry.disabled_by is er.RegistryEntryDisabler.INTEGRATION
    for unique_id_suffix, object_id, expected_state in EXPECTED_SENSORS:
        entity_id = _entity_id(hass, unique_id_suffix)
        assert entity_id == f"sensor.home_{object_id}"
        state = hass.states.get(entity_id)
        assert state is not None
        assert state.state == expected_state, entity_id
        assert state.attributes["device_id"] == DEVICE_ID

    device = dr.async_get(hass).async_get_device_by_connection(
        (dr.CONNECTION_NETWORK_MAC, DEVICE_ID),
        config_entry.entry_id,
    )
    assert device is not None
    assert device.name == "Home"
    assert device.manufacturer == "Hildebrand Technology Limited"
    assert device.model == "Glow IHD"


async def test_names(
    hass: HomeAssistant,
    mqtt_mock: MqttMockHAClient,  # noqa: ARG001
    config_entry: MockConfigEntry,
) -> None:
    """Sensors are named after their device, then the translated name."""
    await _setup(hass, config_entry)
    await _publish_all(hass)
    state = hass.states.get(_entity_id(hass, "electricity_import"))
    assert state is not None
    assert state.attributes["friendly_name"] == ("Home Electricity: Import")


async def test_cost_last_reset(
    hass: HomeAssistant,
    mqtt_mock: MqttMockHAClient,  # noqa: ARG001
    config_entry: MockConfigEntry,
) -> None:
    """Cost sensors reset at midnight in their meter's time zone."""
    await _setup(hass, config_entry)
    await _publish_all(hass)

    # The electricity meter is in Europe/London, 00:38 BST on 12 June
    electricity = hass.states.get(
        _entity_id(hass, "electricity_cost_today"),
    )
    assert electricity is not None
    assert electricity.attributes["last_reset"] == "2022-06-11T23:00:00+00:00"
    # The gas meter is in UTC
    gas = hass.states.get(_entity_id(hass, "gas_cost_today"))
    assert gas is not None
    assert gas.attributes["last_reset"] == "2022-06-11T00:00:00+00:00"


async def test_zero_and_error_values(
    hass: HomeAssistant,
    mqtt_mock: MqttMockHAClient,  # noqa: ARG001
    config_entry: MockConfigEntry,
) -> None:
    """Zero lifetime readings are ignored, the power error value is unknown."""
    await _setup(hass, config_entry)
    await _publish_all(hass)

    payload = json.loads(json.dumps(ELECTRICITY_PAYLOAD))
    payload["electricitymeter"]["energy"]["import"]["cumulative"] = 0
    payload["electricitymeter"]["power"]["value"] = -8388.608
    _publish(hass, ELECTRICITY_TOPIC, payload)
    await hass.async_block_till_done()

    imported = hass.states.get(_entity_id(hass, "electricity_import"))
    assert imported is not None
    assert imported.state == "6613.405"
    power = hass.states.get(_entity_id(hass, "electricity_power"))
    assert power is not None
    assert power.state == STATE_UNKNOWN


async def test_missing_fields(
    hass: HomeAssistant,
    mqtt_mock: MqttMockHAClient,  # noqa: ARG001
    config_entry: MockConfigEntry,
) -> None:
    """A payload missing a sensor's field makes only that sensor unknown."""
    await _setup(hass, config_entry)
    await _publish_all(hass)

    payload = json.loads(json.dumps(STATE_PAYLOAD))
    del payload["han"]
    _publish(hass, STATE_TOPIC, payload)
    await hass.async_block_till_done()

    rssi = hass.states.get(_entity_id(hass, "ihd_han_rssi"))
    assert rssi is not None
    assert rssi.state == STATE_UNKNOWN
    software = hass.states.get(_entity_id(hass, "ihd_software_version"))
    assert software is not None
    assert software.state == "v1.8.12"


@pytest.mark.parametrize(
    ("topic", "payload"),
    [
        (STATE_TOPIC, "not json"),
        (STATE_TOPIC, "[1, 2, 3]"),
        (f"glow/{DEVICE_ID}/SENSOR/other", STATE_PAYLOAD),
    ],
)
async def test_other_messages_ignored(
    hass: HomeAssistant,
    mqtt_mock: MqttMockHAClient,  # noqa: ARG001
    config_entry: MockConfigEntry,
    topic: str,
    payload: dict[str, Any] | str,
) -> None:
    """Messages that aren't Glow messages add no sensors and raise nothing."""
    await _setup(hass, config_entry)
    _publish(hass, topic, payload)
    await hass.async_block_till_done()
    assert not hass.states.async_all("sensor")


async def test_device_filter(
    hass: HomeAssistant,
    mqtt_mock: MqttMockHAClient,  # noqa: ARG001
) -> None:
    """An entry for one device ignores the others."""
    entry = MockConfigEntry(
        domain=DOMAIN,
        unique_id=f"{DOMAIN}_{DEVICE_ID}",
        data={**ENTRY_DATA, "device_id": DEVICE_ID.lower()},
    )
    await _setup(hass, entry)
    _publish(hass, f"glow/{OTHER_DEVICE_ID}/STATE", STATE_PAYLOAD)
    await hass.async_block_till_done()
    assert not hass.states.async_all("sensor")

    _publish(hass, STATE_TOPIC, STATE_PAYLOAD)
    await hass.async_block_till_done()
    assert hass.states.get(_entity_id(hass, "ihd_hardware")) is not None


async def test_existing_entity_id_kept(
    hass: HomeAssistant,
    mqtt_mock: MqttMockHAClient,  # noqa: ARG001
) -> None:
    """Entities from earlier versions get the new unique ID, and keep their IDs."""
    entry = MockConfigEntry(
        domain=DOMAIN,
        title="Hildebrand Glow IHD",
        unique_id=f"{DOMAIN}_+",
        data=ENTRY_DATA,
        minor_version=2,
    )
    entry.add_to_hass(hass)
    entity_registry = er.async_get(hass)
    entity_registry.async_get_or_create(
        "sensor",
        DOMAIN,
        f"{DEVICE_ID.lower()}_smart_meter_electricity_import",
        suggested_object_id="smart_meter_electricity_import",
        config_entry=entry,
    )
    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()
    assert entry.minor_version == 3
    assert (
        entity_registry.async_get_entity_id(
            "sensor",
            DOMAIN,
            f"{DEVICE_ID.lower()}_electricity_import",
        )
        == "sensor.smart_meter_electricity_import"
    )

    _publish(hass, ELECTRICITY_TOPIC, ELECTRICITY_PAYLOAD)
    await hass.async_block_till_done()
    state = hass.states.get("sensor.smart_meter_electricity_import")
    assert state is not None
    assert state.state == "6613.405"
    # The migrated entity is updated, not duplicated
    assert len(
        er.async_entries_for_config_entry(entity_registry, entry.entry_id),
    ) == len(
        EXPECTED_SENSORS,
    ) + len(
        DISABLED_SENSORS,
    )


async def test_migration_skips_taken_unique_id(
    hass: HomeAssistant,
    mqtt_mock: MqttMockHAClient,  # noqa: ARG001
    caplog: pytest.LogCaptureFixture,
) -> None:
    """An old unique ID is left alone if its new one is already taken."""
    entry = MockConfigEntry(
        domain=DOMAIN,
        unique_id=f"{DOMAIN}_+",
        data=ENTRY_DATA,
        minor_version=2,
    )
    entry.add_to_hass(hass)
    entity_registry = er.async_get(hass)
    old = entity_registry.async_get_or_create(
        "sensor",
        DOMAIN,
        f"{DEVICE_ID.lower()}_smart_meter_electricity_import",
        config_entry=entry,
    )
    entity_registry.async_get_or_create(
        "sensor",
        DOMAIN,
        f"{DEVICE_ID.lower()}_electricity_import",
        config_entry=entry,
    )
    # Not a Glow sensor unique ID, left as it is
    other = entity_registry.async_get_or_create(
        "sensor",
        DOMAIN,
        "something_else",
        config_entry=entry,
    )
    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()
    assert entity_registry.async_get(old.entity_id).unique_id == (  # type: ignore[union-attr]
        f"{DEVICE_ID.lower()}_smart_meter_electricity_import"
    )
    assert entity_registry.async_get(other.entity_id).unique_id == "something_else"  # type: ignore[union-attr]
    assert "another entity has it" in caplog.text


async def test_reload_and_unload(
    hass: HomeAssistant,
    mqtt_mock: MqttMockHAClient,  # noqa: ARG001
    config_entry: MockConfigEntry,
) -> None:
    """Sensors come back after a reload, and stop updating once unloaded."""
    await _setup(hass, config_entry)
    await _publish_all(hass)
    entity_id = _entity_id(hass, "ihd_hardware")

    assert await hass.config_entries.async_reload(config_entry.entry_id)
    await hass.async_block_till_done()
    _publish(hass, STATE_TOPIC, {**STATE_PAYLOAD, "hardware": "RELOADED"})
    await hass.async_block_till_done()
    state = hass.states.get(entity_id)
    assert state is not None
    assert state.state == "RELOADED"

    assert await hass.config_entries.async_unload(config_entry.entry_id)
    await hass.async_block_till_done()
    _publish(hass, STATE_TOPIC, {**STATE_PAYLOAD, "hardware": "UNLOADED"})
    await hass.async_block_till_done()
    state = hass.states.get(entity_id)
    assert state is not None
    assert state.state == STATE_UNAVAILABLE


async def test_price_sensors_have_no_state_class(
    hass: HomeAssistant,
    mqtt_mock: MqttMockHAClient,  # noqa: ARG001
    config_entry: MockConfigEntry,
) -> None:
    """Prices aren't totals, so they aren't added up in statistics."""
    await _setup(hass, config_entry)
    await _publish_all(hass)
    unit_rate = hass.states.get(
        _entity_id(hass, "electricity_import_unit_rate"),
    )
    assert unit_rate is not None
    assert "state_class" not in unit_rate.attributes
    assert "device_class" not in unit_rate.attributes
    assert unit_rate.attributes["unit_of_measurement"] == "GBP/kWh"
    standing_charge = hass.states.get(
        _entity_id(hass, "electricity_import_standing_charge"),
    )
    assert standing_charge is not None
    assert "state_class" not in standing_charge.attributes
    assert standing_charge.attributes["device_class"] == "monetary"


async def test_unavailable_when_device_goes_quiet(
    hass: HomeAssistant,
    mqtt_mock: MqttMockHAClient,  # noqa: ARG001
    config_entry: MockConfigEntry,
    freezer: FrozenDateTimeFactory,
    caplog: pytest.LogCaptureFixture,
) -> None:
    """A device's sensors go unavailable without messages, and come back."""
    await _setup(hass, config_entry)
    await _publish_all(hass)
    entity_id = _entity_id(hass, "electricity_import")

    freezer.tick(AVAILABILITY_TIMEOUT - timedelta(minutes=1))
    async_fire_time_changed(hass)
    await hass.async_block_till_done()
    assert hass.states.get(entity_id).state == "6613.405"  # type: ignore[union-attr]

    freezer.tick(timedelta(minutes=2))
    async_fire_time_changed(hass)
    await hass.async_block_till_done()
    assert hass.states.get(entity_id).state == STATE_UNAVAILABLE  # type: ignore[union-attr]
    assert f"Glow device {DEVICE_ID} hasn't published" in caplog.text

    # Any message brings back every sensor of the device
    _publish(hass, STATE_TOPIC, STATE_PAYLOAD)
    await hass.async_block_till_done()
    assert hass.states.get(entity_id).state == "6613.405"  # type: ignore[union-attr]
    assert f"Glow device {DEVICE_ID} is publishing again" in caplog.text


async def test_device_versions(
    hass: HomeAssistant,
    mqtt_mock: MqttMockHAClient,  # noqa: ARG001
    config_entry: MockConfigEntry,
) -> None:
    """The device page shows the IHD's software and hardware versions."""
    await _setup(hass, config_entry)
    # The first message isn't the state, so the versions aren't known yet
    _publish(hass, ELECTRICITY_TOPIC, ELECTRICITY_PAYLOAD)
    await hass.async_block_till_done()
    device_registry = dr.async_get(hass)
    device = device_registry.async_get_device_by_connection(
        (dr.CONNECTION_NETWORK_MAC, DEVICE_ID),
        config_entry.entry_id,
    )
    assert device is not None
    assert device.sw_version is None

    _publish(hass, STATE_TOPIC, STATE_PAYLOAD)
    await hass.async_block_till_done()
    updated = device_registry.async_get_device_by_connection(
        (dr.CONNECTION_NETWORK_MAC, DEVICE_ID),
        config_entry.entry_id,
    )
    assert updated is not None
    assert updated.sw_version == "v1.8.12"
    assert updated.hw_version == "GLOW-IHD-01-1v4-SMETS2"

    _publish(hass, STATE_TOPIC, {**STATE_PAYLOAD, "software": "v1.9.0"})
    await hass.async_block_till_done()
    updated = device_registry.async_get_device_by_connection(
        (dr.CONNECTION_NETWORK_MAC, DEVICE_ID),
        config_entry.entry_id,
    )
    assert updated is not None
    assert updated.sw_version == "v1.9.0"


async def test_device_versions_from_first_message(
    hass: HomeAssistant,
    mqtt_mock: MqttMockHAClient,  # noqa: ARG001
    config_entry: MockConfigEntry,
) -> None:
    """A device whose first message is its state gets its versions straight away."""
    await _setup(hass, config_entry)
    _publish(hass, STATE_TOPIC, STATE_PAYLOAD)
    await hass.async_block_till_done()
    device = dr.async_get(hass).async_get_device_by_connection(
        (dr.CONNECTION_NETWORK_MAC, DEVICE_ID),
        config_entry.entry_id,
    )
    assert device is not None
    assert device.sw_version == "v1.8.12"


async def test_repair_issue_when_nothing_heard(
    hass: HomeAssistant,
    mqtt_mock: MqttMockHAClient,  # noqa: ARG001
    config_entry: MockConfigEntry,
    freezer: FrozenDateTimeFactory,
) -> None:
    """A repair issue is raised if no device publishes, and removed when one does."""
    await _setup(hass, config_entry)
    issue_id = f"no_messages_{config_entry.entry_id}"
    issue_registry = ir.async_get(hass)

    freezer.tick(AVAILABILITY_TIMEOUT + timedelta(seconds=1))
    async_fire_time_changed(hass)
    await hass.async_block_till_done()
    issue = issue_registry.async_get_issue(DOMAIN, issue_id)
    assert issue is not None
    assert issue.translation_placeholders == {
        "title": "Hildebrand Glow IHD",
        "topic": "glow/+/#",
        "minutes": "15",
    }

    _publish(hass, STATE_TOPIC, STATE_PAYLOAD)
    await hass.async_block_till_done()
    assert issue_registry.async_get_issue(DOMAIN, issue_id) is None


async def test_no_repair_issue_when_heard(
    hass: HomeAssistant,
    mqtt_mock: MqttMockHAClient,  # noqa: ARG001
    config_entry: MockConfigEntry,
    freezer: FrozenDateTimeFactory,
) -> None:
    """No repair issue is raised once a device has published."""
    await _setup(hass, config_entry)
    await _publish_all(hass)
    freezer.tick(AVAILABILITY_TIMEOUT + timedelta(seconds=1))
    async_fire_time_changed(hass)
    await hass.async_block_till_done()
    assert not ir.async_get(hass).async_get_issue(
        DOMAIN,
        f"no_messages_{config_entry.entry_id}",
    )


async def test_disabled_sensors(
    hass: HomeAssistant,
    mqtt_mock: MqttMockHAClient,  # noqa: ARG001
    config_entry: MockConfigEntry,
) -> None:
    """The sensors that are off by default report their values once enabled."""
    await _setup(hass, config_entry)
    await _publish_all(hass)
    entity_registry = er.async_get(hass)
    for unique_id_suffix, _, _ in DISABLED_SENSORS:
        entity_registry.async_update_entity(
            _entity_id(hass, unique_id_suffix),
            disabled_by=None,
        )
    assert await hass.config_entries.async_reload(config_entry.entry_id)
    await hass.async_block_till_done()
    await _publish_all(hass)

    for unique_id_suffix, object_id, expected_state in DISABLED_SENSORS:
        entity_id = _entity_id(hass, unique_id_suffix)
        assert entity_id == f"sensor.home_{object_id}"
        state = hass.states.get(entity_id)
        assert state is not None
        assert state.state == expected_state, entity_id


@pytest.mark.parametrize("bad_value", ["not a number", "nan", True, [1], {"a": 1}])
async def test_unusable_value_logged_once(
    hass: HomeAssistant,
    mqtt_mock: MqttMockHAClient,  # noqa: ARG001
    config_entry: MockConfigEntry,
    caplog: pytest.LogCaptureFixture,
    bad_value: Any,
) -> None:
    """An unusable value makes the sensor unknown, and is warned about once."""
    await _setup(hass, config_entry)
    await _publish_all(hass)
    entity_id = _entity_id(hass, "electricity_power")

    payload = json.loads(json.dumps(ELECTRICITY_PAYLOAD))
    payload["electricitymeter"]["power"]["value"] = bad_value
    _publish(hass, ELECTRICITY_TOPIC, payload)
    _publish(hass, ELECTRICITY_TOPIC, payload)
    await hass.async_block_till_done()

    state = hass.states.get(entity_id)
    assert state is not None
    assert state.state == STATE_UNKNOWN
    warnings = [
        record
        for record in caplog.records
        if record.levelname == "WARNING" and "Unusable value" in record.message
    ]
    assert len(warnings) == 1
    # The other sensors of the message are still updated
    imported = hass.states.get(_entity_id(hass, "electricity_import"))
    assert imported is not None
    assert imported.state == "6613.405"

    _publish(hass, ELECTRICITY_TOPIC, ELECTRICITY_PAYLOAD)
    await hass.async_block_till_done()
    state = hass.states.get(entity_id)
    assert state is not None
    assert state.state == "0.951"
    assert "Usable values for" in caplog.text


async def test_numeric_text_is_used(
    hass: HomeAssistant,
    mqtt_mock: MqttMockHAClient,  # noqa: ARG001
    config_entry: MockConfigEntry,
) -> None:
    """A number sent as text is used as the number."""
    await _setup(hass, config_entry)
    payload = json.loads(json.dumps(ELECTRICITY_PAYLOAD))
    payload["electricitymeter"]["power"]["value"] = "1.5"
    _publish(hass, ELECTRICITY_TOPIC, payload)
    await hass.async_block_till_done()
    state = hass.states.get(_entity_id(hass, "electricity_power"))
    assert state is not None
    assert state.state == "1.5"


async def test_unreadable_payload_logged_once(
    hass: HomeAssistant,
    mqtt_mock: MqttMockHAClient,  # noqa: ARG001
    config_entry: MockConfigEntry,
    caplog: pytest.LogCaptureFixture,
) -> None:
    """A topic that keeps sending unreadable payloads is warned about once."""
    await _setup(hass, config_entry)
    for _ in range(3):
        _publish(hass, STATE_TOPIC, "not json")
    await hass.async_block_till_done()
    warnings = [
        record
        for record in caplog.records
        if record.levelname == "WARNING" and "isn't a JSON object" in record.message
    ]
    assert len(warnings) == 1
    assert not hass.states.async_all("sensor")

    _publish(hass, STATE_TOPIC, STATE_PAYLOAD)
    await hass.async_block_till_done()
    assert f"Messages on {STATE_TOPIC} can be read again" in caplog.text


async def test_unknown_topic_not_warned(
    hass: HomeAssistant,
    mqtt_mock: MqttMockHAClient,  # noqa: ARG001
    config_entry: MockConfigEntry,
    caplog: pytest.LogCaptureFixture,
) -> None:
    """Messages on topics the integration doesn't use aren't warned about."""
    await _setup(hass, config_entry)
    _publish(hass, f"glow/{DEVICE_ID}/SENSOR/other", "not json")
    await hass.async_block_till_done()
    assert "WARNING" not in [record.levelname for record in caplog.records]


async def test_existing_device_renamed(
    hass: HomeAssistant,
    mqtt_mock: MqttMockHAClient,  # noqa: ARG001
    config_entry: MockConfigEntry,
) -> None:
    """Devices named by earlier versions get the name without "Smart Meter"."""
    config_entry.add_to_hass(hass)
    device_registry = dr.async_get(hass)
    device_registry.async_get_or_create(
        config_entry_id=config_entry.entry_id,
        connections={(dr.CONNECTION_NETWORK_MAC, DEVICE_ID)},
        name=f"Glow Smart Meter {DEVICE_ID}",
        model="Glow Smart Meter IHD",
    )
    assert await hass.config_entries.async_setup(config_entry.entry_id)
    await hass.async_block_till_done()
    await _publish_all(hass)

    device = device_registry.async_get_device_by_connection(
        (dr.CONNECTION_NETWORK_MAC, DEVICE_ID),
        config_entry.entry_id,
    )
    assert device is not None
    assert device.name == "Home"
    assert device.model == "Glow IHD"


async def test_entry_without_name_keeps_old_device_name(
    hass: HomeAssistant,
    mqtt_mock: MqttMockHAClient,  # noqa: ARG001
) -> None:
    """Entries made before setup asked for a name keep their device names."""
    data = {key: value for key, value in ENTRY_DATA.items() if key != "name"}
    entry = MockConfigEntry(
        domain=DOMAIN,
        unique_id=f"{DOMAIN}_+",
        data=data,
        minor_version=3,
    )
    await _setup(hass, entry)
    await _publish_all(hass)
    device = dr.async_get(hass).async_get_device_by_connection(
        (dr.CONNECTION_NETWORK_MAC, DEVICE_ID),
        entry.entry_id,
    )
    assert device is not None
    assert device.name == f"Glow {DEVICE_ID}"
    assert (
        _entity_id(hass, "electricity_import")
        == f"sensor.glow_{DEVICE_ID.lower()}_electricity_import"
    )


@pytest.mark.parametrize(
    ("old_entity_id", "expected_entity_id"),
    [
        # Made from the unique ID by an earlier version, renamed
        (
            f"sensor.{DEVICE_ID.lower()}_electricity_import",
            "sensor.home_electricity_import",
        ),
        # Changed by the user, left alone
        ("sensor.my_meter", "sensor.my_meter"),
    ],
)
async def test_device_id_entity_ids_renamed(
    hass: HomeAssistant,
    mqtt_mock: MqttMockHAClient,  # noqa: ARG001
    config_entry: MockConfigEntry,
    old_entity_id: str,
    expected_entity_id: str,
) -> None:
    """Entity IDs made from the device ID get the name given at setup."""
    config_entry.add_to_hass(hass)
    entity_registry = er.async_get(hass)
    entity_registry.async_get_or_create(
        "sensor",
        DOMAIN,
        f"{DEVICE_ID.lower()}_electricity_import",
        suggested_object_id=old_entity_id.removeprefix("sensor."),
        config_entry=config_entry,
    )
    assert await hass.config_entries.async_setup(config_entry.entry_id)
    await hass.async_block_till_done()
    await _publish_all(hass)
    await hass.async_block_till_done()

    assert _entity_id(hass, "electricity_import") == expected_entity_id
    state = hass.states.get(expected_entity_id)
    assert state is not None
    assert state.state == "6613.405"
    if old_entity_id != expected_entity_id:
        assert hass.states.get(old_entity_id) is None


async def test_device_id_entity_id_kept_without_name(
    hass: HomeAssistant,
    mqtt_mock: MqttMockHAClient,  # noqa: ARG001
) -> None:
    """Entries without a name keep entity IDs made from the device ID."""
    data = {key: value for key, value in ENTRY_DATA.items() if key != "name"}
    entry = MockConfigEntry(
        domain=DOMAIN,
        unique_id=f"{DOMAIN}_+",
        data=data,
        minor_version=3,
    )
    entry.add_to_hass(hass)
    er.async_get(hass).async_get_or_create(
        "sensor",
        DOMAIN,
        f"{DEVICE_ID.lower()}_electricity_import",
        suggested_object_id=f"{DEVICE_ID.lower()}_electricity_import",
        config_entry=entry,
    )
    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()
    await _publish_all(hass)
    assert (
        _entity_id(hass, "electricity_import")
        == f"sensor.{DEVICE_ID.lower()}_electricity_import"
    )


async def test_rename_skipped_when_taken(
    hass: HomeAssistant,
    mqtt_mock: MqttMockHAClient,  # noqa: ARG001
    config_entry: MockConfigEntry,
) -> None:
    """An entity ID isn't renamed onto one another entity already has."""
    config_entry.add_to_hass(hass)
    entity_registry = er.async_get(hass)
    entity_registry.async_get_or_create(
        "sensor",
        DOMAIN,
        f"{DEVICE_ID.lower()}_electricity_import",
        suggested_object_id=f"{DEVICE_ID.lower()}_electricity_import",
        config_entry=config_entry,
    )
    entity_registry.async_get_or_create(
        "sensor",
        "other",
        "taken",
        suggested_object_id="home_electricity_import",
    )
    assert await hass.config_entries.async_setup(config_entry.entry_id)
    await hass.async_block_till_done()
    await _publish_all(hass)
    assert (
        _entity_id(hass, "electricity_import")
        == f"sensor.{DEVICE_ID.lower()}_electricity_import"
    )


async def test_unavailable_until_first_reading(
    hass: HomeAssistant,
    mqtt_mock: MqttMockHAClient,  # noqa: ARG001
    config_entry: MockConfigEntry,
) -> None:
    """Sensors without a reading yet are unavailable, not unknown."""
    await _setup(hass, config_entry)
    _publish(hass, STATE_TOPIC, STATE_PAYLOAD)
    await hass.async_block_till_done()

    hardware = hass.states.get(_entity_id(hass, "ihd_hardware"))
    assert hardware is not None
    assert hardware.state == "GLOW-IHD-01-1v4-SMETS2"
    cost = hass.states.get(_entity_id(hass, "electricity_cost_today"))
    assert cost is not None
    assert cost.state == STATE_UNAVAILABLE

    _publish(hass, ELECTRICITY_TOPIC, ELECTRICITY_PAYLOAD)
    await hass.async_block_till_done()
    cost = hass.states.get(_entity_id(hass, "electricity_cost_today"))
    assert cost is not None
    assert cost.state == "0.9"
    # Gas hasn't reported yet
    gas = hass.states.get(_entity_id(hass, "gas_import"))
    assert gas is not None
    assert gas.state == STATE_UNAVAILABLE
