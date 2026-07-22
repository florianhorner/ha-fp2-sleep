# Quiet Proof Loop episode template

Copy this directory to `videos/<episode-slug>/`, then:

1. Replace every `replace-me` and bracketed placeholder.
2. Answer the seven contract questions in `BRIEF.md`.
3. Copy the required local runtime assets and licenses into `assets/`.
4. Replace `assets/manifest.json` entries with real SHA-256 digests.
5. Project the selected `frame.md` values into the shot plan, composition,
   and motion assertions.
6. Keep root/composition HTML and motion files byte-identical.
7. Register the episode in `../projects.json` and run the source validator.

Do not place renders or snapshots in Git. The verifier generates
`VERIFICATION.md`; use `VERIFICATION.template.md` only as the human-facing
outline.
