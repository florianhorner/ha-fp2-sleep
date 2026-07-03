# Contributing

This project is intentionally small. The goal is to make Aqara FP2 sleep data
available in Home Assistant with the least moving parts possible.

## Good Contributions

- Clear bug reports with redacted logs.
- Fixes for add-on install or startup problems.
- Documentation improvements that make setup easier.
- Region-specific notes that are tested with a real account.

## Keep Out Of Scope

- Auto-posting, marketing automation, or unrelated launch tooling.
- Replacing this add-on with a full custom integration.
- Adding dashboards that require private entity IDs.
- Large rewrites without a concrete user-facing failure.

## Privacy Rules

Do not commit:

- Aqara account credentials
- Home Assistant tokens
- `.env` files
- real `subject_id` values
- private Home Assistant URLs
- screenshots with private dashboard state

Run the validator before opening a PR:

```bash
python3 scripts/validate_repository.py
node tests/sleepradar-card.test.js
```
