# TODOS

## Poller

### Add `watchdog: true` to config.yaml

**What:** Configure the add-on's Supervisor watchdog so it auto-restarts on crash.

**Why:** The MQTT connect retry/backoff in `make_mqtt()` (added in the "first-install friction" PR) widens the window where the broker can come up before giving up, but after 6 attempts (~135s) it still raises and the process exits. Without `watchdog: true` in `config.yaml`, Supervisor won't restart it — the underlying race (add-on starts before the broker is ready) isn't structurally closed, just made less likely to matter.

**Context:** Flagged by adversarial review during the poller-fixes ship (2026-07-02). Deliberately left out of that PR since it's a `config.yaml` behavior change (auto-restart policy), not a doc/logging fix — needs its own review of restart-loop implications (e.g. crash-looping on a genuinely bad `AQARA_USER`/`PASS` config).

**Effort:** S
**Priority:** P2
**Depends on:** None

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
