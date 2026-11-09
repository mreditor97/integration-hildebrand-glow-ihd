"""Tests for the integration's helpers."""

import json
from datetime import UTC, datetime
from typing import Any
from zoneinfo import ZoneInfo

import pytest

from custom_components.hildebrand_glow_ihd.const import MeterInterval, TopicKind
from custom_components.hildebrand_glow_ihd.helpers import (
    GlowTopic,
    InvalidValueError,
    calculate_cost_today,
    calculate_period_cost,
    days_into_interval,
    determine_last_reset,
    entry_title,
    gas_volume,
    normalize_device_id,
    normalize_topic_prefix,
    parse_message,
    parse_topic,
    payload_timestamp,
    subscription_topic,
    validate_state_value,
)
from tests.const import ELECTRICITY_PAYLOAD, GAS_PAYLOAD, STATE_PAYLOAD


@pytest.mark.parametrize(
    ("device_id", "expected"),
    [
        ("+", "Hildebrand Glow IHD"),
        ("", "Hildebrand Glow IHD"),
        (None, "Hildebrand Glow IHD"),
        (" AABBCCDDEEFF ", "Hildebrand Glow IHD (AABBCCDDEEFF)"),
    ],
)
def test_entry_title(device_id: str | None, expected: str) -> None:
    """The title names the device, unless every device is detected."""
    assert entry_title(device_id) == expected


@pytest.mark.parametrize(
    ("device_id", "expected"),
    [
        ("aa:bb:cc:dd:ee:ff", "AABBCCDDEEFF"),
        (" AABBCC DDEEFF ", "AABBCCDDEEFF"),
        ("+", "+"),
        ("", "+"),
        (None, "+"),
    ],
)
def test_normalize_device_id(device_id: str | None, expected: str) -> None:
    """Device IDs are upper case without separators, blank means every device."""
    assert normalize_device_id(device_id) == expected


@pytest.mark.parametrize(
    ("topic_prefix", "expected"),
    [
        ("glow", "glow"),
        (" glow/# ", "glow"),
        ("glow/", "glow"),
        ("home/glow", "home/glow"),
        ("", "glow"),
        (None, "glow"),
    ],
)
def test_normalize_topic_prefix(topic_prefix: str | None, expected: str) -> None:
    """Prefixes lose wildcards, spaces and outer slashes, blank means glow."""
    assert normalize_topic_prefix(topic_prefix) == expected


def test_subscription_topic() -> None:
    """The subscription covers one device, or every device with +."""
    assert subscription_topic("glow", "+") == "glow/+/#"
    assert subscription_topic("glow", "AABBCCDDEEFF") == "glow/AABBCCDDEEFF/#"


@pytest.mark.parametrize(
    ("topic", "expected"),
    [
        ("glow/AABBCCDDEEFF/STATE", GlowTopic("AABBCCDDEEFF", TopicKind.STATE)),
        (
            "glow/AABBCCDDEEFF/SENSOR/electricitymeter",
            GlowTopic("AABBCCDDEEFF", TopicKind.ELECTRICITY_METER),
        ),
        (
            "glow/AABBCCDDEEFF/SENSOR/gasmeter",
            GlowTopic("AABBCCDDEEFF", TopicKind.GAS_METER),
        ),
        ("glow/AABBCCDDEEFF/SENSOR/other", None),
        ("glow/AABBCCDDEEFF", None),
        ("other/AABBCCDDEEFF/STATE", None),
        ("glowing/AABBCCDDEEFF/STATE", None),
    ],
)
def test_parse_topic(topic: str, expected: GlowTopic | None) -> None:
    """Only the three kinds of Glow topic under the prefix are recognised."""
    assert parse_topic("glow", topic) == expected


def test_parse_topic_with_nested_prefix() -> None:
    """A prefix with more than one level still finds the device ID."""
    assert parse_topic("home/glow", "home/glow/AABBCCDDEEFF/STATE") == GlowTopic(
        "AABBCCDDEEFF",
        TopicKind.STATE,
    )


def test_parse_state_message() -> None:
    """A STATE message is decoded with its own timestamp."""
    message = parse_message(
        "glow",
        "glow/AABBCCDDEEFF/STATE",
        json.dumps(STATE_PAYLOAD),
    )
    assert message is not None
    assert message.device_id == "AABBCCDDEEFF"
    assert message.kind is TopicKind.STATE
    assert message.payload == STATE_PAYLOAD
    assert message.timestamp == datetime(2022, 6, 11, 20, 54, 53, tzinfo=UTC)


