<p align="center">
  <img src="assets/sleepradar-logo.svg" alt="SleepRadar logo" width="460">
</p>

# SleepRadar

Contact-free sleep vitals (heart rate, breathing, and stages) from an Aqara FP2
in Home Assistant. No wearable, no Docker bridge, no developer account.

This is a small Home Assistant add-on for people who use an Aqara FP2 in
Sleep Monitor mode and want the sleep data that the local HomeKit or Matter
integration does not expose.

## What It Looks Like

**Now, live:**

![Live sleep readout: current stage, heart rate, and breathing](assets/now-live.png)

**Last night, summary:**

![Last night summary: sleep duration, measured heart rate and breathing, stage timeline](assets/last-night.png)

Heart rate and breathing are **measured** directly by the sensor. Sleep stages
are the device's **best guess**, shown honestly as such. The point is not a
prettier chart. It is that this data was hidden from Home Assistant entirely,
and now it is five entities you can see, automate, and build on.

(These are example readouts. The add-on gives you the raw entities; how you draw
them is up to you. See `examples/` for a starting dashboard.)

It creates five MQTT sensors in Home Assistant:

| Sensor | What it shows | Kind |
| --- | --- | --- |
| `sensor.aqara_fp2_sleep_heart_rate` | Heart rate in bpm | measured |
| `sensor.aqara_fp2_sleep_respiration_rate` | Respiration rate in breaths per minute | measured |
| `sensor.aqara_fp2_sleep_sleep_state` | Sleep stage (raw Aqara code) | best guess |
| `sensor.aqara_fp2_sleep_body_movement` | Body movement value | measured |
| `sensor.aqara_fp2_sleep_illuminance` | Illuminance in lux | measured |

The short version: install the add-on, enter your Aqara Home app account and
your FP2 device id, start it, then check that the five sensors appear.

## Before You Start

You need:

- Home Assistant OS or Home Assistant Supervised.
- The Mosquitto broker add-on, or another MQTT broker exposed to add-ons.
- An Aqara FP2 in Sleep Monitor mode.
- Your Aqara Home app account. This is not the Aqara store login.
- The FP2 `subject_id` from the Aqara app.

This add-on talks to the Aqara Home app cloud API. It does not need a separate
PC, Java service, Node-RED flow, or RocketMQ bridge.

**API note:** this uses Aqara's private, unofficial Home app API, not a
documented public one. Aqara can change or restrict it without notice. If
that happens, the sensors stop updating — history already recorded in Home
Assistant stays yours.

## Install

1. In Home Assistant, open **Settings > Add-ons > Add-on Store**.
2. Open the three-dot menu and choose **Repositories**.
3. Add this repository URL:

   ```text
   https://github.com/florianhorner/ha-fp2-sleep
   ```

4. Install **SleepRadar**.
5. Open the **Configuration** tab and set:

   ```yaml
   aqara_username: "your Aqara Home app email"
   aqara_password: "your Aqara Home app password"
   aqara_area: "EU"
   subject_id: "your FP2 subject_id"
   poll_interval: 60
   log_level: info
   device_name: "Aqara FP2 Sleep Monitor"
   mqtt_node_id: "aqara_fp2_sleep"
   ```

6. Start the add-on.
7. Open the log. A working setup shows:

   ```text
   Aqara login OK
   Published discovery for 5 sensors
   ```

8. In Home Assistant, check **Developer Tools > States** for the five
   `sensor.aqara_fp2_sleep_*` sensors.

The first useful success moment is simple: the sensors exist, and
`sensor.aqara_fp2_sleep_sleep_state` changes when the FP2 reports a bed or
sleep state.

## Find Your `subject_id`

In the Aqara Home app, open the sleep FP2, then look under device information.
The value is the device identifier used by Aqara for that FP2.

Treat it as private. It is not a password, but it identifies your device.
When asking for help, redact it like this:

```text
lumi1.xxxxxxxxxxxx
```

Do not paste a full Supervisor options dump into an issue.

## Optional Templates And Dashboard

The add-on publishes raw data. The `examples/` folder contains optional Home
Assistant YAML for nicer names and a simple sleep dashboard.

- `examples/sleep_tracking.yaml` maps the raw sleep state into a readable
  phase sensor. Pre-wired to the add-on's default entities; load it as-is.
- `examples/dashboard-sleep.yaml` is an optional Lovelace view. It uses
  Mushroom cards, ApexCharts Card, and card-mod. Load `sleep_tracking.yaml`
  first; the view reads the phase sensor it creates.
- `examples/recorder.yaml` shows one way to keep the sleep sensors in
  Recorder. Pre-wired; load it as-is.
- `examples/automations.yaml` shows example automations that act on the data.
  These need your own light, vacuum, and thermostat entity IDs.

If you kept the default `mqtt_node_id`, the only `PLACEHOLDER_*` values left
to fill in are your own devices: the automations' light/vacuum/thermostat and
the dashboard's optional bed-status cross-check card (delete that card if you
have no separate bed sensor). If you changed `mqtt_node_id`, also update the
`sensor.aqara_fp2_sleep_*` references to match your node id.

## What You Can Build

Because these are normal Home Assistant entities, you can automate on them using
raw, measured data instead of a statistical guess about whether someone is
asleep. A few starting points (see `examples/automations.yaml`):

- Do not run lights at full brightness while someone is asleep.
- Hold off the robot vacuum until the room is empty or awake.
- Nudge the thermostat down during deep sleep.

This is the part the local integration cannot give you: the bedroom reacting to
what the sensor actually reads.

## Sleep State Codes

The raw `sleep_state` value is exposed as-is. The optional template maps it like
this:

| Code | Meaning |
| --- | --- |
| `0` | Out of bed |
| `1`, `2` | Awake |
| `3` | REM |
| `4` | Light sleep |
| `5` | Deep sleep |

Aqara reports two near-identical "awake" codes (`1` and `2`). The template shows
both as **Awake** to keep it plain: you are either awake, or in one of the three
sleep stages. The raw code stays available as an attribute if you want it.

Heart rate and breathing are measured directly and are the reliable part. Sleep
**stage** scoring is the device's best guess. In my own testing across multiple
nights it matched expected sleep architecture (deep sleep front-loaded, REM toward
morning), but some Aqara FP2 users report the device marking someone awake while
asleep. Treat the stages as indicative, the vitals as measured, and cross-check if
it matters to you.

## Troubleshooting

### Login Fails

Use the Aqara Home app account, not the Aqara store account. The store account
used for buying hardware is separate from the app account used by devices.

Also check `aqara_area`. Accounts are region-bound. `EU` uses the Germany
endpoint and is the default.

### Sensors Do Not Appear

Check:

- MQTT broker add-on is installed and running.
- The add-on log says `Published discovery for 5 sensors`.
- MQTT discovery is enabled in Home Assistant.
- `mqtt_node_id` is still `aqara_fp2_sleep`, unless you intentionally changed it.

### Values Stay Unknown

Check:

- The FP2 is in Sleep Monitor mode.
- `subject_id` points to the sleep FP2, not another Aqara device.
- The Aqara Home app still shows current sleep data for that FP2.

## Security And Privacy

Your Aqara username and password stay in the add-on options managed by
Supervisor. They are not stored in YAML by this repository.

The `appid`, `appkey`, and RSA public key in the source are public constants
from the Aqara Home app. They are not user credentials.

This add-on uses a private Aqara app API. Aqara can change it. The add-on will
try to log in again when the app token expires, but it cannot promise that the
private API will keep working forever.

See `SECURITY.md` before opening an issue with logs.
