"""Helpers for the Home Assistant Hildebrand Glow IHD Integration.

These read the MQTT topics and payloads a Glow device publishes, and
calculate values from its meter readings.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime, time, timedelta, tzinfo
from math import isfinite
from typing import Any

from homeassistant.const import MAX_LENGTH_STATE_STATE
from homeassistant.util.json import json_loads_object

from .const import (
    DEFAULT_DEVICE_ID,
    DEFAULT_TITLE,
    DEFAULT_TOPIC_PREFIX,
    GAS_VOLUME_UNITS,
    MeterInterval,
    TopicKind,
)


def entry_title(device_id: str | None) -> str:
    """Return the config entry title for a configured device ID."""
    device_id = (device_id or "").strip()
    if not device_id or device_id == DEFAULT_DEVICE_ID:
        return DEFAULT_TITLE
    return f"{DEFAULT_TITLE} ({device_id})"


def no_messages_issue_id(entry_id: str) -> str:
    """Return the ID of the repair issue raised when an entry hears nothing."""
    return f"no_messages_{entry_id}"


def period_costs_removed_issue_id(entry_id: str) -> str:
    """Return the ID of the repair issue raised when cost sensors are removed."""
    return f"period_costs_removed_{entry_id}"


@dataclass(frozen=True, slots=True)
class GlowTopic:
    """The device and kind of message an MQTT topic is for."""

    device_id: str
    kind: TopicKind


def normalize_device_id(device_id: str | None) -> str:
    """Return a device ID in the form the IHD uses in its MQTT topics.

    The ID is the device's MAC address in upper case without separators,
    e.g. ``AABBCCDDEEFF``. A blank ID, like ``+``, matches every device.
    """
    normalized = (device_id or "").strip().upper().replace(":", "").replace(" ", "")
    return normalized or DEFAULT_DEVICE_ID


def normalize_topic_prefix(topic_prefix: str | None) -> str:
    """Return a topic prefix with wildcards, spaces and slashes removed."""
    normalized = (topic_prefix or "").strip().replace("#", "").replace(" ", "")
    return normalized.strip("/") or DEFAULT_TOPIC_PREFIX


def settings_overlap(
    topic_prefix: str,
    device_id: str,
    other_topic_prefix: str,
    other_device_id: str,
) -> bool:
    """Return whether two entries' settings would pick up the same device.

    The settings are expected to be normalised. Two entries for the same
    device would create sensors with the same unique IDs, and Home Assistant
    would refuse the second set. The sensors' unique IDs don't include the
    topic prefix, so the same device ID clashes under any prefix.
    """
    if device_id == other_device_id:
        return True
    return topic_prefix == other_topic_prefix and DEFAULT_DEVICE_ID in (
        device_id,
        other_device_id,
    )


def subscription_topic(topic_prefix: str, device_id: str) -> str:
    """Return the MQTT topic filter for one device's messages, or every device's."""
    return f"{topic_prefix}/{device_id}/#"


def parse_topic(topic_prefix: str, topic: str) -> GlowTopic | None:
    """Return the device and kind of message a topic is for.

    Returns None for a topic that isn't under the prefix or isn't one of the
    kinds in ``TopicKind``.
    """
    prefix = f"{topic_prefix}/"
    if not topic.startswith(prefix):
        return None
    device_id, _, rest = topic.removeprefix(prefix).partition("/")
    if not device_id or not rest:
        return None
    try:
        kind = TopicKind(rest.rpartition("/")[2])
    except ValueError:
        return None
    return GlowTopic(device_id=device_id, kind=kind)


@dataclass(frozen=True, slots=True)
class GlowMessage:
    """A message from a Glow device, with its JSON payload decoded."""

    device_id: str
    kind: TopicKind
    payload: dict[str, Any]
    # When the IHD sent the message, or None if the payload has no timestamp
    timestamp: datetime | None


def payload_timestamp(payload: dict[str, Any]) -> datetime | None:
    """Return the timestamp of a payload, or None if it has no valid one.

    The IHD sends its timestamps in UTC, so one without a time zone is read
    as UTC.
    """
    timestamp = payload.get("timestamp")
    for meter in ("electricitymeter", "gasmeter"):
        if timestamp:
            break
        meter_data = payload.get(meter)
        if isinstance(meter_data, dict):
            timestamp = meter_data.get("timestamp")
    try:
        parsed = datetime.fromisoformat(timestamp)  # type: ignore[arg-type]
    except (TypeError, ValueError):
        return None
    return parsed if parsed.tzinfo is not None else parsed.replace(tzinfo=UTC)


def parse_message(
    topic_prefix: str,
    topic: str,
    payload: str | bytes | bytearray,
) -> GlowMessage | None:
    """Return a Glow message, or None if the topic or payload isn't one.

    Messages on other topics, and payloads that aren't a JSON object, are
    ignored rather than raising.
    """
    glow_topic = parse_topic(topic_prefix, topic)
    if glow_topic is None:
        return None
    try:
        data = json_loads_object(payload)
    except ValueError:
        return None
    return GlowMessage(
        device_id=glow_topic.device_id,
        kind=glow_topic.kind,
        payload=data,
        timestamp=payload_timestamp(data),
    )


def device_versions(payload: dict[str, Any]) -> tuple[str | None, str | None]:
    """Return the software and hardware versions from a STATE payload."""
    software = payload.get("software")
    hardware = payload.get("hardware")
    return (
        software if isinstance(software, str) else None,
        hardware if isinstance(hardware, str) else None,
    )


class InvalidValueError(ValueError):
    """A value from a payload can't be used as a sensor's state."""


def validate_state_value(value: Any, *, numeric: bool, timestamp: bool) -> Any:
    """Return a value from a payload if it can be a sensor's state.

    Home Assistant raises an error on every state write for a numeric sensor
    with a value that isn't a finite number, a timestamp sensor with a value
    that isn't a time zone aware datetime, or a state longer than 255
    characters. Raise InvalidValueError for those instead, so the sensor can
    report unknown and log it once. None, a missing value, is always valid.
    """
    if value is None:
        return None
    if timestamp:
        if isinstance(value, datetime) and value.tzinfo is not None:
            return value
        msg = f"{value!r} is not a time zone aware datetime"
        raise InvalidValueError(msg)
    if isinstance(value, bool) or not isinstance(value, (str, int, float)):
        msg = f"{value!r} is not a number or text"
        raise InvalidValueError(msg)
    if numeric:
        try:
            number = float(value)
        except ValueError:
            msg = f"{value!r} is not a number"
            raise InvalidValueError(msg) from None
        if not isfinite(number):
            msg = f"{value!r} is not a finite number"
            raise InvalidValueError(msg)
        return number if isinstance(value, str) else value
    if len(str(value)) > MAX_LENGTH_STATE_STATE:
        msg = f"{value!r} is longer than {MAX_LENGTH_STATE_STATE} characters"
        raise InvalidValueError(msg)
    return value


def calculate_cost_today(meter_data: dict[str, Any]) -> float | None:
    """Return today's cost (standing charge + day kWh * unit rate)."""
    return calculate_period_cost(meter_data, "day", 1)


