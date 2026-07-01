# Changelog

## Unreleased

- Adds SleepRadar design language guidance and logo assets for public docs.
- Adds an upfront README disclosure that the add-on relies on Aqara's private,
  unofficial Home app API, which Aqara can change or restrict without notice.
- Pre-wires `examples/sleep_tracking.yaml` and `examples/dashboard-sleep.yaml`
  to the add-on's own default entity IDs so both load with no editing beyond
  the dashboard's optional bed-status cross-check card.
- Aligns the root README with the pre-wired examples, documents that
  `sleep_tracking.yaml` must load before the dashboard, and widens the
  example validator's foreign-entity guard from `sensor.` to all common
  entity domains (service-call lines excluded).

## 1.0.0

- Initial public package for Aqara FP2 sleep telemetry in Home Assistant.
- Adds a Home Assistant add-on that polls Aqara sleep resources and publishes
  five MQTT discovery sensors.
- Adds plain-language setup docs, placeholder-only examples, and a privacy
  validator for release checks.
