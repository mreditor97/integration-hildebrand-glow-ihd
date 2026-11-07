"""Test data for the Home Assistant Hildebrand Glow IHD Integration tests."""

from typing import Any, Final

DEVICE_ID: Final = "AABBCCDDEEFF"
OTHER_DEVICE_ID: Final = "112233445566"

ENTRY_DATA: Final[dict[str, Any]] = {
    "name": "Home",
    "device_id": "+",
    "topic_prefix": "glow",
    "time_zone_electricity": "Europe/London",
    "time_zone_gas": "UTC",
}

STATE_PAYLOAD: Final[dict[str, Any]] = {
    "software": "v1.8.12",
    "timestamp": "2022-06-11T20:54:53Z",
    "hardware": "GLOW-IHD-01-1v4-SMETS2",
    "ethmac": "1234567890AB",
    "smetsversion": "SMETS2",
    "eui": "12:34:56:78:91:23:45",
    "zigbee": "1.2.5",
    "han": {"rssi": -75, "status": "joined", "lqi": 100},
}

ELECTRICITY_PAYLOAD: Final[dict[str, Any]] = {
    "electricitymeter": {
        # 00:38 in the UK on 12 June, so today started at 23:00 UTC
        "timestamp": "2022-06-11T23:38:00Z",
        "energy": {
            "export": {"cumulative": 0.0, "units": "kWh"},
            "import": {
                "cumulative": 6613.405,
                "day": 13.252,
                "week": 141.71,
                "month": 293.598,
                "units": "kWh",
                "mpan": "1234",
                "supplier": "ABC ENERGY",
                "price": {"unitrate": 0.04998, "standingcharge": 0.2403},
            },
        },
        "power": {"value": 0.951, "units": "kW"},
    },
}

GAS_PAYLOAD: Final[dict[str, Any]] = {
    "gasmeter": {
        "timestamp": "2022-06-11T20:53:52Z",
        "energy": {
            "export": {"cumulative": 0.0, "units": "kWh"},
            "import": {
                "cumulative": 17940.852,
                "day": 11.128,
                "week": 104.749,
                "month": 217.122,
                "units": "kWh",
                "mprn": "1234",
                "supplier": "---",
                "cumulativevol": 1500.2,
                "cumulativevolunits": "m3",
                "dayvol": 1.1,
                "weekvol": 2.2,
                "monthvol": 3.3,
                "dayweekmonthvolunits": "kWh",
                "price": {"unitrate": None, "standingcharge": 0.1785},
            },
        },
        "power": {"value": 0.0, "units": "kW"},
    },
}
