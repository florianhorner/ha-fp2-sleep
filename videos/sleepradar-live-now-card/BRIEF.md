---
schema_version: 1
workflow: motion-graphics
flow: automation
storyboard: false
message: "Three current SleepRadar signals resolve into one honest Live Now card"
destination: vertical-social
aspect: "720x1280"
language: en
audience: "Aqara FP2 owners who use Home Assistant"
length: "6s"
angle: live-state-proof
narration: false
claim: "The shipped SleepRadar card turns sleep stage, heart rate, and breathing into one honest current-state readout."
opening_state: "The bed is empty, the card says Out of bed, and retained vitals are hidden behind dashes."
payoff_state: "The same card shows the public Light sleep, 56 bpm, and 13 br/min fixture with measured-versus-estimated language attached."
motion_verb: resolve
uncertainty: "Whether the dense real-card truth copy remains readable at phone-feed scale."
truth:
  source_refs:
    - "README.md:33-50"
    - "README.md:232-247"
    - "card/sleepradar-card.js:1-23"
    - "card/sleepradar-card.js:106-156"
    - "tests/sleepradar-card.test.js:78-108"
  checked_at: "2026-07-21"
  baseline_commit: "995f81b402cbd15ed0500a6968a96d94c427933e"
  release_tag: "v1.2.1"
  qualifiers:
    - "Heart rate and breathing are measured; sleep stage is the device's best estimate."
    - "Retained vitals are hidden while the bed is empty."
  visible_required:
    - "Three signals."
    - "One honest live card."
    - "Out of bed"
    - "not measuring"
    - "Light sleep"
    - "56"
    - "bpm"
    - "13"
    - "br/min"
    - "best guess"
  visible_forbidden:
    - "Body movement"
    - "Illuminance"
---

## Intent

Create GIF 2 in the five-part SleepRadar batch. Open on the shipped card's
honest empty-bed state, then resolve the same three consumed sensors into the
canonical public live fixture. The locked hook is:

> Three signals.<br>
> One honest live card.

## Locked product truth

Truth was reconfirmed on 2026-07-21 against `origin/main` at
`995f81b402cbd15ed0500a6968a96d94c427933e`. The latest release remains
`v1.2.1`, published 2026-07-03 (tag commit
`4f74afab5eccb0693dd0d0b536623ed432b9458d`). These are separate repository
and release facts; this brief does not imply the tag points at `origin/main`.

- `../../README.md:29-38` identifies the shipped card, limits it to sleep
  stage, heart rate, and breathing, and distinguishes measured vitals from the
  estimated stage.
- `../../README.md:224-241` maps code `0` to Out of bed and code `4` to Light
  sleep, then repeats the measured-versus-estimated contract.
- `../../assets/now-live.png` is the canonical public fixture: READING NOW,
  Light sleep, 56 bpm, 13 br/min, and the visible best-guess qualifier.
- `../../card/sleepradar-card.js:1-23` names the only three entities consumed by
  the card.
- `../../card/sleepradar-card.js:106-156` defines Paused out of bed, hides
  retained vitals while the bed is empty, and states the live truth note.
- `../../card/sleepradar-card.js:267-335` implements the card hierarchy, dashes
  for hidden values, the neutral not-measuring badge, and live-value gating.
- `../../tests/sleepradar-card.test.js:78-108` guards both sides: out-of-bed
  dashes must not expose retained readings, while fresh in-bed values render as
  Live now.

## Visual and motion contract

- Reuse the approved pilot shell: `720x1280`, six seconds, silent, Inter,
  `#101112` background, two-line frame-zero hook, one 608px solid card surface,
  thin `#2b2d31` border, and calm transform/opacity motion.
- Frame zero shows Out of bed, a neutral `not measuring` badge, and dashes for
  both vitals. Every unavailable value remains visibly Paused out of bed.
- Motion starts exactly at `0.8s`. The live header, stage, vitals, and truth note
  settle in reading order and are complete by `3.0s`.
- Hold the complete payoff through `5.25s`, reverse the exact state sequence
  through `5.9s`, and hold the exact CSS opening state through `6.0s`.
- The live stage always keeps “the sensor's best guess” visibly attached.
  The footer keeps measured vitals and estimated stage explicit in text.

## Truth guards

- Show only the card's three consumed sensors.
- Never show a retained numeric vital in the empty-bed state.
- The values `56 bpm` and `13 br/min` are the public repository fixture, not
  personal telemetry.
- No diagnosis, precision, safety, timeline, session-summary, or future-product
  implication.

## Delivery boundary

This project is self-contained source for a later checked render. Inter Variable
and GSAP 3.14.2 are pinned as local project assets, so checks and renders do not
depend on external font or script requests. This first pass does not publish,
deploy, commit, alter Home Assistant, or claim final binary verification.
