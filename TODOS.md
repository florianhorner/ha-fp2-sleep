# TODOS

## Poller

### Add `watchdog: true` to config.yaml

**What:** Configure the add-on's Supervisor watchdog so it auto-restarts on crash.

**Why:** The MQTT connect retry/backoff in `make_mqtt()` (added in the "first-install friction" PR) widens the window where the broker can come up before giving up, but after 6 attempts (~135s) it still raises and the process exits. Without `watchdog: true` in `config.yaml`, Supervisor won't restart it — the underlying race (add-on starts before the broker is ready) isn't structurally closed, just made less likely to matter.

**Context:** Flagged by adversarial review during the poller-fixes ship (2026-07-02). Deliberately left out of that PR since it's a `config.yaml` behavior change (auto-restart policy), not a doc/logging fix — needs its own review of restart-loop implications (e.g. crash-looping on a genuinely bad `AQARA_USER`/`PASS` config).

**Update (2026-07-03, /autoplan review):** the "crash-loop on bad credentials"
worry does not hold once you trace the code — `main()` ignores the startup
`aqara.login()` return (`aqara_fp2_sleep_poller.py:390`) and the poll loop keeps
re-trying login every cycle, marking entities offline, so bad credentials never
exit the process (no crash-loop; instead a green-looking add-on producing no
data). The real restart-loop risk from watchdog is the **missing-config /
unknown-area `SystemExit`** path, which exits *before* the MQTT backoff and would
tight-loop. Scoped and implemented in Part 1 (watchdog + cooldown guard on the
tight-loop startup exits via `fatal_startup()` + one clear startup auth-failure
log line).

**Effort:** S
**Priority:** P2
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
