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
    """Return today's cost (standing charge + day kWh * unit rate).

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
        (standing_charge or 0) + (energy_import.get("day") or 0) * (unit_rate or 0),
        2,
    )


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


def _parse_datetime(value: Any) -> datetime | None:
    """Return a stored ISO datetime, or None if it isn't one."""
    if not isinstance(value, str):
        return None
    try:
        parsed = datetime.fromisoformat(value)
    except ValueError:
        return None
    return parsed if parsed.tzinfo is not None else None


@dataclass(slots=True)
class PeriodCost:
    """A week's or month's cost, added up from the meter's daily costs.

    The IHD only reports the cost of the current day, and at midnight that
    falls to the day's standing charge rather than to 0. Adding up the
    increases of the daily cost, as a Utility Meter helper does, misses that
    standing charge every day. Instead keep the cost of the days that have
    finished in the period, and add the latest cost of the current day.
    """

    # The start of the week or month being added up, None before any reading
    period_start: datetime | None = None
    # The start of the day the latest reading was for
    day_start: datetime | None = None
    # The cost of the days of the period that have finished
    finished_days_cost: float = 0.0
    # The latest cost reported for the current day
    day_cost: float = 0.0

    @property
    def total(self) -> float | None:
        """Return the period's cost so far, or None before any reading."""
        if self.period_start is None:
            return None
        return round(self.finished_days_cost + self.day_cost, 2)

    def update(
        self,
        day_cost: float,
        day_start: datetime,
        period_start: datetime,
    ) -> None:
        """Add a reading of the current day's cost."""
        if (
            self.period_start is not None
            and self.day_start is not None
            and (
                period_start < self.period_start
                or (period_start == self.period_start and day_start < self.day_start)
            )
        ):
            # A late message from a period or day already moved on from
            return
        if period_start != self.period_start:
            self.period_start = period_start
            self.finished_days_cost = 0.0
        elif day_start != self.day_start:
            # The previous day has finished, its last reported cost is its cost
            self.finished_days_cost += self.day_cost
        self.day_start = day_start
        self.day_cost = day_cost

    def restore(self, previous: PeriodCost) -> None:
        """Merge in the cost saved before Home Assistant restarted.

        A reading can arrive before the saved cost is loaded, so the saved
        cost is only kept if it is for the same period as the readings since.
        """
        if previous.period_start is None or previous.day_start is None:
            return
        if self.period_start is None or self.day_start is None:
            self.period_start = previous.period_start
            self.day_start = previous.day_start
            self.finished_days_cost = previous.finished_days_cost
            self.day_cost = previous.day_cost
            return
        if previous.period_start != self.period_start:
            return
        if previous.day_start == self.day_start:
            self.finished_days_cost = previous.finished_days_cost
        elif previous.day_start < self.day_start:
            self.finished_days_cost = previous.finished_days_cost + previous.day_cost

    def as_dict(self) -> dict[str, Any]:
        """Return the cost in a form that can be saved as JSON."""
        return {
            "period_start": (
                self.period_start.isoformat() if self.period_start else None
            ),
            "day_start": self.day_start.isoformat() if self.day_start else None,
            "finished_days_cost": self.finished_days_cost,
            "day_cost": self.day_cost,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> PeriodCost:
        """Return a cost saved by as_dict, or an empty one if it can't be read."""
        period_start = _parse_datetime(data.get("period_start"))
        day_start = _parse_datetime(data.get("day_start"))
        finished_days_cost = data.get("finished_days_cost")
        day_cost = data.get("day_cost")
        if (
            period_start is None
            or day_start is None
            or not isinstance(finished_days_cost, (int, float))
            or not isinstance(day_cost, (int, float))
        ):
            return cls()
        return cls(
            period_start=period_start,
            day_start=day_start,
            finished_days_cost=float(finished_days_cost),
            day_cost=float(day_cost),
        )
