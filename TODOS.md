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

## Completed
