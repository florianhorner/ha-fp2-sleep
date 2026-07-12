# TODOS

## Poller

### Revisit Supervisor watchdog support with a health endpoint

**What:** If SleepRadar needs first-class Supervisor watchdog support later, add
a real health endpoint and set `watchdog` to that URL. Do not use
`watchdog: true` in `config.yaml`: Home Assistant's add-on config uses that key
for a health-check URL, not a repo-side restart-toggle boolean.

**Why:** The MQTT connect retry/backoff in `make_mqtt()` widens the window where
the broker can come up before giving up, but after 6 attempts (~135s) it still
raises and the process exits. The current repo can reduce restart-loop harm by
slow-exiting permanent startup failures, but forcing Supervisor restart policy is
not solved by a boolean `watchdog` key.

**Update (2026-07-07, review fix):** removed the invalid boolean `watchdog`
config, slowed wrapper-level permanent startup exits before returning failure,
made the shell cooldown interruptible, shared the cooldown with Python through
`STARTUP_FAILURE_COOLDOWN`, and added validator coverage to reject the old shape
and catch shell/Python cooldown drift. A real health endpoint remains separate
follow-up work.

**Effort:** M
**Priority:** P3
**Depends on:** HA Supervisor runtime proof

## Supply Chain

### Hash-lock Python installs

**What:** Add a generated, hash-locked requirements file and install with
`pip --require-hashes` in CI and the Docker build.

**Why:** This PR pins package versions, which closes version drift. Hashes would
also pin the exact distributions selected by pip, but they need a deliberate
refresh process so routine dependency updates do not become ambiguous.

**Context:** Deferred from the supply-chain hardening PR because the repo first
needs a low-friction update workflow for the small runtime dependency set.

**Effort:** S
**Priority:** P2
**Depends on:** Pinned requirements contract

### Pin the base image by digest

**What:** Pin `ghcr.io/home-assistant/base-python:3.13-alpine3.21` by digest and
document the refresh cadence.

**Why:** The tag is specific but still mutable. A digest pin would make Docker
build inputs fully reproducible, but it also requires a maintenance path for
Home Assistant base-image security updates.

**Context:** Deferred until the repo has an explicit base-image refresh policy.

**Effort:** S
**Priority:** P2
**Depends on:** Base-image refresh policy

### Run the add-on as non-root

**What:** Move the add-on process to a non-root user if the Home Assistant base
image and bashio startup path support it cleanly.

**Why:** Dropping privileges would reduce container blast radius, but it needs
runtime proof in a real Supervisor environment before shipping.

**Context:** Deferred from the supply-chain hardening PR because it is a runtime
behavior change, not a repo-only CI hardening change.

**Effort:** M
**Priority:** P2
**Depends on:** HA Supervisor runtime proof

## GTM / Distribution (reach machine)

Source: /autoplan strategic session 2026-07-13. Doctrine: reach-first — manufacture
reach, let real (outbound) demand decide feature work. Gate reshaped from passive
"inbound signal in 7 days" to per-channel click/install attribution.

### Seed proof into existing demand pools (capture, don't broadcast)

**What:** Post a tailored, honest reply + demo GIF + tracked install link into the
top FP2-sleep-in-HA demand threads. Lead with the packaging wedge (one-click add-on,
no Node-RED / REST YAML / HACS integration setup, honest stale states), NOT "exposes
FP2 vitals" (competitors already do). Targets, ranked: Aqara Forum t/185765; HA
Community t/967666, t/666598; HA core issues #124529 / #111564 (HomeKit-only-presence
frustration = the wedge in users' words).

**Why:** Demand is already indexed; silence to date is missing reach, not missing
demand. Competitors exist (Darkdragon14/ha-aqara-devices w/ live SSE, sdavides Node-RED,
Komzpa REST/Patreon) — differentiation is packaging.

**Effort:** M **Priority:** P1 **Depends on:** demo GIF asset

### Produce the proof asset (still image, NOT a GIF)

**What:** Sleep vitals are a slow time series — a live dashboard has no motion worth
filming. The asset is the **overnight retrospective still**: last night's 12h sleep-state
chart (already rendered by examples/dashboard-sleep.yaml ApexCharts graph_span:12h) + HR/
breathing history, annotated with the story ("asleep 23:40 · HR bottomed at 52 in deep
sleep · 2 wake-ups · up 06:50"). Plus a **contrast still**: HomeKit→HA = one presence
boolean vs SleepRadar→HA = 5 vitals + overnight chart (dramatizes the wedge; matches the
frustration in HA core issues #124529 / #111564). Reused across every channel.

**Why no new feature needed for v1:** HA recorder + the existing example dashboard already
produce a real overnight chart from one night of data. Deferred "Last night" sessionization
(duration, averaged vitals, segmented timeline) would upgrade the asset later, not gate it.

**Effort:** S **Priority:** P1 **Depends on:** live HA (one night of captured data)

### Tracked-link / attribution scheme

**What:** v1 = GitHub referrer traffic (already available, by source domain). Optional
thread-level = one GoatCounter/Dub short link per thread. This click/install metric is
the outbound signal that replaces the passive demand gate.

**Effort:** S **Priority:** P2 **Depends on:** none

### Browser pass to mine Reddit demand pools

**What:** r/homeassistant + r/Aqara are the largest pools but blocked for the WebSearch
crawler. Mine via a browser session for live "FP2 sleep/vitals in HA" threads; add to
the seed target list. Also scan competitor repos' issues for feature requests (= demand).

**Effort:** S **Priority:** P2 **Depends on:** none

## Dashboard / Entities

### Reconcile `default_entity_id` naming so instances and new installs converge

**What:** The MVP-era MQTT device name "Aqara FP2 Sleep Monitor" makes HA derive
`sensor.aqara_fp2_sleep_monitor_*` entity IDs on installs created before
`default_entity_id` pinning (v1.1.0). New installs get the repo's documented
`sensor.aqara_fp2_sleep_*`. So the shipped examples/card/validator (which expect
`aqara_fp2_sleep_*`) don't bind on older instances — including the maintainer's own,
which blocks dogfooding the shipped "Last night" view without hand-overriding series.

**Why:** Two entity-ID namespaces for the same product is a support and screenshot
trap. Decide the canonical scheme, confirm `default_entity_id` actually pins new
installs to it, and document the one-time migration for pre-pin instances (HA never
renames existing entities). Known dogfood gap from the v1.1.0 notes.

**Effort:** M **Priority:** P2 **Depends on:** live-instance verification of
`default_entity_id` behavior on current HA

## Completed

### Real "Last night" dashboard view

Built on branch `florianhorner/last-night-card`: `examples/dashboard-sleep.yaml` now
charts sleep stage + heart rate + breathing over the previous night (anchored to the
prior night, colorblind-safe palette), replacing the raw rolling 12-hour sleep-state
chart. Chart-only — sessionization (duration, averaged vitals, segmented timeline)
stays deferred. Makes the overnight GTM asset a screenshot of a real card, not a mockup.
