# SleepRadar GIF Batch Playbook

Status: pilot approved on 2026-07-17. This playbook governs GIFs 2–5.
Execution status and sequencing live in `GIF-BATCH-PLAN.md`.

This is a batch-specific historical record. For new work, the normative video
profile is `frame.md` and the evergreen procedure is
`GIF-PRODUCTION-PLAYBOOK.md`.

The goal is one complete internal production and verification pass, followed by
one focused user decision. Do not use the user review to discover claim drift,
generic hooks, stale renders, missing proof, or undefined delivery criteria.

## 1. Lock product truth before writing the hook

- Fetch and inspect current `origin/main`, then compare the claim with the
  latest released tag. Record the commit and tag in the GIF's `BRIEF.md`.
- Verify exact entity counts, names, availability, and measured-versus-estimated
  semantics in runtime source, README, and automated guards.
- Distinguish the complete product surface from a card or dashboard that shows
  only a subset. Never infer the product surface from a single presentation.
- Use no medical, diagnostic, or safety language. Automations are comfort
  features, not safety mechanisms.
- Lock the final hook before animation. It must be concrete, payoff-matched,
  readable on frame zero, and normally 3–7 words. Avoid vague constructions
  such as “More than …”. Prefer a visible before/after or same-hardware/new-value
  contrast such as the approved “Same sensor. Now 5 sleep signals.” pattern.

## 2. Reuse the approved design system

- Canvas: `720×1280`, vertical. Duration: `5–9s`; default to `6s` unless the
  feature needs more reading time. No narration or audio.
- Background `#101112`; card surface `#1b1c1e`; border `#2b2d31`; primary text
  `#e8e8ea`; muted text `#9a9da3`; radar blue `#5aa2ff`; heart red `#ff4d57`;
  estimate amber `#f5a623`; unknown gray `#747982`.
- Use Inter. Keep the approved hook treatment: at most two centered lines,
  `56px`, weight `650`, line-height `1.04`, with the value/payoff line in radar
  blue. Keep card typography, spacing, and geometry consistent with the pilot.
- Show one feature only. Motion must explain the feature rather than decorate it.
  No gradients, logo intro, random motion, persistent shimmer, or invented data.
- Default timing contract:
  - frame zero: readable hook and starting product state;
  - by `0.8s`: the transformation has begun;
  - by `3.0s`: the complete payoff is visible;
  - hold the readable payoff for at least `1.5s`;
  - reserve the final `0.75s` for the return;
  - hold the exact opening state for the final `0.10s`.
- The GIF's first and last decoded frames must be pixel-identical. The MP4's
  first/last decoded-frame SSIM must be at least `0.999000`, followed by visual
  confirmation that no state discontinuity is visible.

## 3. Use an explicit delivery budget

- GIF working target: at most `750 KiB`.
- GIF hard ceiling: `1 MiB`. If visual quality cannot survive that ceiling,
  flag the exception before review instead of silently exceeding it.
- Baseline encoding: `720×1280`, `15 fps`, 128-color global palette, infinite
  loop. Preserve the exact first frame as the final GIF frame.
- MP4 master: `720×1280`, `30 fps`, high-quality H.264. No arbitrary MP4 size
  ceiling; report the actual size.

## 4. Complete QA before handoff

1. Run `npx hyperframes check .`; require zero runtime, layout, motion, and
   contrast errors. Explain any remaining advisory warnings.
2. Render the high-quality MP4, then derive the optimized GIF from that master.
3. Extract a contact sheet directly from each delivered binary, including the
   opening, mid-reveal, full payoff, and final frame. Source snapshots alone are
   insufficient proof of a rerender.
4. Record `ffprobe` resolution, duration, frame rate, frame count, and byte size.
5. Record explicitly labelled `SHA-256 (GIF)` and `SHA-256 (MP4)` values.
6. Record the loop metric, metric name, threshold, observed value, and result.
7. Write a per-GIF `VERIFICATION.md` containing those facts and the exact scope
   of changed versus unchanged dimensions.
8. Serve renders and proof over the workspace's `CONDUCTOR_PORT`; verify every
   `http://localhost:<port>/...` link returns HTTP 200 before sending it.

## 5. Make the review handoff decision-ready

- Restate the standalone verification question and answer it with evidence.
- Name the GIF's slot in the five-GIF set, the single claim it makes, why it is
  distinct, and its inline beat sheet.
- Link the actual GIF, MP4, and binary-derived proof frames.
- Include a compact specs table, explicit SHA-256 labels, loop criteria/results,
  file-size target/result, and any delta from the prior render.
- State exactly what changed and which pacing, color, type, motion, and product
  semantics stayed locked from the approved pilot.
- Point the reviewer at the one real uncertainty, not a generic checklist.
- End with one explicit response: `GO` or a named redo dimension such as
  `HOOK`, `READABILITY`, `ACCURACY`, or `LOOP`.
- Keep global policy changes out of the video-review handoff. Propose any such
  policy change separately with its exact intended diff.

## 6. Product constraints for GIFs 2–5

- **GIF 2 — Live Now card:** the bundled card reads three of the five published
  sensors: sleep stage, heart rate, and breathing. Do not depict all five as
  card-visible. Preserve unavailable, stale, and out-of-bed honesty.
- **GIF 3 — measured heart rate and breathing:** both are measured directly by
  the sensor. Do not imply clinical accuracy, diagnosis, or continuous values
  while the bed is empty.
- **GIF 4 — sleep-stage estimates:** say “estimate”, “best guess”, or equivalent
  on-screen. Never present stage scoring as measured fact.
- **GIF 5 — sleep-aware automations:** show only shipped, supportable Home
  Assistant behavior. Frame it as comfort/convenience, never safety-critical.
