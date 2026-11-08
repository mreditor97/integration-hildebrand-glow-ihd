"""Sensors for the Home Assistant Hildebrand Glow IHD Integration."""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any

from homeassistant.components import mqtt
from homeassistant.components.sensor import (
    SensorDeviceClass,
    SensorEntity,
    SensorEntityDescription,
    SensorStateClass,
)
from homeassistant.const import (
    SIGNAL_STRENGTH_DECIBELS,
    EntityCategory,
    UnitOfEnergy,
    UnitOfPower,
    UnitOfVolume,
)
from homeassistant.core import callback
from homeassistant.helpers import device_registry as dr
from homeassistant.helpers import issue_registry as ir
from homeassistant.helpers.event import async_call_later, async_track_time_interval
from homeassistant.helpers.restore_state import RestoredExtraData, RestoreEntity
from homeassistant.util import dt as dt_util

from .const import (
    AVAILABILITY_CHECK_INTERVAL,
    AVAILABILITY_TIMEOUT,
    DEFAULT_DEVICE_ID,
    DEFAULT_NAME,
    DOMAIN,
    POWER_ERROR_VALUE,
    MeterInterval,
    TopicKind,
)
from .entity import GlowEntity
from .helpers import (
    InvalidValueError,
    PeriodVolume,
    calculate_cost_today,
    determine_last_reset,
    device_versions,
    gas_volume,
    no_messages_issue_id,
    parse_message,
    parse_topic,
    payload_timestamp,
    subscription_topic,
    validate_state_value,
)
from .models import GlowDeviceState

if TYPE_CHECKING:
    from collections.abc import Callable
    from datetime import datetime, tzinfo

    from homeassistant.components.mqtt import ReceiveMessage
    from homeassistant.core import HomeAssistant
    from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback

    from .helpers import GlowMessage
    from .models import GlowConfigEntry

_LOGGER = logging.getLogger(__name__)

# The sensors are updated from MQTT messages, nothing is polled
PARALLEL_UPDATES = 0

# Example payloads:
# glow/XXXXXXYYYYYY/STATE                   {"software":"v1.8.12","timestamp":"2022-06-11T20:54:53Z","hardware":"GLOW-IHD-01-1v4-SMETS2","ethmac":"1234567890AB","smetsversion":"SMETS2","eui":"12:34:56:78:91:23:45","zigbee":"1.2.5","han":{"rssi":-75,"status":"joined","lqi":100}}  # noqa: E501
# glow/XXXXXXYYYYYY/SENSOR/electricitymeter {"electricitymeter":{"timestamp":"2022-06-11T20:38:00Z","energy":{"export":{"cumulative":0.000,"units":"kWh"},"import":{"cumulative":6613.405,"day":13.252,"week":141.710,"month":293.598,"units":"kWh","mpan":"1234","supplier":"ABC ENERGY","price":{"unitrate":0.04998,"standingcharge":0.24030}}},"power":{"value":0.951,"units":"kW"}}}  # noqa: E501
# glow/XXXXXXYYYYYY/SENSOR/gasmeter         {"gasmeter":{"timestamp":"2022-06-11T20:53:52Z","energy":{"export":{"cumulative":0.000,"units":"kWh"},"import":{"cumulative":17940.852,"day":11.128,"week":104.749,"month":217.122,"units":"kWh","mprn":"1234","supplier":"---","price":{"unitrate":0.07320,"standingcharge":0.17850}}},"power":{"value":0.000,"units":"kW"}}}  # noqa: E501


@dataclass(frozen=True, kw_only=True)
class GlowSensorEntityDescription(SensorEntityDescription):
    """Describes a sensor read from a Glow MQTT payload."""

    # The sensor's name before it was translated, without its old "Smart
    # Meter" prefix. The unique ID is made from it, so it must not change.
    unique_id_name: str
    value_fn: Callable[[dict[str, Any]], Any]
    # Keep the previous state when the IHD reports 0
    ignore_zero_values: bool = False
    # Values the IHD reports when it can't read the meter
    error_values: tuple[float, ...] = ()
    # Set for sensors that reset, so last_reset can be reported
    meter_interval: MeterInterval | None = None
    # Set for the gas period volume sensors. When the IHD doesn't report the
    # period's volume in m³, it is worked out from the lifetime volume.
    volume_interval: MeterInterval | None = None


