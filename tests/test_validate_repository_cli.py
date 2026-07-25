"""Regression tests for the repository validator command-line interface."""

from __future__ import annotations

from pathlib import Path
import subprocess
import sys
import unittest


ROOT = Path(__file__).resolve().parents[1]
VALIDATOR = ROOT / "scripts" / "validate_repository.py"


class ValidateRepositoryCliTest(unittest.TestCase):
    def run_validator(self, *arguments: str) -> subprocess.CompletedProcess[str]:
        return subprocess.run(
            [sys.executable, str(VALIDATOR), *arguments],
            cwd=ROOT,
            capture_output=True,
            text=True,
            check=False,
        )

    def test_normal_mode_runs_repository_validation(self) -> None:
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

                self.assertEqual(result.returncode, 2, result.stdout)
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
