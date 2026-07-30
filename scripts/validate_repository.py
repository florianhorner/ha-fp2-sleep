#!/usr/bin/env python3
"""Validate the public SleepRadar package."""

from __future__ import annotations

import copy
import importlib.util
import json
import re
import subprocess
import sys
import types
import xml.etree.ElementTree as ET
from pathlib import Path, PurePosixPath

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


def workflow_jobs() -> dict:
    path = ROOT / ".github/workflows/ci.yml"
    with path.open(encoding="utf-8") as handle:
        workflow = yaml.safe_load(handle)
    if not isinstance(workflow, dict):
        fail(".github/workflows/ci.yml must parse as a YAML mapping")

    if workflow.get("permissions") != {"contents": "read"}:
        fail(".github/workflows/ci.yml must set permissions: contents: read")

    jobs = workflow.get("jobs")
    if not isinstance(jobs, dict):
        fail(".github/workflows/ci.yml must define jobs")
    for name in ["validate", "security", "docker-build"]:
        if name not in jobs:
            fail(f".github/workflows/ci.yml must define jobs.{name}")
        if not isinstance(jobs[name], dict):
            fail(f".github/workflows/ci.yml jobs.{name} must be a mapping")
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


def validate_workflow() -> None:
    jobs = workflow_jobs()
    validate_steps = job_steps(jobs, "validate")
    security_steps = job_steps(jobs, "security")
    docker_steps = job_steps(jobs, "docker-build")
    all_steps = validate_steps + security_steps + docker_steps

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

    whitespace_run = step_run(validate_steps, "Check whitespace")
    for required in ["BASE_SHA", "HEAD_SHA", "git diff --check"]:
        if required not in whitespace_run:
            fail(
                ".github/workflows/ci.yml Check whitespace step must compare "
                f"the checked-out branch with git diff --check using {required}"
            )
    require_run_pattern(
        validate_steps,
        "Check Python syntax",
        (
            r"\bpython3?\s+-m\s+py_compile\s+"
            r"aqara_fp2_sleep/aqara_fp2_sleep_poller\.py\s+"
            r"scripts/validate_repository\.py\s+"
            r"videos/quiet_proof_loops\.py\s+"
            r"videos/validate-gif-batch\.py\s+"
            r"videos/build-gif-deliverables\.py\b"
        ),
        "compile-check the Python and GIF workflow entrypoints",
    )
    require_run_pattern(
        validate_steps,
        "Lint YAML",
        r"\byamllint\s+-c\s+\.yamllint\s+\.",
        "lint YAML with the repo config",
    )
    require_run_pattern(
        validate_steps,
        "Validate add-on package",
        r"\bpython3?\s+scripts/validate_repository\.py\b",
        "run the repository validator",
    )
    require_run_pattern(
        validate_steps,
        "Validator drift self-test",
        r"\bpython3?\s+scripts/validate_repository\.py\s+--self-test\b",
        "run the repository validator self-test",
    )
    require_run_pattern(
        validate_steps,
        "Validate GIF sources",
        r"\A\s*python3?\s+videos/validate-gif-batch\.py\s*\Z",
        "validate the tracked GIF sources without rendering",
    )
    require_run_pattern(
        validate_steps,
        "GIF validator drift self-test",
        r"\A\s*python3?\s+videos/validate-gif-batch\.py\s+--self-test\s*\Z",
        "run the GIF source validator self-test",
    )
    require_run_pattern(
        validate_steps,
        "GIF builder guard self-test",
        r"\A\s*python3?\s+videos/build-gif-deliverables\.py\s+--self-test\s*\Z",
        "run the non-rendering GIF builder guard self-test",
    )
    require_run_pattern(
        validate_steps,
        "Check tracked published baseline",
        (
            r"\A\s*python3?\s+videos/validate-gif-batch\.py\s+"
            r"--check-baseline\s+"
            r"videos/gif-batch-baseline-sha256\.json\s*\Z"
        ),
        "check the tracked published binaries against the SHA-256 baseline",
    )
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
        validate_steps,
        "Test SleepRadar card",
        r"\bnode\s+tests/sleepradar-card\.test\.js\b",
        "run the SleepRadar card test",
    )
    require_run_pattern(
        validate_steps,
        "Check run script syntax",
        r"\bbash\s+-n\s+aqara_fp2_sleep/run\.sh\b",
        "check the add-on run script syntax",
    )
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

    scan_run = step_run(security_steps, "Scan current tree for secrets")
    if "gitleaks dir --no-banner --redact --verbose ." not in scan_run:
        fail(".github/workflows/ci.yml must scan the current worktree with Gitleaks")


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
        fail(
            f"{rel}: matched private strings: "
            + ", ".join(sorted(matches))
        )


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
                if (
                    value == OCCUPANCY_ENTITY
                    or object_id.startswith(("aqara_fp2_sleep_", "fp2_"))
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

    validate_card_default_entities(module.NODE, expected_entity_ids)
    check_recorder_entities(
        (ROOT / "examples/recorder.yaml").read_text(), expected_entity_ids
    )


def validate_card_default_entities(poller_node_id, published_entity_ids) -> None:
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
        "occupied code 0": (
            'if (occupancyConfirmed && code === 0) return "In bed";'
        ),
        "occupied codes 1/2": 'return "In bed — stage unknown";',
        "direct self-reference rejection": (
            "if (Object.values(this._entityIds).includes(entity))"
        ),
    }
    missing = [
        label for label, fragment in gated_contract.items() if fragment not in text
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
    expected = dict(LEGACY_UNGATED_PHASES)
    expected.update(
        {
            0: "In bed; not measuring",
            1: "In bed — stage unknown",
            2: "In bed — stage unknown",
            3: "REM sleep",
        }
    )
    parsed = {}
    for line in section.group(1).splitlines():
        if not line.strip().startswith("|"):
            continue
        cells = [c.strip() for c in line.strip().strip("|").split("|")]
        code_match = re.fullmatch(r"`(\d+)`", cells[0]) if cells else None
        if not code_match:
            continue
        parsed[int(code_match.group(1))] = cells[-1]
    if parsed != expected:
        fail(
            "README.md gated Sleep State Codes column drifted from "
            f"published behavior: {parsed}"
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
        if (
            normalize_template(availability)
            != EXPECTED_SLEEP_TEMPLATE_AVAILABILITY
        ):
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
        fail(
            "examples/dashboard-sleep.yaml must contain exactly one `Now` section"
        )
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


def check_recorder_entities(text: str, expected_entity_ids) -> None:
    data = yaml.safe_load(text) or {}
    entities = set((data.get("include") or {}).get("entities") or [])
    if entities != set(expected_entity_ids):
        fail(
            "examples/recorder.yaml include list drifted from the published "
            f"entities. expected {sorted(expected_entity_ids)}, got {sorted(entities)}"
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

    if not any(
        event[0] == "log"
        and event[1] == "fatal"
        and "Aqara login failed at startup" in event[2]
        for event in events
    ):
        fail("startup login failure did not log the fatal startup hint")
    if not any(event[0] == "res_query" for event in events):
        fail("startup login failure did not fall through to the retry poll loop")


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

    card = (ROOT / "card/sleepradar-card.js").read_text()
    readme = (ROOT / "README.md").read_text()
    tracking = (ROOT / "examples/sleep_tracking.yaml").read_text()
    dashboard = (ROOT / "examples/dashboard-sleep.yaml").read_text()
    automations = (ROOT / "examples/automations.yaml").read_text()
    examples_readme = (ROOT / "examples/README.md").read_text()
    recorder = (ROOT / "examples/recorder.yaml").read_text()
    ghost_vitals_fixture = (ROOT / GHOST_VITALS_FIXTURE).read_text()
    run_script = (ROOT / "aqara_fp2_sleep/run.sh").read_text()
    addon_config = yaml.safe_load((ROOT / "aqara_fp2_sleep/config.yaml").read_text())
    favicon_source = (ROOT / FAVICON_SOURCE).read_bytes()
    favicon = (ROOT / FAVICON_PATH).read_bytes()
    entity_ids = {f"sensor.{oid}" for oid in EXPECTED_OBJECT_IDS}
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
    expect_pass("card real", lambda: check_card_phase_semantics(card))
    expect_pass("readme real", lambda: check_readme_phase_table(readme))
    expect_pass("sleep_tracking real", lambda: check_sleep_tracking_maps(tracking))
    expect_pass("dashboard real", lambda: check_dashboard_maps(dashboard))
    expect_pass("automations real", lambda: check_automation_gates(automations))
    expect_pass(
        "examples readme real",
        lambda: check_examples_readme_gate_contract(examples_readme),
    )
    expect_pass("recorder real", lambda: check_recorder_entities(recorder, entity_ids))
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
        "readme label",
        lambda: check_readme_phase_table(
            mutate(
                readme,
                "| `3` | REM sleep | REM sleep |",
                "| `3` | REM sleep | Light sleep |",
            )
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
                "{{ occupancy in ['on', 'off']\n"
                "           and (occupancy == 'off'",
                "{{ occupancy in ['on', 'off']\n"
                "           or (occupancy == 'off'",
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
        "recorder entity",
        lambda: check_recorder_entities(
            mutate(
                recorder,
                "sensor.aqara_fp2_sleep_heart_rate",
                "sensor.aqara_fp2_sleep_pulse",
            ),
            entity_ids,
        ),
    )

    if failures:
        print("VALIDATOR SELF-TEST FAILED:")
        for line in failures:
            print(f"  - {line}")
        sys.exit(1)
    print("SleepRadar validator self-test OK")


def main() -> None:
    if "--self-test" in sys.argv:
        run_self_test()
        return
    validate_requirements()
    validate_dockerfile()
    validate_workflow()
    validate_tracked_paths()
    validate_yaml()
    validate_favicon()
    validate_addon_config()
    validate_run_script()
    validate_examples()
    validate_discovery_payloads()
    validate_phase_semantics()
    validate_ghost_vitals_evidence()
    scan_private_strings()
    print("SleepRadar package validation OK")


if __name__ == "__main__":
    main()
