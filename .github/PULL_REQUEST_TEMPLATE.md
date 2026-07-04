## What changed

Describe the user-facing issue this fixes or the documentation gap this closes.

## Scope

- [ ] This does not touch the running Home Assistant app.
- [ ] This does not add private entity IDs, credentials, tokens, or full FP2 subject IDs.
- [ ] This stays within the small SleepRadar app package scope.

## Notes

If a check was not run, explain why and what risk remains.

## Proof

- [ ] yaml: `yamllint -c .yamllint .`
- [ ] package: `python3 scripts/validate_repository.py`
- [ ] card: `node tests/sleepradar-card.test.js`
