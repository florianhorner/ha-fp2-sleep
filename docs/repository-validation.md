# Repository Validation

This reference and operations guide is for SleepRadar contributors and
maintainers. It explains what the repository validator checks, how the local
Conductor run relates to CI, and how to change a gate without letting those
surfaces drift.

For setup and the exact pre-PR command sequence, start with
[Contributing](../CONTRIBUTING.md).

## Quick Reference

The validator requires Python 3.11 or newer.

| Command | Purpose | Success output |
| --- | --- | --- |
| `python3 scripts/validate_repository.py` | Validate the current repository state. Stops at the first failure. | `SleepRadar package validation OK` |
| `python3 scripts/validate_repository.py --self-test` | Exercise positive fixtures and deliberate mutations that prove validator guards still fail closed. Reports all failures together. | `SleepRadar validator self-test OK` |
| `python3 tests/test_validate_repository_cli.py` | Test normal mode, self-test mode, help, and invalid option handling. | `OK` |
| `python3 scripts/validate_repository.py --help` | Show the command-line interface without running validation. | Usage text |

`--self-test` replaces normal repository validation; it does not include it.
Run normal mode, self-test mode, and the CLI tests separately. Unknown options
and abbreviations such as `--self` exit with status 2 instead of silently
selecting a mode.

