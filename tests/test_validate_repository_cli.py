"""Regression tests for repository validation and Conductor setup."""

from __future__ import annotations

import importlib.util
import json
import os
from pathlib import Path
import shlex
import subprocess
import sys
import tempfile
import textwrap
import tomllib
import unittest
from unittest import mock


ROOT = Path(__file__).resolve().parents[1]
VALIDATOR = ROOT / "scripts" / "validate_repository.py"
# The validator imports the poller, whose MQTT node and device defaults are
# read from these variables. Inheriting a developer's exported values makes
# normal-mode validation fail with an unrelated "unexpected default MQTT node
# id" error, in a test whose name points at the command-line interface.
AMBIENT_POLLER_VARS = ("MQTT_NODE_ID", "DEVICE_NAME")


class LocalToolStateTest(unittest.TestCase):
    def test_local_files_are_ignored_but_force_added_files_are_rejected(self) -> None:
        spec = importlib.util.spec_from_file_location("repository_validator", VALIDATOR)
        validator = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(validator)
        local_files = (
            ".impeccable/hook.cache.json",
            ".conductor/settings.local.toml",
        )
        shared_files = (
            ".impeccable/config.json",
            ".conductor/settings.toml",
            ".config/commit-rules.json",
            ".config/commit-lint/MANIFEST.json",
        )
        env = {key: value for key, value in os.environ.items()
               if not key.startswith("GIT_")}
        env.update(GIT_CONFIG_NOSYSTEM="1", GIT_CONFIG_GLOBAL=os.devnull)
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            (root / ".gitignore").write_text((ROOT / ".gitignore").read_text())
            for rel in (*local_files, *shared_files):
                path = root / rel
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_text("# synthetic configuration fixture\n")

            def git(*args):
                return subprocess.run(
                    ["git", *args], cwd=root, env=env, check=True,
                    capture_output=True, text=True,
                )

            git("init", "--quiet")
            git("config", "core.excludesFile", os.devnull)
            with mock.patch.object(validator, "ROOT", root), \
                    mock.patch.dict(os.environ, env, clear=True):
                candidates = set(validator.git_tracked_paths())
                self.assertTrue(set(shared_files) <= candidates)
                self.assertTrue(set(local_files).isdisjoint(candidates))
                validator.validate_tracked_paths(candidates)
                scanned = {path.relative_to(root).as_posix()
                           for path in validator.iter_text_files()}
                self.assertTrue(set(shared_files) <= scanned)
                self.assertTrue(set(local_files).isdisjoint(scanned))
                for rel in local_files:
                    with self.subTest(force_added=rel):
                        git("add", "--force", "--", rel)
                        self.assertIn(rel, validator.git_tracked_paths())
                        with self.assertRaises(validator.ValidationError) as caught:
                            validator.validate_tracked_paths()
                        self.assertIn(f"{rel}: local tool state must not be tracked",
                                      str(caught.exception))


class ConductorSetupTest(unittest.TestCase):
    # Model candidate failures using real stdlib venv creation. Only pip is
    # stubbed, so these tests need neither multiple Python versions nor network.
    CANDIDATE = textwrap.dedent('''\
        import json
        import os
        from pathlib import Path
        import subprocess
        import sys

        name = Path(sys.argv[1]).name
        args = sys.argv[2:]
        mode = json.loads(os.environ["SETUP_TEST_MODES"])[name]
        if args[0] == "-c":
            raise SystemExit(1 if mode == "old" else
                             subprocess.run([sys.executable, *args]).returncode)
        assert args[:2] == ["-m", "venv"], args
        with open(os.environ["SETUP_TEST_LOG"], "a") as log:
            log.write(json.dumps(["venv", name]) + "\\n")
        subprocess.run([sys.executable, "-m", "venv", "--without-pip",
                        *args[2:]], check=True)
        env = Path(".venv")
        if mode in ("fail", "broken"):
            broken = Path("broken-python").resolve()
            broken.write_text("#!/bin/sh\\nexit 1\\n")
            broken.chmod(0o755)
            (env / "bin/python").unlink()
            (env / "bin/python").symlink_to(broken)
            raise SystemExit(1 if mode == "fail" else 0)
        if mode != "missing-pip":
            version = f"python{sys.version_info.major}.{sys.version_info.minor}"
            pip = env / "lib" / version / "site-packages/pip"
            pip.mkdir(parents=True, exist_ok=True)
            (pip / "__init__.py").write_text("")
            (pip / "__main__.py").write_text(
                'import json, os, sys\\n'
                'with open(os.environ["SETUP_TEST_LOG"], "a") as log:\\n'
                '    log.write(json.dumps(["pip", *sys.argv[1:]]) + "\\\\n")\\n'
            )
        ''')

    def run_setup(self, shell: str, modes: dict[str, str]):
        setup = tomllib.loads((ROOT / ".conductor/settings.toml").read_text())[
            "scripts"
        ]["setup"]
        with tempfile.TemporaryDirectory(prefix="setup workspace ") as temp:
            work = Path(temp)
            tools = work / "tools"
            tools.mkdir()
            candidate = work / "candidate.py"
            candidate.write_text(self.CANDIDATE)
            for name in modes:
                wrapper = tools / name
                wrapper.write_text(
                    f"#!/bin/sh\nexec {shlex.quote(sys.executable)} "
                    f'{shlex.quote(str(candidate))} "$0" "$@"\n'
                )
                wrapper.chmod(0o755)
            log = work / "events.jsonl"
            env = {
                key: value for key, value in os.environ.items()
                if key not in ("PYTHONHOME", "PYTHONPATH", "ZDOTDIR", "BASH_ENV")
            }
            env.update(
                PATH=str(tools),
                ZDOTDIR=str(work),
                SETUP_TEST_MODES=json.dumps(modes),
                SETUP_TEST_LOG=str(log),
            )
            result = subprocess.run(
                [shell, "-c", setup], cwd=work, env=env,
                capture_output=True, text=True, timeout=30, check=False,
            )
            events = [json.loads(line) for line in log.read_text().splitlines()] \
                if log.exists() else []
            return result, events

    def test_setup_selects_a_working_venv_before_installing(self) -> None:
        cases = [
            ({"python3.13": failure, "python3.11": "good"},
             ["python3.13", "python3.11"])
            for failure in ("fail", "broken", "missing-pip")
        ] + [
            ({"python3.12": "old", "python3": "good"}, ["python3"]),
            ({"python3.12": "good", "python3.13": "good"}, ["python3.12"]),
        ]
        for shell in ("/bin/bash", "/bin/zsh"):
            if not Path(shell).is_file():
                continue
            for modes, attempts in cases:
                with self.subTest(shell=shell, modes=modes):
                    result, events = self.run_setup(shell, modes)
                    self.assertEqual(result.returncode, 0, result.stderr)
                    self.assertEqual(events, [
                        *[["venv", name] for name in attempts],
                        ["pip", "install", "--upgrade", "pip"],
                        ["pip", "install", "-r", "requirements-ci.txt"],
                    ])

    def test_setup_fails_without_installing_when_no_candidate_works(self) -> None:
        for shell in ("/bin/bash", "/bin/zsh"):
            if not Path(shell).is_file():
                continue
            for modes in ({}, {"python3.13": "broken", "python3": "old"}):
                with self.subTest(shell=shell, modes=modes):
                    result, events = self.run_setup(shell, modes)
                    self.assertNotEqual(result.returncode, 0)
                    self.assertIn("requires Python 3.11 or newer", result.stderr)
                    self.assertFalse(any(event[0] == "pip" for event in events))


