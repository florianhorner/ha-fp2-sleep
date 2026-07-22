# Quiet Proof Loops in this repository

This directory contains the reproducible source system for SleepRadar feature
clips. Git owns definitions, adapters, briefs, shot plans, composition source,
fixtures, licenses, and required local runtime assets. Generated renders,
snapshots, and verification receipts stay local.

Approved delivery binaries live under `../assets/feature-gifs/`. The tracked
baseline manifest protects every complete GIF/MP4 pair there—including the
historical pilot—without requiring a render in CI.

## Start here

1. `../DESIGN.md` — product voice and semantic honesty.
2. `frame.md` — normative machine-readable video profile.
3. `GIF-STYLE-GUIDE.md` — creative decision system.
4. `GIF-PRODUCTION-PLAYBOOK.md` — truth, production, proof, and handoff.
5. `_template/` — copyable episode shell.

`projects.json` is the explicit managed-episode registry. The older
`sleepradar-more-than-presence` pilot remains historical evidence: it predates
the v1 adapter and hermetic runtime contract and is intentionally not a managed
v1 episode.

## Validate

```bash
python3 videos/validate-gif-batch.py --self-test
python3 videos/build-gif-deliverables.py --self-test
python3 videos/validate-gif-batch.py
python3 videos/validate-gif-batch.py \
  --fixture videos/fixtures/quiet-proof-loops-minimal
python3 videos/validate-gif-batch.py \
  --check-baseline videos/gif-batch-baseline-sha256.json
```

Normal CI validates source and the tracked published baseline. It does not
install HyperFrames, invoke FFmpeg, or regenerate production artifacts.

## Reuse elsewhere

Copy the template and the generic fixture, create a product-owned frame
profile, and keep each product claim in its episode brief. Do not copy the
SleepRadar palette or product language unless the adopting project actually
owns them. A standalone package is intentionally deferred until a second real
product tests the interface.
