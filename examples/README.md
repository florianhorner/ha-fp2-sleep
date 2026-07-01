# Examples

These examples are optional. They are here to help you turn the five raw MQTT
sensors into a clearer Home Assistant view.

Before using them:

1. Install and start the add-on.
2. Confirm the five `sensor.aqara_fp2_sleep_*` entities exist.
3. `sleep_tracking.yaml`, `dashboard-sleep.yaml`, and `recorder.yaml` are
   pre-wired to the add-on's own default entity IDs — copy them in as-is
   unless you changed `mqtt_node_id` from the default. `automations.yaml`
   and the dashboard's optional "Cross-check" card still need your own
   entity IDs (lights, vacuum, thermostat, or a separate bed-presence
   sensor) — replace those remaining `PLACEHOLDER_*` values, or delete the
   automation/card you don't need.
4. Load `sleep_tracking.yaml` before `dashboard-sleep.yaml`. The dashboard
   reads `sensor.fp2_sleep_phase`, which `sleep_tracking.yaml` creates; the
   phase card shows "unavailable" until that helper exists.
5. Keep private entity IDs out of screenshots and issues.

Files:

- `sleep_tracking.yaml`: template sensors for a readable sleep phase, a
  plain-language live read, and an asleep binary sensor. Pre-wired, load
  as-is.
- `automations.yaml`: example automations that act on the sleep data (dim
  lights while asleep, hold the vacuum, cool down for deep sleep). Needs your
  own light/vacuum/thermostat entity IDs.
- `dashboard-sleep.yaml`: optional Lovelace view. Requires Mushroom cards,
  ApexCharts Card, and card-mod. Pre-wired except the optional "Cross-check"
  card.
- `recorder.yaml`: example Recorder include for long-term history. Pre-wired,
  load as-is.
