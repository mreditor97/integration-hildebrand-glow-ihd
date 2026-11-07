"""Helpers for the Home Assistant Hildebrand Glow IHD Integration.

These read the MQTT topics and payloads a Glow device publishes, and
calculate values from its meter readings.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime, time, timedelta, tzinfo
from typing import Any

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
    """Return the timestamp of a payload, or None if it has no valid one."""
    timestamp = payload.get("timestamp")
    for meter in ("electricitymeter", "gasmeter"):
        if timestamp:
            break
        meter_data = payload.get(meter)
        if isinstance(meter_data, dict):
            timestamp = meter_data.get("timestamp")
    try:
        return datetime.fromisoformat(timestamp)  # type: ignore[arg-type]
    except (TypeError, ValueError):
        return None


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
