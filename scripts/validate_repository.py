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
    print(f"ERROR: {message}")
    sys.exit(1)


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


def validate_addon_config() -> None:
    config = yaml.safe_load((ROOT / "aqara_fp2_sleep/config.yaml").read_text())
    required = {"name", "version", "slug", "description", "arch", "options", "schema"}
    missing = sorted(required - set(config))
    if missing:
        fail(f"add-on config missing required keys: {', '.join(missing)}")

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

    expected = {
        "aqara_fp2_sleep_heart_rate",
        "aqara_fp2_sleep_respiration_rate",
        "aqara_fp2_sleep_sleep_state",
        "aqara_fp2_sleep_body_movement",
        "aqara_fp2_sleep_illuminance",
    }
    if set(object_ids) != expected:
        fail(f"unexpected discovery object ids: {sorted(object_ids)}")
    expected_entity_ids = {f"sensor.{oid}" for oid in expected}
    if set(default_entity_ids) != expected_entity_ids:
        fail(f"unexpected discovery default_entity_ids: {sorted(default_entity_ids)}")

    validate_card_default_entities(module.NODE, expected_entity_ids)


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


def main() -> None:
    validate_requirements()
    validate_dockerfile()
    validate_workflow()
    validate_yaml()
    validate_addon_config()
    validate_examples()
    validate_discovery_payloads()
    scan_private_strings()
    print("SleepRadar package validation OK")


if __name__ == "__main__":
    main()