STATE_SENSORS: tuple[GlowSensorEntityDescription, ...] = (
    GlowSensorEntityDescription(
        key="software_version",
        translation_key="software_version",
        unique_id_name="IHD Software Version",
        entity_category=EntityCategory.DIAGNOSTIC,
        value_fn=lambda js: js["software"],
    ),
    GlowSensorEntityDescription(
        key="hardware",
        translation_key="hardware",
        unique_id_name="IHD Hardware",
        entity_category=EntityCategory.DIAGNOSTIC,
        value_fn=lambda js: js["hardware"],
    ),
    GlowSensorEntityDescription(
        key="han_status",
        translation_key="han_status",
        unique_id_name="IHD HAN Status",
        entity_category=EntityCategory.DIAGNOSTIC,
        value_fn=lambda js: js["han"]["status"],
    ),
    GlowSensorEntityDescription(
        key="han_rssi",
        translation_key="han_rssi",
        unique_id_name="IHD HAN RSSI",
        device_class=SensorDeviceClass.SIGNAL_STRENGTH,
        native_unit_of_measurement=SIGNAL_STRENGTH_DECIBELS,
        state_class=SensorStateClass.MEASUREMENT,
        entity_category=EntityCategory.DIAGNOSTIC,
        value_fn=lambda js: js["han"]["rssi"],
    ),
    GlowSensorEntityDescription(
        key="han_lqi",
        translation_key="han_lqi",
        unique_id_name="IHD HAN LQI",
        state_class=SensorStateClass.MEASUREMENT,
        entity_category=EntityCategory.DIAGNOSTIC,
        value_fn=lambda js: js["han"]["lqi"],
    ),
    GlowSensorEntityDescription(
        key="zigbee_version",
        translation_key="zigbee_version",
        unique_id_name="IHD Zigbee Version",
        entity_category=EntityCategory.DIAGNOSTIC,
        entity_registry_enabled_default=False,
        value_fn=lambda js: js["zigbee"],
    ),
    GlowSensorEntityDescription(
        key="smets_version",
        translation_key="smets_version",
        unique_id_name="IHD SMETS Version",
        entity_category=EntityCategory.DIAGNOSTIC,
        entity_registry_enabled_default=False,
        value_fn=lambda js: js["smetsversion"],
    ),
)

