# Changelog

## 1.3.0

- Adds `binary_sensor.aqara_fp2_sleep_connection_problem`, a diagnostic entity
  that turns on when data stops and carries the reason in its `cause`
  attribute. It is independent of the five vitals sensors, so it stays readable
  while they are unavailable, and its state is retained across a Home Assistant
  restart. Recorded by `examples/recorder.yaml`.

- Raises a Home Assistant notification naming the cause and the fix when the
  Aqara connection fails, updates it if the cause changes, and dismisses it on
  recovery. Needs the new `homeassistant_api: true` permission, used for that
  call only. **Existing installs must approve it once after updating**; until
  then the diagnostic entity still works, the notification is skipped, and the
  log says so at `warning`.

- Names the cause of a failed sign-in instead of passing through Aqara's
  "Request failed. Please try again." Code `106` now reports that the
  configured region rejected the account and points at `aqara_area`.

- Separates transient failures (DNS, timeouts, Aqara 5xx) from permanent ones
  (rejected credentials). Transient failures get a grace window before they are
  flagged; permanent ones are flagged immediately and back off between retries
  instead of re-attempting the sign-in every poll interval.

- Logs the startup sign-in failure at `error` instead of `fatal`. The process
  keeps running and recovers on its own, so `fatal` described a crash that
  never happened.

- Shows the reported cause in the SleepRadar Card instead of the generic "no
  data yet" message once the app has flagged a connection problem. Accepts an
  optional `entities.connection_problem` override.

- Adds an example automation that forwards a connection problem to a notify
  service, with a five-minute delay so a brief network blip does not wake you.

- **Breaking for anyone already using the optional `examples/` templates.**
  `examples/sleep_tracking.yaml` now requires an independent
  `binary_sensor.bed_occupied`. Without it, `sensor.fp2_sleep_phase`,
  `sensor.fp2_sleep_now`, and `binary_sensor.fp2_asleep` go unavailable and any
  automation gated on them stops running. `examples/automations.yaml` also
  renames the deep-sleep trigger state from `"Deep sleep"` to
  `"Deep sleep (indicative)"`; an existing copy of that automation will silently
  never fire again until it is updated. The five MQTT entities, polling, and
  Recorder history are unchanged.

- Documents that the `sleep_state` 0-5 mapping is community-derived and
  unverified. Aqara's public resource documentation does not publish the FP2
  enumeration, and the community mapping checked by this project reads code
  `1` as "In Bed" rather than "Awake". Codes `0`/`1`/`2` are no longer treated
  as occupancy or wake authority when an independent occupancy gate is active;
  the legacy no-gate labels remain backward-compatible.

- Adds a privacy-safe regression fixture for an approximately 2.5-hour
  ghost-vitals incident: 300 sleep-state updates across codes `4`/`5`/`3` and
  301 heart-rate updates collapsing to 27 consecutive value runs, 17 distinct
  values, and a 50-77 bpm range while independent occupancy stayed empty.
  Absolute timestamps and entity IDs are omitted.

- Adds an optional, fail-closed `bed_occupancy` gate to the SleepRadar Card so
  independent occupancy can hide ghost vitals without changing MQTT or
  Recorder history. Confirmed occupancy makes codes `0`/`1`/`2` render as
  in-bed with no asserted wake stage, direct self-reference is rejected, and
  the documented contract trusts Home Assistant availability without imposing
  an occupancy-age timeout. The optional dashboard now uses the production card
  for its live view and labels its previous-night charts as raw Aqara telemetry.

- Refreshes the affected Quiet Proof Loops briefs against the occupancy-gate
  contract and clarifies that their visible "measured" label names a
  sensor-reported signal category, not independently validated accuracy. The
  approved GIF/MP4 binaries and their hashes are unchanged; no rerender is
  implied.

- Contributor tooling only; the add-on is unchanged. The GIF truth validator
  no longer rejects a brief when a squash merge erases its `baseline_commit`.
  This fixes the failure that turned `main` CI red after #34. If the pin is not
  reachable from `HEAD`, validation uses the last commit that touched the brief
  and still checks cited-content drift against that snapshot. A brief with no
  committed history still fails closed.

- Contributor tooling only; no change to the add-on itself. The local
  pre-PR validation chain now runs the same gates as CI's `validate` job from a
  single shared list, reducing the chance of gate-membership drift between
  them. Repository tooling requires Python 3.11+ (the add-on runtime is
  unchanged). Adds
  `docs/repository-validation.md` describing what the validator checks, how the
  local and CI lanes relate, and how to change a gate safely, plus direct
  bug-report and security-policy links in the README.