The ordered pre-PR sequence lives in
[Contributing](../CONTRIBUTING.md#local-setup). Its shared validation block is
a manually maintained mirror of the machine-readable gate list, so it is not
duplicated here.

## What the Validator Checks

`scripts/validate_repository.py` is a policy checker, not an umbrella test
runner. Normal mode covers these domains:

| Domain | Guarded contract |
| --- | --- |
| Dependencies and Dockerfile | Runtime and CI requirement files contain the exact pinned packages; the Dockerfile copies the runtime requirements before installing them and does not inline those package names. |
| CI and Conductor policy | Required CI jobs, read-only permissions, SHA-pinned actions, Python versions, named steps, command shapes, and the ordered Conductor gate chain remain intact. |
| Repository and media hygiene | The prospective commit surface excludes generated `.gstack` state, `.DS_Store`, video renders, snapshots, and verification receipts; published GIF/MP4 files stay paired and have at least one corresponding path under `videos/<stem>/` on that surface. |
| Privacy, YAML, and assets | `.env` files and known private strings are rejected, required YAML parses, and the public favicon remains byte-identical to its canonical SVG without external content. |
| App configuration and startup | Required configuration keys, blank credential defaults, schema parity, the canonical MQTT node ID, the app changelog, and interruptible startup-failure cooldown behavior remain consistent. |
| Examples | Optional YAML uses placeholders for foreign entity IDs while the intentionally pre-wired SleepRadar files keep only canonical entities. |
| MQTT discovery and card entities | The app publishes the expected five discovery entities, includes `force_update: true`, avoids local naming, and stays aligned with card defaults and Recorder examples. |
| Sleep semantics | Phase labels stay synchronized across the card, README, sleep template, and dashboard; in-bed sets align between the card and template, asleep codes remain constrained in the template, and Recorder entity IDs stay canonical. |

The validator imports the poller with local dependency stubs to inspect MQTT
payloads. It does not connect to Aqara, MQTT, or Home Assistant.

## Validation Lanes

| Lane | What it runs | What it does not prove |
| --- | --- | --- |
| Conductor shared run | The ordered shared validation chain against the current workspace. Local `git diff --check` inspects unstaged changes to tracked files. | Whitespace errors in staged-only or untracked files, dependency auditing, Gitleaks scanning, Docker image construction, a running app, or Home Assistant behavior. |
| CI `validate` | The same shared gates under Python 3.12. Its whitespace step compares the committed base-to-head range when the base commit is available. | The separate `security` and `docker-build` jobs. |
| CI `security` | Runtime dependency audit, pinned and checksum-verified Gitleaks installation, scanner controls, and a current-tree secret scan. | Git-history scanning, Docker construction, or runtime behavior. |
| CI `docker-build` | Builds the app image with `BUILD_VERSION=ci`. | Starting the image, contacting external services, or changing Home Assistant. |

A green Conductor run means the shared `validate` lane passed locally. It does
not mean the full CI pipeline passed. Likewise, the repository validator
checks that external-tool steps are defined correctly; it does not itself run
yamllint, Node, the GIF validators, `pip-audit`, Gitleaks, or Docker.

The shared `.conductor/settings.toml` file is repository configuration.
Conductor reflects changes to that shared configuration after they are merged
to the remote default branch. The validator can still inspect the version in a
feature workspace, and its run command can be executed there for pre-merge
proof.

## Sources of Truth and Synchronization

`CONDUCTOR_GATES` in `scripts/validate_repository.py` is the machine source for
the shared lane. Each entry owns the local command used by Conductor.
Non-whitespace entries also own:

- the matching CI `validate` step name;
- the purpose enforced by the validator.

CI's whitespace step is a special case because it normally checks a committed
base-to-head range instead of the local working-tree form.

The validator derives fully anchored CI command patterns from the named
entries. It requires each named runnable gate and rejects an unknown named
runnable step in the CI `validate` job. It does not currently enforce CI gate
order or unique step names, and additional `uses:` steps are allowed when
SHA-pinned. Separately, it requires Conductor to expose exactly one run command
with the same gates in the same order. Real TOML parsing prevents gate text in
comments or unrelated strings from satisfying the Conductor check.

Three human-facing mirrors are not parsed into the machine contract:

- the command sequence in [Contributing](../CONTRIBUTING.md);
- the proof checklist in the
  [pull request template](../.github/PULL_REQUEST_TEMPLATE.md);
- this reference.

Update those mirrors in the same change whenever a gate or responsibility
changes. Do not describe them as mechanically synchronized.

## Changing a Gate

1. Decide which lane owns the check.
   - Put checks needed in every shared Conductor/CI validation run in
     `CONDUCTOR_GATES`.
   - Keep dependency auditing, secret scanning, and Docker-only checks in their
     dedicated CI jobs unless they are intentionally becoming shared gates.
2. For a shared gate, update `CONDUCTOR_GATES`, its exact named CI step, and the
   single Conductor run chain together. CI step names are contract keys.
3. Update the exact command in Contributing and the pull request proof
   checklist.
4. Update this reference if the check's purpose, ownership, or failure mode
   changed.
5. Add a positive control and a mutation or CLI regression that fails when the
   invariant is broken.
6. Run normal validation, validator self-test, CLI tests, and the complete
   shared pre-PR chain.
7. Run the relevant CI-only security or Docker proof locally when the tool is
   available. Otherwise, disclose the omission in the PR proof and rely on CI
   for that lane.

## Security Checks

The repository uses several independent layers:

- The validator's privacy scan rejects `.env` files and known private URLs,
  paths, subject IDs, entity names, email addresses, and token shapes in
  authored text.
- Prospective-path validation checks tracked files plus non-ignored new files.
  Generated `.gstack/` paths must never enter that surface.
- Gitleaks keeps its default rules enabled. Repository-wide line-shape
  allowlists cover Aqara `appid` and `appkey` assignments plus constrained
  validator-test literals; these exceptions are not path-scoped. A separate
  path allowlist covers generated `.gstack/**.{log,jsonl,json}` files.
  Arbitrary `.env`, `.pem`, `.key`, and `.txt` files under `.gstack/` remain
  scannable.
- CI first proves the default scanner detects a planted `api_key`. A second
  control loads the repository config and proves that the same shape fails in
  a normal path while the named generated `.gstack` JSON file is excluded.
  These controls do not exercise the repository-wide `appid` and `appkey`
  line-shape exceptions.
- `gitleaks dir` scans the current tree, not Git history, and does not rely on
  `.gitignore`.
- `pip-audit` checks the runtime requirements only. CI installs the audit tool
  separately because it is not a project dependency.

Do not broaden a path allowlist to silence one local false positive. Narrow the
rule to the generated file shape and keep a positive detection control.

## Self-Test Design and Limits

The validator self-test uses current repository fixtures and in-memory
mutations. It verifies real inputs pass, then changes one invariant at a time
and requires `ValidationError`. It aggregates failures so one broken guard
does not hide the next.

The poller behavior test replaces MQTT, Aqara, logging, and sleep dependencies;
it makes no network call. Self-test coverage is intentionally separate from
normal validation and does not claim a mutation for every normal-mode branch.
Known lower-priority GIF-related gaps remain tracked in
[TODOs](../TODOS.md#gif-pipeline-hardening-pre-ship-review-squad-2026-07-22).

## Troubleshooting

### The validator requires Python 3.11 or newer

Check the interpreter inside the active environment:

```bash
python3 --version
```

Recreate an old venv with Python 3.11 or newer, then reinstall
`requirements-ci.txt`. CI pins Python 3.12. The shared Conductor setup tries
Python 3.12, 3.13, then 3.11.

### A Conductor gate is missing, unexpected, or out of order

Treat the first Conductor-chain error as the synchronization list. Update
`CONDUCTOR_GATES`, the named CI step, `.conductor/settings.toml`,
Contributing, and the pull request template in one change. Run the failing
command directly, then rerun the full chain. Review CI order and duplicate step
names manually because the validator does not enforce either.

### Validation reports an unexpected MQTT node or device name

The validator imports the poller, whose defaults can be changed by ambient
`MQTT_NODE_ID` and `DEVICE_NAME` variables. Clear them before validating the
repository defaults:

```bash
unset MQTT_NODE_ID DEVICE_NAME
python3 scripts/validate_repository.py
```

### A Gitleaks control prints a detected secret

Detection of the deliberately planted value is the expected positive control.
The positive-control step fails if Gitleaks does not detect that value. The
final current-tree scan must still report no leaks.

If generated `.gstack` state triggers a finding, first confirm the file is a
generated `.log`, `.jsonl`, or `.json` file. Other extensions are
intentionally scanned. Do not add a directory-wide exception.

### Conductor is green but CI fails

Check which CI lane failed. Security and Docker are outside the shared
Conductor run. If the failure is whitespace-only, remember that Conductor
checks only unstaged tracked-file changes while CI normally checks the
committed base-to-head range.

### A shared settings change is not visible in Conductor

Shared repository settings are picked up after the change reaches the remote
default branch. A feature-workspace edit is valid pre-merge input for the
validator, but it does not update the shared project configuration by itself.

## Related

- [Validator source](../scripts/validate_repository.py)
- [Contributing](../CONTRIBUTING.md)
- [CI workflow](../.github/workflows/ci.yml)
- [Conductor settings](../.conductor/settings.toml)
- [Gitleaks configuration](../.gitleaks.toml)
- [Pull request template](../.github/PULL_REQUEST_TEMPLATE.md)
- [Security policy](../SECURITY.md)
- [Quiet Proof Loops validation](../videos/README.md#validate)