ELECTRICITY_SENSORS: tuple[GlowSensorEntityDescription, ...] = (
    GlowSensorEntityDescription(
        key="electricity_export",
        translation_key="electricity_export",
        unique_id_name="Electricity: Export",
        device_class=SensorDeviceClass.ENERGY,
        native_unit_of_measurement=UnitOfEnergy.KILO_WATT_HOUR,
        state_class=SensorStateClass.TOTAL_INCREASING,
        value_fn=lambda js: js["electricitymeter"]["energy"]["export"]["cumulative"],
    ),
    GlowSensorEntityDescription(
        key="electricity_import",
        translation_key="electricity_import",
        unique_id_name="Electricity: Import",
        device_class=SensorDeviceClass.ENERGY,
        native_unit_of_measurement=UnitOfEnergy.KILO_WATT_HOUR,
        state_class=SensorStateClass.TOTAL_INCREASING,
        value_fn=lambda js: js["electricitymeter"]["energy"]["import"]["cumulative"],
        ignore_zero_values=True,
    ),
    GlowSensorEntityDescription(
        key="electricity_import_today",
        translation_key="electricity_import_today",
        unique_id_name="Electricity: Import (Today)",
        device_class=SensorDeviceClass.ENERGY,
        native_unit_of_measurement=UnitOfEnergy.KILO_WATT_HOUR,
        state_class=SensorStateClass.TOTAL_INCREASING,
        value_fn=lambda js: js["electricitymeter"]["energy"]["import"]["day"],
    ),
    GlowSensorEntityDescription(
        key="electricity_import_week",
        translation_key="electricity_import_week",
        unique_id_name="Electricity: Import (This week)",
        device_class=SensorDeviceClass.ENERGY,
        native_unit_of_measurement=UnitOfEnergy.KILO_WATT_HOUR,
        state_class=SensorStateClass.TOTAL_INCREASING,
        value_fn=lambda js: js["electricitymeter"]["energy"]["import"]["week"],
    ),
    GlowSensorEntityDescription(
        key="electricity_import_month",
        translation_key="electricity_import_month",
        unique_id_name="Electricity: Import (This month)",
        device_class=SensorDeviceClass.ENERGY,
        native_unit_of_measurement=UnitOfEnergy.KILO_WATT_HOUR,
        state_class=SensorStateClass.TOTAL_INCREASING,
        value_fn=lambda js: js["electricitymeter"]["energy"]["import"]["month"],
    ),
    GlowSensorEntityDescription(
        key="electricity_unit_rate",
        translation_key="electricity_unit_rate",
        unique_id_name="Electricity: Import Unit Rate",
        native_unit_of_measurement="GBP/kWh",
        value_fn=lambda js: js["electricitymeter"]["energy"]["import"]["price"][
            "unitrate"
        ],
        ignore_zero_values=True,
    ),
    GlowSensorEntityDescription(
        key="electricity_standing_charge",
        translation_key="electricity_standing_charge",
        unique_id_name="Electricity: Import Standing Charge",
        device_class=SensorDeviceClass.MONETARY,
        native_unit_of_measurement="GBP",
        value_fn=lambda js: js["electricitymeter"]["energy"]["import"]["price"][
            "standingcharge"
        ],
        ignore_zero_values=True,
    ),
    GlowSensorEntityDescription(
        key="electricity_power",
        translation_key="electricity_power",
        unique_id_name="Electricity: Power",
        device_class=SensorDeviceClass.POWER,
        native_unit_of_measurement=UnitOfPower.KILO_WATT,
        state_class=SensorStateClass.MEASUREMENT,
        value_fn=lambda js: js["electricitymeter"]["power"]["value"],
        error_values=(POWER_ERROR_VALUE,),
    ),
    GlowSensorEntityDescription(
        key="electricity_cost_today",
        translation_key="electricity_cost_today",
        unique_id_name="Electricity: Cost (Today)",
        device_class=SensorDeviceClass.MONETARY,
        native_unit_of_measurement="GBP",
        state_class=SensorStateClass.TOTAL,
        meter_interval=MeterInterval.DAY,
        value_fn=lambda js: calculate_cost_today(js["electricitymeter"]),
    ),
    # Changes with every message, so it is off by default to keep it out of
    # the recorder unless it is wanted
    GlowSensorEntityDescription(
        key="electricity_last_reading",
        translation_key="electricity_last_reading",
        unique_id_name="Electricity: Last Reading",
        device_class=SensorDeviceClass.TIMESTAMP,
        entity_category=EntityCategory.DIAGNOSTIC,
        entity_registry_enabled_default=False,
        value_fn=payload_timestamp,
    ),
)

