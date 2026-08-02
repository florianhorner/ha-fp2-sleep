## What changed

Describe the user-facing issue this fixes or the documentation gap this closes.

## Scope

- [ ] This does not touch the running Home Assistant app.
- [ ] This does not add private entity IDs, credentials, tokens, or full FP2 subject IDs.
- [ ] This stays within the small SleepRadar app package scope.

## Notes

If a check was not run, explain why and what risk remains.

## Proof

- [ ] whitespace: `git diff --check`
- [ ] python compile: `python3 -m py_compile aqara_fp2_sleep/aqara_fp2_sleep_poller.py scripts/validate_repository.py videos/quiet_proof_loops.py videos/validate-gif-batch.py videos/build-gif-deliverables.py`
- [ ] yaml: `yamllint -c .yamllint .`
- [ ] package: `python3 scripts/validate_repository.py`
- [ ] validator self-test: `python3 scripts/validate_repository.py --self-test`
- [ ] validator CLI: `python3 tests/test_validate_repository_cli.py`
- [ ] GIF sources: `python3 videos/validate-gif-batch.py`
- [ ] GIF validator self-test: `python3 videos/validate-gif-batch.py --self-test`
- [ ] GIF builder self-test: `python3 videos/build-gif-deliverables.py --self-test`
- [ ] published GIF baseline: `python3 videos/validate-gif-batch.py --check-baseline videos/gif-batch-baseline-sha256.json`
- [ ] card: `node tests/sleepradar-card.test.js`
- [ ] shell: `bash -n aqara_fp2_sleep/run.sh`
- [ ] dependency audit: `pip-audit -r aqara_fp2_sleep/requirements.txt --progress-spinner off`
- [ ] secret scan: `gitleaks dir --no-banner --redact --verbose .`
- [ ] docker: `docker build --build-arg BUILD_VERSION=ci aqara_fp2_sleep`
