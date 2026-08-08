# Examples

These examples are optional. They are here to help you turn the five raw MQTT
sensors into a clearer Home Assistant view.

Before using them:

1. Install and start the app.
2. Confirm the five `sensor.aqara_fp2_sleep_*` entities exist.
3. Expose a separate occupancy source as `binary_sensor.bed_occupied`. It must
   not be derived from `sensor.aqara_fp2_sleep_sleep_state`. The template
   helpers and live dashboard fail closed: they do not emit live stages,
   vitals, or an asleep state when this entity is unknown, unavailable, or not
   occupied.
4. `sleep_tracking.yaml`, `dashboard-sleep.yaml`, and `recorder.yaml` use the
   app's default raw entity IDs. Update those references if you changed
   `mqtt_node_id`. `automations.yaml` also needs your light, vacuum, and
   thermostat entity IDs.
5. Register `card/sleepradar-card.js` as `/local/sleepradar-card.js` before
   loading `dashboard-sleep.yaml`. The historical charts also require
   ApexCharts Card. The optional "Cross-check" section requires
   `sleep_tracking.yaml` and Mushroom Cards; card-mod is not required.
6. Keep private entity IDs out of screenshots and issues.

Files:

- `sleep_tracking.yaml`: template sensors for a readable sleep phase, a
  plain-language live read, and an occupancy-gated asleep binary sensor. Codes
  0–2 never assert an in-bed stage; codes 3–5 are indicative labels only.
- `automations.yaml`: example automations. The first forwards a SleepRadar
  connection problem to a notify service; it is the only one here that tells
  you when the app stops. It needs your notify service and no occupancy gate,
  because it acts on the diagnostic entity rather than on sleep data. The rest
  act on sleep data (dim lights while asleep, hold the vacuum, cool down for
  deep sleep) and need your own light/vacuum/thermostat entity IDs and the
  occupancy-gated helpers.
- `dashboard-sleep.yaml`: optional Lovelace view. Requires the SleepRadar Card
  and ApexCharts Card; its optional cross-check also uses Mushroom Cards and
  the template helper. It has a live "Now" card plus a "Last night" view of raw
  sleep-state, heart-rate, and breathing telemetry from Recorder. Its enabled
  `bed_occupancy` block gates only the live card; it does not filter history.
  Codes 3–5 are indicative sleep stages; heart rate and breathing are
  sensor-reported.
- `recorder.yaml`: example Recorder include for long-term history. Pre-wired,
  load as-is. It records the diagnostic entity alongside the five sensors, so a
  gap in the history still comes with a reason.
