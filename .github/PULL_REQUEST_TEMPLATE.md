## What changed

Describe the user-facing issue this fixes or the documentation gap this closes.

## Scope

- [ ] This does not touch the running Home Assistant app.
- [ ] This does not add private entity IDs, credentials, tokens, or full FP2 subject IDs.
- [ ] This stays within the small SleepRadar app package scope.

## Notes

If a check was not run, explain why and what risk remains.

## Proof

- [ ] python compile: `python3 -m py_compile aqara_fp2_sleep/aqara_fp2_sleep_poller.py scripts/validate_repository.py`
- [ ] yaml: `yamllint -c .yamllint .`
- [ ] package: `python3 scripts/validate_repository.py`
- [ ] card: `node tests/sleepradar-card.test.js`
- [ ] shell: `bash -n aqara_fp2_sleep/run.sh`
- [ ] dependency audit: `pip-audit -r aqara_fp2_sleep/requirements.txt --progress-spinner off`
- [ ] secret scan: `gitleaks dir --no-banner --redact --verbose .`
- [ ] docker: `docker build --build-arg BUILD_VERSION=ci aqara_fp2_sleep`
