# Compact SleepRadar card

The current readout puts the sleep phase above two labeled, sensor-reported
vitals. It uses the existing card configuration and data interpretation.
See [the design language](../DESIGN.md#compact-current-readout) for dimensions,
phase colors and theme overrides, and [the README](../README.md#the-sleepradar-card)
for installation and configuration.

## Rendering contract

- Fresh REM, Light sleep and Deep sleep use a diamond, hollow circle and filled
  circle respectively. Keep the literal phase name and best-guess caption.
- Stale, unavailable, unmapped and occupancy-blocked states remain neutral.
  Independent occupancy gates the phase and vitals before stage rendering.
- Retain missing-value, freshness, compatibility and connection explanations.
  Suppress only redundant healthy-state prose and repeated Live now labels.
- Inherit Home Assistant surfaces, text and dividers. A theme-only update must
  repaint the card even when sensor objects are unchanged. Missing theme-mode
  metadata uses the inherited primary text color for phase ink.
- Keep the existing three-poll stale threshold and 30-second recheck. A
  disconnected element must release its timer; reconnecting restores it.

## Implementation boundary

`card/sleepradar-card.js` parses the existing entities, applies occupancy and
freshness decisions, then passes computed display values to one shared compact
renderer. Normal and occupancy-blocked views share the presentation template;
the missing-feed view retains its diagnostic template. Dynamic text is escaped
at the rendering boundary. Only fresh stage codes 3, 4 and 5 receive accents.

Theme mode participates in the render signature alongside relevant entity
values, timestamps and connection diagnostics. Unrelated Home Assistant
updates continue to skip rendering. The card adds no runtime dependencies,
network requests, history queries or new configuration fields. MQTT entities,
polling and Recorder behavior are unchanged.

## Automated validation

Run `node tests/sleepradar-card.test.js` and the complete shared validation
block in [CONTRIBUTING.md](../CONTRIBUTING.md#local-setup).

| Scenario | Required result |
| --- | --- |
| Fresh REM, Light and Deep | Correct phase category, labeled values and units, one best-guess caption |
| Empty or unknown occupancy | Neutral output; retained phase and vitals suppressed; gate explanation preserved |
| Occupied code 0; codes 1 and 2 | Existing in-bed labels and unverified-code caveats preserved |
| Stale, future, missing or invalid timestamp | Vitals hidden, neutral phase, explicit freshness caveat |
| Missing or nonnumeric vital | Only the affected metric is hidden and explained |
| Missing feed or connection fault | Recovery text remains visible and escaped, including behind a blocked gate |
| Identical entities with a theme change | Palette updates without changing sensor semantics |
| No entity updates across the stale boundary | Timer hides vitals and removes the phase accent |
| Disconnect and reconnect | Timer is released and replaced without detached DOM writes |

## Visual validation

Open [the synthetic preview](../proof/compact-card-preview.html) from a checkout.
It loads the production card script and mocks only the Home Assistant card
shell and entity data. It does not connect to Home Assistant or Aqara.

Check 440px and 320px card widths, light and dark modes, and 200% text. Phase
names, geometric cues, captions, values and units must remain visible. Long
diagnostic text must wrap and appear as text. Changing only the theme must
repaint each normal, blocked and diagnostic view. Default phase text must meet
4.5:1 contrast against its surface; custom theme overrides need their own check.

The Node harness checks rendering semantics and timer behavior; it cannot
establish computed CSS contrast, visual clipping or screen-reader behavior.
Synthetic preview checks do not establish live Supervisor, MQTT or Aqara
integration, independent stage accuracy, or clinical validity.
