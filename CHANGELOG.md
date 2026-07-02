# Changelog

## Unreleased

## 1.2.0

- Adds `card/sleepradar-card.js`, a dependency-free custom Lovelace card that
  renders the "Now, live" README view (phase, heart rate, breathing) from
  three of the add-on's default sensors, with honest unavailable/stale
  states. Install is a manual dashboard resource. The "Last night"
  screenshot is relabeled as a preview of a future release, since the
  optional examples dashboard does not actually reproduce it (see below).
  The card sanitizes a custom `mqtt_node_id` the same way the add-on does,
  and its `poll_interval_seconds` option keeps the "stale" badge accurate
  if you changed the add-on's `poll_interval` from the 60-second default.
- Adds `force_update: true` to the add-on's MQTT discovery payloads. Without
  it, Home Assistant does not advance an entity's `last_updated` when a poll
  republishes an unchanged value (e.g. a stable deep-sleep reading), which
  would have made the SleepRadar Card's "stale" badge false-positive during
  normal operation.
- `scripts/validate_repository.py` now checks that the card's default
  entities are a subset of what the add-on actually publishes, and that
  every discovery payload sets `force_update: true`.
- The card now treats a `sleep_state` of `"None"`/`"none"` as unavailable.
  The poller's `value_template` only guards Jinja's `Undefined`, not a
  literal `null`, so a null Aqara reading renders as the literal text
  "None" in Home Assistant — without this, the card showed a fabricated
  "Unknown" live reading instead of the honest "no data yet" state.
- Corrects the README's "Last night" claim: `examples/dashboard-sleep.yaml`
  only produces a live "Now" card plus a raw 12-hour sleep-state chart, not
  the session duration, averaged vitals, or segmented stage timeline shown
  in the screenshot — that sessionization is still a future release, not
  something buildable today from the example.

## 1.1.0

- Adds `default_entity_id` to MQTT discovery payloads alongside the existing
  `object_id`, so entity IDs are pinned correctly on Home Assistant ≥2026.4
  where `object_id` was removed from the discovery schema.

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
- Adds a one-click "Add repository to my Home Assistant" install badge and a
  CI status badge to the README, and documents the full `aqara_area` region
  list (`CN`, `EU`, `USA`, `RU`, `KR`) inline instead of only in the config
  schema.
- Poll failures now log a plain-English cause (the Aqara API error code and
  message, or a clear description of an unexpected response) instead of a
  raw JSON dump.
- The add-on now retries the MQTT broker connection with backoff (up to
  ~2 minutes) instead of exiting immediately if the broker is still starting
  up — common right after a fresh install when both add-ons boot together —
  and still responds promptly to add-on stop/restart during that retry
  window.

## 1.0.0

- Initial public package for Aqara FP2 sleep telemetry in Home Assistant.
- Adds a Home Assistant add-on that polls Aqara sleep resources and publishes
  five MQTT discovery sensors.
- Adds plain-language setup docs, placeholder-only examples, and a privacy
  validator for release checks.
