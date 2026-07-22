# SleepRadar GIF Batch Plan

Updated: 2026-07-18

## Objective

Produce four additional 5–9 second vertical SleepRadar GIFs using the approved
pilot as a locked design, motion, product-truth, verification, and handoff
baseline. Deliver one feature per GIF, an optimized GIF plus MP4 master for
each, and one consolidated review package.

No product/API work, Home Assistant changes, publishing, commits, or deployment
are included.

This file is the historical execution record for GIFs 2–5. New episodes use
the evergreen decision system in `frame.md`, `GIF-STYLE-GUIDE.md`, and
`GIF-PRODUCTION-PLAYBOOK.md`; this record does not override those owners.

## Status

| Step | Status | Exit criterion |
| --- | --- | --- |
| Pilot: “Same sensor. Now 5 sleep signals.” | Complete — approved | User approved final GIF on 2026-07-17 |
| Lock reusable batch system | Complete | `GIF-BATCH-PLAYBOOK.md` records visual, truth, budget, proof, and handoff rules |
| Verify GIFs 2–5 against current product surface | Complete | All four `BRIEF.md` files cite `origin/main` at `a03399c6d72799a015c559ad0a72d4c1b6811ea3`, release `v1.2.1`, and supporting source |
| Lock hooks and beat sheets | Complete | Four frame-zero-readable hooks and six-second shot plans are locked |
| Author and render GIFs 2–5 | Complete | Four isolated HyperFrames `0.7.61` projects produced silent 30 fps MP4 masters and 15 fps GIFs |
| Run final-binary QA | Complete | All artifacts pass source checks, strict composition checks, hashes, artifact-derived proof, hard budget, and loop thresholds |
| Consolidated user review | Ready for review | Localhost package is complete; response is `GO ALL` or `REDO <GIF> <dimension>` |

## Production gate record

- Repository baseline reconfirmed at `origin/main`
  `a03399c6d72799a015c559ad0a72d4c1b6811ea3`, release `v1.2.1`.
- Repository validator, validator self-test, card-state tests, batch validator,
  and batch-validator self-test pass.
- All four strict HyperFrames checks pass at `0`, `0.8`, `1.8`, `3.0`, `4.5`,
  and `5.9s`, including transition samples and snapshots.
- All GIFs are `720×1280`, 15 fps, 90 frames, six seconds, silent, and have
  pixel-identical decoded endpoints.
- All MP4 masters are H.264 `720×1280`, 30 fps, 180 frames, six seconds,
  silent, and exceed endpoint SSIM `0.999000`.
- GIFs 3–5 meet the `750 KiB` target. GIF 2 uses the allowed 64-color fallback
  and is `932221` bytes: above the target but below the hard `1 MiB` ceiling.
- Final-binary contact sheets and SHA-256 manifests are recorded in each
  project's `renders/` directory and `VERIFICATION.md`.

## Locked baseline from the pilot

- Vertical `720×1280`; 5–9 seconds; silent.
- Reuse the approved palette, Inter typography, two-line hook hierarchy, card
  geometry, calm motion, readable hold, and exact-return loop grammar.
- Hook visible at frame zero; motion begins by `0.8s`; payoff complete by
  `3.0s`; payoff holds at least `1.5s`; exact opening state holds for the final
  `0.10s`.
- GIF target `≤750 KiB`, hard ceiling `1 MiB`; MP4 master at 30 fps.
- GIF seam: first and last decoded frames pixel-identical.
- MP4 seam: first/last decoded-frame SSIM `≥0.999000` plus visual confirmation.
- Follow every truth, QA, proof, link, and handoff rule in
  `GIF-BATCH-PLAYBOOK.md`.

## Remaining GIFs

### GIF 2 — Live Now card

- **Single claim:** SleepRadar turns three current sensor readings into one
  honest live Home Assistant readout.
- **Must show:** sleep stage, heart rate, and breathing inside the real card
  hierarchy.
- **Must preserve:** unavailable, stale, and out-of-bed honesty.
- **Must not imply:** that body movement and illuminance are displayed in the
  Live Now card, even though they remain published entities.

### GIF 3 — Measured heart rate and breathing

- **Single claim:** heart rate and breathing are measured contact-free by the
  FP2 and exposed to Home Assistant.
- **Must show:** both values as measured signals with restrained, non-medical
  language.
- **Must not imply:** clinical accuracy, diagnosis, continuous readings while
  the bed is empty, or invented personal telemetry.

### GIF 4 — Honestly labelled sleep-stage estimates

- **Single claim:** SleepRadar exposes sleep stages while clearly identifying
  them as the sensor's estimate.
- **Must show:** the estimate/best-guess qualifier on-screen as part of the
  payoff, not only in supporting copy.
- **Must not imply:** measured stage truth, medical precision, or an unshipped
  session-summary feature.

### GIF 5 — Sleep-aware Home Assistant automations

- **Single claim:** a SleepRadar state can drive a shipped, supportable comfort
  automation in Home Assistant.
- **Must show:** one simple input → automation → home response chain.
- **Must not imply:** safety-critical behavior, medical monitoring, or support
  for an automation that is not present in current examples/product docs.

## Execution sequence

1. Refresh `origin/main` and latest release truth once, then record any shared
   product-surface facts used across the batch.
2. Create a `BRIEF.md` and time-coded beat sheet for each GIF. Lock all four
   hooks before composition work begins.
3. Author GIFs 2–5 independently against the same approved tokens and timing
   contract. Do not redesign the shared system per GIF.
4. Run composition checks and visual inspection before any delivery render.
5. Render each MP4 master, derive each optimized GIF, and run final-binary QA.
6. Generate one artifact-derived proof sheet and `VERIFICATION.md` per GIF.
7. Serve every render and proof asset on the allocated Conductor localhost
   port; verify HTTP 200 responses.
8. Present one consolidated review with four rows: claim, GIF, MP4, proof,
   specs/budget, highest uncertainty, and decision.
9. Accept only `GO ALL` or targeted feedback in the form
   `REDO <GIF number> <HOOK|READABILITY|ACCURACY|LOOP>`; keep approved GIFs
   untouched while revising the named one.

## Batch completion criteria

- All four concepts are visually distinct but unmistakably one family.
- Every marketed fact is current and evidenced.
- Every GIF meets the size ceiling and exact-loop requirement.
- Every MP4 meets the SSIM threshold and visual seam check.
- Every handoff link resolves and every checksum is explicitly labelled
  SHA-256.
- No product, API, Home Assistant, global-policy, publishing, or deployment
  changes occurred.
