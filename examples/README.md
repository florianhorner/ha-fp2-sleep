# Examples

These examples are optional. They are here to help you turn the five raw MQTT
sensors into a clearer Home Assistant view.

Before using them:

1. Install and start the add-on.
2. Confirm the five `sensor.aqara_fp2_sleep_*` entities exist.
3. Replace every `PLACEHOLDER_*` value with your real entity IDs.
4. Keep private entity IDs out of screenshots and issues.

Files:

- `sleep_tracking.yaml`: template sensors for a readable sleep phase, a
  plain-language live read, and an asleep binary sensor.
- `automations.yaml`: example automations that act on the sleep data (dim
  lights while asleep, hold the vacuum, cool down for deep sleep).
- `dashboard-sleep.yaml`: optional Lovelace view. Requires Mushroom cards,
  ApexCharts Card, and card-mod.
- `recorder.yaml`: example Recorder include for long-term history.
