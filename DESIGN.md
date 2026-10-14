# SleepRadar Design Language

SleepRadar is a small Home Assistant app, not a wellness platform. The
design language should feel calm, technical, and honest: contact-free sleep
telemetry from an Aqara FP2, exposed as normal Home Assistant entities.

## Product Voice

- Lead with utility: sleep vitals that HomeKit and Matter do not expose.
- Keep the setup promise plain: no wearable, no Docker bridge, no developer
  account.
- Separate sensor-reported measurements from inferred data every time it
  matters. Heart rate, breathing, body movement, and illuminance are reported
  by the sensor as measurements. Here, "measured" names the signal category; it
  does not claim independent validation or clinical accuracy. Sleep stage is
  the device's best guess.
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

### Compact current readout

Use a neutral surface with crisp phase accents, not tinted header fills. The
phase heading is 22px, tabular vital values are 32px, and supporting text is
12–13px at the default 16px root size. Text scales with the user's settings.
The header has a 2px phase rail; the vitals share two columns with a quiet
divider, and provenance sits below an inset separator. Let long labels and
diagnostics wrap at narrow widths.

| Current phase | Non-color cue | Light-theme ink | Dark-theme ink |
| --- | --- | --- | --- |
| Deep sleep | Filled circle | `#2758d8` | `#9bb9ff` |
| Light sleep | Hollow circle | `#216dd8` | `#8ec4ff` |
| REM | Diamond | `#925600` | `#f4c773` |
| Stale, blocked or uncertain | Dash | Inherited primary text | Inherited primary text |

Keep the phase name visible and mark its geometric cue decorative for assistive
technology. Phase ink can be overridden by the `--sleepradar-deep-color`,
`--sleepradar-light-color` and `--sleepradar-rem-color` CSS properties. The default
inks meet AA text contrast on white and the documented night surface; custom
themes must check their own foreground/background pairs. Background, text and
dividers inherit Home Assistant theme variables. A theme switch must redraw
even if sensor readings are unchanged; missing mode metadata uses inherited text.

Only a fresh valid stage gets a phase accent. Preserve independent occupancy,
stale-feed, missing-value and diagnostic safeguards. Show the best-guess caption
once beside the phase and use a short sensor-reported-vitals footer for healthy
stages. Keep caveats in fault and compatibility states. Do not repeat healthy
values in a narrative sentence or add duplicate Live now labels.

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
