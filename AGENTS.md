# Repository Instructions

## SleepRadar GIF batch

Before creating, revising, rendering, or handing off any SleepRadar marketing
GIF under `videos/`, read these sources in order:

1. `DESIGN.md` for SleepRadar product voice and semantic honesty.
2. `videos/frame.md` for the normative video profile.
3. `videos/GIF-STYLE-GUIDE.md` for creative direction.
4. `videos/GIF-PRODUCTION-PLAYBOOK.md` for the evergreen production workflow.

For work that touches the historical GIF 2–5 batch, also read
`videos/GIF-BATCH-PLAN.md` and `videos/GIF-BATCH-PLAYBOOK.md`.

- Use neutral, descriptive names for production documentation; call the
  creative-direction document a style guide.

- Treat the approved “Same sensor. Now 5 sleep signals.” pilot as the visual,
  motion, proof, and handoff baseline for GIFs 2–5.
- Verify every product claim against the current canonical repo and latest
  release before authoring the hook.
- Do not modify the product, API, Home Assistant, or global policy files as
  part of the GIF workflow.
- Do not present a render until final-binary proof, explicit specifications,
  loop verification, and verified localhost artifact links are available.
- Keep reproducible source, contracts, fixtures, episode projects, licenses,
  and required runtime assets in Git. Keep `renders/` and `snapshots/`
  generated; publish only approved delivery binaries under
  `assets/feature-gifs/`.
## Cursor Cloud specific instructions

There is no long-running server or standalone app to start. The SleepRadar
Home Assistant add-on (`aqara_fp2_sleep/run.sh`) is `bashio`-only and needs a
real HA Supervisor + MQTT broker + Aqara credentials, so it cannot run in this
environment. The runnable dev workflow is the lint + validate loop documented
in `CONTRIBUTING.md` (mirrored by `.conductor/settings.toml` `[scripts] run`);
run those commands through the project venv, e.g. `.venv/bin/python ...`,
`.venv/bin/yamllint ...`, and `node tests/sleepradar-card.test.js`. That loop
is the same set of gates as CI's `validate` job.

- The startup update script provisions `.venv` from `requirements-ci.txt`.
  Creating the venv requires the `python3.12-venv` system package (baked into
  the environment snapshot, not the update script). Node.js and ffmpeg/ffprobe
  are preinstalled; the card test uses only Node built-ins (no `npm install`).
- `docker` and `gitleaks` are not installed here, so CI's `docker-build` job
  and the `security` job's Gitleaks step cannot run locally — rely on CI for
  those. `pip-audit` is not in `requirements-ci.txt` (see `CONTRIBUTING.md`).
- The SleepRadar card (`card/sleepradar-card.js`) is a zero-dependency custom
  element and can be exercised without Home Assistant: load it in a browser
  with a plain `<script>` tag, call `setConfig({})`, then assign a mock
  `hass = { states: { ... } }` with the `sensor.aqara_fp2_sleep_*` entities.
  It re-renders on each `hass` assignment. Keep `last_updated` within ~3×
  `poll_interval_seconds` (default 60s) or the card hides vitals as stale.
