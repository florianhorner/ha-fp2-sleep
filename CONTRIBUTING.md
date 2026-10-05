# Contributing

This project is intentionally small. The goal is to make Aqara FP2 sleep data
available in Home Assistant with the least moving parts possible.

## Good Contributions

- Clear bug reports with redacted logs.
- Fixes for app install or startup problems.
- Documentation improvements that make setup easier.
- Region-specific notes that are tested with a real account.

## Keep Out Of Scope

- Auto-posting, marketing automation, or unrelated launch tooling.
- Replacing this app with a full custom integration.
- Adding dashboards that require private entity IDs.
- Large rewrites without a concrete user-facing failure.

## Home Assistant UI Labels

Home Assistant renames menus and buttons between releases (Add-ons became Apps;
the install action is now "Install app"). When docs need to point at a Home
Assistant screen:

- Prefer a [My Home Assistant](https://my.home-assistant.io/) redirect link or
  badge. Home Assistant maintains the target, so it cannot go stale.
- Otherwise, link Home Assistant's own official docs for that screen.
- Only as a last resort, write the literal label, and verify it against a live
  Home Assistant instance (a screenshot or the actual UI). A summary from a web
  search or fetch is not acceptable evidence. Paraphrased UI labels are how the
  install steps went stale in the first place.

## Privacy Rules

Do not commit:

- Aqara account credentials
- Home Assistant tokens
- `.env` files
- real `subject_id` values
- private Home Assistant URLs
- screenshots with private dashboard state

## Local Setup

Use the same Python dependency versions as CI, and **Python 3.11 or newer**.
CI pins 3.12 and the add-on image is 3.13; `scripts/validate_repository.py`
parses `.conductor/settings.toml` with the stdlib `tomllib` module, which does
not exist before 3.11. On macOS, bare `python3` is often the system Python 3.9,
so name the interpreter explicitly:

```bash
python3.12 -m venv .venv    # or any python3.11+
. .venv/bin/activate
python3 -m pip install --upgrade pip
python3 -m pip install -r requirements-ci.txt
```

Conductor's `setup` script tries `python3.12`, `python3.13`, `python3.11`,
`python3.14`, then bare `python3`, so a machine that exposes a modern
interpreter under no other name still bootstraps. It checks every candidate's
version before creating the venv. If none provides Python 3.11+ with `venv`
support, setup fails before dependency installation with an actionable error.

If an existing venv still exits with the validator's version error, delete
`.venv` and recreate it with a 3.11+ interpreter.

Node.js is only needed for the SleepRadar Card test. There is no `npm install`
step because the test uses Node's built-in modules.

`pip-audit` is intentionally not in `requirements-ci.txt` because it is audit
tooling, not a repo dependency. CI installs `pip-audit==2.10.1` under Python
3.12. For local audit proof, install it separately with Python 3.10 or newer:

```bash
python3 -m pip install pip-audit==2.10.1
```

Run this shared validation block before opening a PR:

```bash
git diff --check
python3 -m py_compile aqara_fp2_sleep/aqara_fp2_sleep_poller.py scripts/validate_repository.py videos/quiet_proof_loops.py videos/validate-gif-batch.py videos/build-gif-deliverables.py
yamllint -c .yamllint .
python3 scripts/validate_repository.py
python3 scripts/validate_repository.py --self-test
python3 tests/test_validate_repository_cli.py
python3 videos/validate-gif-batch.py
python3 videos/validate-gif-batch.py --self-test
python3 videos/build-gif-deliverables.py --self-test
python3 videos/validate-gif-batch.py --check-baseline videos/gif-batch-baseline-sha256.json
node tests/sleepradar-card.test.js
bash -n aqara_fp2_sleep/run.sh
```

Run the additional security checks when their tools are available:

```bash
pip-audit -r aqara_fp2_sleep/requirements.txt --progress-spinner off
gitleaks dir --no-banner --redact --verbose .
```

Run Gitleaks **from the repository root, with `.` as the target**, and use a
version matching the `GITLEAKS_VERSION` pin in `scripts/validate_repository.py`
(CI installs it checksum-verified). `.gitleaks.toml` uses the top-level
`[[allowlists]]` array form, which older builds silently ignore rather than
reject — they drop every exception and report the public Aqara `appid`/`appkey`
constants as leaks. Scanning an absolute path instead of `.` likewise breaks
the repository-relative `.gstack/` path exclusion.

CI also runs a Docker build with the add-on directory as the build context:

```bash
docker build --build-arg BUILD_VERSION=ci aqara_fp2_sleep
```

If Docker or Gitleaks is not installed locally, note that in the PR proof and
rely on CI for that specific check.

Conductor runs the shared validation block above; its runnable gates correspond
to CI's `validate` job. Local `git diff --check` inspects only unstaged changes
to tracked files, while CI normally checks the committed base-to-head range.
Dependency auditing, Gitleaks, and the Docker build remain separate CI lanes,
so a green Conductor run is not the whole pipeline.

See the [repository validation reference](docs/repository-validation.md) for
gate ownership, synchronization rules, and troubleshooting. Changes to shared
`.conductor/settings.toml` configuration become repository-wide after they
reach the remote default branch.

<!-- BEGIN: commit-message-standards (managed by bootstrap-repo.sh — do not hand-edit) -->
## Commit messages

Use `type(scope): subject`, for example `fix(auth): reject expired sessions`.
Allowed types are `feat fix docs style refactor test chore ci build perf revert`.
Keep the subject at most 72 characters and omit a trailing period. The title of
a pull request opened by a dependency bot (Dependabot, Renovate, pre-commit.ci)
may be longer.

For `feat` commits with >50 lines changed, add a body line beginning with
`Why:` that explains the reason for the change. This is a convention; CI does
not fail without it.

CI checks every commit of a pull request and the pull request title with
`.config/commit-lint/validate-pr.sh`. To check a message before pushing, run
`bash .config/commit-lint/commit-msg <message-file>`. Both files are generated;
do not edit them by hand.

<!-- END: commit-message-standards -->
