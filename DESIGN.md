# SleepRadar Design Language

SleepRadar is a small Home Assistant app, not a wellness platform. The
design language should feel calm, technical, and honest: contact-free sleep
telemetry from an Aqara FP2, exposed as normal Home Assistant entities.

## Product Voice

- Lead with utility: sleep vitals that HomeKit and Matter do not expose.
- Keep the setup promise plain: no wearable, no Docker bridge, no developer
  account.
- Separate measured data from inferred data every time it matters. Heart rate,
  breathing, body movement, and illuminance are measured by the sensor. Sleep
  stage is the device's best guess.
- Treat privacy as part of the product. Never show real credentials, full
  `subject_id` values, private Home Assistant URLs, or personal dashboard state.
- Avoid medical, diagnostic, or coaching language. The app reports data; it
  does not interpret health.

## Visual System

SleepRadar should look like a quiet night readout inside Home Assistant:
low-glare, compact, scan-first, and useful at 02:14.

| Token | Value | Use |
| --- | --- | --- |
| Background | `#101112` | Night-mode page or screenshot background |
| Surface | `#1b1c1e` | Metric cards and readout panels |
| Surface border | `#2b2d31` | Subtle separation without bright outlines |
| Text | `#e8e8ea` | Primary labels and values |
| Muted text | `#9a9da3` | Timestamps, caveats, and supporting copy |
| Radar blue | `#5aa2ff` | Primary accent, sleep state, breathing |
| Deep blue | `#2758d8` | Deep-sleep timeline segments |
| Heart red | `#ff4d57` | Heart rate and awake alerts |
| REM amber | `#f5a623` | REM timeline segments |
| Unknown gray | `#747982` | Unavailable, out-of-bed, or uncertain states |

Use system sans typography. Prefer regular and semibold weights; large metric
numbers can be bold. Keep letter spacing at `0`.

## Components

- Readout panels use compact cards with an 8px radius, thin borders, and enough
  padding to scan at a glance.
- The primary hierarchy is: current phase, measured vitals, then caveats.
- Timeline colors should remain categorical. Do not use smooth gradients for
  sleep stages because they imply precision the device does not provide.
- Copy should be short enough to read in passing. Prefer "the sensor's best
  guess" over clinical or overconfident wording.

## Logo

The approved logo is the radar-ring mark in `assets/sleepradar-mark.svg`: a
circular radar ring with a central sensor dot and subtle breathing/readout bars.
It comes from the existing live-readout visual motif, where the blue ring signals
the sensor reading now.

Use:

- `assets/sleepradar-mark.svg` as the canonical source for square contexts,
  icons, and compact badges.
- `favicon.svg` as the byte-identical browser/Conductor repository-icon copy of
  that mark. Update it with the canonical source; repository validation keeps
  the two in sync.
- `assets/sleepradar-logo.svg` for README, docs, and wider public surfaces.

Do not add medical crosses, wearable shapes, moon mascots, generic calendar
tiles, or heavy wellness branding. SleepRadar should read as a Home Assistant
telemetry tool first.