def calculate_period_cost(
    meter_data: dict[str, Any],
    field: str,
    days: int,
) -> float | None:
    """Return a period's cost from the IHD's kWh for it.

    The cost is the standing charge for each day of the period so far, plus
    the period's kWh at the current unit rate. The IHD only reports the
    current rates, so a period in which they changed is priced at the
    current ones.

    The IHD publishes ``null`` for the unit rate and/or standing charge when
    the supplier has not sent tariff data to the meter. Rather than raising a
    TypeError on every message, treat a missing component as zero and only
    report unknown (None) when there is no price information at all.
    """
    energy_import = meter_data["energy"]["import"]
    price = energy_import.get("price") or {}
    unit_rate = price.get("unitrate")
    standing_charge = price.get("standingcharge")
    if unit_rate is None and standing_charge is None:
        return None
    return round(
        (standing_charge or 0) * days
        + (energy_import.get(field) or 0) * (unit_rate or 0),
        2,
    )


def days_into_interval(
    message_time: datetime,
    meter_time_zone: tzinfo,
    meter_interval: MeterInterval,
) -> int:
    """Return which day of the meter's reset interval a message is from.

    The first day of the interval is 1, so this is the number of standing
    charges in the interval so far.
    """
    start = determine_last_reset(message_time, meter_time_zone, meter_interval)
    start_date = start.astimezone(meter_time_zone).date()
    return (message_time.astimezone(meter_time_zone).date() - start_date).days + 1


