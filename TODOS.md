# TODOS

## Poller

### Review add-on startup failure handling

**What:** Replace the old `watchdog: true` idea with a repo-backed startup
strategy for failures that happen in `aqara_fp2_sleep/run.sh`, before Python
starts. The follow-up should cover missing MQTT service and missing required
add-on options, plus validator coverage that prevents reintroducing an invalid
watchdog shape.

**Why:** The fragile startup paths exit in `run.sh` before
`aqara_fp2_sleep_poller.py` starts, so Python retry/backoff cannot fix them.
Home Assistant add-on `watchdog` is not a boolean restart toggle, and tracking
that as the next fix would send future work toward the wrong boundary.

**Context:** Flagged during the poller-fixes/startup review work and corrected
here because this hardening PR already updates the repo's tracking surface.
Keep the actual runtime behavior change out of this supply-chain PR unless it
gets separate Home Assistant Supervisor runtime proof.

**Effort:** S
**Priority:** P2
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