@pytest.mark.parametrize(
    ("topic", "payload", "kind", "timestamp"),
    [
        (
            "glow/AABBCCDDEEFF/SENSOR/electricitymeter",
            ELECTRICITY_PAYLOAD,
            TopicKind.ELECTRICITY_METER,
            datetime(2022, 6, 11, 23, 38, tzinfo=UTC),
        ),
        (
            "glow/AABBCCDDEEFF/SENSOR/gasmeter",
            GAS_PAYLOAD,
            TopicKind.GAS_METER,
            datetime(2022, 6, 11, 20, 53, 52, tzinfo=UTC),
        ),
    ],
)
def test_parse_meter_message(
    topic: str,
    payload: dict[str, object],
    kind: TopicKind,
    timestamp: datetime,
) -> None:
    """A meter message takes its timestamp from the meter's data."""
    message = parse_message("glow", topic, json.dumps(payload).encode())
    assert message is not None
    assert message.kind is kind
    assert message.timestamp == timestamp


@pytest.mark.parametrize(
    ("topic", "payload"),
    [
        ("glow/AABBCCDDEEFF/STATE", "not json"),
        ("glow/AABBCCDDEEFF/STATE", "[1, 2]"),
        ("glow/AABBCCDDEEFF/OTHER", json.dumps(STATE_PAYLOAD)),
    ],
)
def test_parse_message_ignores_others(topic: str, payload: str) -> None:
    """Invalid JSON, non-object JSON and other topics aren't Glow messages."""
    assert parse_message("glow", topic, payload) is None


@pytest.mark.parametrize(
    "payload",
    [
        {},
        {"timestamp": "not a time"},
        {"timestamp": None},
        {"electricitymeter": "not an object"},
        {"gasmeter": {}},
    ],
)
def test_payload_without_timestamp(payload: dict[str, object]) -> None:
    """A missing or invalid timestamp is None rather than an error."""
    assert payload_timestamp(payload) is None


def _meter(day: float | None, price: dict[str, Any] | None) -> dict[str, Any]:
    """Return meter data with a day's usage and a price."""
    return {"energy": {"import": {"day": day, "price": price}}}


@pytest.mark.parametrize(
    ("meter_data", "expected"),
    [
        (ELECTRICITY_PAYLOAD["electricitymeter"], 0.9),
        (_meter(10, {"unitrate": 0.25, "standingcharge": None}), 2.5),
        (_meter(10, {"unitrate": None, "standingcharge": 0.5}), 0.5),
        (_meter(None, {"unitrate": 0.25, "standingcharge": 0.5}), 0.5),
        (_meter(10, {"unitrate": None, "standingcharge": None}), None),
        (_meter(10, None), None),
    ],
)
def test_calculate_cost_today(
    meter_data: dict[str, Any],
    expected: float | None,
) -> None:
    """Cost is standing charge + usage * unit rate, unknown with no prices."""
    assert calculate_cost_today(meter_data) == expected


def test_gas_volume() -> None:
    """Volumes are only reported when the IHD says they're in cubic metres."""
    assert gas_volume(GAS_PAYLOAD, "cumulativevol", "cumulativevolunits") == 1500.2
    # The IHD reports the day/week/month volumes in kWh in this payload
    assert gas_volume(GAS_PAYLOAD, "dayvol", "dayweekmonthvolunits") is None


def test_gas_volume_without_units() -> None:
    """A volume without a units field is reported as it is."""
    payload = {"gasmeter": {"energy": {"import": {"dayvol": 1.5}}}}
    assert gas_volume(payload, "dayvol", "dayweekmonthvolunits") == 1.5


def test_gas_volume_missing_field() -> None:
    """A missing volume field raises KeyError, which the sensor handles."""
    with pytest.raises(KeyError):
        gas_volume({"gasmeter": {"energy": {"import": {}}}}, "dayvol", "units")


LONDON = ZoneInfo("Europe/London")


@pytest.mark.parametrize(
    ("message_time", "time_zone", "interval", "expected"),
    [
        # 00:38 BST on Sunday 12 June 2022
        (
            datetime(2022, 6, 11, 23, 38, tzinfo=UTC),
            LONDON,
            MeterInterval.DAY,
            datetime(2022, 6, 11, 23, 0, tzinfo=UTC),
        ),
        (
            datetime(2022, 6, 11, 23, 38, tzinfo=UTC),
            ZoneInfo("UTC"),
            MeterInterval.DAY,
            datetime(2022, 6, 11, 0, 0, tzinfo=UTC),
        ),
        # Weeks start on Monday 6 June
        (
            datetime(2022, 6, 11, 23, 38, tzinfo=UTC),
            LONDON,
            MeterInterval.WEEK,
            datetime(2022, 6, 5, 23, 0, tzinfo=UTC),
        ),
        (
            datetime(2022, 6, 11, 23, 38, tzinfo=UTC),
            LONDON,
            MeterInterval.MONTH,
            datetime(2022, 5, 31, 23, 0, tzinfo=UTC),
        ),
        # 1 January is in GMT, so midnight is 00:00 UTC
        (
            datetime(2022, 6, 11, 23, 38, tzinfo=UTC),
            LONDON,
            MeterInterval.YEAR,
            datetime(2022, 1, 1, 0, 0, tzinfo=UTC),
        ),
    ],
)
def test_determine_last_reset(
    message_time: datetime,
    time_zone: ZoneInfo,
    interval: MeterInterval,
    expected: datetime,
) -> None:
    """The last reset is the start of the interval in the meter's time zone."""
    assert determine_last_reset(message_time, time_zone, interval) == expected


