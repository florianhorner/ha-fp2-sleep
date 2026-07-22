# Quiet Proof Loops — production playbook

This is the evergreen workflow for authoring, validating, rendering, and
handing off a Quiet Proof Loop. `frame.md` owns shared tokens, the style guide
owns creative direction, and each episode `BRIEF.md` owns product truth.

## 1. Establish the truth surface

Refresh the repository baseline and latest release before writing the hook.
Record the checked date, commit, release, and repository-root-relative source
references in the brief. Separate measured, estimated, unavailable, retained,
optional, and future behavior. A source reference is evidence; it never
silently changes the episode claim.

Managed episodes fail validation when a cited line does not exist, the
baseline commit is fabricated or unrelated to `HEAD`, a named release tag does
not exist, or the cited evidence has changed since that commit. Re-check the
claim and deliberately refresh the brief instead of moving line numbers until
CI passes.

Stop if the proposed payoff is not shipped, if a qualifier cannot stay visible,
or if the source and product voice disagree.

## 2. Lock the episode brief

Copy `_template/` and answer the seven questions encoded by the closed brief
schema. Choose one motion verb. Write one frame-zero hook and one visible
payoff. Name the highest uncertainty so review can target a real risk.

Run source validation before composition work:

```bash
python3 videos/validate-gif-batch.py --project <episode-slug>
```

## 3. Author deterministic source

Project shared values from the selected frame profile into the shot plan,
composition data attributes, CSS tokens, and motion assertions. Use one paused,
seek-safe HyperFrames timeline registered under the exact composition ID.
Pre-author state in the DOM. Use literal data only, no runtime clock, random
source, network fetch, timer, CSS animation, or infinite timeline.

Make causal motion finish by the profile payoff marker. Preserve a quiet hold,
reverse to the authored opening state, and hold the seam. Keep local fonts,
scripts, marks, and licenses in the asset manifest with SHA-256 digests.

## 4. Check before rendering

From the episode directory, run the project-pinned HyperFrames checks. Inspect
the opening, motion start, mid-reveal, payoff, hold, and return frames.

```bash
npm run check
npx --yes hyperframes@<pinned-version> snapshot . --time 0,0.8,1.8,3,4.5,5.9
```

Require zero runtime, layout, motion, and contrast errors. A source snapshot is
for composition review; it is not proof of the delivered binary.

## 5. Render and derive delivery artifacts

Render only the selected episode, then let the verifier derive the GIF and
binary proof from that MP4:

```bash
python3 videos/build-gif-deliverables.py --project <episode-slug>
```

The verifier checks resolution, frame rate, frame count, duration, silence,
GIF budget, SHA-256 digests, decoded GIF endpoint identity, and MP4 endpoint
SSIM. It writes selected binary-derived frames, contact sheets,
`verification.json`, `SHA256SUMS`, and the project verification receipt.

The GIF target is a target, not permission to hide unreadable copy. The hard
ceiling is a stop. Any target exception requires an explicit human `GO` in the
verification receipt, bound to the exact `Decision GIF SHA-256`, plus a written
account of the rejected simplification. A changed render invalidates the prior
approval automatically.

## 6. Publish only approved delivery binaries

Git owns reproducible source. Episode `renders/` and `snapshots/` are generated
and ignored. After approval, copy only the final GIF and MP4 to
`assets/feature-gifs/`. The baseline manifest guards previously approved
binaries. Refresh it deliberately after adding an approved pair, review the
digest diff, then check it:

```bash
python3 videos/validate-gif-batch.py \
  --write-baseline videos/gif-batch-baseline-sha256.json --replace
python3 videos/validate-gif-batch.py \
  --check-baseline videos/gif-batch-baseline-sha256.json
```

Never rerender existing episodes merely to validate a contract migration.

## 7. Make the handoff decision-ready

Serve the repository over the allocated Conductor port and verify HTTP 200 for
the GIF, MP4, binary-derived proof sheets, verification receipt, JSON evidence,
and checksum file. The handoff states the claim, the beat sheet, the episode's
place in the series, dimensions and budget, exact loop result, hashes, highest
uncertainty, and changed versus intentionally unchanged dimensions.

End with one decision: `GO` or
`REDO <HOOK|READABILITY|ACCURACY|LOOP>`. Do not call a local source edit
published or live.

## Portability boundary

To adopt the system elsewhere, copy `_template/`, use a project-owned
`frame.md`, and populate an adapter plus asset manifest. Keep product claims in
episode briefs and product sources. Extract a standalone package only after a
second real product proves which profile fields remain stable.
