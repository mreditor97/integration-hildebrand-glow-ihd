# Changelog

## 2.0.0

The first release from this repository. It continues
[megakid/ha_hildebrand_glow_ihd_mqtt](https://github.com/megakid/ha_hildebrand_glow_ihd_mqtt),
whose last release was 1.9.1. The integration domain is still
`hildebrand_glow_ihd`, and existing config entries, entity IDs and history
are migrated on upgrade.

### 🚨 Breaking changes

- Needs Home Assistant 2026.4.0 or newer.
- The integration folder is now `custom_components/hildebrand_glow_ihd`
  instead of `custom_components/hildebrand_glow_ihd_mqtt`, to match the
  domain. If you installed the original project by hand, delete the old
  folder before restarting.
- The integration is now called Hildebrand Glow IHD Integration, and
  devices are named "Glow AABBCCDDEEFF" with the model "Glow IHD" instead
  of "Smart Meter". Home Assistant renames existing devices unless you have
  renamed them yourself. Existing entity IDs aren't changed.
- Sensor unique IDs no longer contain `smart_meter_`. Entries migrate to
  version 1.3, which updates the entity registry so sensors keep their
  entity IDs, names and history.
- The unit rate and standing charge sensors no longer have a state class,
  and the unit rate no longer has the monetary device class, because they
  are prices rather than running totals. Home Assistant may offer to remove
  their old long-term statistics in **Developer tools → Statistics**.
- Configure now only changes the meter time zones. The device ID and topic
  prefix moved to a new Reconfigure step.

### ✨ New features

- Discover Glow devices from their `glow/+/STATE` MQTT messages.
- Ask for a name at setup (default "Glow"). It names the device, and new
  entity IDs start with it, e.g. `sensor.home_electricity_import`.
- Weekly and monthly electricity and gas cost sensors, from the IHD's week
  and month kWh figures.
- Gas Import Vol (Today / This week / This month) worked out from the
  lifetime m³ reading when the IHD sends the period volumes in kWh.
- Mark a device's sensors unavailable when it hasn't published for 15
  minutes.
- A repair issue when no message arrives in the 15 minutes after setup,
  which usually means a wrong topic prefix or device ID.
- A diagnostics download, with device IDs, MAC addresses, EUI and
  MPAN/MPRN redacted.
- IHD Zigbee Version, IHD SMETS Version, Electricity: Last Reading and
  Gas: Last Reading diagnostic sensors, off by default.
- The IHD's software and hardware versions on the device page.
- Glow devices can be deleted from the device page.
- A brand icon (an original drawing, not Hildebrand's logo) for Home
  Assistant 2026.3 and newer.

### 🐛 Bug fixes

- Missing tariff prices no longer raise an error on every message. A
  missing price counts as zero, and the cost is unknown only when no price
  data is present.
- Gas volume sensors no longer show kWh figures as cubic metres.
- Config entries get a title instead of an empty string.
- The installed version shown in Home Assistant now matches the release.
- An entry that would read the same device as another one is refused,
  instead of the second entry's sensors being dropped as duplicates.
- Values that Home Assistant would reject (non-numeric, non-finite,
  timestamps without a time zone, states over 255 characters) make the
  sensor unknown with one warning, instead of an error on every message.
  Numbers sent as text are used as numbers.
- A payload that isn't a JSON object is logged once per topic instead of
  on every message.
- Sensors stay unavailable until their first reading arrives, instead of
  showing unknown, which made Utility Meter log warnings.

### 🚀 Enhancements

- Rewritten to current Home Assistant patterns: runtime data on the config
  entry, entity descriptions, unloading and reloading, and one parse per
  MQTT message subscribed only to the configured device's topics.
- Translated entity names without the "Smart Meter" prefix.
- The electricity power sensor shows watts by default for new sensors.
  Existing sensors keep their unit.

### 🧰 Maintenance

- Tests, mypy, pre-commit hooks and a CI test job.
- Release Drafter, hassfest and Home Assistant Marketplace validation.

### 📚 Documentation

- Rewritten README for the Home Assistant Marketplace, with use cases,
  example automations, Energy dashboard setup and troubleshooting.
- MIT licence.
