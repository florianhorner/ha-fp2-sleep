# TODOS

## Poller

### Add `watchdog: true` to config.yaml

**What:** Configure the add-on's Supervisor watchdog so it auto-restarts on crash.

**Why:** The MQTT connect retry/backoff in `make_mqtt()` (added in the "first-install friction" PR) widens the window where the broker can come up before giving up, but after 6 attempts (~135s) it still raises and the process exits. Without `watchdog: true` in `config.yaml`, Supervisor won't restart it — the underlying race (add-on starts before the broker is ready) isn't structurally closed, just made less likely to matter.

**Context:** Flagged by adversarial review during the poller-fixes ship (2026-07-02). Deliberately left out of that PR since it's a `config.yaml` behavior change (auto-restart policy), not a doc/logging fix — needs its own review of restart-loop implications (e.g. crash-looping on a genuinely bad `AQARA_USER`/`PASS` config).

**Effort:** S
**Priority:** P2
**Depends on:** None

## Completed
