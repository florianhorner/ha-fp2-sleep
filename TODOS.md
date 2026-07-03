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

**Update (2026-07-03, /plan-eng-review):** removed the invalid boolean
`watchdog` config, added validator coverage to reject it if it returns, and
slowed wrapper-level permanent startup exits before returning failure. A real
health endpoint remains separate follow-up work.

**Effort:** M
**Priority:** P3
**Depends on:** None

## Validation

### Codegen the sleep-phase constants from a single source (only if drift bites)

**What:** Make one Python data module the single source of truth for the
sleep-phase code map (0-5 labels, in-bed codes {1,2,3,4,5}, asleep codes
{3,4,5}), and add a `scripts/generate_artifacts.py` that renders the mirrored
copies into `card/sleepradar-card.js`, both Jinja blocks in
`examples/sleep_tracking.yaml`, both maps in `examples/dashboard-sleep.yaml`,
the README "Sleep State Codes" table, and `examples/recorder.yaml` — between
`GENERATED — DO NOT EDIT` markers. CI regenerates into a temp dir and fails on
`diff --exit-code`.

**Why:** This is the only option that *removes* the ~6-way duplication instead
of just detecting it. A phase-label rename would become 1 edit + 1 command
instead of 6 hand-edits. End users still copy a plain committed `card.js` — the
generator only runs in the maintainer's dev loop, so "zero build step for users"
is preserved.

**Why deferred (not built now):** Per the /autoplan review (2026-07-03), drift
has caused zero shipped bugs in this repo's history; the validator drift guard
(the current plan's Part 2) is the proportionate response. Codegen is 2-3 days,
runs against the repo's established lightweight-validation grain, needs 4-6
bespoke per-site renderers (the two Jinja blocks and the abbreviated ApexCharts
map are intentionally *different* text for the same codes), and its main payoff
is label renames, not new sensors. Build it only if phase-code drift becomes a
real, recurring, user-facing pain — i.e. if the Part 2 validator guard starts
failing often because the manual multi-file edit keeps being missed.

**Effort:** L (2-3 days)
**Priority:** P3
**Depends on:** Part 2 validator drift guard shipping first (so there's evidence
of whether drift is actually a recurring problem)

## Completed
