#!/usr/bin/env python3
"""Validate the public SleepRadar package."""

from __future__ import annotations

import importlib.util
import json
import types
from pathlib import Path
import re
import sys

import yaml

ROOT = Path(__file__).resolve().parents[1]

CANONICAL_PHASES = {
    0: "Out of bed",
    1: "Awake",
    2: "Awake",
    3: "REM",
    4: "Light sleep",
    5: "Deep sleep",
}
IN_BED_CODES = frozenset({1, 2, 3, 4, 5})
ASLEEP_CODES = frozenset({3, 4, 5})
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
SETUP_PYTHON_ACTION = (
    "actions/setup-python@ece7cb06caefa5fff74198d8649806c4678c61a1"
)
PYTHON_VERSION = "3.12"
PIP_AUDIT_VERSION = "2.10.1"
GITLEAKS_VERSION = "8.30.0"
GITLEAKS_LINUX_X64_SHA256 = (
    "79a3ab579b53f71efd634f3aaf7e04a0fa0cf206b7ed434638d1547a2470a66e"
)
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
    ".gitignore",
    ".Dockerfile",
}

SKIP_DIRS = {".git", "__pycache__", ".pytest_cache", ".ruff_cache", ".venv", ".context"}


def fail(message: str) -> None:
    raise ValidationError(message)


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


def workflow_steps() -> list[dict]:
    path = ROOT / ".github/workflows/ci.yml"
    with path.open(encoding="utf-8") as handle:
        workflow = yaml.safe_load(handle)
    if not isinstance(workflow, dict):
        fail(".github/workflows/ci.yml must parse as a YAML mapping")

    if workflow.get("permissions") != {"contents": "read"}:
        fail(".github/workflows/ci.yml must set permissions: contents: read")

    jobs = workflow.get("jobs")
    if not isinstance(jobs, dict) or "validate" not in jobs:
        fail(".github/workflows/ci.yml must define jobs.validate")
    validate_job = jobs["validate"]
    if not isinstance(validate_job, dict):
        fail(".github/workflows/ci.yml jobs.validate must be a mapping")
    steps = validate_job.get("steps")
    if not isinstance(steps, list):
        fail(".github/workflows/ci.yml jobs.validate.steps must be a list")
    for step in steps:
        if not isinstance(step, dict):
            fail(".github/workflows/ci.yml steps must be mappings")
    return steps


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


def require_run_pattern(steps: list[dict], name: str, pattern: str, description: str) -> None:
    if not re.search(pattern, step_run(steps, name), re.MULTILINE):
        fail(f".github/workflows/ci.yml step {name!r} must {description}")


