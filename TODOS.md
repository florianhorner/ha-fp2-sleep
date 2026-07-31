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

## GIF pipeline hardening (pre-ship review squad, 2026-07-22)

### Close the verified P2 gaps from the Quiet Proof Loops review

**What:** The three-agent pre-ship review of the `videos/` pipeline confirmed these
lower-severity gaps (P0/P1 were fixed before shipping): (1) the CI must-not-render
guard in `scripts/validate_repository.py` only matches literal `python[3]
videos/build-gif-deliverables.py` run lines and never scans extra workflow jobs;
(2) `validate_tracked_paths` passes vacuously when `git ls-files` returns empty
(nested checkout without its own `.git`); (3) nested pairs under
`assets/feature-gifs/sub/` and `.webm`/`.webp`/`.apng` binaries are policed by
neither the tracked-path check nor baseline discovery; (4) the new
`validate_workflow` GIF branches have no mutation self-tests, and both videos/
validators enforce many branches (banned-source classes, projection parity,
truth-pin edge cases) that self-tests don't exercise; (5)
`GIF-PRODUCTION-PLAYBOOK.md` has no `baseline_commit` guidance — a brief pinning a
squash-merged branch commit would permanently fail main CI — and no warning that
citing churny line ranges (TODOS/README) reds unrelated PRs by design; (6)
`checked_at` compares a CET-stamped date against the UTC runner clock (transient
late-evening failure); (7) `batch_default` semantics are undocumented and a bare
`build-gif-deliverables.py` run re-renders exactly the four approved episodes; (8)
episode AGENTS/CLAUDE doc conventions and `meta.json` name style are inconsistent
across the six projects.

**Why:** Each is a verified sharp edge that will cost a future session a debugging
cycle; none blocks the current CI or falsifies published binaries today.

**Effort:** M **Priority:** P2 **Depends on:** shipped Quiet Proof Loops PR

## Occupancy gate (pre-ship review squad, 2026-07-31)

### Stop trusting `last_updated` as measurement freshness

**What:** The card's `isFresh`/`isStale` calculation reads
`sensor.aqara_fp2_sleep_sleep_state.last_updated`, but the app publishes with
MQTT `force_update: true` (required by `scripts/validate_repository.py`), so Home
Assistant rewrites `last_updated` **and** `last_changed` on every poll even when
the value is byte-identical. "Live now" therefore means "the poller is alive",
never "this value is current". Either publish a source-level sample timestamp or
sample id from the Aqara payload and consume that, or drop the freshness and
live-vitals claims where no trustworthy measurement timestamp exists.

**Why:** Two independent adversarial reviews landed on this, and it is the
mechanism behind the original ghost-vitals incident. The occupancy gate now
covers the empty-bed case, but an occupied bed with a wedged poller still renders
retained vitals as `Live now`.

**Effort:** M **Priority:** P1 **Depends on:** poller payload inspection

### Classify unrecognized occupancy states as unknown, not empty

**What:** `_render` treats any occupancy state outside `occupied_states` as "the
bed is empty" unless it is in `UNAVAILABLE_STATES`. A sensor reporting `Off`
(capital O), `offline`, `error`, or `calibrating` renders **Out of bed** with the
footer "the independent bed-occupancy sensor reports the bed is empty" — a
positive claim the sensor never made. Add an explicit `unoccupied_states` and
classify everything outside both sets as `Occupancy unknown`.

**Why:** Safe direction (vitals stay hidden) but the card fabricates a claim
about a third-party sensor. Reproduced by two reviewers.

**Effort:** S **Priority:** P2 **Depends on:** none

### Reconcile the card and the template on codes 1/2

**What:** With occupancy confirmed and raw code `1`/`2`, the card renders live
heart rate and breathing (`IN_BED_SLEEP_CODES` still contains 1 and 2), while
`examples/sleep_tracking.yaml` gates vitals on `code in [3, 4, 5]` and leaves
`binary_sensor.fp2_asleep` off. Two shipped surfaces, two answers, for codes the
project itself declares to have no verified meaning. The validator pins each
independently and never cross-checks them.

**Why:** Whichever answer is right, publishing both invites a support question
nobody can answer from the docs.

**Effort:** S **Priority:** P2 **Depends on:** decision on what codes 1/2 mean

### Remaining fail-open guards in `scripts/validate_repository.py`

**What:** Comment-stripping fixed `check_card_phase_semantics`, but the same
substring-instead-of-parse shape survives elsewhere: `check_dashboard_maps`
regexes the raw YAML for `const phases` (a comment satisfies it),
`check_automation_gates` substring-matches `json.dumps` of a whole automation so
a free-text `alias` counts as a gate, `check_examples_readme_gate_contract`
matches six phrases anywhere in a whitespace-normalized blob (a "do NOT do this"
block passes), and `check_ghost_vitals_evidence` requires bare two-digit tokens
(`27`, `17`, `50`, `77`) that any incidental digits satisfy. Each was reproduced.
Also: `run_self_test` is a single 477-line function and the module is ~1900
lines; split by contract area.

**Why:** A guard that can be satisfied by prose is a guard that will be, and this
file is the repo's only CI-enforced contract layer.

**Effort:** M **Priority:** P2 **Depends on:** none

### Drop `.context` from the privacy scanner's SKIP_DIRS

**What:** `.gitignore` now excludes the agent working-notes directory, but
`scripts/validate_repository.py` still lists `.context` in `SKIP_DIRS`, so the
privacy scan skips it. An ignore
list and a scan-skip list should not be the same trust decision — scan tracked
files via `git ls-files` instead of skipping by directory name.

**Why:** Defense in depth on a public repo about a real bedroom. The ignore rule
is the fix; this is the second layer.

**Effort:** S **Priority:** P2 **Depends on:** none

### Make `aqara_fp2_sleep/Dockerfile`'s version fallback undriftable

**What:** `config.yaml` says `1.2.2`, `Dockerfile` says `ARG BUILD_VERSION=1.2.1`.
Benign today — CI and the HA Supervisor both pass `--build-arg` explicitly, so
the default is unreachable — but it can silently claim a wrong release. Change
the fallback to `dev` and leave `config.yaml` the single source of truth.
Separately, `aqara_fp2_sleep_poller.py` hardcodes `sw_version` /
`ORIGIN["sw"]` as `1.0.0`, so every user's HA device page shows `1.0.0`.

**Why:** Same class, both pre-existing, neither covered by a validator.

**Effort:** S **Priority:** P3 **Depends on:** none

## Completed

### Real "Last night" dashboard view

Built on branch `florianhorner/last-night-card`: `examples/dashboard-sleep.yaml` now
charts sleep stage + heart rate + breathing over the previous night (anchored to the
prior night, colorblind-safe palette), replacing the raw rolling 12-hour sleep-state
chart. Chart-only — sessionization (duration, averaged vitals, segmented timeline)
stays deferred. Makes the overnight GTM asset a screenshot of a real card, not a mockup.
