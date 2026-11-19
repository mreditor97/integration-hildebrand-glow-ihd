"""Tests for the integration's helpers."""

import json
from datetime import UTC, datetime, timedelta
from typing import Any
from zoneinfo import ZoneInfo

import pytest

from custom_components.hildebrand_glow_ihd.const import MeterInterval, TopicKind
from custom_components.hildebrand_glow_ihd.helpers import (
    GlowTopic,
    InvalidValueError,
    PeriodVolume,
    VariableDayCost,
    calculate_cost_today,
    calculate_period_cost,
    days_into_interval,
    determine_last_reset,
    electricity_day_reading,
    entry_title,
    gas_volume,
    normalize_device_id,
    normalize_topic_prefix,
    parse_message,
    parse_topic,
    payload_timestamp,
    subscription_topic,
    unit_rate_from_state,
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


def _utc(text: str) -> datetime:
    return datetime.fromisoformat(text).replace(tzinfo=UTC)


DAY_1 = _utc("2026-11-07T00:00:00")
DAY_2 = _utc("2026-11-08T00:00:00")


def test_period_volume_counts_from_first_reading() -> None:
    """A period that started before the first reading counts from it."""
    period = PeriodVolume()
    assert period.update(_utc("2026-11-07T12:00:00"), 3620.5, DAY_1) == 0.0
    assert period.update(_utc("2026-11-07T12:30:00"), 3621.0, DAY_1) == 0.5
    assert period.update(_utc("2026-11-07T23:30:00"), 3622.817, DAY_1) == 2.317


def test_period_volume_new_period() -> None:
    """A new period starts from the reading at its start."""
    period = PeriodVolume()
    period.update(_utc("2026-11-07T12:00:00"), 3620.0, DAY_1)
    period.update(_utc("2026-11-07T23:45:00"), 3621.0, DAY_1)
    # 15 minutes either side of midnight, half of the 0.2 m³ is today's
    assert period.update(_utc("2026-11-08T00:15:00"), 3621.2, DAY_2) == 0.1
    assert period.update(_utc("2026-11-08T01:00:00"), 3621.5, DAY_2) == 0.4


def test_period_volume_shares_gap_by_time() -> None:
    """Gas used while nothing was heard is shared between periods by time."""
    period = PeriodVolume()
    period.update(_utc("2026-11-07T18:00:00"), 3620.0, DAY_1)
    # Nothing heard for 12 hours, 6 of them today
    assert period.update(_utc("2026-11-08T06:00:00"), 3622.0, DAY_2) == 1.0


def test_period_volume_reading_goes_backwards() -> None:
    """A lifetime reading that goes backwards keeps the period's volume."""
    period = PeriodVolume()
    period.update(_utc("2026-11-08T01:00:00"), 3620.0, DAY_2)
    period.update(_utc("2026-11-08T02:00:00"), 3621.0, DAY_2)
    assert period.update(_utc("2026-11-08T03:00:00"), 5.0, DAY_2) == 1.0
    assert period.update(_utc("2026-11-08T04:00:00"), 5.5, DAY_2) == 1.5
    # A backwards reading across a reset starts the new period from it
    day_3 = DAY_2 + timedelta(days=1)
    assert period.update(_utc("2026-11-09T01:00:00"), 1.0, day_3) == 0.0


def test_period_volume_ignores_older_reading() -> None:
    """A reading older than the latest one is ignored."""
    period = PeriodVolume()
    period.update(_utc("2026-11-08T02:00:00"), 3621.0, DAY_2)
    assert period.update(_utc("2026-11-08T01:00:00"), 3620.0, DAY_2) is None
    assert period.update(_utc("2026-11-08T03:00:00"), 3621.5, DAY_2) == 0.5


def test_period_volume_round_trip() -> None:
    """The stored state is read back the same."""
    period = PeriodVolume()
    period.update(_utc("2026-11-08T01:00:00"), 3620.0, DAY_2)
    period.update(_utc("2026-11-08T02:00:00"), 3621.0, DAY_2)
    stored = json.loads(json.dumps(period.as_dict()))
    assert PeriodVolume.from_dict(stored) == period


@pytest.mark.parametrize(
    "data",
    [
        {},
        {"period_start": "2026-11-08T00:00:00+00:00"},
        {
            "period_start": "not a time",
            "start_volume": 1,
            "last_volume": 1,
            "last_time": "2026-11-08T00:00:00+00:00",
        },
        {
            "period_start": "2026-11-08T00:00:00",
            "start_volume": 1,
            "last_volume": 1,
            "last_time": "2026-11-08T00:00:00+00:00",
        },
        {
            "period_start": "2026-11-08T00:00:00+00:00",
            "start_volume": "nan",
            "last_volume": 1,
            "last_time": "2026-11-08T00:00:00+00:00",
        },
        {
            "period_start": "2026-11-08T00:00:00+00:00",
            "start_volume": True,
            "last_volume": 1,
            "last_time": "2026-11-08T00:00:00+00:00",
        },
        {
            "period_start": 5,
            "start_volume": 1,
            "last_volume": 1,
            "last_time": "2026-11-08T00:00:00+00:00",
        },
    ],
)
def test_period_volume_invalid_stored_state(data: dict[str, Any]) -> None:
    """Unusable stored state starts afresh."""
    assert PeriodVolume.from_dict(data) == PeriodVolume()


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


def test_variable_day_cost_prices_usage_at_previous_rate() -> None:
    """Each increase in kWh is priced at the rate from the reading before."""
    cost = VariableDayCost()
    # The kWh already used today is priced at the current rate
    assert cost.update(_utc("2026-11-07T10:00:00"), DAY_1, 10.0, 0.1, 0.5) == 1.5
    # The rate changes to 0.3, the 2 kWh since were used at 0.1
    assert cost.update(_utc("2026-11-07T11:00:00"), DAY_1, 12.0, 0.3, 0.5) == 1.7
    assert cost.update(_utc("2026-11-07T12:00:00"), DAY_1, 13.5, 0.3, 0.5) == 2.15
    # A missing rate keeps the last one
    assert cost.update(_utc("2026-11-07T13:00:00"), DAY_1, 14.5, None, None) == 2.45


def test_variable_day_cost_new_day() -> None:
    """A new day starts from the kWh reported at its first reading."""
    cost = VariableDayCost()
    cost.update(_utc("2026-11-07T23:00:00"), DAY_1, 10.0, 0.1, 0.5)
    assert cost.update(_utc("2026-11-08T01:00:00"), DAY_2, 1.0, 0.4, 0.5) == 0.9
    assert cost.last_reset == DAY_2


def test_variable_day_cost_meter_resets_after_midnight() -> None:
    """A reading after midnight with yesterday's kWh doesn't stick."""
    cost = VariableDayCost()
    cost.update(_utc("2026-11-07T23:59:00"), DAY_1, 10.0, 0.1, 0.5)
    # The meter hasn't reset its day's kWh yet
    cost.update(_utc("2026-11-08T00:00:10"), DAY_2, 10.0, 0.1, 0.5)
    # Now it has
    assert cost.update(_utc("2026-11-08T00:01:10"), DAY_2, 0.05, 0.1, 0.5) == 0.51
    assert cost.update(_utc("2026-11-08T06:00:00"), DAY_2, 2.0, 0.1, 0.5) == 0.7


def test_variable_day_cost_meter_resets_before_midnight() -> None:
    """The day's kWh going down starts a new day."""
    cost = VariableDayCost()
    cost.update(_utc("2026-11-07T22:00:00"), DAY_1, 10.0, 0.1, 0.5)
    assert cost.update(_utc("2026-11-07T23:10:00"), DAY_1, 0.2, 0.1, 0.5) == 0.52
    assert cost.update(_utc("2026-11-07T23:40:00"), DAY_1, 0.5, 0.1, 0.5) == 0.55


def test_variable_day_cost_no_rate_yet() -> None:
    """Without a unit rate, the kWh is priced from the first reading with one."""
    cost = VariableDayCost()
    assert not cost.has_price(None, None)
    assert cost.has_price(None, 0.5)
    assert cost.update(_utc("2026-11-07T10:00:00"), DAY_1, 10.0, None, 0.5) == 0.5
    assert cost.previous_kwh is None
    assert cost.update(_utc("2026-11-07T11:00:00"), DAY_1, 12.0, 0.1, 0.5) == 1.7
    assert cost.update(_utc("2026-11-07T12:00:00"), DAY_1, 13.0, 0.1, 0.5) == 1.8


def test_variable_day_cost_ignores_older_reading() -> None:
    """A reading older than the latest one is ignored."""
    cost = VariableDayCost()
    cost.update(_utc("2026-11-07T11:00:00"), DAY_1, 12.0, 0.1, 0.5)
    assert cost.update(_utc("2026-11-07T10:00:00"), DAY_1, 10.0, 0.3, 0.5) is None
    assert cost.update(_utc("2026-11-07T12:00:00"), DAY_1, 13.0, 0.1, 0.5) == 1.8


def test_variable_day_cost_ignores_zero_readings() -> None:
    """A 0 sent when the IHD can't read the meter doesn't lose the cost."""
    cost = VariableDayCost()
    cost.update(_utc("2026-11-07T10:00:00"), DAY_1, 10.0, 0.1, 0.5)
    assert cost.update(_utc("2026-11-07T11:00:00"), DAY_1, 12.0, 0.3, 0.5) == 1.7
    # The day's kWh drops to 0
    assert cost.update(_utc("2026-11-07T12:00:00"), DAY_1, 0.0, 0.3, 0.5) == 1.7
    assert cost.update(_utc("2026-11-07T13:00:00"), DAY_1, 13.0, 0.3, 0.5) == 2.0
    # The unit rate drops to 0
    assert cost.update(_utc("2026-11-07T14:00:00"), DAY_1, 14.0, 0.0, 0.5) == 2.3
    assert cost.update(_utc("2026-11-07T15:00:00"), DAY_1, 15.0, 0.3, 0.5) == 2.6


def test_variable_day_cost_zero_at_start_of_day() -> None:
    """A new day's first reading can be 0 kWh."""
    cost = VariableDayCost()
    cost.update(_utc("2026-11-07T23:30:00"), DAY_1, 10.0, 0.1, 0.5)
    assert cost.update(_utc("2026-11-08T00:00:30"), DAY_2, 0.0, 0.1, 0.5) == 0.5
    assert cost.update(_utc("2026-11-08T01:00:00"), DAY_2, 1.0, 0.1, 0.5) == 0.6


def test_variable_day_cost_holds_day_until_meter_resets() -> None:
    """Readings just after midnight with the day before's kWh stay in it."""
    cost = VariableDayCost()
    cost.update(_utc("2026-11-07T23:50:00"), DAY_1, 10.0, 0.1, 0.5)
    # Still the day before's kWh, and its cost
    assert cost.update(_utc("2026-11-08T00:00:10"), DAY_2, 10.2, 0.1, 0.5) == 1.52
    assert cost.last_reset == DAY_1
    # The meter resets
    assert cost.update(_utc("2026-11-08T00:02:00"), DAY_2, 0.01, 0.1, 0.5) == 0.5
    assert cost.last_reset == DAY_2


def test_variable_day_cost_new_day_without_reset() -> None:
    """Without a reset, the day starts half an hour after midnight."""
    cost = VariableDayCost()
    cost.update(_utc("2026-11-07T23:50:00"), DAY_1, 10.0, 0.1, 0.5)
    assert cost.update(_utc("2026-11-08T00:40:00"), DAY_2, 10.5, 0.1, 0.5) == 1.55
    assert cost.last_reset == DAY_2


def test_variable_day_cost_off_across_midnight() -> None:
    """A first reading long after the last one starts the new day."""
    cost = VariableDayCost()
    cost.update(_utc("2026-11-07T20:00:00"), DAY_1, 10.0, 0.1, 0.5)
    assert cost.update(_utc("2026-11-08T00:10:00"), DAY_2, 10.5, 0.1, 0.5) == 1.55
    assert cost.last_reset == DAY_2


def test_variable_day_cost_clock_put_back() -> None:
    """Readings are still used when the IHD's clock is put back."""
    cost = VariableDayCost()
    cost.update(_utc("2026-11-08T00:20:00"), DAY_2, 1.0, 0.1, 0.5)
    # The clock goes back an hour, into the day before
    assert cost.update(_utc("2026-11-07T23:30:00"), DAY_1, 2.0, 0.1, 0.5) == 0.7
    assert cost.last_reset == DAY_2
    assert cost.update(_utc("2026-11-07T23:40:00"), DAY_1, 3.0, 0.1, 0.5) == 0.8


def test_variable_day_cost_real_zero_rate() -> None:
    """A 0 unit rate is used once two readings in a row have it."""
    cost = VariableDayCost()
    cost.update(_utc("2026-11-07T10:00:00"), DAY_1, 10.0, 0.2, 0.5)
    # The first 0 could be a bad reading, so 0.2 is kept for now
    assert cost.update(_utc("2026-11-07T10:01:00"), DAY_1, 10.0, 0.0, 0.5) == 2.5
    assert cost.update(_utc("2026-11-07T10:02:00"), DAY_1, 10.1, 0.0, 0.5) == 2.52
    # Now the rate is 0
    assert cost.update(_utc("2026-11-07T11:00:00"), DAY_1, 15.0, 0.2, 0.5) == 2.52
    assert cost.update(_utc("2026-11-07T12:00:00"), DAY_1, 16.0, 0.2, 0.5) == 2.72


def test_variable_day_cost_round_trip() -> None:
    """The stored state is read back the same."""
    cost = VariableDayCost()
    cost.update(_utc("2026-11-07T11:00:00"), DAY_1, 12.0, 0.1, 0.5)
    stored = json.loads(json.dumps(cost.as_dict()))
    assert VariableDayCost.from_dict(stored) == cost


@pytest.mark.parametrize(
    "data",
    [
        {"energy_cost": "nan"},
        {"energy_cost": True},
        {"previous_kwh": "lots"},
        {"last_reset": "not a time"},
        {"last_reset": "2026-11-08T00:00:00"},
        {"last_message_time": 5},
    ],
)
def test_variable_day_cost_invalid_stored_state(data: dict[str, Any]) -> None:
    """Unusable stored state starts afresh."""
    assert VariableDayCost.from_dict(data) == VariableDayCost()


def test_electricity_day_reading() -> None:
    """The day's kWh and prices are read from an electricity payload."""
    payload = json.loads(json.dumps(ELECTRICITY_PAYLOAD))
    energy_import = payload["electricitymeter"]["energy"]["import"]
    energy_import.update(
        {"day": 1.5, "price": {"unitrate": 0.2, "standingcharge": None}},
    )
    assert electricity_day_reading(payload) == (1.5, 0.2, None)
    energy_import["price"] = None
    assert electricity_day_reading(payload) == (1.5, None, None)


@pytest.mark.parametrize(
    ("day", "price", "error"),
    [
        (None, {}, ValueError),
        ("lots", {}, ValueError),
        (1.0, [0.2], TypeError),
        (1.0, {"unitrate": True}, TypeError),
    ],
)
def test_electricity_day_reading_invalid(
    day: Any,
    price: Any,
    error: type[Exception],
) -> None:
    """An unusable day's kWh or price raises."""
    payload = json.loads(json.dumps(ELECTRICITY_PAYLOAD))
    payload["electricitymeter"]["energy"]["import"].update({"day": day, "price": price})
    with pytest.raises(error):
        electricity_day_reading(payload)


@pytest.mark.parametrize(
    ("state", "unit", "rate"),
    [
        ("0.25", "GBP/kWh", 0.25),
        ("0.25", "£/kWh", 0.25),
        ("25", "p/kWh", 0.25),
        ("-2.5", "p / kWh", -0.025),
    ],
)
def test_unit_rate_from_state(state: str, unit: str, rate: float) -> None:
    """A unit rate sensor's state is read in GBP/kWh."""
    assert unit_rate_from_state(state, unit) == pytest.approx(rate)


@pytest.mark.parametrize(
    ("state", "unit"),
    [
        ("0.25", None),
        ("0.25", "GBP"),
        ("unavailable", "GBP/kWh"),
        ("nan", "GBP/kWh"),
    ],
)
def test_unit_rate_from_state_invalid(state: str, unit: str | None) -> None:
    """An unusable unit rate sensor state raises."""
    with pytest.raises(ValueError, match=r"."):
        unit_rate_from_state(state, unit)


def test_variable_day_cost_trusted_zero_rate() -> None:
    """A trusted 0 unit rate is used straight away."""
    cost = VariableDayCost()
    cost.update(_utc("2026-11-07T10:00:00"), DAY_1, 10.0, 0.2, 0.5)
    cost.update(
        _utc("2026-11-07T10:01:00"),
        DAY_1,
        10.0,
        0.0,
        0.5,
        trust_zero_rate=True,
    )
    assert cost.update(_utc("2026-11-07T11:00:00"), DAY_1, 15.0, 0.2, 0.5) == 2.5