- Hardens the repository validator so its own checks assert behavior rather than
  the presence of expected text, with regression coverage for the new guard
  paths (coverage is not exhaustive), and makes the CI secret-scanning controls
  prove both that the config detects a planted value and that it excludes
  generated local state. Also adds a command-line test suite for the validator
  and makes it independent of ambient environment variables.

- Adds the "Last night" feature GIF to the README dashboard section and tracks
  its reproducible production source in git: `videos/` now carries the frame
  contract, style guide, production playbooks, per-episode projects, template,
  and validators for the five managed projects, with a SHA-256 baseline locking
  all six published binaries (the pilot GIF stays an unmanaged historical
  reference). CI validates the GIF sources, the baseline, and the
  validator self-tests without rendering; `scripts/validate_repository.py`
  enforces that published GIF/MP4 pairs live under `assets/feature-gifs/` with
  tracked source under `videos/` and that generated render output stays
  untracked. Adds the repository social preview image
  (`assets/sleepradar-social-preview.png` plus its editable SVG source) and a
  repo-local `AGENTS.md` routing file for GIF authoring.

- Adds a "Last night" section to `examples/dashboard-sleep.yaml`: sleep stage,
  heart rate, and breathing charted over the previous night, replacing the raw
  rolling 12-hour sleep-state chart. The window anchors to the prior night
  instead of the last 12 hours, and the palette is colorblind-safe. Sleep stage
  stays labeled as Aqara's estimate; the planned sessionization summary (session
  duration, averaged vitals, segmented timeline) is unchanged and still a mockup.

- Adds the short SleepRadar feature GIFs to the README: the shipped Live Now
  card is now the primary visual proof, and the automation section shows the
  sleep-aware lighting example.

- Fixes the SleepRadar add-on store card so the icon has transparent rounded
  corners and the summary fits cleanly in the Home Assistant app list.

- Pins the add-on's runtime Python dependencies in
  `aqara_fp2_sleep/requirements.txt`, installs the Docker image from that
  contract, and mirrors the supply-chain checks across CI, repository
  validation, contributor docs, and Conductor setup. CI now audits only runtime
  dependencies, verifies Gitleaks before scanning the current tree, and builds
  the add-on image as a smoke test.

- Aligns the docs to Home Assistant's current terminology. User-facing text
  now says **app / Apps** (Home Assistant renamed Add-ons to Apps; the install
  action is **Settings > Apps > Install app**), while historical changelog
  entries and package internals keep "add-on" where that is still the
  underlying Home Assistant packaging term. Swaps the two rot-prone navigation
  paths (entity states, dashboard resources) to My Home Assistant redirect links
  that Home Assistant maintains, so they can't silently drift on the next UI
  rename.

- Clarifies in the README and the SleepRadar Card's "no data" message that
  Home Assistant pins an entity's id the first time it creates that entity
  and never renames it afterward — so upgrading past v1.1.0 (which added
  `default_entity_id` to pin new entities correctly) does not retroactively
  fix entity ids for installs where the entities already existed. Found by
  dogfooding the card on a live instance whose sensors predated that fix and
  still don't match the card's `sensor.aqara_fp2_sleep_*` defaults; the card
  now points users at Developer Tools > States and the `entities:` override
  instead of implying the app itself is broken.

## 1.2.2

- Removes the invalid boolean `watchdog` add-on config and adds a validator
  guard so `watchdog`, if ever used, must be a health-check URL string instead
  of a restart-toggle boolean.
- Permanent startup failures now slow-exit before returning an error: the
  wrapper waits ~30s for missing MQTT service or required Aqara config, and the
  Python poller does the same for direct-run missing config or unknown
  `aqara_area`. This prevents rapid loops when an external Supervisor watchdog
  is enabled.
- Logs a clear `[fatal]` line when the initial Aqara login fails, instead of
  only per-poll warnings. The app keeps retrying and the sensors stay
  unavailable until login succeeds.

## 1.2.1

- Fixes the SleepRadar Card's out-of-bed state so retained FP2 heart-rate and
  breathing values are hidden instead of looking live after the bed is empty.
  The card now labels freshness in the header, shows per-vital status text,
  and only renders live vitals when the sleep state is fresh and in-bed.

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