def validate_workflow() -> None:
    steps = workflow_steps()
    uses = [step.get("uses") for step in steps if "uses" in step]
    if CHECKOUT_ACTION not in uses:
        fail(".github/workflows/ci.yml must use the SHA-pinned checkout action")
    if SETUP_PYTHON_ACTION not in uses:
        fail(".github/workflows/ci.yml must use the SHA-pinned setup-python action")
    for action in uses:
        if not isinstance(action, str) or not SHA_PINNED_ACTION.match(action):
            fail(f".github/workflows/ci.yml action is not SHA-pinned: {action}")

    setup_step = next(step for step in steps if step.get("uses") == SETUP_PYTHON_ACTION)
    if setup_step.get("with", {}).get("python-version") != PYTHON_VERSION:
        fail(
            ".github/workflows/ci.yml setup-python must use "
            f"Python {PYTHON_VERSION}"
        )

    install_run = step_run(steps, "Install dependencies")
    if not re.search(r"\bpython3?\s+-m\s+pip\s+install\s+-r\s+requirements-ci\.txt\b", install_run):
        fail(".github/workflows/ci.yml must install requirements-ci.txt")

    require_run_pattern(
        steps,
        "Lint YAML",
        r"\byamllint\s+-c\s+\.yamllint\s+\.",
        "lint YAML with the repo config",
    )
    require_run_pattern(
        steps,
        "Validate add-on package",
        r"\bpython3?\s+scripts/validate_repository\.py\b",
        "run the repository validator",
    )
    require_run_pattern(
        steps,
        "Test SleepRadar card",
        r"\bnode\s+tests/sleepradar-card\.test\.js\b",
        "run the SleepRadar card test",
    )
    require_run_pattern(
        steps,
        "Check run script syntax",
        r"\bbash\s+-n\s+aqara_fp2_sleep/run\.sh\b",
        "check the add-on run script syntax",
    )
    require_run_pattern(
        steps,
        "Build add-on image",
        r"\bdocker\s+build\s+--build-arg\s+BUILD_VERSION=ci\s+aqara_fp2_sleep\b",
        "build the add-on image with the add-on directory as context",
    )

    audit_run = step_run(steps, "Audit runtime Python dependencies")
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

    gitleaks_step = step_by_name(steps, "Install Gitleaks")
    env = gitleaks_step.get("env")
    if not isinstance(env, dict):
        fail(".github/workflows/ci.yml Install Gitleaks step must define env")
    if env.get("GITLEAKS_VERSION") != GITLEAKS_VERSION:
        fail(f".github/workflows/ci.yml must install Gitleaks {GITLEAKS_VERSION}")
    if env.get("GITLEAKS_SHA256") != GITLEAKS_LINUX_X64_SHA256:
        fail(".github/workflows/ci.yml has the wrong Gitleaks Linux x64 SHA256")
    install_gitleaks_run = step_run(steps, "Install Gitleaks")
    if (
        "sha256sum -c -" not in install_gitleaks_run
        or "gitleaks version" not in install_gitleaks_run
    ):
        fail(".github/workflows/ci.yml must verify and print the Gitleaks binary")

    self_test_run = step_run(steps, "Self-test secret scanner")
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

    scan_run = step_run(steps, "Scan current tree for secrets")
    if "gitleaks dir --no-banner --redact --verbose ." not in scan_run:
        fail(".github/workflows/ci.yml must scan the current worktree with Gitleaks")


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


def scan_private_strings() -> None:
    errors = []
    for path in ROOT.rglob(".env"):
        errors.append(
            f"{path.relative_to(ROOT)}: environment file must not be included"
        )
    for path in iter_text_files():
        rel = path.relative_to(ROOT)
        text = path.read_text(encoding="utf-8")
        for label, pattern in PRIVATE_PATTERNS.items():
            if pattern.search(text):
                errors.append(f"{rel}: matched {label}")
    if errors:
        fail("privacy scan failed:\n" + "\n".join(f"  - {err}" for err in errors))


def validate_yaml() -> None:
    for rel in [
        "repository.yaml",
        "aqara_fp2_sleep/config.yaml",
        "examples/sleep_tracking.yaml",
        "examples/dashboard-sleep.yaml",
        "examples/recorder.yaml",
    ]:
        path = ROOT / rel
        with path.open() as handle:
            yaml.safe_load(handle)


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
    expected_cooldown = 'export STARTUP_FAILURE_COOLDOWN="${STARTUP_FAILURE_COOLDOWN:-30}"'
    if expected_cooldown not in text:
        fail(
            "aqara_fp2_sleep/run.sh must export STARTUP_FAILURE_COOLDOWN with "
            "the canonical 30s default for Python"
        )
    if (
        "startup_failure()" not in text
        or "sleep \"${STARTUP_FAILURE_COOLDOWN}\" &" not in text
    ):
        fail("aqara_fp2_sleep/run.sh is missing the interruptible startup_failure helper")
    if "trap 'kill \"${sleep_pid}\"" not in text:
        fail("aqara_fp2_sleep/run.sh startup_failure sleep must be interruptible")
    for message in [
        "No MQTT service available",
        "aqara_username and aqara_password are required.",
        "subject_id is required.",
    ]:
        if f"startup_failure \"{message}" not in text:
            fail(f"aqara_fp2_sleep/run.sh does not slow-exit for: {message}")