GAS_SENSORS: tuple[GlowSensorEntityDescription, ...] = (
    GlowSensorEntityDescription(
        key="gas_import",
        translation_key="gas_import",
        unique_id_name="Gas: Import",
        device_class=SensorDeviceClass.ENERGY,
        native_unit_of_measurement=UnitOfEnergy.KILO_WATT_HOUR,
        state_class=SensorStateClass.TOTAL_INCREASING,
        value_fn=lambda js: js["gasmeter"]["energy"]["import"]["cumulative"],
        ignore_zero_values=True,
    ),
    GlowSensorEntityDescription(
        key="gas_import_volume",
        translation_key="gas_import_volume",
        unique_id_name="Gas: Import Vol",
        device_class=SensorDeviceClass.GAS,
        native_unit_of_measurement=UnitOfVolume.CUBIC_METERS,
        state_class=SensorStateClass.TOTAL_INCREASING,
        value_fn=lambda js: gas_volume(js, "cumulativevol", "cumulativevolunits"),
        ignore_zero_values=True,
    ),
    GlowSensorEntityDescription(
        key="gas_import_volume_today",
        translation_key="gas_import_volume_today",
        unique_id_name="Gas: Import Vol (Today)",
        device_class=SensorDeviceClass.GAS,
        native_unit_of_measurement=UnitOfVolume.CUBIC_METERS,
        state_class=SensorStateClass.TOTAL_INCREASING,
        value_fn=lambda js: gas_volume(js, "dayvol", "dayweekmonthvolunits"),
        volume_interval=MeterInterval.DAY,
    ),
    GlowSensorEntityDescription(
        key="gas_import_volume_week",
        translation_key="gas_import_volume_week",
        unique_id_name="Gas: Import Vol (This week)",
        device_class=SensorDeviceClass.GAS,
        native_unit_of_measurement=UnitOfVolume.CUBIC_METERS,
        state_class=SensorStateClass.TOTAL_INCREASING,
        value_fn=lambda js: gas_volume(js, "weekvol", "dayweekmonthvolunits"),
        volume_interval=MeterInterval.WEEK,
    ),
    GlowSensorEntityDescription(
        key="gas_import_volume_month",
        translation_key="gas_import_volume_month",
        unique_id_name="Gas: Import Vol (This month)",
        device_class=SensorDeviceClass.GAS,
        native_unit_of_measurement=UnitOfVolume.CUBIC_METERS,
        state_class=SensorStateClass.TOTAL_INCREASING,
        value_fn=lambda js: gas_volume(js, "monthvol", "dayweekmonthvolunits"),
        volume_interval=MeterInterval.MONTH,
    ),
    GlowSensorEntityDescription(
        key="gas_import_today",
        translation_key="gas_import_today",
        unique_id_name="Gas: Import (Today)",
        device_class=SensorDeviceClass.ENERGY,
        native_unit_of_measurement=UnitOfEnergy.KILO_WATT_HOUR,
        state_class=SensorStateClass.TOTAL_INCREASING,
        value_fn=lambda js: js["gasmeter"]["energy"]["import"]["day"],
    ),
    GlowSensorEntityDescription(
        key="gas_import_week",
        translation_key="gas_import_week",
        unique_id_name="Gas: Import (This week)",
        device_class=SensorDeviceClass.ENERGY,
        native_unit_of_measurement=UnitOfEnergy.KILO_WATT_HOUR,
        state_class=SensorStateClass.TOTAL_INCREASING,
        value_fn=lambda js: js["gasmeter"]["energy"]["import"]["week"],
    ),
    GlowSensorEntityDescription(
        key="gas_import_month",
        translation_key="gas_import_month",
        unique_id_name="Gas: Import (This month)",
        device_class=SensorDeviceClass.ENERGY,
        native_unit_of_measurement=UnitOfEnergy.KILO_WATT_HOUR,
        state_class=SensorStateClass.TOTAL_INCREASING,
        value_fn=lambda js: js["gasmeter"]["energy"]["import"]["month"],
    ),
    GlowSensorEntityDescription(
        key="gas_unit_rate",
        translation_key="gas_unit_rate",
        unique_id_name="Gas: Import Unit Rate",
        native_unit_of_measurement="GBP/kWh",
        value_fn=lambda js: js["gasmeter"]["energy"]["import"]["price"]["unitrate"],
        ignore_zero_values=True,
    ),
    GlowSensorEntityDescription(
        key="gas_standing_charge",
        translation_key="gas_standing_charge",
        unique_id_name="Gas: Import Standing Charge",
        device_class=SensorDeviceClass.MONETARY,
        native_unit_of_measurement="GBP",
        value_fn=lambda js: js["gasmeter"]["energy"]["import"]["price"][
            "standingcharge"
        ],
        ignore_zero_values=True,
    ),
    # The "Smart Meter Gas: Power" sensor was removed in June 2022, IHD
    # software update 1.8.13 stopped publishing the gas power value
    GlowSensorEntityDescription(
        key="gas_cost_today",
        translation_key="gas_cost_today",
        unique_id_name="Gas: Cost (Today)",
        device_class=SensorDeviceClass.MONETARY,
        native_unit_of_measurement="GBP",
        state_class=SensorStateClass.TOTAL,
        meter_interval=MeterInterval.DAY,
        value_fn=lambda js: calculate_cost_today(js["gasmeter"]),
    ),
    # Shows how old the gas readings are, gas meters report less often
    GlowSensorEntityDescription(
        key="gas_last_reading",
        translation_key="gas_last_reading",
        unique_id_name="Gas: Last Reading",
        device_class=SensorDeviceClass.TIMESTAMP,
        entity_category=EntityCategory.DIAGNOSTIC,
        entity_registry_enabled_default=False,
        value_fn=payload_timestamp,
    ),
)