def test_payload_timestamp_without_time_zone_is_utc() -> None:
    """The IHD's timestamps are in UTC, even without a time zone."""
    assert payload_timestamp({"timestamp": "2022-06-11T20:54:53"}) == datetime(
        2022,
        6,
        11,
        20,
        54,
        53,
        tzinfo=UTC,
    )


@pytest.mark.parametrize(
    ("value", "numeric", "timestamp", "expected"),
    [
        (None, True, False, None),
        (1, True, False, 1),
        (0.5, True, False, 0.5),
        ("1.5", True, False, 1.5),
        ("joined", False, False, "joined"),
        (100, False, False, 100),
        (
            datetime(2022, 6, 11, tzinfo=UTC),
            False,
            True,
            datetime(2022, 6, 11, tzinfo=UTC),
        ),
    ],
)
def test_validate_state_value(
    value: Any,
    numeric: bool,  # noqa: FBT001
    timestamp: bool,  # noqa: FBT001
    expected: Any,
) -> None:
    """Values that can be a sensor's state are returned."""
    assert validate_state_value(value, numeric=numeric, timestamp=timestamp) == (
        expected
    )


@pytest.mark.parametrize(
    ("value", "numeric", "timestamp"),
    [
        ("abc", True, False),
        ("inf", True, False),
        (float("nan"), True, False),
        (True, True, False),
        ([1], False, False),
        ({"a": 1}, False, False),
        ("x" * 256, False, False),
        (datetime(2022, 6, 11), False, True),  # noqa: DTZ001
        ("2022-06-11T00:00:00Z", False, True),
    ],
)
def test_validate_state_value_invalid(
    value: Any,
    numeric: bool,  # noqa: FBT001
    timestamp: bool,  # noqa: FBT001
) -> None:
    """Values that can't be a sensor's state raise InvalidValueError."""
    with pytest.raises(InvalidValueError):
        validate_state_value(value, numeric=numeric, timestamp=timestamp)


def test_calculate_period_cost() -> None:
    """A period's cost has a standing charge for each day so far."""
    meter = {
        "energy": {
            "import": {
                "week": 4.761,
                "price": {"unitrate": 0.2061, "standingcharge": 0.4781},
            },
        },
    }
    # Monday, the first day of the week
    assert calculate_period_cost(meter, "week", 1) == 1.46
    assert calculate_period_cost(meter, "week", 3) == 2.42
    meter["energy"]["import"]["price"] = None
    assert calculate_period_cost(meter, "week", 3) is None


@pytest.mark.parametrize(
    ("message_time", "time_zone", "interval", "expected"),
    [
        # Monday 9 November 2026, the first day of the week
        (datetime(2026, 11, 9, 20, 32, tzinfo=UTC), UTC, MeterInterval.WEEK, 1),
        (datetime(2026, 11, 9, 20, 32, tzinfo=UTC), UTC, MeterInterval.MONTH, 9),
        (datetime(2026, 11, 8, 23, 59, tzinfo=UTC), UTC, MeterInterval.WEEK, 7),
        # 00:38 BST on Sunday 12 June 2022 is still Saturday in UTC
        (
            datetime(2022, 6, 11, 23, 38, tzinfo=UTC),
            ZoneInfo("Europe/London"),
            MeterInterval.WEEK,
            7,
        ),
        (datetime(2022, 6, 11, 23, 38, tzinfo=UTC), UTC, MeterInterval.WEEK, 6),
        (datetime(2022, 6, 11, 23, 38, tzinfo=UTC), UTC, MeterInterval.DAY, 1),
    ],
)
def test_days_into_interval(
    message_time: datetime,
    time_zone: ZoneInfo,
    interval: MeterInterval,
    expected: int,
) -> None:
    """The day of the interval counts from 1, in the meter's time zone."""
    assert days_into_interval(message_time, time_zone, interval) == expected
