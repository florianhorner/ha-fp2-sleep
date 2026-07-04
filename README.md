<p align="center">
  <img src="assets/sleepradar-logo.svg" alt="SleepRadar logo" width="460">
</p>

# SleepRadar

[![CI](https://github.com/florianhorner/ha-fp2-sleep/actions/workflows/ci.yml/badge.svg)](https://github.com/florianhorner/ha-fp2-sleep/actions/workflows/ci.yml)

Contact-free sleep vitals (heart rate, breathing, and sleep stages) from an
Aqara FP2 in Home Assistant. No wearable, no Docker bridge, no developer
account.

> **Terminology.** "App" means the SleepRadar Home Assistant app. "Aqara Home
> app" means the Aqara mobile app. They are different things.

SleepRadar is a Home Assistant app for people who use an Aqara FP2 in Sleep
Monitor mode and want the sleep data that the local HomeKit or Matter
integration does not expose. It polls the Aqara Home app API and publishes
five MQTT entities you can see, automate, and build on.

> **Unofficial API.** SleepRadar uses Aqara's private, undocumented app API.
> Aqara can change or restrict it without notice. If that happens, the sensors
> stop updating. History already recorded in Home Assistant stays yours.

## What It Looks Like

**Now, live — the SleepRadar card, installed as-is:**

![Live sleep readout: current stage, heart rate, and breathing](assets/now-live.png)

This is the SleepRadar Card (`card/sleepradar-card.js`). It ships with the
repo, reads three of the five sensors (sleep stage, heart rate, breathing),
and needs no other cards or plugins. See [The SleepRadar Card](#the-sleepradar-card).

Heart rate and breathing are **measured** directly by the sensor. Sleep stages
are the device's **best estimate**, shown honestly as such. The point is not a
prettier chart — it is that this data was hidden from Home Assistant entirely,
and now it is five entities you can see, automate, and build on.

SleepRadar creates five MQTT sensors in Home Assistant:

| Sensor | What it shows | Kind |
| --- | --- | --- |
| `sensor.aqara_fp2_sleep_heart_rate` | Heart rate in bpm | Measured |
| `sensor.aqara_fp2_sleep_respiration_rate` | Respiration rate in breaths/min | Measured |
| `sensor.aqara_fp2_sleep_sleep_state` | Sleep stage (raw Aqara code) | Estimated |
| `sensor.aqara_fp2_sleep_body_movement` | Body movement value | Measured |
| `sensor.aqara_fp2_sleep_illuminance` | Illuminance in lux | Measured |

## Before You Start

You need:

- Home Assistant OS or Home Assistant Supervised.
- The Mosquitto Broker app, or another MQTT broker accessible to apps.
- MQTT discovery enabled in Home Assistant.
- An Aqara FP2 in Sleep Monitor mode.
- Your Aqara Home app account credentials. This is the mobile app login, not
  the Aqara webshop account — they are separate.
- The FP2 `subject_id` from the Aqara Home app.

## Install

[![Add repository to my Home Assistant](https://my.home-assistant.io/badges/supervisor_add_addon_repository.svg)](https://my.home-assistant.io/redirect/supervisor_add_addon_repository/?repository_url=https%3A%2F%2Fgithub.com%2Fflorianhorner%2Fha-fp2-sleep)

If the button opens My Home Assistant and asks for your Home Assistant URL,
enter it there once, or skip the button and use the manual repository URL
below. The manual path works the same way.

Or add it by hand:

1. In Home Assistant, open **Settings > Apps > Install app**.
2. Open the three-dot menu (top right), choose **Repositories**, then click
   **Add** (bottom right). This opens an **Add repository** box.
3. Paste this repository URL in the box, then click **Add**:

   ```text
   https://github.com/florianhorner/ha-fp2-sleep
   ```

4. Install **SleepRadar**.
5. Open the **Configuration** tab and fill in your details:

   ```yaml
   # Required
   aqara_username: "your-aqara-home-app-email"
   aqara_password: "your-aqara-home-app-password"
   subject_id: "lumi1.xxxxxxxxxxxx"
   aqara_area: "EU"   # CN | EU | USA | RU | KR — must match your account region

   # Optional
   poll_interval: 60
   log_level: info
   device_name: "Aqara FP2 Sleep Monitor"
   mqtt_node_id: "aqara_fp2_sleep"
   ```

6. Start the app.
7. Open the log. A working setup shows:

   ```text
   Aqara login OK
   Published discovery for 5 sensors
   ```

8. Check for the five `sensor.aqara_fp2_sleep_*` sensors in [your entity
   states](https://my.home-assistant.io/redirect/developer_states/) (Developer
   Tools, then States).

First useful moment: `sensor.aqara_fp2_sleep_sleep_state` changes when the
FP2 reports a bed or sleep state.

## Find Your `subject_id`

In the Aqara Home app, open the sleep FP2, then open **Device Information**. It
looks like `lumi1.xxxxxxxxxxxx`. Treat it as private because it identifies your
device.

When asking for help, redact it:

```text
lumi1.xxxxxxxxxxxx
```

Do not paste a full app options dump into an issue.

## The SleepRadar Card

1. Download `card/sleepradar-card.js` from this repository.
2. Copy it to `/config/www/sleepradar-card.js`.
3. Open [your dashboard resources](https://my.home-assistant.io/redirect/lovelace_resources/)
   (Settings > Dashboards, three-dot menu, then **Resources**).
4. Add a resource:
   - URL: `/local/sleepradar-card.js`
   - Resource type: **JavaScript module**
5. Hard-refresh your browser (`Ctrl+Shift+R` / `Cmd+Shift+R`).
6. Add a card manually:

   ```yaml
   type: custom:sleepradar-card
   ```

The card defaults to the app's default entities. Override if you changed
`mqtt_node_id`:

```yaml
type: custom:sleepradar-card
mqtt_node_id: your_custom_node_id
```

Or override individual entities:

```yaml
type: custom:sleepradar-card
entities:
  sleep_state: sensor.your_sleep_state_entity
  heart_rate: sensor.your_heart_rate_entity
  respiration_rate: sensor.your_respiration_rate_entity
```

If you changed `poll_interval`, set the same value on the card so the stale
badge stays accurate:

```yaml
type: custom:sleepradar-card
poll_interval_seconds: 120
```

The card shows "no data yet" if the sleep state sensor is missing, "not
measuring" when the bed is empty, and a "stale" badge if readings are older
than three poll intervals. In those states it hides retained heart-rate and
breathing values rather than showing stale in-bed numbers as live.

> **Entity ID note.** Home Assistant pins an entity ID on first creation and
> does not rename it later. If you installed before v1.1.0, your entity IDs
> may not match the `sensor.aqara_fp2_sleep_*` defaults. Check
> [your entity states](https://my.home-assistant.io/redirect/developer_states/)
> and use `entities:` to override if needed.

## Optional Templates and Dashboard

The `examples/` folder contains optional YAML. Load in this order if you want
the full dashboard:

- `examples/sleep_tracking.yaml` maps raw sleep codes to readable names. It
  has no dependencies.
- `examples/recorder.yaml` keeps sleep sensors in Recorder. It has no
  dependencies.
- `examples/dashboard-sleep.yaml` is a Lovelace sleep dashboard. It requires
  `sleep_tracking.yaml`, [Mushroom Cards](https://github.com/piitaya/lovelace-mushroom),
  [ApexCharts Card](https://github.com/RomRider/apexcharts-card), and
  [card-mod](https://github.com/thomasloven/lovelace-card-mod).
- `examples/automations.yaml` contains example automations. Replace
  `PLACEHOLDER_*` values with your own light, vacuum, and thermostat entity
  IDs.

All files are pre-wired to the default `mqtt_node_id`. If you changed it,
update `sensor.aqara_fp2_sleep_*` references to match.

## What You Can Build

Because these are normal Home Assistant entities, you can automate on raw
measured data. A few starting points (see `examples/automations.yaml`):

- Don't run lights at full brightness while someone is asleep.
- Hold off the robot vacuum until the room is empty or awake.
- Nudge the thermostat down during deep sleep.

## What's Next

**A preview of what's coming, not a current feature:**

![Planned: last-night summary with sleep duration, averaged vitals, and stage timeline](assets/last-night.png)

Today, `examples/dashboard-sleep.yaml` gives you a live "Now" card plus a raw
12-hour sleep-state chart. It does not compute session duration, averaged
vitals, or the segmented stage timeline shown above. That sessionization is the
next planned SleepRadar Card release.

## Sleep State Codes

| Code | Meaning |
| --- | --- |
| `0` | Out of bed |
| `1` | Awake |
| `2` | Awake (alternate code, treated identically to `1`) |
| `3` | REM sleep |
| `4` | Light sleep |
| `5` | Deep sleep |

The optional template (`examples/sleep_tracking.yaml`) maps these
automatically. The raw code stays available as an attribute.

Heart rate and breathing are measured directly and are the reliable part.
Sleep stage scoring is the device's best estimate. In testing it matched
expected sleep architecture, but some FP2 users report false "awake" readings.
Treat stages as indicative, vitals as measured.

## Troubleshooting

### Login Fails

Use the Aqara Home app account (mobile app email), not the Aqara webshop
account. Check `aqara_area` because accounts are region-bound.

### Sensors Do Not Appear

- Mosquitto Broker app is installed and running.
- SleepRadar log shows `Published discovery for 5 sensors`.
- MQTT discovery is enabled in Home Assistant.
- `mqtt_node_id` is `aqara_fp2_sleep` unless you changed it.

> **MQTT startup race.** If SleepRadar and the broker start at the same time
> (for example, after a reboot), the log may show `MQTT connect failed —
> retrying` for up to about 2 minutes. This is expected. If it still fails
> after that, restart SleepRadar once the broker app shows as running.

### Values Stay Unknown

- The FP2 is in Sleep Monitor mode.
- `subject_id` points to the sleep FP2, not another Aqara device.
- The Aqara Home app still shows current sleep data for that FP2.

### The Card Shows "No Data Yet"

- `sleepradar-card.js` is registered as a resource (see
  [The SleepRadar Card](#the-sleepradar-card)) and the browser was
  hard-refreshed after adding it.
- The five sensors exist in
  [your entity states](https://my.home-assistant.io/redirect/developer_states/).
- If you changed `mqtt_node_id`, the card config reflects it.
- Check actual entity IDs. See the Entity ID note in
  [The SleepRadar Card](#the-sleepradar-card).

## Security and Privacy

Your Aqara credentials are stored in Home Assistant app options only. They are
not stored in any YAML file in this repository.

The `appid`, `appkey`, and RSA public key in the source are public constants
from the Aqara Home app, not user credentials.

SleepRadar re-authenticates when the session token expires but cannot
guarantee the private API keeps working indefinitely.

See `SECURITY.md` before opening an issue with logs.