DESCRIPTIONS_BY_KIND: dict[TopicKind, tuple[GlowSensorEntityDescription, ...]] = {
    TopicKind.STATE: STATE_SENSORS,
    TopicKind.ELECTRICITY_METER: ELECTRICITY_SENSORS,
    TopicKind.GAS_METER: GAS_SENSORS,
}


async def async_setup_entry(
    hass: HomeAssistant,
    entry: GlowConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    """Set up the Glow sensors, adding each device's when it first publishes."""
    handler = GlowMessageHandler(hass, entry, async_add_entities)
    # Subscribe to one device's topics when one is set, otherwise to all
    entry.async_on_unload(
        await mqtt.async_subscribe(
            hass,
            handler.topic,
            handler.async_message_received,
            qos=1,
        ),
    )
    entry.async_on_unload(
        async_track_time_interval(
            hass,
            handler.async_check_availability,
            AVAILABILITY_CHECK_INTERVAL,
        ),
    )
    entry.async_on_unload(
        async_call_later(
            hass,
            AVAILABILITY_TIMEOUT,
            handler.async_raise_issue_if_nothing_heard,
        ),
    )


class GlowMessageHandler:
    """Create and update the sensors of the Glow devices an entry hears from."""

    def __init__(
        self,
        hass: HomeAssistant,
        entry: GlowConfigEntry,
        async_add_entities: AddConfigEntryEntitiesCallback,
    ) -> None:
        """Initialise the handler."""
        self._hass = hass
        self._entry = entry
        self._settings = entry.runtime_data
        self._async_add_entities = async_add_entities
        self.topic = subscription_topic(
            self._settings.topic_prefix,
            self._settings.device_id,
        )
        # The time zone each kind of message's resets are reported in
        self._time_zones: dict[TopicKind, tzinfo | None] = {
            TopicKind.STATE: None,
            TopicKind.ELECTRICITY_METER: self._settings.time_zone_electricity,
            TopicKind.GAS_METER: self._settings.time_zone_gas,
        }
        # The sensors of each device found so far, by the kind of message
        # that updates them
        self._sensors: dict[str, dict[TopicKind, list[GlowSensor]]] = {}
        # The topics whose last payload couldn't be read, so a device that
        # keeps sending bad payloads is logged once rather than every time
        self._bad_payload_topics: set[str] = set()

    @callback
    def _async_add_device(
        self,
        message: GlowMessage,
    ) -> dict[TopicKind, list[GlowSensor]]:
        """Add the sensors of a newly found device."""
        device_id = message.device_id
        _LOGGER.debug("New Glow device found: %s", device_id)
        device_state = GlowDeviceState(
            # Entries made before setup asked for a name keep the old one
            name=self._settings.name or f"{DEFAULT_NAME} {device_id}",
            named=self._settings.name is not None,
            last_seen=dt_util.utcnow(),
            payloads={message.kind: message.payload},
        )
        self._settings.devices[device_id] = device_state
        sensors = {
            kind: [
                (
                    GlowPeriodVolumeSensor
                    if description.volume_interval is not None
                    else GlowSensor
                )(device_id, description, self._time_zones[kind], device_state)
                for description in descriptions
            ]
            for kind, descriptions in DESCRIPTIONS_BY_KIND.items()
        }
        self._async_add_entities(
            sensor for kind_sensors in sensors.values() for sensor in kind_sensors
        )
        self._sensors[device_id] = sensors
        # Hearing from a device means the topic settings are right
        ir.async_delete_issue(
            self._hass,
            DOMAIN,
            no_messages_issue_id(self._entry.entry_id),
        )
        return sensors

    @callback
    def _async_write_device_sensors(self, device_id: str) -> None:
        """Write the state of every sensor of a device."""
        for kind_sensors in self._sensors[device_id].values():
            for sensor in kind_sensors:
                sensor.async_write_state_if_added()

    @callback
    def _async_update_device_versions(self, message: GlowMessage) -> None:
        """Show a device's software and hardware versions on its device page."""
        software, hardware = device_versions(message.payload)
        device_registry = dr.async_get(self._hass)
        # Looked up by the entry's devices, as async_get_device_by_connection
        # is newer than the oldest Home Assistant version supported
        connection = (dr.CONNECTION_NETWORK_MAC, dr.format_mac(message.device_id))
        device = next(
            (
                device
                for device in dr.async_entries_for_config_entry(
                    device_registry,
                    self._entry.entry_id,
                )
                if connection in device.connections
            ),
            None,
        )
        if device is None:
            # Not registered yet, the sensors' device info will set them
            return
        if (device.sw_version, device.hw_version) != (software, hardware):
            device_registry.async_update_device(
                device.id,
                sw_version=software,
                hw_version=hardware,
            )

    @callback
    def async_message_received(self, mqtt_message: ReceiveMessage) -> None:
        """Update a device's sensors from an MQTT message."""
        settings = self._settings
        topic = mqtt_message.topic
        glow_topic = parse_topic(settings.topic_prefix, topic)
        if glow_topic is None:
            _LOGGER.debug("Ignored message on %s, it is not a Glow topic", topic)
            return
        if settings.device_id not in (DEFAULT_DEVICE_ID, glow_topic.device_id):
            return
        message = parse_message(settings.topic_prefix, topic, mqtt_message.payload)
        if message is None:
            self._async_log_bad_payload(topic, mqtt_message.payload)
            return
        if topic in self._bad_payload_topics:
            self._bad_payload_topics.discard(topic)
            _LOGGER.info("Messages on %s can be read again", topic)

        _LOGGER.debug(
            "Received message on %s: %s",
            mqtt_message.topic,
            mqtt_message.payload,
        )
        if (sensors := self._sensors.get(message.device_id)) is None:
            sensors = self._async_add_device(message)
        device_state = settings.devices[message.device_id]
        device_state.last_seen = dt_util.utcnow()
        device_state.payloads[message.kind] = message.payload
        if message.kind is TopicKind.STATE:
            self._async_update_device_versions(message)
        if not device_state.available:
            _LOGGER.info("Glow device %s is publishing again", message.device_id)
            device_state.available = True
            self._async_write_device_sensors(message.device_id)
        for sensor in sensors[message.kind]:
            sensor.async_process_message(message)

    @callback
    def _async_log_bad_payload(self, topic: str, payload: Any) -> None:
        """Log a payload that isn't a JSON object, once until one is read."""
        if topic in self._bad_payload_topics:
            _LOGGER.debug("Ignored another unreadable payload on %s", topic)
            return
        self._bad_payload_topics.add(topic)
        _LOGGER.warning(
            "Ignored a message on %s, its payload isn't a JSON object: %.100r."
            " Further unreadable messages on this topic are logged at debug"
            " level until a readable one arrives",
            topic,
            payload,
        )

    @callback
    def async_check_availability(self, now: datetime) -> None:
        """Mark the sensors of devices that have stopped publishing unavailable."""
        for device_id, device_state in self._settings.devices.items():
            if (
                device_state.available
                and now - device_state.last_seen > AVAILABILITY_TIMEOUT
            ):
                _LOGGER.info(
                    "Glow device %s hasn't published for %s, its sensors are"
                    " unavailable until it does",
                    device_id,
                    AVAILABILITY_TIMEOUT,
                )
                device_state.available = False
                self._async_write_device_sensors(device_id)

    @callback
    def async_raise_issue_if_nothing_heard(self, _now: datetime) -> None:
        """Raise a repair issue if no device has published since setup."""
        if self._settings.devices:
            return
        ir.async_create_issue(
            self._hass,
            DOMAIN,
            no_messages_issue_id(self._entry.entry_id),
            is_fixable=False,
            severity=ir.IssueSeverity.WARNING,
            translation_key="no_messages",
            translation_placeholders={
                "title": self._entry.title,
                "topic": self.topic,
                "minutes": str(int(AVAILABILITY_TIMEOUT.total_seconds() // 60)),
            },
        )


class GlowSensor(GlowEntity, SensorEntity):
    """A sensor of a Glow device."""

    entity_description: GlowSensorEntityDescription

    def __init__(
        self,
        device_id: str,
        description: GlowSensorEntityDescription,
        time_zone: tzinfo | None,
        device_state: GlowDeviceState,
    ) -> None:
        """Initialise the sensor."""
        super().__init__(
            device_id,
            description,
            description.unique_id_name,
            device_state,
        )
        self._time_zone = time_zone
        self._attr_native_value = None
        # Whether a message has updated the sensor yet. Until one has, the
        # sensor has no reading and is unavailable rather than unknown, so
        # helpers like Utility Meter don't warn about an invalid state while
        # they wait for, say, the first gas message after a restart.
        self._has_reading = False
        # Whether an unusable value has been logged since the last good one
        self._invalid_value_logged = False
        self._numeric = bool(
            description.native_unit_of_measurement
            or description.state_class
            or (
                description.device_class is not None
                and description.device_class is not SensorDeviceClass.TIMESTAMP
            ),
        )
        if description.meter_interval is not None:
            self._attr_last_reset = None

    @property
    def available(self) -> bool:
        """Return whether the device is publishing and has sent this reading."""
        return super().available and self._has_reading

    def _validated(self, value: Any) -> Any:
        """Return a value if it can be the state, otherwise None.

        An unusable value is logged as a warning once, then at debug level
        until a usable one arrives, so a device that keeps sending it doesn't
        fill the log.
        """
        try:
            value = validate_state_value(
                value,
                numeric=self._numeric,
                timestamp=(
                    self.entity_description.device_class is SensorDeviceClass.TIMESTAMP
                ),
            )
        except InvalidValueError as err:
            if self._invalid_value_logged:
                _LOGGER.debug("Unusable value for %s: %s", self.unique_id, err)
            else:
                self._invalid_value_logged = True
                _LOGGER.warning(
                    "Unusable value for %s: %s. Its state is unknown until a"
                    " usable value arrives, and further unusable values are"
                    " logged at debug level",
                    self.unique_id,
                    err,
                )
            return None
        if value is not None and self._invalid_value_logged:
            self._invalid_value_logged = False
            _LOGGER.info("Usable values for %s again", self.unique_id)
        return value

    def _read_value(self, message: GlowMessage) -> Any:
        """Return the sensor's value from a message, or None if it has none."""
        try:
            return self.entity_description.value_fn(message.payload)
        except (AttributeError, IndexError, KeyError, TypeError, ValueError) as err:
            # A field this sensor depends on is missing or null in the payload
            # (e.g. no tariff data from the supplier). Report the state as
            # unknown instead of raising, so the other sensors of the same
            # topic are still updated.
            _LOGGER.debug(
                "Unable to read value for %s from payload (%r), state unknown",
                self.unique_id,
                err,
            )
            return None

    @callback
    def _async_set_value(self, value: Any) -> None:
        """Set the sensor's state from a reading."""
        self._attr_native_value = self._validated(value)
        self._has_reading = True
        self.async_write_state_if_added()

    @callback
    def async_process_message(self, message: GlowMessage) -> None:
        """Update the sensor from a Glow message."""
        description = self.entity_description
        value = self._read_value(message)

        if description.ignore_zero_values and value == 0:
            _LOGGER.debug("Ignored value of 0 for %s", self.unique_id)
            return
        if value in description.error_values:
            _LOGGER.debug(
                "Received error value %s for %s, state unknown",
                value,
                self.unique_id,
            )
            value = None

        if (
            description.meter_interval is not None
            and self._time_zone is not None
            and message.timestamp is not None
        ):
            self._attr_last_reset = determine_last_reset(
                message.timestamp,
                self._time_zone,
                description.meter_interval,
            )

        self._async_set_value(value)


class GlowPeriodVolumeSensor(GlowSensor, RestoreEntity):
    """A gas volume for the day, week or month.

    The IHD's own figure is used when it is in m³. Some IHDs report it in kWh
    instead, then it is worked out from the lifetime volume, which is in m³.
    The lifetime reading at the start of the period is stored across
    restarts.
    """

    def __init__(
        self,
        device_id: str,
        description: GlowSensorEntityDescription,
        time_zone: tzinfo | None,
        device_state: GlowDeviceState,
    ) -> None:
        """Initialise the sensor."""
        super().__init__(device_id, description, time_zone, device_state)
        self._period_volume = PeriodVolume()
        # Messages arrive before the stored state is read when the sensor is
        # added, the latest one is kept until then
        self._restored = False
        self._pending_message: GlowMessage | None = None

    async def async_added_to_hass(self) -> None:
        """Read the stored period, then any message that came before it."""
        await super().async_added_to_hass()
        if (data := await self.async_get_last_extra_data()) is not None:
            self._period_volume = PeriodVolume.from_dict(data.as_dict())
        self._restored = True
        if (message := self._pending_message) is not None:
            self._pending_message = None
            self.async_process_message(message)

    @property
    def extra_restore_state_data(self) -> RestoredExtraData:
        """Return the period's start reading, to store across restarts."""
        return RestoredExtraData(self._period_volume.as_dict())

    def _lifetime_volume(self, message: GlowMessage) -> float | None:
        """Return the lifetime volume in m³, or None if there is no usable one."""
        try:
            value = validate_state_value(
                gas_volume(message.payload, "cumulativevol", "cumulativevolunits"),
                numeric=True,
                timestamp=False,
            )
        except (
            AttributeError,
            IndexError,
            KeyError,
            TypeError,
            ValueError,
        ):
            return None
        if value is None or float(value) <= 0:
            # 0 is what the IHD sends when it can't read the meter
            return None
        return float(value)

    @callback
    def async_process_message(self, message: GlowMessage) -> None:
        """Update the sensor from a Glow message."""
        if not self._restored:
            self._pending_message = message
            return
        interval = self.entity_description.volume_interval
        if TYPE_CHECKING:
            assert interval is not None
        calculated = None
        volume = self._lifetime_volume(message)
        if volume is not None and self._time_zone is not None:
            reading_time = message.timestamp or dt_util.utcnow()
            calculated = self._period_volume.update(
                reading_time,
                volume,
                determine_last_reset(reading_time, self._time_zone, interval),
            )
            if calculated is None:
                _LOGGER.debug(
                    "Ignored a reading for %s older than the latest one",
                    self.unique_id,
                )
                return
        # The calculation is kept up to date even when the IHD's own figure
        # is used, so it can take over if the IHD stops sending it in m³
        if (value := self._read_value(message)) is None:
            value = calculated
        self._async_set_value(value)