def gas_volume(payload: dict[str, Any], field: str, units_field: str) -> float | None:
    """Return a gas volume reading only if the IHD reports it in cubic metres.

    Some meters/IHDs populate the volume fields with the kWh figures and say
    so in the accompanying units field (e.g. "dayweekmonthvolunits": "kWh").
    Reporting those as m³ is wrong, and kWh can't be converted to m³ without
    the calorific value, so report the state as unknown instead.
    """
    energy_import = payload["gasmeter"]["energy"]["import"]
    units = energy_import.get(units_field)
    if units is not None and str(units).strip().lower() not in GAS_VOLUME_UNITS:
        return None
    value: float = energy_import[field]
    return value


def determine_last_reset(
    message_time: datetime,
    meter_time_zone: tzinfo,
    meter_interval: MeterInterval,
) -> datetime:
    """Return the start of the meter's current reset interval in UTC."""
    meter_datetime = message_time.astimezone(meter_time_zone)
    meter_midnight = datetime.combine(
        meter_datetime.date(),
        time.min,
        meter_datetime.tzinfo,
    )
    match meter_interval:
        case MeterInterval.DAY:
            last_reset = meter_midnight
        case MeterInterval.WEEK:
            last_reset = meter_midnight - timedelta(days=meter_midnight.weekday())
        case MeterInterval.MONTH:
            last_reset = meter_midnight.replace(day=1)
        case MeterInterval.YEAR:
            last_reset = meter_midnight.replace(day=1, month=1)
    return last_reset.astimezone(UTC)


# Gas meters report to 3 decimal places of a cubic metre
GAS_VOLUME_PRECISION = 3


