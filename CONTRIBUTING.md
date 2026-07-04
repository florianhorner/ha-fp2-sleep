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
python3 -m pip install pyyaml==6.0.2 yamllint==1.35.1 paho-mqtt pycryptodome
```

Node.js is only needed for the SleepRadar Card test. There is no `npm install`
step because the test uses Node's built-in modules.

Run these checks before opening a PR:

```bash
yamllint -c .yamllint .
python3 scripts/validate_repository.py
node tests/sleepradar-card.test.js
```
