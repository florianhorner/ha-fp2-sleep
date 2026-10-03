#!/usr/bin/env python3
"""Create a usable SleepRadar workspace venv without mixing Python versions.

This bootstrap intentionally runs with the macOS system Python 3.9. The project
venv and repository validator require Python 3.11 or newer.
"""

import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile


CANDIDATES = ("python3.12", "python3.13", "python3.11", "python3.14", "python3")
HEALTH_CODE = (
    "import encodings, json, pip, sys, tomllib; "
    "print(json.dumps({'version': sys.version_info[:2], "
    "'prefix': sys.prefix, 'base_prefix': sys.base_prefix}))"
)


class SetupError(Exception):
    pass


def capture(*command):
    return subprocess.run(command, text=True, capture_output=True, check=False)


def version_from_config(venv):
    config = venv / "pyvenv.cfg"
    if not config.is_file():
        return None
    for line in config.read_text(encoding="utf-8").splitlines():
        key, separator, value = line.partition("=")
        if separator and key.strip() == "version":
            parts = value.strip().split(".")
            try:
                return tuple(int(part) for part in parts[:2])
            except ValueError:
                return None
    return None


def healthy_venv(venv):
    """Return its Python version only when the executable and config agree."""
    if venv.is_symlink() or not (venv / "bin/python").is_file():
        return None
    try:
        result = capture(str(venv / "bin/python"), "-c", HEALTH_CODE)
    except OSError:
        return None
    if result.returncode:
        return None
    try:
        state = json.loads(result.stdout)
        version = tuple(state["version"])
        if (
            version != version_from_config(venv)
            or version < (3, 11)
            or Path(state["prefix"]).resolve() != venv.resolve()
            or state["base_prefix"] == state["prefix"]
        ):
            return None
    except (KeyError, TypeError, ValueError, OSError):
        return None
    return version


def probe_candidate(candidate):
    executable = shutil.which(candidate)
    if not executable:
        return None, "not installed"
    try:
        version_result = capture(
            executable,
            "-c",
            "import json, sys; print(json.dumps(sys.version_info[:2]))",
        )
    except OSError as exc:
        return None, "interpreter cannot start: {}".format(exc)
    if version_result.returncode:
        return None, "interpreter cannot start"
    try:
        version = tuple(json.loads(version_result.stdout))
    except (TypeError, ValueError):
        return None, "interpreter did not report its version"
    if version < (3, 11):
        return None, "Python 3.11 or newer is required"

    # A base interpreter can start while its venv cannot (the observed macOS
    # Python 3.13 failure). Never probe inside the real workspace venv.
    with tempfile.TemporaryDirectory(prefix="sleepradar-python-probe-") as temp:
        probe = Path(temp) / "venv"
        try:
            result = capture(executable, "-m", "venv", str(probe))
        except OSError as exc:
            return None, "venv cannot start: {}".format(exc)
        if result.returncode:
            detail = result.stderr.strip().splitlines()[-1] if result.stderr.strip() else "venv failed"
            return None, detail
        if healthy_venv(probe) != version:
            return None, "venv interpreter failed its startup check"
    return (executable, version), None


def choose_python(candidates=CANDIDATES):
    failures = []
    for candidate in candidates:
        selected, error = probe_candidate(candidate)
        if selected:
            return selected
        failures.append("{}: {}".format(candidate, error))
    raise SetupError(
        "No working Python 3.11+ venv interpreter found. "
        "CI uses Python 3.12. Tried: " + "; ".join(failures)
    )


def install_dependencies(venv):
    python = str(venv / "bin/python")
    subprocess.run(
        [python, "-m", "pip", "install", "--upgrade", "pip"],
        cwd=str(venv.parent), check=True,
    )
    subprocess.run(
        [python, "-m", "pip", "install", "-r", "requirements-ci.txt"],
        cwd=str(venv.parent), check=True,
    )


def verify_dependencies(venv):
    python = str(venv / "bin/python")
    subprocess.run([python, "-c", "import encodings, pip, tomllib, yaml, yamllint"], check=True)
    subprocess.run([python, "-m", "pip", "check"], check=True)
    subprocess.run([str(venv / "bin/yamllint"), "--version"], check=True)


def setup_workspace(workspace, candidates=CANDIDATES, installer=install_dependencies,
                    verifier=verify_dependencies):
    workspace = Path(workspace).resolve()
    venv = workspace / ".venv"
    if venv.is_symlink() or (venv.exists() and not venv.is_dir()):
        raise SetupError("Refusing to replace a non-directory or symlink at {}".format(venv))
    if not (workspace / "requirements-ci.txt").is_file():
        raise SetupError("Run setup from the SleepRadar workspace root")

    executable, version = choose_python(candidates)
    if healthy_venv(venv) == version:
        print("Reusing healthy Python {}.{} workspace venv".format(*version), flush=True)
        installer(venv)
        verifier(venv)
        return

    backup_dir = None
    backup = None
    if venv.exists():
        backups = workspace / ".context" / "setup-backups"
        backups.mkdir(parents=True, exist_ok=True)
        backup_dir = Path(tempfile.mkdtemp(prefix="venv-", dir=str(backups)))
        backup = backup_dir / ".venv"
        os.replace(str(venv), str(backup))
        print("Replacing unusable workspace venv", flush=True)

    try:
        subprocess.run([executable, "-m", "venv", str(venv)], check=True)
        if healthy_venv(venv) != version:
            raise SetupError("New workspace venv failed its startup check")
        installer(venv)
        verifier(venv)
    except Exception:
        try:
            if venv.is_symlink():
                venv.unlink()
            elif venv.is_dir():
                shutil.rmtree(venv)
            if backup:
                os.replace(str(backup), str(venv))
                shutil.rmtree(backup_dir)
        except OSError as recovery_error:
            raise SetupError(
                "Could not restore the previous venv; backup is at {}: {}".format(
                    backup, recovery_error
                )
            ) from recovery_error
        raise
    else:
        if backup_dir:
            shutil.rmtree(backup_dir)
        print("SleepRadar workspace setup OK (Python {}.{})".format(*version), flush=True)


if __name__ == "__main__":
    try:
        setup_workspace(Path.cwd())
    except (SetupError, OSError, subprocess.CalledProcessError) as exc:
        print("SleepRadar setup failed: {}".format(exc), file=sys.stderr)
        sys.exit(1)