@dataclass(slots=True)
class PeriodVolume:
    """Works out a period's gas volume from the lifetime volume reading.

    Some IHDs report the day, week and month volumes in kWh, which can't be
    turned into m³. The lifetime volume is still in m³, so a period's volume
    is the lifetime reading now less its reading when the period started.

    The reading at the start of a period is worked out from the last reading
    before it and the first one after it. A meter sends a reading every half
    hour or so, so they are close together, unless Home Assistant was off
    across the start. Then the gas used while it was off is shared between
    the two periods by time, as if it had been used at a steady rate.

    A period that started before the first reading is counted from that
    reading, so the first day, week and month after an install are short.
    """

    # When the current period started, in UTC
    period_start: datetime | None = None
    # The lifetime reading when the current period started
    start_volume: float | None = None
    # The latest lifetime reading and when it was taken
    last_volume: float | None = None
    last_time: datetime | None = None

    def update(
        self,
        reading_time: datetime,
        volume: float,
        period_start: datetime,
    ) -> float | None:
        """Add a lifetime reading and return the period's volume so far.

        Returns None for a reading older than the latest one.
        """
        last_time, last_volume = self.last_time, self.last_volume
        if last_time is not None and reading_time < last_time:
            return None
        if (
            self.period_start != period_start
            or self.start_volume is None
            or last_volume is None
        ):
            self.period_start = period_start
            self.start_volume = volume
            if (
                last_time is not None
                and last_volume is not None
                and last_time < period_start
                and last_volume <= volume
            ):
                # Share the gas used between the two readings by time
                share = (period_start - last_time) / (reading_time - last_time)
                self.start_volume = last_volume + (volume - last_volume) * share
        elif volume < last_volume:
            # The lifetime reading went backwards, e.g. a new meter. Keep the
            # period's volume so far and count on from the new reading.
            self.start_volume = volume - (last_volume - self.start_volume)
        self.last_time, self.last_volume = reading_time, volume
        return round(max(volume - self.start_volume, 0.0), GAS_VOLUME_PRECISION)

    def as_dict(self) -> dict[str, Any]:
        """Return the state to store across restarts."""
        return {
            "period_start": _isoformat(self.period_start),
            "start_volume": self.start_volume,
            "last_volume": self.last_volume,
            "last_time": _isoformat(self.last_time),
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> PeriodVolume:
        """Return the state stored before a restart, or a new one if invalid."""
        try:
            restored = cls(
                period_start=_parse_utc(data.get("period_start")),
                start_volume=_optional_float(data.get("start_volume")),
                last_volume=_optional_float(data.get("last_volume")),
                last_time=_parse_utc(data.get("last_time")),
            )
        except (TypeError, ValueError):
            return cls()
        if None in (restored.period_start, restored.start_volume) or None in (
            restored.last_time,
            restored.last_volume,
        ):
            return cls()
        return restored


def electricity_day_reading(
    payload: dict[str, Any],
) -> tuple[float, float | None, float | None]:
    """Return the day's import kWh, unit rate and standing charge.

    Raises KeyError, TypeError or ValueError when the day's kWh is missing or
    any of them isn't a number. The rates are None when the IHD sends null.
    """
    energy_import = payload["electricitymeter"]["energy"]["import"]
    price = energy_import.get("price") or {}
    if not isinstance(price, dict):
        msg = f"{price!r} is not a price"
        raise TypeError(msg)
    day_kwh = _optional_float(energy_import.get("day"))
    if day_kwh is None:
        msg = "The day's kWh is missing"
        raise ValueError(msg)
    return (
        day_kwh,
        _optional_float(price.get("unitrate")),
        _optional_float(price.get("standingcharge")),
    )


# The units a unit rate sensor can be in, and what to multiply its state by
# to get GBP/kWh
UNIT_RATE_UNITS: dict[str, float] = {
    "gbp/kwh": 1.0,
    "£/kwh": 1.0,
    "p/kwh": 0.01,
    "pence/kwh": 0.01,
}


def unit_rate_from_state(state: str, unit: str | None) -> float:
    """Return a unit rate sensor's state in GBP/kWh.

    Raises ValueError when the state isn't a number or its unit isn't one
    in UNIT_RATE_UNITS.
    """
    factor = UNIT_RATE_UNITS.get((unit or "").replace(" ", "").lower())
    if factor is None:
        msg = f"{unit!r} isn't a unit rate unit, such as GBP/kWh or p/kWh"
        raise ValueError(msg)
    rate = float(state)
    if not isfinite(rate):
        msg = f"{state!r} is not a finite number"
        raise ValueError(msg)
    return rate * factor


# How long either side of midnight the meter's day kWh can still be the day
# before's
METER_RESET_GRACE = timedelta(minutes=30)


@dataclass(slots=True)
class VariableDayCost:
    """Works out today's electricity cost when the unit rate can change.

    The IHD reports the day's kWh and the current unit rate. Each increase in
    the day's kWh is priced at the rate from the reading before it, as that
    rate applied while the energy was used. The cost so far and the latest
    reading are stored across restarts.

    A new day starts when the day's kWh goes down, as it does when the meter
    resets its daily total. If it hasn't gone down by half an hour after the
    meter's midnight, e.g. because Home Assistant was off across it, the day
    starts then. The kWh already used when a day starts that way, or after
    setup, is priced at the current rate.
    """

    # When the current day started, in UTC
    last_reset: datetime | None = None
    # The cost of the day's kWh so far, without the standing charge
    energy_cost: float = 0.0
    # The latest reading's day kWh and the unit rate it reported
    previous_kwh: float | None = None
    previous_rate: float | None = None
    # The latest standing charge reported
    standing_charge: float | None = None
    # When the latest reading was taken
    last_message_time: datetime | None = None
    # Whether the latest reading's unit rate was 0
    zero_rate_seen: bool = False

    def has_price(self, unit_rate: float | None, standing_charge: float | None) -> bool:
        """Return whether a reading with these rates can be priced."""
        return any(
            value is not None
            for value in (
                unit_rate,
                standing_charge,
                self.previous_rate,
                self.standing_charge,
            )
        )

    def _meter_not_reset_yet(
        self,
        reading_time: datetime,
        period_start: datetime,
        day_kwh: float,
    ) -> bool:
        """Return whether the meter's day kWh is still the day before's.

        The meter resets its day's kWh a little after midnight, so for a
        short time after it the readings are still the day before's. They
        are added to that day until the kWh goes down.
        """
        return (
            self.previous_kwh is not None
            and self.last_message_time is not None
            and day_kwh >= self.previous_kwh
            and self.last_message_time >= period_start - METER_RESET_GRACE
            and reading_time < period_start + METER_RESET_GRACE
        )

    def _unit_rate(
        self,
        unit_rate: float | None,
        *,
        trust_zero_rate: bool,
    ) -> float | None:
        """Return a reading's unit rate, or None if it shouldn't be used.

        The IHD sends 0 when it can't read the meter, but a tariff's rate
        can really be 0. A 0 is used once a second reading in a row has it,
        or straight away when it is trusted, e.g. from a unit rate sensor.
        """
        if unit_rate != 0 or trust_zero_rate:
            self.zero_rate_seen = False
            return unit_rate
        if self.zero_rate_seen:
            return unit_rate
        self.zero_rate_seen = True
        return None

    def update(  # noqa: PLR0913
        self,
        reading_time: datetime,
        period_start: datetime,
        day_kwh: float,
        unit_rate: float | None,
        standing_charge: float | None,
        *,
        trust_zero_rate: bool = False,
    ) -> float | None:
        """Add a reading and return the day's cost so far.

        The day the cost is for is then last_reset. Returns None for a
        reading that is ignored.

        A reading older than the latest one is ignored if its kWh is lower,
        so a message that arrives late doesn't start a new day. If its kWh
        isn't lower, the IHD's clock was put back, and it is used.

        A 0 for the day's kWh after the day has started is what the IHD
        sends when it can't read the meter, so it isn't used.
        """
        last_time = self.last_message_time
        if last_time is not None and reading_time < last_time:
            if self.previous_kwh is None or day_kwh < self.previous_kwh:
                return None
            # The clock was put back, keep counting from the latest reading
            reading_time = last_time
        if self.last_reset is not None and (
            period_start < self.last_reset
            or self._meter_not_reset_yet(reading_time, period_start, day_kwh)
        ):
            period_start = self.last_reset
        new_day = self.last_reset != period_start
        if day_kwh == 0 and not new_day and self.previous_kwh:
            # The IHD sends 0 when it can't read the meter. Only a new day's
            # 0 is real, a drop to 0 later in the day would lose the cost so
            # far, so the reading is skipped.
            return self._cost()
        unit_rate = self._unit_rate(unit_rate, trust_zero_rate=trust_zero_rate)
        if standing_charge is not None:
            self.standing_charge = standing_charge
        if (
            new_day
            or self.previous_kwh is None
            or self.previous_rate is None
            or day_kwh < self.previous_kwh
        ):
            rate = unit_rate if unit_rate is not None else self.previous_rate
            self.energy_cost = day_kwh * (rate or 0.0)
            self.previous_rate = rate
        else:
            self.energy_cost += (day_kwh - self.previous_kwh) * self.previous_rate
            if unit_rate is not None:
                self.previous_rate = unit_rate
        # Until a rate is known the kWh can't be priced, so it is priced from
        # the first reading with one
        self.previous_kwh = day_kwh if self.previous_rate is not None else None
        self.last_reset = period_start
        self.last_message_time = reading_time
        return self._cost()

    def _cost(self) -> float:
        """Return the day's cost so far, with the standing charge."""
        return round(self.energy_cost + (self.standing_charge or 0.0), 2)

    def as_dict(self) -> dict[str, Any]:
        """Return the state to store across restarts."""
        return {
            "last_reset": _isoformat(self.last_reset),
            "energy_cost": self.energy_cost,
            "previous_kwh": self.previous_kwh,
            "previous_rate": self.previous_rate,
            "standing_charge": self.standing_charge,
            "last_message_time": _isoformat(self.last_message_time),
            "zero_rate_seen": self.zero_rate_seen,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> VariableDayCost:
        """Return the state stored before a restart, or a new one if invalid."""
        try:
            energy_cost = _optional_float(data.get("energy_cost"))
            return cls(
                last_reset=_parse_utc(data.get("last_reset")),
                energy_cost=energy_cost if energy_cost is not None else 0.0,
                previous_kwh=_optional_float(data.get("previous_kwh")),
                previous_rate=_optional_float(data.get("previous_rate")),
                standing_charge=_optional_float(data.get("standing_charge")),
                last_message_time=_parse_utc(data.get("last_message_time")),
                zero_rate_seen=data.get("zero_rate_seen") is True,
            )
        except (TypeError, ValueError):
            return cls()


def _isoformat(value: datetime | None) -> str | None:
    return value.isoformat() if value is not None else None


def _parse_utc(value: Any) -> datetime | None:
    if value is None:
        return None
    parsed = datetime.fromisoformat(value)
    if parsed.tzinfo is None:
        msg = f"{value!r} has no time zone"
        raise ValueError(msg)
    return parsed.astimezone(UTC)


def _optional_float(value: Any) -> float | None:
    if value is None:
        return None
    if isinstance(value, bool):
        msg = f"{value!r} is not a number"
        raise TypeError(msg)
    number = float(value)
    if not isfinite(number):
        msg = f"{value!r} is not a finite number"
        raise ValueError(msg)
    return number