class ValidateRepositoryCliTest(unittest.TestCase):
    def run_validator(self, *arguments: str) -> subprocess.CompletedProcess[str]:
        env = {
            key: value
            for key, value in os.environ.items()
            if key not in AMBIENT_POLLER_VARS
        }
        return subprocess.run(
            [sys.executable, str(VALIDATOR), *arguments],
            cwd=ROOT,
            capture_output=True,
            text=True,
            check=False,
            env=env,
        )

    def test_normal_mode_runs_repository_validation(self) -> None:
        result = self.run_validator()

        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("SleepRadar package validation OK", result.stdout)

    def test_ambient_poller_env_does_not_reach_the_validator(self) -> None:
        """The AMBIENT_POLLER_VARS scrub must stay load-bearing.

        Dropping `env=` leaves this suite green in a clean CI environment and
        fails only on a developer machine that exports these — the exact drift
        the scrub exists to prevent.
        """

        ambient = {name: "drifted-local-value" for name in AMBIENT_POLLER_VARS}
        with mock.patch.dict(os.environ, ambient):
            result = self.run_validator()

        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("SleepRadar package validation OK", result.stdout)

    def test_help_exits_without_running_validation(self) -> None:
        result = self.run_validator("--help")

        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("usage:", result.stdout)
        self.assertIn("--self-test", result.stdout)
        self.assertNotIn("SleepRadar package validation OK", result.stdout)
        self.assertNotIn("SleepRadar validator self-test OK", result.stdout)

    def test_self_test_mode_is_preserved(self) -> None:
        result = self.run_validator("--self-test")

        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("SleepRadar validator self-test OK", result.stdout)
        self.assertNotIn("SleepRadar package validation OK", result.stdout)

    def test_unknown_option_is_actionable_and_nonzero(self) -> None:
        result = self.run_validator("--invalid")

        self.assertEqual(result.returncode, 2)
        self.assertIn("usage:", result.stderr)
        self.assertIn("unrecognized arguments: --invalid", result.stderr)
        self.assertNotIn("SleepRadar package validation OK", result.stdout)

    def test_abbreviated_option_is_rejected(self) -> None:
        """argparse abbreviation would silently run the wrong gate.

        With argparse's default allow_abbrev=True, `--self` and `--s` resolve
        to --self-test, so a typo runs the drift self-test and exits 0 while
        the caller believes package validation ran.
        """

        for abbreviation in ("--self", "--s"):
            with self.subTest(abbreviation=abbreviation):
                result = self.run_validator(abbreviation)

                self.assertEqual(result.returncode, 2, result.stderr)
                self.assertIn("usage:", result.stderr)
                self.assertIn(f"unrecognized arguments: {abbreviation}", result.stderr)
                self.assertNotIn("SleepRadar validator self-test OK", result.stdout)
                self.assertNotIn("SleepRadar package validation OK", result.stdout)

    def test_self_test_with_unknown_option_is_rejected(self) -> None:
        result = self.run_validator("--self-test", "--invalid")

        self.assertEqual(result.returncode, 2)
        self.assertIn("usage:", result.stderr)
        self.assertIn("unrecognized arguments: --invalid", result.stderr)
        self.assertNotIn("SleepRadar validator self-test OK", result.stdout)


if __name__ == "__main__":
    unittest.main()
