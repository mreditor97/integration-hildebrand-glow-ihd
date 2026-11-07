# Home Assistant Hildebrand Glow IHD Integration

A Home Assistant custom integration for the **Hildebrand Glow IHD** (in-home display) and **Glow CAD**. It reads your smart meter data **locally over MQTT**: no cloud account or API polling is needed.

The device publishes the readings from your SMETS1/SMETS2 smart meter to your MQTT broker. This integration subscribes to those messages and creates Home Assistant sensors for electricity and gas usage, tariff prices, daily cost and device diagnostics, which you can use in the Energy dashboard.

![Glow device and sensors in Home Assistant](https://user-images.githubusercontent.com/1478003/173249987-4724af89-ceaa-4422-a426-4b8a2b16d98e.png)

## Contents

- [Requirements](#requirements)
- [Installation](#installation)
- [Configuration](#configuration)
- [Sensors](#sensors)
- [Energy dashboard](#energy-dashboard)
- [Use cases](#use-cases)
- [Example automations](#example-automations)
- [How the data updates](#how-the-data-updates)
- [Troubleshooting](#troubleshooting)
- [Known limitations](#known-limitations)
- [Removing the integration](#removing-the-integration)
- [Development](#development)
- [Credits](#credits)

## Requirements

- A [Hildebrand Glow IHD or CAD](https://shop.glowmarkt.com/products/display-and-cad-combined-for-smart-meter-customers) paired with your smart meter.
- An MQTT broker, such as the Mosquitto broker add-on, and the [MQTT integration](https://www.home-assistant.io/integrations/mqtt/) set up in Home Assistant.
- Local MQTT turned on for your Glow device and pointed at your broker. This [guide by Joshua Cooper](https://medium.com/@joshua.cooper/glow-local-mqtt-f69b776b7af4) explains how.
- Home Assistant 2026.11 or newer, which includes the Marketplace.

The integration works with any device that publishes Glow's local MQTT messages: the Glow IHD and the Glow CAD, with SMETS1 or SMETS2 meters. It needs nothing from Hildebrand's cloud service.

## Installation

### Home Assistant Marketplace (recommended)

1. Open **Settings → Marketplace** and add this repository as a custom repository, with the type **Integration**:
   `https://github.com/mreditor97/integration-hildebrand-glow-ihd`
2. Search for **Hildebrand Glow IHD Integration** and install it.
3. Restart Home Assistant.

### Manual

1. Copy the `custom_components/hildebrand_glow_ihd` folder from this repository into your Home Assistant config folder's `custom_components` folder. The folder name must match the integration's domain, `hildebrand_glow_ihd`.
2. Restart Home Assistant.

## Configuration

Once your Glow device publishes to your broker, Home Assistant finds it and shows it under **Settings → Devices & services → Discovered**. Select **Add**, choose the meters' time zones, and submit. Discovery only looks for the default `glow` topic prefix.

To add it yourself instead, go to **Settings → Devices & services → Add integration** and search for **Hildebrand Glow IHD Integration**.

| Option                      | Default           | Description                                                                                                                                                                                                          |
| --------------------------- | ----------------- | -------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| Name                        | `Glow`            | The device's name, and the start of new entity IDs. For example, `Home` gives `sensor.home_electricity_import`.                                                                                                      |
| Device ID                   | `+`               | Leave as `+` to detect every Glow device publishing to your broker (recommended). To limit it to one device, enter that device's ID: the part of the topic after the prefix, e.g. `glow/`**`AABBCCDDEEFF`**`/STATE`. |
| Topic prefix                | `glow`            | The first part of the MQTT topic. Only change this if you changed it on the device.                                                                                                                                  |
| Electricity meter time zone | Your HA time zone | The time zone your electricity meter's daily total resets in.                                                                                                                                                        |
| Gas meter time zone         | Your HA time zone | The time zone your gas meter's daily total resets in. Some gas meters reset at midnight UTC (01:00 during British Summer Time). If yours does, choose `UTC`.                                                         |

Each Glow device appears as a device with the name you gave, and its sensors appear as soon as the first MQTT message arrives. If one entry with device ID `+` finds more than one device, they share the name and Home Assistant adds `_2` to the second device's entity IDs. To tell them apart, add one entry per device instead.

To change the time zones later, open the integration and select **Configure**. To change the device ID or topic prefix, open the entry's menu and select **Reconfigure**. The integration reloads to apply either.

You can add more than one entry, for example one per device, as long as two entries never read the same device. An entry with device ID `+` reads every device under its topic prefix, so it can't sit next to an entry for a single device with the same prefix.

## Sensors

Home Assistant shows each sensor after its device's name, e.g. **Home Electricity: Import (Today)** for a device named `Home`, and new entity IDs start with the name, e.g. `sensor.home_electricity_import_today`. Entity IDs of sensors you already have aren't changed. Entries added before setup asked for a name keep the device name **Glow &lt;device id&gt;**. Give them a name with **Reconfigure**.

### Electricity

| Sensor                                               | Unit    | Notes                                       |
| ---------------------------------------------------- | ------- | ------------------------------------------- |
| Electricity: Import                                  | kWh     | Lifetime meter reading                      |
| Electricity: Import (Today / This week / This month) | kWh     | Reset by the meter                          |
| Electricity: Export                                  | kWh     | Lifetime export reading                     |
| Electricity: Power                                   | kW      | Current demand                              |
| Electricity: Import Unit Rate                        | GBP/kWh | Current unit rate, no long-term statistics  |
| Electricity: Import Standing Charge                  | GBP     | Daily standing charge, no long-term stats   |
| Electricity: Cost (Today)                            | GBP     | Standing charge + today's usage × unit rate |

### Gas

| Sensor                                           | Unit    | Notes                                       |
| ------------------------------------------------ | ------- | ------------------------------------------- |
| Gas: Import                                      | kWh     | Lifetime meter reading                      |
| Gas: Import (Today / This week / This month)     | kWh     | Reset by the meter                          |
| Gas: Import Vol                                  | m³      | Lifetime volume reading                     |
| Gas: Import Vol (Today / This week / This month) | m³      | Reset by the meter                          |
| Gas: Import Unit Rate                            | GBP/kWh | Current unit rate, no long-term statistics  |
| Gas: Import Standing Charge                      | GBP     | Daily standing charge, no long-term stats   |
| Gas: Cost (Today)                                | GBP     | Standing charge + today's usage × unit rate |

There is no live gas power sensor: the IHD stopped publishing gas power in software update 1.8.13 (June 2022).

### Diagnostics

IHD software version, hardware, HAN (Zigbee) status, HAN RSSI and HAN LQI. The device page also shows the IHD's software and hardware versions.

These diagnostic sensors are off by default. Turn them on from the device page if you want them:

- **IHD Zigbee Version** and **IHD SMETS Version**.
- **Electricity: Last Reading** and **Gas: Last Reading**: when each meter last sent a reading, useful to spot a gas meter that has stopped reporting. They change with every message, so they add to the recorder's database when turned on.

The unit rate and standing charge sensors are prices rather than running totals, so Home Assistant keeps their history but no long-term statistics. If you upgraded from a version before this change, **Developer tools → Statistics** may list them with a fix to remove their old statistics.

## Energy dashboard

In **Settings → Dashboards → Energy**:

- **Electricity grid consumption:** `Electricity: Import`
- **Return to grid:** `Electricity: Export` (if you export)
- **Gas consumption:** `Gas: Import` (kWh) or `Gas: Import Vol` (m³)
- **Cost:** choose _Use an entity with current price_ and pick the matching **Import Unit Rate** sensor.

The lifetime **Import** sensors give the most reliable statistics. The _Today_ sensors and _Cost (Today)_ reset every day, so a reset at an unexpected time can show up as a spike or a negative value.

## Use cases

- **Track your energy use and cost** in the Energy dashboard, with live electricity demand and the day's running cost.
- **Spot high usage as it happens**, for example an appliance left on, from the live **Electricity: Power** sensor.
- **Run things when power is cheap or demand is low**, using the unit rate and power sensors as conditions.
- **Keep an eye on the meters themselves**: the device goes unavailable if the IHD stops publishing, and **Gas: Last Reading** shows when the gas meter last reported.
- **Check your bill**: the unit rate and standing charge sensors show what your supplier has sent to the meter.

## Example automations

These use the entity IDs a new install named `Home` gets. Change them to match yours, which you can find on the device page. You can build the same automations in the automation editor.

Notify when the house draws more than 3 kW for 5 minutes:

```yaml
alias: High electricity demand
triggers:
  - trigger: numeric_state
    entity_id: sensor.home_electricity_power
    above: 3
    for:
      minutes: 5
actions:
  - action: notify.notify
    data:
      message: >-
        Electricity demand has been over 3 kW for 5 minutes, it is now
        {{ states('sensor.home_electricity_power') }} kW.
```

Notify when the gas meter hasn't reported for 2 hours. This needs **Gas: Last Reading**, which is off by default, so turn it on from the device page first:

```yaml
alias: Gas meter stopped reporting
triggers:
  - trigger: state
    entity_id: sensor.home_gas_last_reading
    for:
      hours: 2
actions:
  - action: notify.notify
    data:
      message: The gas meter hasn't sent a reading for 2 hours.
```

Send the day's electricity cost every evening:

```yaml
alias: Daily electricity cost
triggers:
  - trigger: time
    at: "21:00:00"
actions:
  - action: notify.notify
    data:
      message: >-
        Electricity so far today: £{{ states('sensor.home_electricity_cost_today') }}.
```

## How the data updates

The Glow device pushes its readings to your MQTT broker, and the sensors update as each message arrives. Nothing is polled. How often readings arrive is up to the device and your meters: gas readings usually arrive much less often than electricity readings.

If a device publishes nothing at all for 15 minutes, its sensors become unavailable until its next message, and a line is logged at info level each way.

Bad data is logged without filling the log. A message whose payload isn't JSON is logged once as a warning per topic, then at debug level until a readable message arrives on that topic. A sensor that receives a value it can't use, such as text where a number is expected, shows unknown, and the value is logged once as a warning, then at debug level until a usable value arrives. Missing fields, such as prices before your supplier sends them, are logged at debug level only.

## Troubleshooting

**No sensors appear.** If no message arrives in the 15 minutes after the integration is set up, a repair issue appears under **Settings → Repairs**. Check that the device is publishing to your broker. Subscribe to `glow/#`, for example with MQTT Explorer or:

```sh
mosquitto_sub -h <broker> -u <user> -P <password> -t 'glow/#' -v
```

You should see `glow/<device id>/STATE`, `glow/<device id>/SENSOR/electricitymeter` and, if you have gas, `glow/<device id>/SENSOR/gasmeter`. If the topic prefix or device ID doesn't match your configuration, no sensors are created.

**Prices or cost show as unknown.** The device publishes `null` prices until your supplier sends tariff data to the meter. This depends on the supplier, not on this integration.

**Daily values reset at 01:00 instead of midnight.** The meter resets its daily totals in UTC. Open the integration, select **Configure** and set that meter's time zone to `UTC` (see [Configuration](#configuration)).

**Sensors are unavailable.** The device hasn't published for 15 minutes. Check that it is powered, on your network and connected to the broker.

**Reporting a problem.** Open the integration's menu and select **Download diagnostics**, then attach the file to an [issue](https://github.com/mreditor97/integration-hildebrand-glow-ihd/issues). It has the entry's settings and the latest message of each kind from each device, with device IDs, MAC addresses, the EUI and MPAN/MPRN numbers removed.

**Debug logging.** Open the integration and select **Enable debug logging**, reproduce the problem, then select **Disable debug logging** to download the log. Or add this to `configuration.yaml`, restart, and check the log:

```yaml
logger:
  logs:
    custom_components.hildebrand_glow_ihd: debug
```

## Known limitations

- Prices are always shown in GBP, the currency the device reports for UK meters.
- Gas volume sensors are unknown when the device reports the volume fields in kWh, because kWh can't be converted to m³ without the calorific value.
- There is no gas power sensor, see [Gas](#gas).
- Discovery only finds devices using the default `glow` topic prefix. Add other prefixes by hand.
- A device's sensors appear only after its first message following a restart or reload.

## Removing the integration

1. Go to **Settings → Devices & services** and open **Hildebrand Glow IHD Integration**.
2. Open each entry's menu and select **Delete**.
3. If you installed it from the Marketplace, remove it there too, then restart Home Assistant. For a manual install, delete the `custom_components/hildebrand_glow_ihd` folder and restart.

Removing the integration doesn't change your Glow device or broker settings.

See the [releases](https://github.com/mreditor97/integration-hildebrand-glow-ihd/releases) for what changed in each version.

## Development

The integration is in `custom_components/hildebrand_glow_ihd`. The files Home Assistant loads by name (`__init__.py`, `config_flow.py`, `sensor.py`, `manifest.json` and the translations) are at the top of that folder. `helpers.py` reads the topics and payloads the Glow device publishes.

The development tools need [uv](https://docs.astral.sh/uv/) and Python 3.14. The tests run against the Home Assistant version that `pytest-homeassistant-custom-component` pins in `pyproject.toml`.

```bash
uv sync
uv run pytest
uv run mypy
uv run pre-commit run --all-files
```

## Credits

- Originally created by [@megakid](https://github.com/megakid) as [ha_hildebrand_glow_ihd_mqtt](https://github.com/megakid/ha_hildebrand_glow_ihd_mqtt), and improved by its contributors.
- Inspired by and heavily based on [@robertalexa](https://github.com/robertalexa)'s [Home Assistant community thread](https://community.home-assistant.io/t/glow-hildebrand-display-local-mqtt-access-template-help/428638).
