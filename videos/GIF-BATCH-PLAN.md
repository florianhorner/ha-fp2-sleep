# SleepRadar GIF Batch Reference

This document maps GIFs 2–5 to their product claims and reproduction constraints.
The pilot, “Same sensor. Now 5 sleep signals.”, supplies the shared visual and
motion baseline. Each episode owns one feature, a GIF and an MP4 master.

For new episodes, use `frame.md`, `GIF-STYLE-GUIDE.md` and
`GIF-PRODUCTION-PLAYBOOK.md`. For this batch's additional constraints, use
`GIF-BATCH-PLAYBOOK.md`. Episode briefs own current claim evidence; the
historical pins below do not establish that a claim is current.

## Artifact map

| Slot | Episode directory | Single claim |
| --- | --- | --- |
| 2 | `sleepradar-live-now-card/` | Three current readings form one honest Home Assistant readout |
| 3 | `sleepradar-contact-free-vitals/` | Heart rate and breathing are sensor-reported measurement signals |
| 4 | `sleepradar-honest-sleep-stages/` | Sleep stages remain visibly labelled as estimates |
| 5 | `sleepradar-sleep-aware-lighting/` | A published state can drive a comfort automation |

Check each directory's `BRIEF.md` and `package.json` for its current source
pin, claim and renderer version. Delivery pairs live in `assets/feature-gifs/`;
`gif-batch-baseline-sha256.json` binds the tracked binary bytes.

## Historical source pins

| Purpose | Source |
| --- | --- |
| Initial batch product baseline | `a03399c6d72799a015c559ad0a72d4c1b6811ea3`, release `v1.2.1` |
| Occupancy-gate claim refresh | `5a02e00003a0d87c73ce38aa19df139baab20f42` (`5a02e00`) |
| Initial batch renderer | HyperFrames `0.7.61` |

A documentation-only evidence refresh does not prove a new delivery render.
Recheck current claims against each brief's pinned implementation before
rendering; preserve unchanged delivery binaries during unrelated migrations.

## Shared baseline

- Vertical `720×1280`; six seconds within the historical `5–9s` range; silent.
- Inter typography, a two-line hook hierarchy, restrained palette and card
  geometry follow the pilot and the shared profile.
- Hook visible at frame zero; motion begins by `0.8s`; payoff complete by
  `3.0s`; readable payoff holds at least `1.5s`; the exact opening state holds
  for the final `0.10s`.
- GIF: `15 fps`, 90 frames at six seconds, infinite loop. Working target
  `≤750 KiB`; hard ceiling `1 MiB`. The historical Live Now delivery is
  `932221` bytes using a 64-color fallback, above target and below ceiling;
  this is not a target exception for a future render.
- MP4: H.264, `30 fps`, 180 frames at six seconds, silent. No MP4 size ceiling
  is defined; report actual bytes.
- GIF first and last decoded frames must be pixel-identical. MP4 endpoint
  SSIM must be `≥0.999000`, with a visual seam check.
- Inspect source at `0`, `0.8`, `1.8`, `3.0`, `4.5` and `5.9s`, plus transition
  samples. Inspect proof extracted from the final delivery binaries too.

## Episode constraints

### GIF 2 — Live Now card

Show sleep stage, heart rate and breathing in the real card hierarchy. Preserve
unavailable, stale and out-of-bed behavior. The existing empty-bed opening uses
the legacy no-gate code-`0` label; an optional independent gate can override
that label. Body movement and illuminance remain published entities but are
not displayed by this card.

### GIF 3 — Measured heart rate and breathing

Show both values with the visible `measured` category. That word identifies
sensor-reported signals; it does not establish independent validation,
clinical accuracy or diagnosis. Do not imply continuous readings while the
bed is empty or depict personal telemetry.

### GIF 4 — Sleep-stage estimates

Keep the estimate or best-guess qualifier visible in the payoff. Do not imply
measured stage truth, medical precision or an unshipped session summary.

### GIF 5 — Sleep-aware automations

Show one supported input → automation → home response chain from current
examples. Describe comfort or convenience, never safety-critical behavior or
medical monitoring.

## Reproduction checks

1. Verify the claim against the current implementation and released behavior;
   update the episode's source pin deliberately when evidence changes.
2. Preserve shared tokens and timing while keeping the episode's feature
   distinct. Run composition checks before rendering.
3. Render the selected MP4, derive its GIF and inspect artifact-derived proof.
   Record dimensions, rates, counts, duration, silence, bytes, SHA-256 digests
   and endpoint metrics in the generated verification file.
4. Check the delivery baseline digest diff. Do not rerender sibling episodes
   merely to validate a source-contract change.
