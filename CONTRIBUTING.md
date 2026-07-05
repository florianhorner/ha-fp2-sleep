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

Use the same Python dependency versions as CI:

```bash
python3 -m venv .venv
. .venv/bin/activate
python3 -m pip install --upgrade pip
python3 -m pip install -r requirements-ci.txt
```

Node.js is only needed for the SleepRadar Card test. There is no `npm install`
step because the test uses Node's built-in modules.

`pip-audit` is intentionally not in `requirements-ci.txt` because it is audit
tooling, not a repo dependency. CI installs `pip-audit==2.10.1` under Python
3.12. For local audit proof, install it separately with Python 3.10 or newer:

```bash
python3 -m pip install pip-audit==2.10.1
```

Run these checks before opening a PR:

```bash
python3 -m py_compile aqara_fp2_sleep/aqara_fp2_sleep_poller.py scripts/validate_repository.py
yamllint -c .yamllint .
python3 scripts/validate_repository.py
node tests/sleepradar-card.test.js
bash -n aqara_fp2_sleep/run.sh
pip-audit -r aqara_fp2_sleep/requirements.txt --progress-spinner off
gitleaks dir --no-banner --redact --verbose .
```

CI also runs a Docker build with the add-on directory as the build context:

```bash
docker build --build-arg BUILD_VERSION=ci aqara_fp2_sleep
```

If Docker or Gitleaks is not installed locally, note that in the PR proof and
rely on CI for that specific check.
