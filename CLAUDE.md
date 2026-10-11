<!-- BEGIN: commit-message-standards (managed by bootstrap-repo.sh — do not hand-edit) -->
## Commit message standards

Use Conventional Commits: `type(scope): subject`, with a subject of at most
72 characters and no trailing period. The title of a pull request opened by a
dependency bot may be longer.
For `feat` commits with >50 lines changed, add a `Why:` line to the body; this
is a convention and CI does not fail without it. CI runs
`.config/commit-lint/validate-pr.sh` on every pull request commit and on the
pull request title. Check a message before pushing with
`bash .config/commit-lint/commit-msg <message-file>`.

<!-- END: commit-message-standards -->
