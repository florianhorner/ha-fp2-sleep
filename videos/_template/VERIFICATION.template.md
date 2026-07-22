# Final binary verification

## Claim and evidence

- **Claim:** [from BRIEF.md]
- **Binary proof:** [what the delivered frames show]
- **Highest uncertainty:** [from BRIEF.md]

## Delivered artifacts

Record codec, dimensions, duration, frame rate, frame count, byte size, and
explicitly labelled SHA-256 for the GIF and MP4.

## Budget and loop seam

Record target, hard ceiling, observed GIF size, decoded endpoint identity, GIF
SSIM, MP4 endpoint SSIM, and pass/fail status.

## Human decision

`GO` or `REDO <HOOK|READABILITY|ACCURACY|LOOP>`. A budget-exception `GO`
must remain next to the exact generated `Decision GIF SHA-256`; any new binary
requires a new decision.