def validate_examples() -> None:
    examples = list((ROOT / "examples").glob("*.yaml"))
    if not examples:
        fail("no example YAML files found")
    # recorder.yaml and sleep_tracking.yaml are pre-wired to the add-on's own
    # default entity IDs on purpose and intentionally contain no PLACEHOLDER_
    # tokens. The privacy-relevant check is the allowlist regex below, not
    # this one — it just used to also gate on "looks templated".
    fully_wired = {"recorder.yaml", "sleep_tracking.yaml"}
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
    foreign_entity = re.compile(
        rf"\b(?:{entity_domains})\.(?!aqara_fp2_sleep_|fp2_)[a-z0-9_]+"
    )
    service_line = re.compile(r"^\s*(?:-\s*)?(?:service|action):")
    for path in examples:
        text = path.read_text()
        if path.name not in fully_wired and "PLACEHOLDER_" not in text:
            fail(f"{path.relative_to(ROOT)} must use PLACEHOLDER_* entity IDs")
        for line in text.splitlines():
            if service_line.match(line):
                continue
            if foreign_entity.search(line):
                fail(
                    f"{path.relative_to(ROOT)} contains a non-placeholder "
                    f"entity id: {line.strip()}"
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


def check_card_phase_semantics(text: str) -> None:
    block = re.search(r"const PHASES\s*=\s*\{(.*?)\}", text, re.DOTALL)
    if not block:
        fail("card/sleepradar-card.js: could not find the PHASES map")
    phases = _code_label_pairs(block.group(1))
    if phases != CANONICAL_PHASES:
        fail(f"card/sleepradar-card.js PHASES drifted from canonical: {phases}")

    in_bed = re.search(r"IN_BED_SLEEP_CODES\s*=\s*new Set\(\[([^\]]*)\]\)", text)
    if not in_bed:
        fail("card/sleepradar-card.js: could not find IN_BED_SLEEP_CODES")
    if set(_int_list(in_bed.group(1))) != set(IN_BED_CODES):
        fail(
            "card/sleepradar-card.js IN_BED_SLEEP_CODES drifted: "
            f"{sorted(_int_list(in_bed.group(1)))}"
        )


def check_readme_phase_table(text: str) -> None:
    section = re.search(r"## Sleep State Codes(.*?)(?:\n## |\Z)", text, re.DOTALL)
    if not section:
        fail("README.md: could not find the '## Sleep State Codes' section")
    expected = dict(CANONICAL_PHASES)
    expected.update(
        {
            2: "Awake (alternate code, treated identically to `1`)",
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
        fail(f"README.md Sleep State Codes table drifted from canonical: {parsed}")


def check_sleep_tracking_maps(text: str) -> None:
    phases_block = re.search(r"phases\s*=\s*\{(.*?)\}", text, re.DOTALL)
    if not phases_block:
        fail("examples/sleep_tracking.yaml: could not find the `phases` map")
    phases = _code_label_pairs(phases_block.group(1))
    if phases != CANONICAL_PHASES:
        fail(f"examples/sleep_tracking.yaml `phases` map drifted: {phases}")

    names_block = re.search(r"names\s*=\s*\{(.*?)\}", text, re.DOTALL)
    if not names_block:
        fail("examples/sleep_tracking.yaml: could not find the `names` map")
    names = _code_label_pairs(names_block.group(1))
    if set(names) != set(CANONICAL_PHASES):
        fail(
            "examples/sleep_tracking.yaml `names` map has the wrong code set: "
            f"{sorted(names)}"
        )
    for code, label in names.items():
        if code in (1, 2):
            if not label.startswith("Awake"):
                fail(
                    f"examples/sleep_tracking.yaml `names`[{code}] must start "
                    f"with 'Awake': {label!r}"
                )
        elif label != CANONICAL_PHASES[code]:
            fail(f"examples/sleep_tracking.yaml `names`[{code}] drifted: {label!r}")

    lists = [set(_int_list(m)) for m in re.findall(r"code in \[([\d,\s]+)\]", text)]
    if set(IN_BED_CODES) not in lists:
        fail(
            "examples/sleep_tracking.yaml is missing the in-bed code list "
            f"{sorted(IN_BED_CODES)}; found {[sorted(s) for s in lists]}"
        )
    if set(ASLEEP_CODES) not in lists:
        fail(
            "examples/sleep_tracking.yaml is missing the asleep code list "
            f"{sorted(ASLEEP_CODES)}; found {[sorted(s) for s in lists]}"
        )


def check_dashboard_maps(text: str) -> None:
    icons = re.search(r"icons\s*=\s*\{(.*?)\}", text, re.DOTALL)
    if not icons:
        fail("examples/dashboard-sleep.yaml: could not find the `icons` map")
    labels = set(re.findall(r"'([^']+)'\s*:\s*'mdi:", icons.group(1)))
    unknown = labels - set(CANONICAL_PHASES.values())
    if unknown:
        fail(
            "examples/dashboard-sleep.yaml icon map has non-canonical phase "
            f"labels: {sorted(unknown)}"
        )

    apex = re.search(r"const phases\s*=\s*\{([^}]*)\}", text)
    if not apex:
        fail("examples/dashboard-sleep.yaml: could not find the ApexCharts phases map")
    apex_map = _code_label_pairs(apex.group(1))
    if not apex_map or not set(apex_map).issubset({2, 3, 4, 5}):
        fail(
            "examples/dashboard-sleep.yaml ApexCharts map has unexpected codes: "
            f"{sorted(apex_map)}"
        )
    for code, label in apex_map.items():
        if not CANONICAL_PHASES[code].startswith(label):
            fail(
                f"examples/dashboard-sleep.yaml ApexCharts label for code {code} "
                f"({label!r}) is not a prefix of canonical {CANONICAL_PHASES[code]!r}"
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
    recorder = (ROOT / "examples/recorder.yaml").read_text()
    run_script = (ROOT / "aqara_fp2_sleep/run.sh").read_text()
    addon_config = yaml.safe_load((ROOT / "aqara_fp2_sleep/config.yaml").read_text())
    entity_ids = {f"sensor.{oid}" for oid in EXPECTED_OBJECT_IDS}

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
    expect_pass("recorder real", lambda: check_recorder_entities(recorder, entity_ids))

    def mutate(text, old, new):
        if old not in text:
            failures.append(f"self-test anchor not found: {old!r}")
        return text.replace(old, new)

    expect_fail(
        "addon config boolean watchdog",
        lambda: validate_addon_config(dict(addon_config, watchdog=True)),
    )
    expect_fail(
        "addon config non-URL watchdog",
        lambda: validate_addon_config(dict(addon_config, watchdog="true")),
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
                'trap \'kill "${sleep_pid}" 2>/dev/null\' TERM INT',
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
        "readme label",
        lambda: check_readme_phase_table(
            mutate(readme, "| `3` | REM sleep |", "| `3` | Light sleep |")
        ),
    )
    expect_fail(
        "sleep_tracking phases label",
        lambda: check_sleep_tracking_maps(mutate(tracking, "1: 'Awake',", "1: 'Sleepy',")),
    )
    expect_fail(
        "sleep_tracking names awake-prefix",
        lambda: check_sleep_tracking_maps(
            mutate(tracking, "1: 'Awake in bed'", "1: 'Sleeping'")
        ),
    )
    expect_fail(
        "sleep_tracking asleep list",
        lambda: check_sleep_tracking_maps(
            mutate(tracking, "code in [3, 4, 5]", "code in [4, 5]")
        ),
    )
    expect_fail(
        "sleep_tracking in-bed list",
        lambda: check_sleep_tracking_maps(
            mutate(tracking, "code in [1, 2, 3, 4, 5]", "code in [2, 3, 4, 5]")
        ),
    )
    expect_fail(
        "dashboard icon label",
        lambda: check_dashboard_maps(
            mutate(dashboard, "'REM': 'mdi:brain'", "'Napping': 'mdi:brain'")
        ),
    )
    expect_fail(
        "dashboard apex label",
        lambda: check_dashboard_maps(mutate(dashboard, '4: "Light"', '4: "Napping"')),
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
    validate_yaml()
    validate_addon_config()
    validate_run_script()
    validate_examples()
    validate_discovery_payloads()
    validate_phase_semantics()
    scan_private_strings()
    print("SleepRadar package validation OK")


if __name__ == "__main__":
    main()
