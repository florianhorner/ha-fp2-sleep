# Examples

These examples are optional. They are here to help you turn the five raw MQTT
sensors into a clearer Home Assistant view.

Before using them:

1. Install and start the app.
2. Confirm the five `sensor.aqara_fp2_sleep_*` entities exist.
3. `sleep_tracking.yaml`, `dashboard-sleep.yaml`, and `recorder.yaml` are
   pre-wired to the app's own default entity IDs — copy them in as-is
   unless you changed `mqtt_node_id` from the default. `automations.yaml`
   still needs your own light, vacuum, and thermostat entity IDs. The
   dashboard's optional Cross-check section needs your separate bed-presence
   entity; replace `PLACEHOLDER_BED_STATUS_ENTITY` or delete that section.
4. Register `card/sleepradar-card.js` as `/local/sleepradar-card.js` before
   loading `dashboard-sleep.yaml`. The historical charts also require
   ApexCharts Card. The optional "Cross-check" section requires
   `sleep_tracking.yaml` and Mushroom Cards; card-mod is not required.
5. The dashboard's optional `bed_occupancy` block is commented out. If you
   enable it, replace `PLACEHOLDER_BED_STATUS_ENTITY` with your independent
   occupancy entity. A binary sensor uses `occupied_states: ['on']`.
6. Keep private entity IDs out of screenshots and issues.

Files:

- `sleep_tracking.yaml`: template sensors for a readable sleep phase, a
  plain-language live read, and an asleep binary sensor. Pre-wired, load
  as-is.
- `automations.yaml`: example automations that act on the sleep data (dim
  lights while asleep, hold the vacuum, cool down for deep sleep). Needs your
  own light/vacuum/thermostat entity IDs.
- `dashboard-sleep.yaml`: optional Lovelace view. Requires the SleepRadar Card
  and ApexCharts Card; its optional cross-check also uses Mushroom Cards and
  the template helper. It has a live "Now" card plus a "Last night" view of raw
  sleep-state, heart-rate, and breathing telemetry from Recorder. The commented
  `bed_occupancy` block gates only the live card; it does not filter history.
  Sleep stage is Aqara's estimate; heart rate and breathing are measured.
- `recorder.yaml`: example Recorder include for long-term history. Pre-wired,
  load as-is.
